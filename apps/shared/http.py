import ipaddress
import logging
import socket
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = (5, 30)

_MAX_RETRIES = 2
_POOL_SIZE = 20


def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=_MAX_RETRIES,
        connect=_MAX_RETRIES,
        read=0,
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


MAX_REDIRECTS = 3
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
_CHUNK = 64 * 1024


class UnsafeURLError(ValueError):
    pass


def assert_public_url(url: str) -> None:
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
        raise UnsafeURLError(f"could not resolve {host}") from exc

    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            raise UnsafeURLError(f"{host} resolves to non-public address {address}")


def fetch_external(url: str, max_bytes: int = MAX_DOWNLOAD_BYTES, **kwargs) -> bytes:
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
                    raise UnsafeURLError(f"response exceeded {max_bytes} bytes")
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            response.close()

    raise UnsafeURLError(f"more than {MAX_REDIRECTS} redirects")
