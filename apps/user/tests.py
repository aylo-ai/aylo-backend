from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.shared.addons import verification
from apps.shared.addons.enums import NotificationTypes, UserRoles
from apps.user.models import Notification, User

NO_THROTTLE = override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}
)

def local_cache(location):
    return override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": location,
            }
        }
    )


class FakeRedis:
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

        ok, message = verification.verify_code_cache("+998901112233", "000000")
        self.assertFalse(ok)
        self.assertIn("Too many", message)
        self.assertIsNone(self.redis.get("+998901112233"))

        ok, _msg = verification.verify_code_cache("+998901112233", "123456")
        self.assertFalse(ok)

    def test_correct_code_verifies_and_marks_the_identifier(self):
        self.redis.set("+998901112233", 123456)

        ok, _msg = verification.verify_code_cache("+998901112233", "123456")

        self.assertTrue(ok)
        self.assertEqual(self.redis.get("+998901112233_verified"), b"True")

    def test_a_correct_code_cannot_be_replayed(self):
        self.redis.set("+998901112233", 123456)

        self.assertTrue(verification.verify_code_cache("+998901112233", "123456")[0])
        ok, message = verification.verify_code_cache("+998901112233", "123456")

        self.assertFalse(ok)
        self.assertIn("expired", message)

    def test_an_expired_code_is_rejected(self):
        ok, message = verification.verify_code_cache("+998901112233", "123456")

        self.assertFalse(ok)
        self.assertIn("expired", message)

    def test_the_stored_code_is_compared_in_constant_time(self):
        self.redis.set("+998901112233", 123456)

        with mock.patch.object(
            verification.hmac, "compare_digest", wraps=verification.hmac.compare_digest
        ) as compare:
            verification.verify_code_cache("+998901112233", "123456")

        compare.assert_called_once()


