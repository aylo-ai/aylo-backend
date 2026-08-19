import os
import threading
import uuid

from django.core.exceptions import ImproperlyConfigured, SuspiciousFileOperation
from django.utils.text import get_valid_filename
from storages.backends.s3boto3 import S3Boto3Storage
from storages.utils import clean_name

MAX_KEY_LENGTH = 255

MAX_STEM_LENGTH = 60


def build_media_key(prefix, filename):
    prefix = prefix.strip("/")
    base = os.path.basename(filename or "")

    try:
        base = get_valid_filename(base)
    except SuspiciousFileOperation:
        base = ""

    stem, ext = os.path.splitext(base or "file")
    stem = (stem or "file")[:MAX_STEM_LENGTH]
    ext = ext[:16].lower()

    unique = uuid.uuid4().hex
    overhead = len(f"{prefix}/{unique}/{ext}") + 1
    if overhead + len(stem) > MAX_KEY_LENGTH:
        stem = stem[: max(1, MAX_KEY_LENGTH - overhead)]

    return f"{prefix}/{unique}/{stem}{ext}"


class MediaStorage(S3Boto3Storage):
    default_acl = None

    file_overwrite = False

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

        if not (self.access_key and self.secret_key):
            raise ImproperlyConfigured(
                "MediaStorage requires MINIO_ACCESS_KEY and MINIO_SECRET_KEY. "
                "Without them boto3 falls back to ambient AWS credentials and "
                "every media request fails with InvalidAccessKeyId."
            )

        self._signing_connections = threading.local()

    @property
    def signing_connection(self):
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
