"""Authentication tests.

These run offline: Redis, SMS/email delivery and Google's token endpoint are all
faked, so the tests exercise the auth *logic* — OTP brute-force limits, the
verification gate on registration, notification scoping and OAuth CSRF — without
touching the network.
"""
from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.user.models import User, Notification
from shared.addons import verification
from shared.addons.enums import NotificationTypes

# Throttling stores its history in the default cache; DummyCache makes every
# request pass so rate limits never make these tests flaky.
NO_THROTTLE = override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}
)


class FakeRedis:
    """Just enough of the redis API for the verification helpers."""

    def __init__(self):
        self.store = {}

    def get(self, key):
        value = self.store.get(key)
        if value is None:
            return None
        return value if isinstance(value, bytes) else str(value).encode()

    def set(self, key, value):
        self.store[key] = value

    def setex(self, key, ttl, value):
        self.store[key] = value

    def expire(self, key, time=None):
        return True

    def incr(self, key):
        value = int(self.store.get(key, 0)) + 1
        self.store[key] = value
        return value

    def delete(self, *keys):
        removed = 0
        for key in keys:
            if key in self.store:
                del self.store[key]
                removed += 1
        return removed


class OtpAttemptTests(TestCase):
    """The OTP must be unusable after a handful of wrong guesses."""

    def setUp(self):
        self.redis = FakeRedis()
        patch = mock.patch.object(verification, "redis_connection", self.redis)
        patch.start()
        self.addCleanup(patch.stop)

    def test_wrong_phone_code_is_thrown_away_after_the_attempt_cap(self):
        self.redis.set("+998901112233", 123456)

        for _ in range(verification.MAX_VERIFY_ATTEMPTS - 1):
            ok, _msg = verification.verify_code_cache("+998901112233", "000000")
            self.assertFalse(ok)

        # The attempt that hits the cap must burn the code.
        ok, message = verification.verify_code_cache("+998901112233", "000000")
        self.assertFalse(ok)
        self.assertIn("Too many", message)
        self.assertIsNone(self.redis.get("+998901112233"))

        # Even the correct code no longer works once it has been discarded.
        ok, _msg = verification.verify_code_cache("+998901112233", "123456")
        self.assertFalse(ok)

    def test_correct_code_verifies_and_marks_the_identifier(self):
        self.redis.set("+998901112233", 123456)

        ok, _msg = verification.verify_code_cache("+998901112233", "123456")

        self.assertTrue(ok)
        self.assertEqual(self.redis.get("+998901112233_verified"), b"True")


@NO_THROTTLE
class VerifyOtpViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_wrong_code_does_not_create_a_user(self):
        with mock.patch("user.views.verify_code_cache", return_value=(False, "Code is incorrect")):
            response = self.client.post(
                "/api/v1/user/auth/verify-otp/",
                {"phone_number": "+998901112233", "code": "000000"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(phone_number="+998901112233").exists())

    def test_correct_code_creates_the_user_once_and_returns_tokens(self):
        with mock.patch("user.views.verify_code_cache", return_value=(True, "ok")):
            first = self.client.post(
                "/api/v1/user/auth/verify-otp/",
                {"phone_number": "+998901112233", "code": "123456"},
            )
            second = self.client.post(
                "/api/v1/user/auth/verify-otp/",
                {"phone_number": "+998901112233", "code": "123456"},
            )

        self.assertEqual(first.status_code, 200)
        self.assertIn("access", first.data["data"]["tokens"])
        self.assertEqual(User.objects.filter(phone_number="+998901112233").count(), 1)
        self.assertEqual(second.status_code, 200)


LOCMEM_EMAIL = override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_HOST_USER="noreply@example.com",
)


