"""Object-storage backends.

All user media — knowledge-base documents, message audio, campaign images —
lives in MinIO, reached over the S3 API through django-storages. The bucket is
**private**: no object is readable without a signature, so :meth:`MediaStorage.url`
always returns a presigned URL that expires.

Two subtleties are worth reading before editing this file.

**1. Signing host.** A SigV4 signature covers the request host and the full
path. Django runs inside the compose network and talks to ``http://minio:9000``,
but a browser has to fetch the object from the public nginx origin. Signing with
the internal host yields links that only validate from inside the network, so
:meth:`MediaStorage.url` signs with a second client pointed at the public
origin. nginx proxies ``/<bucket>/…`` straight through without rewriting the
path, MinIO recomputes the same signature, and the link validates. If you ever
add a path prefix or a rewrite to that nginx location, every media URL starts
returning 403 — the signature no longer matches the path MinIO receives.

**2. Never set ``custom_domain`` on this backend.** ``S3Boto3Storage.url()``
short-circuits on it and returns an *unsigned* URL; it only signs when a
CloudFront signer is configured, which MinIO has no equivalent of. Against a
private bucket that turns every media link into a 403. :meth:`__init__` refuses
the combination rather than letting it reach production quietly.
"""

import os
import threading
import uuid

from django.core.exceptions import ImproperlyConfigured, SuspiciousFileOperation
from django.utils.text import get_valid_filename
from storages.backends.s3boto3 import S3Boto3Storage
from storages.utils import clean_name

# `Message.audio_file` and `AssistantFileUpload.file` are both varchar(255).
# A key longer than this cannot be stored, and django-storages would rather
# truncate the filename away entirely than fail loudly, so budget for it here.
MAX_KEY_LENGTH = 255

# Enough to keep a name recognisable in a download dialog without letting a
# 200-character filename crowd out the prefix.
MAX_STEM_LENGTH = 60


def build_media_key(prefix, filename):
    """Build a collision-free, sanitised object key under ``prefix``.

    Two properties matter, and the previous ``f"{prefix}/{filename}"`` scheme had
    neither:

    **Uniqueness.** A random segment is inserted before the filename, so two
    uploads of ``catalog.pdf`` by the same tenant land on different keys. Without
    it the two rows shared one object, and deleting either row deleted the file
    out from under the other. A content hash would dedupe better but reintroduce
    exactly that shared-object problem, so it is not used here.

    **Bounded length.** The stem is truncated so the finished key always fits
    ``MAX_KEY_LENGTH``, instead of relying on django-storages' overwrite-name
    truncation, which raises ``SuspiciousFileOperation`` once the prefix alone
    fills the column.

    The filename is sanitised but is *not* the security boundary — Django
    basenames multipart filenames and ``S3Boto3Storage`` rejects traversal on top
    of that. This only keeps keys predictable and printable.
    """
    prefix = prefix.strip("/")
    base = os.path.basename(filename or "")

    try:
        base = get_valid_filename(base)
    except SuspiciousFileOperation:
        # get_valid_filename rejects "", "." and ".." outright.
        base = ""

    stem, ext = os.path.splitext(base or "file")
    stem = (stem or "file")[:MAX_STEM_LENGTH]
    # A long trailing "extension" is not one; cap it rather than trust it.
    ext = ext[:16].lower()

    unique = uuid.uuid4().hex
    overhead = len(f"{prefix}/{unique}/{ext}") + 1
    if overhead + len(stem) > MAX_KEY_LENGTH:
        stem = stem[: max(1, MAX_KEY_LENGTH - overhead)]

    return f"{prefix}/{unique}/{stem}{ext}"


class MediaStorage(S3Boto3Storage):
    """Private, presigned-URL media storage backed by MinIO.

    Configured through ``STORAGES["default"]["OPTIONS"]`` in settings rather than
    the global ``AWS_*`` settings, so the legacy AWS credentials can coexist for
    as long as the migration command needs them.
    """

    # MinIO governs access with a bucket policy, not per-object ACLs. Sending an
    # ACL header would fail against a bucket with object locking or simply be
    # ignored — either way it is not what grants access here.
    default_acl = None

    # Two uploads of the same filename must not silently clobber each other;
    # django-storages appends a suffix instead.
    file_overwrite = False

    # Every URL is signed. Turning this off would emit bare URLs that 403.
    querystring_auth = True

    def __init__(self, **settings):
        self.public_endpoint_url = settings.pop("public_endpoint_url", None)
        super().__init__(**settings)

        if self.custom_domain:
            raise ImproperlyConfigured(
                "MediaStorage cannot be used with custom_domain: S3Boto3Storage."
                "url() returns an unsigned URL when it is set, which a private "
                "bucket rejects. Use public_endpoint_url instead."
            )

        # Refuse to start without an explicit credential. Left as None, boto3
        # walks its own resolution chain and picks up the *legacy AWS* keys that
        # are still in the environment for the migration — every request then
        # goes to MinIO signed with an AWS key and 403s as InvalidAccessKeyId,
        # which reads like a MinIO or nginx fault rather than a missing setting.
        if not (self.access_key and self.secret_key):
            raise ImproperlyConfigured(
                "MediaStorage requires MINIO_ACCESS_KEY and MINIO_SECRET_KEY. "
                "Without them boto3 falls back to ambient AWS credentials and "
                "every media request fails with InvalidAccessKeyId."
            )

        self._signing_connections = threading.local()

    @property
    def signing_connection(self):
        """A boto3 resource bound to the *public* origin, used only to sign URLs.

        Falls back to the regular connection when no public origin is configured
        (local development, where Django and MinIO share a host).
        """
        if not self.public_endpoint_url:
            return self.connection

        connection = getattr(self._signing_connections, "connection", None)
        if connection is None:
            session = self._create_session()
            connection = session.resource(
                "s3",
                region_name=self.region_name,
                endpoint_url=self.public_endpoint_url,
                config=self.client_config,
                verify=self.verify,
            )
            self._signing_connections.connection = connection
        return connection

    def url(self, name, parameters=None, expire=None, http_method=None):
        """Return a presigned URL valid for ``querystring_expire`` seconds."""
        name = self._normalize_name(clean_name(name))
        params = parameters.copy() if parameters else {}
        params["Bucket"] = self.bucket_name
        params["Key"] = name

        if expire is None:
            expire = self.querystring_expire

        return self.signing_connection.meta.client.generate_presigned_url(
            "get_object",
            Params=params,
            ExpiresIn=expire,
            HttpMethod=http_method,
        )
