from pathlib import Path

import yaml
from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)
DOCKER_SOCKET = "/var/run/docker.sock"


def load_compose():
    return yaml.safe_load((ROOT / "compose.yml").read_text())


class DozzleHardeningTests(SimpleTestCase):
    def setUp(self):
        compose = load_compose()
        self.project = compose["name"]
        self.dozzle = compose["services"]["dozzle"]
        self.proxy = compose["services"]["docker-socket-proxy"]
        self.networks = compose["networks"]

    def test_dozzle_never_mounts_the_docker_socket(self):
        mounts = [v.split(":")[0] for v in self.dozzle["volumes"]]
        self.assertNotIn(DOCKER_SOCKET, mounts)
        self.assertEqual(
            self.dozzle["environment"]["DOZZLE_REMOTE_HOST"],
            "tcp://docker-socket-proxy:2375",
        )

    def test_dozzle_requires_a_login(self):
        env = self.dozzle["environment"]
        self.assertEqual(env["DOZZLE_AUTH_PROVIDER"], "simple")
        self.assertIn("users.yml:/data/users.yml:ro", "".join(self.dozzle["volumes"]))

    def test_dozzle_is_read_only_viewer(self):
        env = self.dozzle["environment"]
        self.assertEqual(env["DOZZLE_ENABLE_ACTIONS"], "false")
        self.assertEqual(env["DOZZLE_ENABLE_SHELL"], "false")

    def test_dozzle_shows_only_this_projects_containers(self):
        self.assertEqual(
            self.dozzle["environment"]["DOZZLE_FILTER"],
            f"label=com.docker.compose.project={self.project}",
        )

    def test_dozzle_publishes_on_loopback_only(self):
        for mapping in self.dozzle["ports"]:
            self.assertTrue(
                str(mapping).startswith("127.0.0.1:"),
                f"{mapping} would expose Dozzle on every interface",
            )

    def test_dozzle_drops_capabilities_and_runs_read_only(self):
        self.assertEqual(self.dozzle["cap_drop"], ["ALL"])
        self.assertTrue(self.dozzle["read_only"])

    def test_socket_proxy_mounts_the_socket_read_only_and_blocks_writes(self):
        self.assertIn(f"{DOCKER_SOCKET}:{DOCKER_SOCKET}:ro", self.proxy["volumes"])
        env = self.proxy["environment"]
        self.assertEqual(env["POST"], 0, "POST=1 would re-enable container actions")
        self.assertEqual(set(env) - {"POST"}, {"CONTAINERS", "INFO", "EVENTS"})

    def test_socket_proxy_is_not_published(self):
        self.assertNotIn("ports", self.proxy)

    def test_log_viewer_is_isolated_from_the_application_network(self):
        for service in (self.dozzle, self.proxy):
            self.assertEqual(service["networks"], ["logs-net"])
        self.assertIn("logs-net", self.networks)

    def test_log_viewer_is_opt_in_and_pinned(self):
        for service in (self.dozzle, self.proxy):
            self.assertEqual(service["profiles"], ["logs"])
            self.assertNotIn(":latest", service["image"])
            self.assertIn(":", service["image"], "image must be version-pinned")


class DozzleNginxTests(SimpleTestCase):
    def setUp(self):
        self.conf = (ROOT / "deployment/nginx/api.aylo.uz.conf").read_text()

    def test_logs_location_matches_the_dozzle_base_path(self):
        base = load_compose()["services"]["dozzle"]["environment"]["DOZZLE_BASE"]
        self.assertIn(f"location {base}/ {{", self.conf)
        self.assertIn("proxy_pass http://127.0.0.1:8080;", self.conf)

    def test_logs_location_upgrades_websockets(self):
        logs_block = self.conf.split("location /_logs/ {")[1].split("location / {")[0]
        self.assertIn("proxy_set_header Upgrade    $http_upgrade;", logs_block)
        self.assertIn('proxy_set_header Connection "upgrade";', logs_block)


class DozzleSecretsTests(SimpleTestCase):
    def test_users_file_is_gitignored(self):
        self.assertIn(
            "deployment/dozzle/users.yml", (ROOT / ".gitignore").read_text()
        )