@LOCMEM_EMAIL
class EmailCodeDeliveryTests(TestCase):
    """Sign-up by email: the code must only exist once the mail is out."""

    def setUp(self):
        self.redis = FakeRedis()
        patch = mock.patch.object(verification, "redis_connection", self.redis)
        patch.start()
        self.addCleanup(patch.stop)
        mail.outbox = []

    def test_code_is_emailed_and_stored(self):
        ok, _message = verification.send_email_code("signup@example.com")

        self.assertTrue(ok)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["signup@example.com"])

        stored = self.redis.get("signup@example.com").decode()
        # The code the user was emailed is the code the cache will accept.
        self.assertIn(stored, mail.outbox[0].body)
        self.assertEqual(len(stored), 6)

    def test_a_failed_send_stores_no_code_and_leaks_no_smtp_detail(self):
        self.redis.setex("signup@example.com", 300, 111111)

        with mock.patch.object(
            verification, "send_mail",
            side_effect=Exception("SMTP auth failed for user@smtppro.zoho.com"),
        ):
            ok, message = verification.send_email_code("signup@example.com")

        self.assertFalse(ok)
        self.assertNotIn("smtppro", str(message))
        # The previously issued code survives — a failed send must not replace
        # a code the user is still holding with one they never received.
        self.assertEqual(self.redis.get("signup@example.com").decode(), "111111")

    def test_correct_code_verifies_and_is_burned(self):
        self.redis.setex("signup@example.com", 300, 654321)

        ok, _message = verification.verify_email_code("signup@example.com", "654321")

        self.assertTrue(ok)
        self.assertEqual(self.redis.get("signup@example.com_verified"), b"true")
        self.assertIsNone(self.redis.get("signup@example.com"))
        # Replaying the same code now fails.
        self.assertFalse(verification.verify_email_code("signup@example.com", "654321")[0])

    def test_wrong_email_code_is_thrown_away_after_the_attempt_cap(self):
        self.redis.setex("signup@example.com", 300, 654321)

        for _ in range(verification.MAX_VERIFY_ATTEMPTS - 1):
            self.assertFalse(
                verification.verify_email_code("signup@example.com", "000000")[0]
            )

        ok, message = verification.verify_email_code("signup@example.com", "000000")

        self.assertFalse(ok)
        self.assertIn("Too many", str(message))
        self.assertIsNone(self.redis.get("signup@example.com"))
        # Even the right code is dead once the cap burned it.
        self.assertFalse(verification.verify_email_code("signup@example.com", "654321")[0])


@NO_THROTTLE
class EmailSignUpFlowTests(TestCase):
    """The two endpoints the email sign-up screen calls, end to end."""

    def setUp(self):
        self.client = APIClient()

    def test_send_otp_accepts_an_email(self):
        with mock.patch("user.views.send_email_code", return_value=(True, "sent")) as send:
            response = self.client.post(
                "/api/v1/user/auth/send-otp/", {"email": "new@example.com"},
            )

        self.assertEqual(response.status_code, 200)
        send.assert_called_once_with("new@example.com")

    def test_send_otp_rejects_a_malformed_email(self):
        with mock.patch("user.views.send_email_code") as send:
            response = self.client.post(
                "/api/v1/user/auth/send-otp/", {"email": "not-an-email"},
            )

        self.assertEqual(response.status_code, 400)
        send.assert_not_called()

    def test_verifying_an_email_code_creates_the_account_once(self):
        with mock.patch("user.views.verify_email_code", return_value=(True, "ok")):
            first = self.client.post(
                "/api/v1/user/auth/verify-otp/",
                {"email": "new@example.com", "code": "123456"},
            )
            second = self.client.post(
                "/api/v1/user/auth/verify-otp/",
                {"email": "new@example.com", "code": "123456"},
            )

        self.assertEqual(first.status_code, 200)
        self.assertIn("access", first.data["data"]["tokens"])
        self.assertEqual(second.status_code, 200)

        users = User.objects.filter(email="new@example.com")
        self.assertEqual(users.count(), 1)
        self.assertEqual(users.first().auth_type, "email")

    def test_a_wrong_email_code_creates_no_account(self):
        with mock.patch("user.views.verify_email_code", return_value=(False, "Invalid verification code")):
            response = self.client.post(
                "/api/v1/user/auth/verify-otp/",
                {"email": "new@example.com", "code": "000000"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(email="new@example.com").exists())

    def test_a_brand_new_account_starts_with_no_name_and_no_subscription(self):
        """What the frontend keys the 'complete profile' and 'choose a plan'
        onboarding steps off — both must be empty for a first-time sign-up."""
        with mock.patch("user.views.verify_email_code", return_value=(True, "ok")):
            self.client.post(
                "/api/v1/user/auth/verify-otp/",
                {"email": "new@example.com", "code": "123456"},
            )

        user = User.objects.get(email="new@example.com")
        self.client.force_authenticate(user)
        profile = self.client.get("/api/v1/user/auth/profile/")

        self.assertEqual(profile.status_code, 200)
        self.assertIsNone(profile.data["first_name"])
        self.assertIsNone(profile.data["subscription"])


class RegisterGateTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.payload = {
            "first_name": "Aziz",
            "last_name": "Karimov",
            "phone_number": "+998901112233",
        }

    def test_registration_is_rejected_without_a_verified_otp(self):
        with mock.patch("user.serializers.check_verification_status", return_value=(False, "not verified")):
            response = self.client.post("/api/v1/user/auth/register/", self.payload)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(phone_number="+998901112233").exists())

    def test_registration_succeeds_for_a_verified_number(self):
        with mock.patch("user.serializers.check_verification_status", return_value=(True, "ok")), \
             mock.patch("user.views.redis_connection"):
            response = self.client.post("/api/v1/user/auth/register/", self.payload)

        self.assertEqual(response.status_code, 201)
        self.assertTrue(User.objects.filter(phone_number="+998901112233").exists())

    def test_duplicate_number_is_a_clean_400_not_a_500(self):
        User.objects.create(phone_number="+998901112233", first_name="X", last_name="Y")

        with mock.patch("user.serializers.check_verification_status", return_value=(True, "ok")):
            response = self.client.post("/api/v1/user/auth/register/", self.payload)

        self.assertEqual(response.status_code, 400)


class NotificationScopingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create(phone_number="+998900000001", first_name="A", last_name="A")
        self.other = User.objects.create(phone_number="+998900000002", first_name="B", last_name="B")
        self.note = Notification.objects.create(
            user=self.owner, title="t", content="c", type=NotificationTypes.choices()[0][0],
        )

    def test_a_user_cannot_update_someone_elses_notification(self):
        self.client.force_authenticate(self.other)
        response = self.client.patch(f"/api/v1/user/notification/{self.note.id}/", {"is_read": True})

        self.assertEqual(response.status_code, 404)
        self.note.refresh_from_db()
        self.assertFalse(self.note.is_read)

    def test_a_user_can_update_their_own_notification(self):
        self.client.force_authenticate(self.owner)
        response = self.client.patch(f"/api/v1/user/notification/{self.note.id}/", {"is_read": True})

        self.assertEqual(response.status_code, 200)
        self.note.refresh_from_db()
        self.assertTrue(self.note.is_read)


class GoogleOAuthCsrfTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_callback_without_state_is_rejected(self):
        response = self.client.get("/api/v1/user/accounts/google/login/callback/?code=abc")
        self.assertEqual(response.status_code, 400)

    def test_callback_with_an_unknown_state_is_rejected(self):
        redis = mock.MagicMock()
        redis.delete.return_value = 0  # state not found → forged/expired
        with mock.patch("user.views.redis_connection", redis):
            response = self.client.get(
                "/api/v1/user/accounts/google/login/callback/?code=abc&state=forged"
            )
        self.assertEqual(response.status_code, 400)


class GoogleOAuthEmailVerificationTests(TestCase):
    """H1 (2026-07-22) — an unverified Google email claim must not match or
    link to an existing account with that email (account-takeover vector)."""

    def setUp(self):
        self.client = APIClient()
        self.victim = User.objects.create(
            username="victim", auth_type="email", email="victim@example.com",
        )

    def callback(self, claims):
        redis = mock.MagicMock()
        redis.delete.return_value = 1  # state found and consumed
        token_response = mock.Mock()
        token_response.json.return_value = {"id_token": "raw-token"}
        with mock.patch("user.views.redis_connection", redis), \
                mock.patch("user.views.requests.post", return_value=token_response), \
                mock.patch("user.views.google_id_token.verify_oauth2_token",
                           return_value=claims):
            return self.client.get(
                "/api/v1/user/accounts/google/login/callback/?code=abc&state=ok"
            )

    def test_unverified_email_does_not_link_to_the_existing_account(self):
        response = self.callback({
            "sub": "attacker-sub", "email": "victim@example.com",
            "email_verified": False, "name": "Att Acker",
        })
        self.assertEqual(response.status_code, 200)
        self.victim.refresh_from_db()
        self.assertIsNone(self.victim.sub)
        attacker = User.objects.get(sub="attacker-sub")
        self.assertNotEqual(attacker.id, self.victim.id)
        self.assertIsNone(attacker.email)

    def test_verified_email_links_to_the_existing_account(self):
        response = self.callback({
            "sub": "google-sub", "email": "victim@example.com",
            "email_verified": True, "name": "Vic Tim",
        })
        self.assertEqual(response.status_code, 200)
        self.victim.refresh_from_db()
        self.assertEqual(self.victim.sub, "google-sub")