@NO_THROTTLE
class VerifyOtpViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_wrong_code_does_not_create_a_user(self):
        with mock.patch("apps.user.views.verify_code_cache", return_value=(False, "Code is incorrect")):
            response = self.client.post(
                "/api/v1/user/auth/verify-otp/",
                {"phone_number": "+998901112233", "code": "000000"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(phone_number="+998901112233").exists())

    def test_correct_code_creates_the_user_once_and_returns_tokens(self):
        with mock.patch("apps.user.views.verify_code_cache", return_value=(True, "ok")):
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
        self.assertEqual(self.redis.get("signup@example.com").decode(), "111111")

    def test_correct_code_verifies_and_is_burned(self):
        self.redis.setex("signup@example.com", 300, 654321)

        ok, _message = verification.verify_email_code("signup@example.com", "654321")

        self.assertTrue(ok)
        self.assertEqual(self.redis.get("signup@example.com_verified"), b"true")
        self.assertIsNone(self.redis.get("signup@example.com"))
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
        self.assertFalse(verification.verify_email_code("signup@example.com", "654321")[0])


@NO_THROTTLE
class EmailSignUpFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_send_otp_accepts_an_email(self):
        with mock.patch("apps.user.views.send_email_code", return_value=(True, "sent")) as send:
            response = self.client.post(
                "/api/v1/user/auth/send-otp/", {"email": "new@example.com"},
            )

        self.assertEqual(response.status_code, 200)
        send.assert_called_once_with("new@example.com")

    def test_send_otp_rejects_a_malformed_email(self):
        with mock.patch("apps.user.views.send_email_code") as send:
            response = self.client.post(
                "/api/v1/user/auth/send-otp/", {"email": "not-an-email"},
            )

        self.assertEqual(response.status_code, 400)
        send.assert_not_called()

    def test_verifying_an_email_code_creates_the_account_once(self):
        with mock.patch("apps.user.views.verify_email_code", return_value=(True, "ok")):
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
        with mock.patch("apps.user.views.verify_email_code", return_value=(False, "Invalid verification code")):
            response = self.client.post(
                "/api/v1/user/auth/verify-otp/",
                {"email": "new@example.com", "code": "000000"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(email="new@example.com").exists())

    def test_a_brand_new_account_starts_with_no_name_and_no_subscription(self):
        with mock.patch("apps.user.views.verify_email_code", return_value=(True, "ok")):
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
        with mock.patch("apps.user.serializers.check_verification_status", return_value=(False, "not verified")):
            response = self.client.post("/api/v1/user/auth/register/", self.payload)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(phone_number="+998901112233").exists())

    def test_registration_succeeds_for_a_verified_number(self):
        with mock.patch("apps.user.serializers.check_verification_status", return_value=(True, "ok")), \
             mock.patch("apps.user.views.redis_connection"):
            response = self.client.post("/api/v1/user/auth/register/", self.payload)

        self.assertEqual(response.status_code, 201)
        self.assertTrue(User.objects.filter(phone_number="+998901112233").exists())

    def test_duplicate_number_is_a_clean_400_not_a_500(self):
        User.objects.create(phone_number="+998901112233", first_name="X", last_name="Y")

        with mock.patch("apps.user.serializers.check_verification_status", return_value=(True, "ok")):
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
        redis.delete.return_value = 0
        with mock.patch("apps.user.views.redis_connection", redis):
            response = self.client.get(
                "/api/v1/user/accounts/google/login/callback/?code=abc&state=forged"
            )
        self.assertEqual(response.status_code, 400)


class GoogleOAuthEmailVerificationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.victim = User.objects.create(
            username="victim", auth_type="email", email="victim@example.com",
        )

    def callback(self, claims):
        redis = mock.MagicMock()
        redis.delete.return_value = 1
        token_response = mock.Mock()
        token_response.json.return_value = {"id_token": "raw-token"}
        with mock.patch("apps.user.views.redis_connection", redis), \
                mock.patch("apps.user.views.requests.post", return_value=token_response), \
                mock.patch("apps.user.views.google_id_token.verify_oauth2_token",
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


@NO_THROTTLE
class StaffRoleEscalationTests(TestCase):
    DASHBOARD_USERS = "/api/v1/dashboard/users/"

    def setUp(self):
        self.client = APIClient()
        self.customer = User.objects.create(
            phone_number="+998900000101", first_name="Cus", last_name="Tomer",
            user_role=UserRoles.CUSTOMER.value,
        )
        self.support_agent = User.objects.create(
            phone_number="+998900000102", first_name="Sup", last_name="Port",
            user_role=UserRoles.SUPPORT_AGENT.value,
        )

    def mint_staff_token(self):
        self.client.force_authenticate(self.customer)
        response = self.client.post(
            "/api/v1/user/add-staff/",
            {
                "first_name": "Emp",
                "last_name": "Loyee",
                "email_or_phone_number": "employee@example.com",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        return response.data["data"]["tokens"]["access"]

    def test_add_staff_still_works_and_still_creates_a_staff_account(self):
        self.mint_staff_token()

        employee = User.objects.get(email="employee@example.com")
        self.assertEqual(employee.user_role, UserRoles.STAFF.value)
        self.assertEqual(employee.created_by, self.customer)

    def test_a_customer_minted_staff_token_cannot_reach_the_dashboard(self):
        access = self.mint_staff_token()

        attacker = APIClient()
        attacker.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        response = attacker.get(self.DASHBOARD_USERS)

        self.assertEqual(response.status_code, 403)

    def test_a_support_agent_still_reaches_the_dashboard(self):
        self.client.force_authenticate(self.support_agent)
        response = self.client.get(self.DASHBOARD_USERS)

        self.assertEqual(response.status_code, 200)

    def test_a_rejected_id_token_leaks_no_verification_detail(self):
        redis = mock.MagicMock()
        redis.delete.return_value = 1
        token_response = mock.Mock()
        token_response.json.return_value = {"id_token": "raw-token"}
        with mock.patch("apps.user.views.redis_connection", redis), \
                mock.patch("apps.user.views.requests.post", return_value=token_response), \
                mock.patch("apps.user.views.google_id_token.verify_oauth2_token",
                           side_effect=ValueError("Audience mismatch: expected 123.apps.googleusercontent.com")):
            response = self.client.get(
                "/api/v1/user/accounts/google/login/callback/?code=abc&state=ok"
            )

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("googleusercontent", str(response.data))


@local_cache("otp-identifier-throttle")
class OtpIdentifierThrottleTests(TestCase):
    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.client = APIClient()

    def verify(self, identifier_field, identifier, ip):
        return self.client.post(
            "/api/v1/user/auth/verify-otp/",
            {identifier_field: identifier, "code": "000000"},
            REMOTE_ADDR=ip,
        )

    def test_guesses_against_one_number_are_capped_across_changing_ips(self):
        with mock.patch("apps.user.views.verify_code_cache", return_value=(False, "Code is incorrect")):
            statuses = [
                self.verify("phone_number", "+998901112233", f"10.0.0.{i}").status_code
                for i in range(1, 25)
            ]

        self.assertIn(429, statuses)

    def test_one_number_being_attacked_does_not_lock_out_another(self):
        with mock.patch("apps.user.views.verify_code_cache", return_value=(False, "Code is incorrect")):
            for i in range(1, 25):
                self.verify("phone_number", "+998901112233", f"10.0.0.{i}")
            victim = self.verify("phone_number", "+998909998877", "10.0.0.99")

        self.assertNotEqual(victim.status_code, 429)

    def test_sending_codes_to_one_address_is_capped_across_changing_ips(self):
        with mock.patch("apps.user.views.send_email_code", return_value=(True, "sent")):
            statuses = [
                self.client.post(
                    "/api/v1/user/auth/send-otp/", {"email": "target@example.com"},
                    REMOTE_ADDR=f"10.1.0.{i}",
                ).status_code
                for i in range(1, 15)
            ]

        self.assertIn(429, statuses)

    def test_the_throttle_key_is_the_identifier_not_the_address(self):
        from apps.user.services.throttles import OtpVerifyIdentifierThrottle

        throttle = OtpVerifyIdentifierThrottle()
        request = mock.Mock(data={"phone_number": "+998901112233"})
        other_ip = mock.Mock(data={"phone_number": "+998901112233"})
        different = mock.Mock(data={"phone_number": "+998909998877"})

        self.assertEqual(
            throttle.get_cache_key(request, None), throttle.get_cache_key(other_ip, None)
        )
        self.assertNotEqual(
            throttle.get_cache_key(request, None), throttle.get_cache_key(different, None)
        )

    def test_the_identifier_never_appears_in_the_cache_key(self):
        from apps.user.services.throttles import OtpSendIdentifierThrottle

        key = OtpSendIdentifierThrottle().get_cache_key(
            mock.Mock(data={"email": "target@example.com"}), None
        )
        self.assertNotIn("target@example.com", key)


class EmailOtpResendCooldownTests(TestCase):
    def setUp(self):
        self.redis = FakeRedis()
        patch = mock.patch.object(verification, "redis_connection", self.redis)
        patch.start()
        self.addCleanup(patch.stop)
        mail.outbox = []

    @LOCMEM_EMAIL
    def test_a_second_request_inside_the_cooldown_sends_nothing(self):
        self.assertTrue(verification.send_email_code("target@example.com")[0])

        ok, _message = verification.send_email_code("target@example.com")

        self.assertFalse(ok)
        self.assertEqual(len(mail.outbox), 1)


class LogoutRevocationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create(
            phone_number="+998900000010", first_name="A", last_name="B",
        )
        self.other = User.objects.create(
            phone_number="+998900000011", first_name="C", last_name="D",
        )

    def logout(self, user, refresh):
        self.client.force_authenticate(user)
        return self.client.post(
            "/api/v1/user/auth/logout/", {"refresh_token": str(refresh)}, format="json",
        )

    def test_a_logged_out_refresh_token_cannot_mint_a_new_access_token(self):
        refresh = RefreshToken.for_user(self.user)

        self.assertEqual(self.logout(self.user, refresh).status_code, 205)

        self.client.force_authenticate(None)
        response = self.client.post(
            "/api/v1/user/auth/login/refresh/", {"refresh_token": str(refresh)},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_a_refresh_token_is_single_use(self):
        refresh = RefreshToken.for_user(self.user)

        first = self.client.post(
            "/api/v1/user/auth/login/refresh/", {"refresh_token": str(refresh)},
            format="json",
        )
        second = self.client.post(
            "/api/v1/user/auth/login/refresh/", {"refresh_token": str(refresh)},
            format="json",
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 400)

    def test_one_user_cannot_log_another_one_out(self):
        victim_refresh = RefreshToken.for_user(self.other)

        response = self.logout(self.user, victim_refresh)

        self.assertEqual(response.status_code, 400)
        self.client.force_authenticate(None)
        refreshed = self.client.post(
            "/api/v1/user/auth/login/refresh/", {"refresh_token": str(victim_refresh)},
            format="json",
        )
        self.assertEqual(refreshed.status_code, 200)

    def test_a_deactivated_user_cannot_refresh(self):
        refresh = RefreshToken.for_user(self.user)
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        response = self.client.post(
            "/api/v1/user/auth/login/refresh/", {"refresh_token": str(refresh)},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_a_deactivated_users_access_token_stops_working(self):
        access = str(RefreshToken.for_user(self.user).access_token)
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        response = self.client.get("/api/v1/user/auth/profile/")

        self.assertEqual(response.status_code, 401)


class ProfileMassAssignmentTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create(
            phone_number="+998900000020", first_name="A", last_name="B",
        )
        self.client.force_authenticate(self.user)

    def patch(self, payload):
        return self.client.patch("/api/v1/user/auth/update-user/", payload, format="json")

    def test_a_user_cannot_promote_themselves(self):
        response = self.patch({
            "first_name": "A", "last_name": "B",
            "user_role": UserRoles.SUPER_ADMIN.value,
            "is_staff": True, "is_superuser": True,
        })

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.user_role, UserRoles.CUSTOMER.value)
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)

    def test_a_user_cannot_attach_themselves_to_a_subscription(self):
        from apps.payment.models import Subscription
        from apps.shared.addons.enums import SubscriptionStatuses

        paid = Subscription.objects.create(
            status=SubscriptionStatuses.ACTIVE.value, remained_request_count=10000,
        )

        response = self.patch({
            "first_name": "A", "last_name": "B", "subscription": str(paid.id),
        })

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.subscription)

    def test_the_phone_number_is_not_writable_and_leaks_no_account(self):
        User.objects.create(phone_number="+998900000021", first_name="X", last_name="Y")

        response = self.patch({
            "first_name": "A", "last_name": "B", "phone_number": "+998900000021",
        })

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("already", str(response.data).lower())
        self.user.refresh_from_db()
        self.assertEqual(self.user.phone_number, "+998900000020")

    def test_a_user_cannot_reassign_who_created_them(self):
        response = self.patch({
            "first_name": "A", "last_name": "B", "created_by": str(self.user.id),
        })

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.created_by)


class NotificationMassAssignmentTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create(
            phone_number="+998900000030", first_name="A", last_name="B",
        )
        self.note = Notification.objects.create(
            user=self.user, title="Quota warning", content="c",
            type=NotificationTypes.choices()[0][0],
        )
        self.client.force_authenticate(self.user)

    def test_only_the_read_flag_can_be_written(self):
        response = self.client.patch(
            f"/api/v1/user/notification/{self.note.id}/",
            {"is_read": True, "title": "Rewritten", "content": "Rewritten"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.note.refresh_from_db()
        self.assertTrue(self.note.is_read)
        self.assertEqual(self.note.title, "Quota warning")

    def test_a_notification_cannot_be_handed_to_another_user(self):
        other = User.objects.create(
            phone_number="+998900000031", first_name="C", last_name="D",
        )

        self.client.patch(
            f"/api/v1/user/notification/{self.note.id}/",
            {"user": str(other.id)}, format="json",
        )

        self.note.refresh_from_db()
        self.assertEqual(self.note.user, self.user)


class DashboardRoleSeparationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.customer = User.objects.create(
            phone_number="+998900000040", first_name="A", last_name="B",
            user_role=UserRoles.CUSTOMER.value,
        )
        self.staff = User.objects.create(
            phone_number="+998900000041", first_name="C", last_name="D",
            user_role=UserRoles.STAFF.value, created_by=self.customer,
        )
        self.admin = User.objects.create(
            phone_number="+998900000042", first_name="E", last_name="F",
            user_role=UserRoles.ADMIN.value,
        )

    def test_staff_is_not_a_dashboard_role(self):
        from apps.shared.permissions import DASHBOARD_ROLES

        self.assertNotIn(UserRoles.STAFF.value, DASHBOARD_ROLES)

    def test_a_tenants_staff_account_cannot_list_every_user(self):
        self.client.force_authenticate(self.staff)
        response = self.client.get("/api/v1/dashboard/users/")
        self.assertEqual(response.status_code, 403)

    def test_a_tenants_staff_account_cannot_read_platform_statistics(self):
        self.client.force_authenticate(self.staff)
        response = self.client.get("/api/v1/dashboard/statistics/")
        self.assertEqual(response.status_code, 403)

    def test_a_customer_cannot_reach_the_dashboard_either(self):
        self.client.force_authenticate(self.customer)
        response = self.client.get("/api/v1/dashboard/users/")
        self.assertEqual(response.status_code, 403)

    def test_an_admin_still_can(self):
        self.client.force_authenticate(self.admin)
        response = self.client.get("/api/v1/dashboard/users/")
        self.assertEqual(response.status_code, 200)


class StaffScopingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.customer = User.objects.create(
            phone_number="+998900000050", first_name="A", last_name="B",
            user_role=UserRoles.CUSTOMER.value,
        )
        self.rival = User.objects.create(
            phone_number="+998900000051", first_name="C", last_name="D",
            user_role=UserRoles.CUSTOMER.value,
        )
        self.employee = User.objects.create(
            phone_number="+998900000052", first_name="E", last_name="F",
            user_role=UserRoles.STAFF.value, created_by=self.customer,
        )

    def test_a_rival_does_not_see_the_employee(self):
        self.client.force_authenticate(self.rival)
        response = self.client.get("/api/v1/user/staff/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"], [])

    def test_a_rival_cannot_delete_the_employee(self):
        self.client.force_authenticate(self.rival)
        response = self.client.delete(f"/api/v1/user/staff/{self.employee.id}/")

        self.assertEqual(response.status_code, 404)
        self.assertTrue(User.objects.filter(pk=self.employee.pk).exists())

    def test_an_employee_cannot_create_further_employees(self):
        self.client.force_authenticate(self.employee)
        response = self.client.post(
            "/api/v1/user/add-staff/",
            {"first_name": "G", "last_name": "H", "email_or_phone_number": "g@example.com"},
            format="json",
        )

        self.assertIn(response.status_code, (403, 404))
        self.assertFalse(User.objects.filter(email="g@example.com").exists())
