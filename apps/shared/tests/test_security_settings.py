"""Transport, CORS and token-lifetime settings are security controls.

They live in `config/settings.py`, where a well-meaning edit ("add the tunnel so
I can demo", "bump the access token so people stop getting logged out") silently
removes a boundary and nothing fails. These tests fail that edit.

The `if not DEBUG:` block is exercised by re-importing the settings module with
`DEBUG` unset, so the assertions describe *production* rather than whatever the
developer's `.env` happens to say.
"""
import importlib
import os
import re
from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase


def production_settings():
    """`config.settings` as it evaluates with DEBUG off."""
    env = dict(os.environ)
    env["DEBUG"] = "False"
    env.setdefault("SECRET_KEY", "test-only-secret-key-for-settings-import")
    env.setdefault("AMOCRM_CLIENT_ID", "test")
    env.setdefault("AMOCRM_SECRET_KEY", "test")
    with mock.patch.dict(os.environ, env, clear=True):
        module = importlib.import_module("config.settings")
        return importlib.reload(module)


class ProductionSecurityHeaderTests(SimpleTestCase):
    """`manage.py check --deploy` in test form."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.prod = production_settings()

    @classmethod
    def tearDownClass(cls):
        # Leave the imported module matching the running configuration again,
        # otherwise every later test in the process sees DEBUG-off values.
        importlib.reload(importlib.import_module("config.settings"))
        super().tearDownClass()

    def test_cookies_are_https_only(self):
        self.assertTrue(self.prod.SESSION_COOKIE_SECURE)
        self.assertTrue(self.prod.CSRF_COOKIE_SECURE)

    def test_cookies_are_not_readable_from_javascript(self):
        self.assertTrue(self.prod.SESSION_COOKIE_HTTPONLY)
        self.assertTrue(self.prod.CSRF_COOKIE_HTTPONLY)

    def test_hsts_is_long_enough_to_matter(self):
        # Under a year browsers ignore it for preloading, and `check --deploy`
        # flags anything shorter.
        self.assertGreaterEqual(self.prod.SECURE_HSTS_SECONDS, 31536000)
        self.assertTrue(self.prod.SECURE_HSTS_INCLUDE_SUBDOMAINS)
        self.assertTrue(self.prod.SECURE_HSTS_PRELOAD)

    def test_content_type_sniffing_is_off(self):
        self.assertTrue(self.prod.SECURE_CONTENT_TYPE_NOSNIFF)

    def test_the_api_cannot_be_framed(self):
        self.assertEqual(self.prod.X_FRAME_OPTIONS, "DENY")

    def test_referrers_do_not_leak_across_origins(self):
        self.assertEqual(self.prod.SECURE_REFERRER_POLICY, "same-origin")

    def test_https_is_recognised_behind_the_proxy(self):
        self.assertEqual(
            self.prod.SECURE_PROXY_SSL_HEADER, ("HTTP_X_FORWARDED_PROTO", "https")
        )


class CorsTests(SimpleTestCase):
    """`CORS_ALLOW_CREDENTIALS` makes the origin list an authorisation list."""

    def test_credentials_are_only_shared_with_an_explicit_list(self):
        self.assertTrue(settings.CORS_ALLOW_CREDENTIALS)
        self.assertFalse(settings.CORS_ORIGIN_ALLOW_ALL)
        self.assertTrue(settings.CORS_ALLOWED_ORIGINS)

    def test_no_wildcard_origin_is_allowed(self):
        for origin in settings.CORS_ALLOWED_ORIGINS:
            self.assertNotIn("*", origin, msg=origin)

    def test_no_public_tunnel_host_is_trusted(self):
        """ngrok/loca.lt/trycloudflare subdomains are recycled to whoever asks
        next, so trusting one hands a stranger credentialed cross-origin reads
        (and, in CSRF_TRUSTED_ORIGINS, a working CSRF origin)."""
        tunnels = re.compile(
            r"(ngrok[-.]|loca\.lt|trycloudflare\.com|serveo\.net|localtunnel)",
            re.IGNORECASE,
        )
        for origin in settings.CORS_ALLOWED_ORIGINS + settings.CSRF_TRUSTED_ORIGINS:
            self.assertIsNone(tunnels.search(origin), msg=origin)


class TokenLifetimeTests(SimpleTestCase):
    """Nothing can revoke an access token, so its lifetime is the blast radius."""

    def test_access_tokens_are_short_lived(self):
        self.assertLessEqual(
            settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"], timedelta(hours=24)
        )

    def test_refresh_tokens_rotate_and_the_old_one_is_revoked(self):
        self.assertTrue(settings.SIMPLE_JWT["ROTATE_REFRESH_TOKENS"])
        self.assertTrue(settings.SIMPLE_JWT["BLACKLIST_AFTER_ROTATION"])

    def test_blacklisting_is_actually_installed(self):
        """Rotation without this app is a no-op: `token.blacklist()` needs the
        tables, so logout and rotation would silently revoke nothing."""
        self.assertIn(
            "rest_framework_simplejwt.token_blacklist", settings.INSTALLED_APPS
        )

    def test_signing_is_symmetric_and_keyed_off_the_secret(self):
        self.assertEqual(settings.SIMPLE_JWT["ALGORITHM"], "HS256")
        self.assertEqual(settings.SIMPLE_JWT["SIGNING_KEY"], settings.SECRET_KEY)


class OtpThrottleRateTests(SimpleTestCase):
    """A six-digit code is only safe if guesses are bounded."""

    def test_both_the_ip_and_the_identifier_scopes_are_configured(self):
        rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
        for scope in (
            "otp_send", "otp_verify",
            "otp_send_identifier", "otp_verify_identifier",
        ):
            self.assertIn(scope, rates)
            self.assertTrue(rates[scope], msg=scope)


class PasswordValidatorTests(SimpleTestCase):
    def test_password_validators_are_configured(self):
        names = {v["NAME"].rsplit(".", 1)[-1] for v in settings.AUTH_PASSWORD_VALIDATORS}
        self.assertIn("MinimumLengthValidator", names)
        self.assertIn("CommonPasswordValidator", names)
        self.assertIn("NumericPasswordValidator", names)
        self.assertIn("UserAttributeSimilarityValidator", names)
