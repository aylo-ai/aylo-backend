"""`fetch_external` — the guard on URLs that arrive from outside.

Instagram webhook payloads carry an attachment URL that a Celery worker then
downloads. Fetching that with a plain `requests.get` pointed the worker's own
network at whatever the URL said: Postgres, Redis, MinIO, and the cloud metadata
endpoint at 169.254.169.254. Every test here is a way that used to work.
"""

from unittest import mock

import requests
from django.test import SimpleTestCase

from apps.shared import http


def fake_addrinfo(ip):
    return lambda *args, **kwargs: [(2, 1, 6, "", (ip, 443))]


class AssertPublicURLTests(SimpleTestCase):
    def test_loopback_is_refused(self):
        with self.assertRaises(http.UnsafeURLError):
            http.assert_public_url("http://127.0.0.1:8000/admin/")

    def test_localhost_is_refused(self):
        with self.assertRaises(http.UnsafeURLError):
            http.assert_public_url("http://localhost/")

    def test_cloud_metadata_endpoint_is_refused(self):
        with self.assertRaises(http.UnsafeURLError):
            http.assert_public_url("http://169.254.169.254/latest/meta-data/")

    def test_private_ranges_are_refused(self):
        for address in ("http://10.0.0.5/", "http://192.168.1.1/", "http://172.16.0.9/"):
            with self.subTest(address=address), self.assertRaises(http.UnsafeURLError):
                http.assert_public_url(address)

    def test_the_internal_minio_hostname_is_refused(self):
        """The migration put a service holding every document on the worker's network."""
        with mock.patch("socket.getaddrinfo", fake_addrinfo("172.18.0.4")):
            with self.assertRaises(http.UnsafeURLError):
                http.assert_public_url("http://minio:9000/aylo-media/")

    def test_non_http_schemes_are_refused(self):
        for url in ("file:///etc/passwd", "gopher://x/", "ftp://x/"):
            with self.subTest(url=url), self.assertRaises(http.UnsafeURLError):
                http.assert_public_url(url)

    def test_an_unresolvable_host_is_refused(self):
        with mock.patch("socket.getaddrinfo", side_effect=OSError):
            with self.assertRaises(http.UnsafeURLError):
                http.assert_public_url("https://nope.invalid/")

    def test_a_public_address_is_allowed(self):
        with mock.patch("socket.getaddrinfo", fake_addrinfo("93.184.216.34")):
            http.assert_public_url("https://cdn.example.com/audio.mp4")


def make_response(status=200, headers=None, chunks=(b"",), is_redirect=False):
    response = mock.Mock(spec=requests.Response)
    response.status_code = status
    response.headers = headers or {}
    response.is_redirect = is_redirect
    response.is_permanent_redirect = False
    response.iter_content.return_value = iter(chunks)
    response.raise_for_status.return_value = None
    response.close.return_value = None
    return response


class FetchExternalTests(SimpleTestCase):
    def setUp(self):
        patcher = mock.patch("socket.getaddrinfo", fake_addrinfo("93.184.216.34"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_it_returns_the_body(self):
        response = make_response(chunks=(b"audio", b"-bytes"))
        with mock.patch.object(http.session, "get", return_value=response):
            self.assertEqual(
                http.fetch_external("https://cdn.example.com/a.mp4"), b"audio-bytes"
            )

    def test_redirects_are_revalidated_not_followed_blindly(self):
        """The original bug: requests followed redirects with no second check.

        A signature-verified CDN URL that 302s to an internal address was a free
        SSRF, because only the first URL was ever looked at.
        """
        redirect = make_response(
            status=302,
            headers={"Location": "http://169.254.169.254/latest/meta-data/"},
            is_redirect=True,
        )
        with mock.patch.object(http.session, "get", return_value=redirect):
            with self.assertRaises(http.UnsafeURLError):
                http.fetch_external("https://cdn.example.com/a.mp4")

    def test_a_redirect_to_a_public_host_is_followed(self):
        redirect = make_response(
            status=302,
            headers={"Location": "https://cdn2.example.com/a.mp4"},
            is_redirect=True,
        )
        final = make_response(chunks=(b"ok",))
        with mock.patch.object(http.session, "get", side_effect=[redirect, final]):
            self.assertEqual(
                http.fetch_external("https://cdn.example.com/a.mp4"), b"ok"
            )

    def test_a_redirect_loop_terminates(self):
        redirect = make_response(
            status=302,
            headers={"Location": "https://cdn.example.com/a.mp4"},
            is_redirect=True,
        )
        with mock.patch.object(http.session, "get", return_value=redirect):
            with self.assertRaises(http.UnsafeURLError):
                http.fetch_external("https://cdn.example.com/a.mp4")

    def test_an_oversized_declared_length_is_refused_before_download(self):
        response = make_response(headers={"Content-Length": str(500 * 1024 * 1024)})
        with mock.patch.object(http.session, "get", return_value=response):
            with self.assertRaises(http.UnsafeURLError):
                http.fetch_external("https://cdn.example.com/big.mp4")
        response.iter_content.assert_not_called()

    def test_a_lying_content_length_is_still_capped_mid_stream(self):
        response = make_response(chunks=(b"x" * 1024,) * 64)
        with mock.patch.object(http.session, "get", return_value=response):
            with self.assertRaises(http.UnsafeURLError):
                http.fetch_external("https://cdn.example.com/big.mp4", max_bytes=1024)
