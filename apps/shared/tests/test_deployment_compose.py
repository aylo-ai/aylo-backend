"""The log viewer's isolation is config, not code — so it is asserted here.

Dozzle is a web UI reachable from the internet through nginx. Every control that
keeps a compromised or mis-authenticated viewer from becoming host access lives
in compose.yml, where a one-line edit ("just mount the socket, it's easier")
silently removes it. These tests fail that edit.
"""
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
        self.dozzle = compose["services"]["dozzle"]
        self.proxy = compose["services"]["docker-socket-proxy"]
        self.networks = compose["networks"]

    def test_dozzle_never_mounts_the_docker_socket(self):
        """Socket access is the whole attack surface — it goes through the proxy."""
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
            "label=com.docker.compose.project=repliuz",
        )

    def test_dozzle_publishes_on_loopback_only(self):
        """nginx is the sole public listener, as for web-blue/web-green."""
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
        # CONTAINERS + INFO is the entire allowlist Dozzle needs; anything else
        # granted here (IMAGES, EXEC, VOLUMES, SWARM, …) widens the blast radius.
        self.assertEqual(set(env) - {"POST"}, {"CONTAINERS", "INFO"})

    def test_socket_proxy_is_not_published(self):
        """An exposed proxy port is an unauthenticated Docker API on the LAN."""
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
        """Log streaming dies at the edge without these two headers."""
        logs_block = self.conf.split("location /_logs/ {")[1].split("location / {")[0]
        self.assertIn("proxy_set_header Upgrade    $http_upgrade;", logs_block)
        self.assertIn('proxy_set_header Connection "upgrade";', logs_block)


class DozzleSecretsTests(SimpleTestCase):
    def test_users_file_is_gitignored(self):
        """users.yml holds password hashes — it is a host secret, like .env."""
        self.assertIn(
            "deployment/dozzle/users.yml", (ROOT / ".gitignore").read_text()
        )
