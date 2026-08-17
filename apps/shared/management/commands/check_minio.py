"""Prove that a media upload really reaches MinIO, end to end.

This exists because the failure it catches is invisible from the code. The
storage layer can be correct, the settings can be correct, the tests can be
green, and uploads can still go nowhere -- because ``deployment/minio/init.sh``
never ran against the live server, so the bucket and the scoped application
user do not exist. That state looks identical to a healthy one until a user
tries to upload something, and the error it produces (``InvalidAccessKeyId``,
or a 403 on ``HeadBucket``) reads like a credential typo rather than a missing
bootstrap step.

The unit suite cannot cover this: ``config.settings`` swaps the default storage
for ``InMemoryStorage`` under ``manage.py test``, which is exactly the code path
that proves nothing about MinIO. So this is a command, meant to be run against
a real deployment::

    python manage.py check_minio

Every write it makes is to a ``_healthcheck/`` prefix and is deleted again, so
it is safe to run against production. ``--keep`` leaves the object behind when
you want to look at it in the console.

Exit status is 0 only if every check passed, so it works as a deploy gate::

    python manage.py check_minio && ./deployment/start.sh
"""

import urllib.error
import urllib.request
import uuid

from botocore.exceptions import ClientError
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.management.base import BaseCommand

PAYLOAD = b"aylo minio healthcheck"

# Long enough to fetch a small object, short enough that a hung proxy fails the
# check instead of hanging the deploy.
HTTP_TIMEOUT = 15


class Command(BaseCommand):
    help = "Verify that media uploads reach MinIO and come back through a presigned URL."

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep",
            action="store_true",
            help="leave the probe object in the bucket instead of deleting it",
        )

    def handle(self, *args, **options):
        self.failures = []
        storage = storages["default"]

        self.stdout.write(f"backend  {type(storage).__module__}.{type(storage).__name__}")
        self.stdout.write(f"endpoint {getattr(storage, 'endpoint_url', None)}")
        self.stdout.write(f"bucket   {getattr(storage, 'bucket_name', None)}")
        self.stdout.write(f"public   {getattr(storage, 'public_endpoint_url', None) or '(none)'}\n")

        if type(storage).__name__ != "MediaStorage":
            # Nothing below would be meaningful against InMemoryStorage.
            self.stderr.write(
                self.style.ERROR(
                    f"default storage is {type(storage).__name__}, not MediaStorage — "
                    f"this command only means something against the real backend"
                )
            )
            raise SystemExit(1)

        key = f"_healthcheck/{uuid.uuid4().hex}.txt"
        saved = self._upload(storage, key)
        if saved is None:
            self._summarise()

        self._read_back(storage, saved)
        self._presigned_url(storage, saved)
        self._bucket_is_private(storage, saved)

        if options["keep"]:
            self.stdout.write(f"\nleaving {saved} in the bucket (--keep)")
        else:
            self._delete(storage, saved)

        self._summarise()

    # -- individual checks -------------------------------------------------

    def _check(self, name, ok, detail=""):
        style = self.style.SUCCESS if ok else self.style.ERROR
        self.stdout.write(style(f"[{'ok  ' if ok else 'FAIL'}] {name}") + (f"  {detail}" if detail else ""))
        if not ok:
            self.failures.append(name)
        return ok

    def _upload(self, storage, key):
        """The check that actually matters: does a write reach the bucket?"""
        try:
            saved = storage.save(key, ContentFile(PAYLOAD))
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            self._check("upload", False, self._explain(code))
            return None
        except Exception as exc:  # noqa: BLE001 — surface anything as a failed check
            self._check("upload", False, f"{type(exc).__name__}: {exc}")
            return None
        self._check("upload", True, saved)
        return saved

    def _read_back(self, storage, name):
        try:
            with storage.open(name) as fh:
                body = fh.read()
        except Exception as exc:  # noqa: BLE001
            self._check("read back", False, f"{type(exc).__name__}: {exc}")
            return
        self._check("read back", body == PAYLOAD, f"{len(body)} bytes")

    def _presigned_url(self, storage, name):
        """The step that breaks in production when nginx has no bucket route."""
        url = storage.url(name)
        if not self._check("url is signed", "X-Amz-Signature" in url, url.split("?")[0]):
            return
        status, body = self._fetch(url)
        self._check(
            "presigned URL fetches",
            status == 200 and body == PAYLOAD,
            self._explain_http(status, storage),
        )

    def _bucket_is_private(self, storage, name):
        origin = storage.public_endpoint_url or storage.endpoint_url
        status, _ = self._fetch(f"{origin.rstrip('/')}/{storage.bucket_name}/{name}")
        self._check(
            "unsigned URL is refused",
            status in (403, 404),
            f"HTTP {status} — anonymous access must not be allowed"
            if status not in (403, 404)
            else "",
        )

    def _delete(self, storage, name):
        try:
            storage.delete(name)
        except Exception as exc:  # noqa: BLE001
            self._check("delete", False, f"{type(exc).__name__}: {exc}")
            return
        self._check("delete", not storage.exists(name))

    # -- helpers -----------------------------------------------------------

    def _fetch(self, url):
        try:
            with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except Exception as exc:  # noqa: BLE001
            return None, str(exc).encode()

    def _explain(self, code):
        """Translate the S3 error codes that actually mean 'not bootstrapped'.

        boto3 does not report these consistently: a write with an unknown key
        surfaces as ``InvalidAccessKeyId`` from ``put_object`` but as a bare
        ``403`` when django-storages probes the bucket first. Both mean the same
        thing to an operator, so both get the same instruction.
        """
        bootstrap = "Run deployment/minio/init.sh (docker compose up minio-init)."

        if code in ("InvalidAccessKeyId", "SignatureDoesNotMatch", "403", "AccessDenied"):
            return (
                f"{code} — MINIO_ACCESS_KEY is not a user on this MinIO server, or "
                f"its policy does not allow writing to {settings.MINIO_BUCKET_NAME}. "
                f"{bootstrap}"
            )
        if code in ("NoSuchBucket", "404"):
            return (
                f"{code} — bucket {settings.MINIO_BUCKET_NAME} does not exist. "
                f"{bootstrap}"
            )
        return code

    def _explain_http(self, status, storage):
        if status == 200:
            return ""
        if status == 404 and storage.public_endpoint_url:
            return (
                f"HTTP 404 — nginx has no `location /{storage.bucket_name}/` block, "
                f"so the request fell through to the app upstream"
            )
        if status == 403:
            return (
                "HTTP 403 — the signature did not validate. Check that nginx passes "
                "the path through unrewritten and preserves the Host header"
            )
        return f"HTTP {status}"

    def _summarise(self):
        if self.failures:
            self.stderr.write(
                self.style.ERROR(f"\n{len(self.failures)} check(s) failed: {', '.join(self.failures)}")
            )
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS("\nall checks passed — media uploads reach MinIO"))