class MinioHardeningTests(SimpleTestCase):
    def setUp(self):
        compose = load_compose()
        self.minio = compose["services"]["minio"]
        self.init = compose["services"]["minio-init"]
        self.volumes = compose["volumes"]

    def test_minio_publishes_on_loopback_only(self):
        for mapping in self.minio["ports"]:
            self.assertTrue(
                str(mapping).startswith("127.0.0.1:"),
                f"{mapping} would expose MinIO on every interface",
            )

    def test_minio_data_is_on_a_named_volume(self):
        self.assertIn("minio-data:/data", self.minio["volumes"])
        self.assertIn("minio-data", self.volumes)

    def test_minio_image_is_pinned(self):
        for service in (self.minio, self.init):
            self.assertNotIn(":latest", service["image"])
            self.assertIn(":", service["image"], "image must be version-pinned")

    def test_minio_drops_capabilities(self):
        self.assertEqual(self.minio["cap_drop"], ["ALL"])

    def test_blank_root_credentials_cannot_start_the_service(self):
        env = self.minio["environment"]
        for name in ("MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD"):
            self.assertRegex(
                env[name],
                rf"^\$\{{{name}:\?",
                f"{name} must use ${{{name}:?…}} so an unset value fails loudly",
            )

    def test_the_admin_console_is_off_by_default(self):
        self.assertEqual(self.minio["environment"]["MINIO_BROWSER"], "${MINIO_BROWSER:-off}")

    def test_the_app_credential_is_not_the_root_credential(self):
        init_script = (ROOT / "deployment/minio/init.sh").read_text()
        self.assertIn("mc admin user add local", init_script)
        self.assertIn("mc admin policy attach local", init_script)

        env_example = (ROOT / ".env.example").read_text()
        for name in ("MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD", "MINIO_ACCESS_KEY"):
            self.assertIn(name, env_example)

        settings_source = (ROOT / "config/settings.py").read_text()
        self.assertIn('os.environ.get("MINIO_ACCESS_KEY")', settings_source)
        self.assertNotIn("MINIO_ROOT_PASSWORD", settings_source)

    def test_the_bucket_denies_anonymous_access(self):
        init_script = (ROOT / "deployment/minio/init.sh").read_text()
        self.assertIn("mc anonymous set none", init_script)

    def test_the_app_policy_is_scoped_to_one_bucket(self):
        import json

        policy = json.loads((ROOT / "deployment/minio/policy.json").read_text())
        resources = [
            resource
            for statement in policy["Statement"]
            for resource in statement["Resource"]
        ]
        self.assertTrue(resources)
        for resource in resources:
            self.assertTrue(
                resource.startswith("arn:aws:s3:::__BUCKET__"),
                f"{resource} grants access beyond the media bucket",
            )
        for statement in policy["Statement"]:
            for action in statement["Action"]:
                self.assertTrue(action.startswith("s3:"), action)
                self.assertNotEqual(action, "s3:*")


class MinioNginxTests(SimpleTestCase):
    def setUp(self):
        self.conf = (ROOT / "deployment/nginx/api.aylo.uz.conf").read_text()

    def test_the_media_location_does_not_rewrite_the_path(self):
        block = self.conf.split("location /aylo-media/ {")[1].split("\n    location")[0]
        self.assertIn("proxy_pass http://127.0.0.1:9000;", block)
        self.assertNotIn("proxy_pass http://127.0.0.1:9000/;", block)
        self.assertNotIn("rewrite", block)
        self.assertIn("proxy_set_header Host              $host;", block)

    def test_the_media_location_is_read_only(self):
        block = self.conf.split("location /aylo-media/ {")[1].split("\n    location")[0]
        self.assertIn("limit_except GET HEAD", block)
        self.assertIn("deny all;", block)

    def test_the_old_filesystem_media_alias_is_gone(self):
        directives = [
            line.strip()
            for line in self.conf.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        self.assertNotIn("alias /var/www/media/;", directives)
        self.assertNotIn("location /media/ {", directives)

    def test_no_service_bind_mounts_a_media_directory(self):
        for name, service in load_compose()["services"].items():
            for mount in service.get("volumes") or []:
                self.assertNotIn(
                    "/var/www/media", str(mount), f"{name} still mounts media"
                )

    def test_the_location_matches_the_configured_bucket(self):
        from django.conf import settings

        self.assertIn(f"location {settings.MEDIA_URL} {{", self.conf)
