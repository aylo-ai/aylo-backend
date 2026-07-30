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
import logging

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
