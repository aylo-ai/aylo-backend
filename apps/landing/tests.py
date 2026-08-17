"""Landing-page endpoint tests.

Both endpoints are `AllowAny` and both run offline here: the Telegram lead bot
is mocked at `apps.landing.views.http`.

The lead-bot webhook is the sharp edge. It registers Telegram groups that then
receive every landing lead's name, phone number and Telegram handle, and it used
to accept any POST from anyone — guarded only by a password with a default value
committed to this repository. Forging one `/verify` update was enough to
subscribe an attacker's own group to the whole lead pipeline.
"""
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from apps.landing.models import LandingLead, LeadNotificationGroup

WEBHOOK_SECRET = "lead-bot-webhook-secret"
BOT_PASSWORD = "correct horse battery staple"


class LeadBotWebhookTests(TestCase):
    URL = "/api/v1/landing/lead-bot/webhook/"

    def setUp(self):
        cache.clear()  # throttle history lives in the cache
        self.client = APIClient()
        self.http = mock.patch("apps.landing.views.http").start()
        mock.patch("apps.landing.views.LEAD_BOT_TOKEN", "lead-bot-token").start()
        mock.patch("apps.landing.views.LEAD_BOT_PASSWORD", BOT_PASSWORD).start()
        self.addCleanup(mock.patch.stopall)

    def post(self, payload, secret=..., webhook_secret=WEBHOOK_SECRET):
        extra = {}
        if secret is ...:
            secret = WEBHOOK_SECRET
        if secret is not None:
            extra["HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN"] = secret
        with self.settings(LEAD_BOT_WEBHOOK_SECRET=webhook_secret):
            return self.client.post(self.URL, payload, format="json", **extra)

    @staticmethod
    def verify_update(password=BOT_PASSWORD, chat_id=-100123):
        return {"message": {
            "chat": {"id": chat_id, "type": "supergroup", "title": "Sales"},
            "text": f"/verify {password}",
        }}

    def test_a_valid_secret_and_password_registers_the_group(self):
        response = self.post(self.verify_update())

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            LeadNotificationGroup.objects.filter(group_id="-100123", is_active=True).exists()
        )

    def test_a_missing_secret_header_is_rejected(self):
        """The classic fail-open bug — and here it hands an attacker the whole
        lead feed."""
        response = self.post(self.verify_update(), secret=None)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(LeadNotificationGroup.objects.exists())

    def test_a_wrong_secret_is_rejected(self):
        response = self.post(self.verify_update(), secret="not-the-secret")

        self.assertEqual(response.status_code, 403)
        self.assertFalse(LeadNotificationGroup.objects.exists())

    def test_an_unconfigured_secret_fails_closed(self):
        response = self.post(self.verify_update(), secret="", webhook_secret="")

        self.assertEqual(response.status_code, 403)
        self.assertFalse(LeadNotificationGroup.objects.exists())

    def test_a_wrong_password_does_not_register_the_group(self):
        response = self.post(self.verify_update(password="repli2024"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(LeadNotificationGroup.objects.exists())

    def test_an_unconfigured_password_refuses_every_verification(self):
        """No default password: unset must reject, not accept the empty
        string."""
        with mock.patch("apps.landing.views.LEAD_BOT_PASSWORD", ""):
            response = self.post(self.verify_update(password=""))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(LeadNotificationGroup.objects.exists())

    def test_a_private_chat_cannot_register_itself(self):
        response = self.post({"message": {
            "chat": {"id": 42, "type": "private"},
            "text": f"/verify {BOT_PASSWORD}",
        }})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(LeadNotificationGroup.objects.exists())

    def test_being_removed_from_a_group_deactivates_it(self):
        LeadNotificationGroup.objects.create(group_id="-100123", is_active=True)

        response = self.post({"my_chat_member": {
            "chat": {"id": -100123, "type": "supergroup", "title": "Sales"},
            "new_chat_member": {"status": "kicked"},
        }})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            LeadNotificationGroup.objects.get(group_id="-100123").is_active
        )

    def test_a_handler_error_is_acknowledged_not_500ed(self):
        """Telegram backs a webhook off after repeated failures."""
        with mock.patch(
            "apps.landing.views.LeadNotificationGroup.objects.get_or_create",
            side_effect=RuntimeError("boom"),
        ):
            response = self.post(self.verify_update())

        self.assertEqual(response.status_code, 200)
        self.assertFalse(LeadNotificationGroup.objects.exists())

    def test_the_webhook_is_rate_limited(self):
        from rest_framework.throttling import SimpleRateThrottle

        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"lead_bot": "1/minute"}):
            first = self.post(self.verify_update())
            second = self.post(self.verify_update())

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)


