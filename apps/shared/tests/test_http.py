from unittest import mock

from django.test import SimpleTestCase

from apps.shared import http


class DefaultTimeoutTests(SimpleTestCase):
    def test_every_verb_applies_the_default_timeout(self):
        for verb in ("get", "post", "put", "patch", "delete"):
            with self.subTest(verb=verb):
                with mock.patch.object(http.session, "request") as request:
                    getattr(http, verb)("https://example.test/x")
                self.assertEqual(
                    request.call_args.kwargs["timeout"], http.DEFAULT_TIMEOUT
                )

    def test_explicit_timeout_is_not_overridden(self):
        with mock.patch.object(http.session, "request") as request:
            http.get("https://example.test/x", timeout=1)
        self.assertEqual(request.call_args.kwargs["timeout"], 1)

    def test_caller_kwargs_are_passed_through(self):
        with mock.patch.object(http.session, "request") as request:
            http.post("https://example.test/x", json={"a": 1}, headers={"H": "v"})

        self.assertEqual(request.call_args.args, ("POST", "https://example.test/x"))
        self.assertEqual(request.call_args.kwargs["json"], {"a": 1})
        self.assertEqual(request.call_args.kwargs["headers"], {"H": "v"})


class RetryPolicyTests(SimpleTestCase):
    def test_post_is_never_retried(self):
        retry = http.session.get_adapter("https://example.test").max_retries
        self.assertNotIn("POST", retry.allowed_methods)
        self.assertIn("GET", retry.allowed_methods)

    def test_reads_are_not_retried(self):
        retry = http.session.get_adapter("https://example.test").max_retries
        self.assertEqual(retry.read, 0)
