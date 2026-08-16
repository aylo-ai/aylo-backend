"""Outbound HTTP with a timeout that cannot be forgotten.

Every third-party call in this codebase goes through here. `requests` defaults to
*no* timeout, so a single unresponsive Meta, Telegram or amoCRM socket parks a
gunicorn or Celery worker until the OS gives up — minutes, sometimes never. These
wrappers apply `DEFAULT_TIMEOUT` whenever the caller did not pass one, so the
failure mode is a fast exception the caller can already handle.

The shared `Session` also keeps connections alive between calls. The gateways talk
to a handful of hosts over and over, and reusing the pool skips a TLS handshake
per message.

Drop-in for the `requests` functions it mirrors::

    from apps.shared import http

    response = http.get(url, params=params)

Retries cover connection-level failures and 5xx on idempotent methods only —
`urllib3`'s default `allowed_methods` deliberately excludes POST, so a message
send is never silently duplicated.
"""
import ipaddress
import logging
import socket
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# (connect, read). Connecting should be quick; reads cover slow upstream APIs
# such as Instagram media lookups.
DEFAULT_TIMEOUT = (5, 30)

_MAX_RETRIES = 2
_POOL_SIZE = 20


def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=_MAX_RETRIES,
        connect=_MAX_RETRIES,
        read=0,  # a read timeout may mean the request was already applied
        status=_MAX_RETRIES,
        status_forcelist=(500, 502, 503, 504),
        backoff_factor=0.5,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=_POOL_SIZE,
        pool_maxsize=_POOL_SIZE,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


session = _build_session()


def request(method: str, url: str, **kwargs) -> requests.Response:
    """Send a request, defaulting the timeout if the caller omitted one."""
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    return session.request(method, url, **kwargs)


def get(url: str, **kwargs) -> requests.Response:
    return request("GET", url, **kwargs)


def post(url: str, **kwargs) -> requests.Response:
    return request("POST", url, **kwargs)


def put(url: str, **kwargs) -> requests.Response:
    return request("PUT", url, **kwargs)


def patch(url: str, **kwargs) -> requests.Response:
    return request("PATCH", url, **kwargs)


def delete(url: str, **kwargs) -> requests.Response:
    return request("DELETE", url, **kwargs)


# --- Fetching a URL that came from outside ----------------------------------
#
# The functions above are for talking to hosts *we* chose. `fetch_external` is
# for the opposite case: a URL that arrived in a webhook payload, which the
# worker is about to request from inside the private network.
#
# Without a guard that is a server-side request forgery primitive. The worker
# can reach Postgres, Redis, MinIO and the cloud metadata endpoint at
# 169.254.169.254; `requests` follows redirects by default, so even a
# signature-verified Meta CDN URL can bounce the worker onto an internal
# address. MinIO makes this materially worse than it was — it puts a service
# holding every customer's documents on an internal address the worker can
# already reach.
#
# Residual risk worth knowing: this validates the addresses a hostname resolves
# to and then makes the request, so a DNS rebind that answers differently on the
# second lookup is not blocked. Closing that needs the connection pinned to the
# validated IP. The redirect and size limits below are not affected.

MAX_REDIRECTS = 3
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024  # matches the transcription size ceiling
_CHUNK = 64 * 1024


class UnsafeURLError(ValueError):
    """Raised when a URL points somewhere a webhook must not send us."""


def assert_public_url(url: str) -> None:
    """Reject non-HTTP schemes and any host resolving to a non-public address."""
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError(f"scheme {parsed.scheme!r} is not allowed")

    host = parsed.hostname
    if not host:
        raise UnsafeURLError("url has no host")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        # gaierror is the common case, but resolution can fail with other
        # OSErrors too; an unresolvable host must be refused, never raised past
        # here as something the caller has to recognise separately.
        raise UnsafeURLError(f"could not resolve {host}") from exc

    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        # is_global excludes loopback, private, link-local (169.254.169.254),
        # reserved and unspecified ranges in one check, for v4 and v6 alike.
        if not address.is_global:
            raise UnsafeURLError(f"{host} resolves to non-public address {address}")


def fetch_external(url: str, max_bytes: int = MAX_DOWNLOAD_BYTES, **kwargs) -> bytes:
    """Download a URL supplied by a third party, safely and with a size cap.

    Redirects are followed manually so that every hop is validated — letting
    `requests` follow them would check only the first URL. The body is streamed
    and refused past ``max_bytes`` rather than read whole into the worker.
    """
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)

    for _ in range(MAX_REDIRECTS + 1):
        assert_public_url(url)
        response = session.get(url, allow_redirects=False, stream=True, **kwargs)
        try:
            if response.is_redirect or response.is_permanent_redirect:
                location = response.headers.get("Location")
                if not location:
                    raise UnsafeURLError("redirect without a Location header")
                url = urljoin(url, location)
                continue

            response.raise_for_status()

            declared = response.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise UnsafeURLError(f"response declares {declared} bytes, over the limit")

            chunks = []
            total = 0
            for chunk in response.iter_content(_CHUNK):
                total += len(chunk)
                if total > max_bytes:
                    # A lying or absent Content-Length must not get us further
                    # than one chunk past the limit.
                    raise UnsafeURLError(f"response exceeded {max_bytes} bytes")
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            response.close()

    raise UnsafeURLError(f"more than {MAX_REDIRECTS} redirects")