class LandingLeadCreateTests(TestCase):
    URL = "/api/v1/landing/lead/"

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        # The send loop itself lives in `apps.landing.notifications` — it is
        # shared with the custom-package request in `apps.payment`. The view
        # still guards on its own token before composing the message, so both
        # constants have to be patched.
        self.http = mock.patch("apps.landing.notifications.http").start()
        mock.patch("apps.landing.views.LEAD_BOT_TOKEN", "lead-bot-token").start()
        mock.patch("apps.landing.notifications.LEAD_BOT_TOKEN", "lead-bot-token").start()
        self.addCleanup(mock.patch.stopall)

    def payload(self, **overrides):
        data = {
            "full_name": "Ali Valiyev",
            "phone_number": "+998 90 123-45-67",
            "telegram_username": "alivaliyev",
            "source_page": "/pricing",
        }
        data.update(overrides)
        return data

    def test_a_valid_lead_is_stored(self):
        response = self.client.post(self.URL, self.payload(), format="json")

        self.assertEqual(response.status_code, 201)
        lead = LandingLead.objects.get()
        self.assertEqual(lead.full_name, "Ali Valiyev")
        # The serializer normalises the phone number before it is stored.
        self.assertEqual(lead.phone_number, "+998901234567")

    def test_a_short_phone_number_is_rejected(self):
        response = self.client.post(
            self.URL, self.payload(phone_number="123"), format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(LandingLead.objects.exists())

    def test_the_endpoint_never_lists_stored_leads(self):
        LandingLead.objects.create(full_name="Ali", phone_number="+998901234567")

        response = self.client.get(self.URL)

        self.assertEqual(response.status_code, 405)

    def test_the_telegram_notification_escapes_the_lead_supplied_text(self):
        """The notification is sent with parse_mode=HTML, and every field in it
        comes from an anonymous public form."""
        LeadNotificationGroup.objects.create(group_id="-100123", is_active=True)

        response = self.client.post(
            self.URL,
            self.payload(full_name='<a href="https://evil.example">Ali</a>'),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        text = self.http.post.call_args.kwargs["json"]["text"]
        self.assertNotIn("<a href=", text)
        self.assertIn("&lt;a href=", text)

    def test_a_telegram_outage_does_not_lose_the_lead(self):
        LeadNotificationGroup.objects.create(group_id="-100123", is_active=True)
        self.http.post.side_effect = RuntimeError("telegram is down")

        response = self.client.post(self.URL, self.payload(), format="json")

        self.assertEqual(response.status_code, 201)
        self.assertTrue(LandingLead.objects.exists())

    def test_an_inactive_group_is_not_notified(self):
        LeadNotificationGroup.objects.create(group_id="-100123", is_active=False)

        self.client.post(self.URL, self.payload(), format="json")

        self.http.post.assert_not_called()

    def test_lead_submission_is_rate_limited(self):
        from rest_framework.throttling import SimpleRateThrottle

        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"landing_lead": "1/minute"}):
            first = self.client.post(self.URL, self.payload(), format="json")
            second = self.client.post(self.URL, self.payload(), format="json")

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(LandingLead.objects.count(), 1)
