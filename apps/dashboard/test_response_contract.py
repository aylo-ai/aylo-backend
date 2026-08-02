"""Response-contract guard for the dashboard views package.

`views.py` was split into `views/` and the copy-pasted list/retrieve/create/
update/destroy bodies were collapsed into the mixins in
`apps.dashboard.views.mixins`. Those mixins now decide the status code, the
envelope shape and the message text of ~25 endpoints at once, so a slip in one
of them is a silent contract change across the whole dashboard. These tests pin
the exact strings and shapes the API answered with before the split.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from apps.assistant.models import Assistant, Conversation, Lead, PromptTemplate
from apps.integration.models import Integration
from apps.payment.models import Feature, PricingPackage, Subscription, Transaction
from apps.shared.addons.enums import PaymentStatuses, SubscriptionStatuses, UserRoles
from apps.user.models import User

BASE = "/api/v1/dashboard"


class DashboardSmokeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create(
            username="smoke-admin", auth_type="email",
            user_role=UserRoles.SUPER_ADMIN.value,
        )
        cls.assistant = Assistant.objects.create(name="A1", user=cls.admin)
        cls.conversation = Conversation.objects.create(assistant=cls.assistant)
        cls.lead = Lead.objects.create(assistant=cls.assistant, full_name="L")
        cls.txn = Transaction.objects.create(amount=1, status=PaymentStatuses.SUCCESS.value)
        cls.sub = Subscription.objects.create(status=SubscriptionStatuses.ACTIVE.value)
        cls.feature = Feature.objects.create(name="F")
        cls.package = PricingPackage.objects.create(name="P", price=1, request_count=1, duration_days=1)
        cls.template = PromptTemplate.objects.create(name="T", content="c")
        cls.integration = Integration.objects.create(name="I", assistant=cls.assistant)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def get(self, path):
        r = self.client.get(f"{BASE}{path}")
        self.assertEqual(r.status_code, 200, f"{path} -> {r.status_code} {r.content[:300]}")
        return r.json()

    # ---- plain paginated lists (DashboardListMixin) ----
    def test_plain_lists_paginated_envelope(self):
        for path in [
            "/leads/", "/audit-logs/", "/messages/", "/notifications/",
            "/balances/", "/cards/", "/features/", "/pricingpackages/",
            "/prompts/", "/assistantfiles/",
        ]:
            body = self.get(path)
            self.assertIn("results", body, path)
            self.assertIn("count", body, path)

    # ---- stats lists (DashboardStatsListMixin) ----
    def test_stats_lists_carry_stats_block(self):
        expected = {
            "/conversations/": {"total", "open", "escalated", "total_messages"},
            "/transactions/": {"total", "successful_total", "successful_count", "failed"},
            "/subscriptions/": {"total", "active", "expiring_soon", "cancelled"},
            "/integrations/": {"total", "active", "total_conversations", "total_leads"},
            "/assistants/": {"total", "active", "ai_enabled", "with_integrations"},
        }
        for path, keys in expected.items():
            body = self.get(path)
            self.assertIn("stats", body, path)
            self.assertEqual(set(body["stats"]), keys, path)
            self.assertIn("results", body, path)

    # ---- retrieve messages ----
    def test_retrieve_messages(self):
        cases = [
            (f"/users/{self.admin.id}/", "User retrieved successfully"),
            (f"/transactions/{self.txn.id}/", "Transaction retrieved successfully"),
            (f"/subscriptions/{self.sub.id}/", "Subscription retrieved successfully"),
            (f"/integrations/{self.integration.id}/", "Integration retrieved successfully"),
            (f"/leads/{self.lead.id}/", "Lead retrieved successfully"),
            (f"/features/{self.feature.id}/", "Feature retrieved"),
            (f"/pricingpackages/{self.package.id}/", "Pricing package retrieved"),
            (f"/prompts/{self.template.id}/", "Prompt template retrieved successfully"),
        ]
        for path, message in cases:
            body = self.get(path)
            self.assertEqual(body.get("message"), message, path)
            self.assertIn("data", body, path)

    # ---- update messages (partial) ----
    def test_update_messages(self):
        cases = [
            (f"/transactions/{self.txn.id}/", {"payment_method": "click"}, "Transaction updated successfully"),
            (f"/leads/{self.lead.id}/", {"full_name": "L2"}, "Lead updated successfully"),
            (f"/features/{self.feature.id}/", {"name": "F2"}, "Feature updated"),
            (f"/prompts/{self.template.id}/", {"name": "T2"}, "Prompt template updated successfully"),
            (f"/conversations/{self.conversation.id}/", {"username": "u"}, "Conversation updated successfully"),
        ]
        for path, payload, message in cases:
            r = self.client.patch(f"{BASE}{path}", payload, format="json")
            self.assertEqual(r.status_code, 200, f"{path} -> {r.content[:300]}")
            self.assertEqual(r.json().get("message"), message, path)

    # ---- create messages ----
    def test_create_messages(self):
        cases = [
            ("/features/", {"name": "NF"}, "Feature created"),
            ("/prompts/", {"name": "NT", "content": "c"}, "Prompt template created successfully"),
            ("/pricingpackages/", {"name": "NP", "price": 2, "request_count": 2, "duration_days": 2},
             "Pricing package created"),
        ]
        for path, payload, message in cases:
            r = self.client.post(f"{BASE}{path}", payload, format="json")
            self.assertEqual(r.status_code, 201, f"{path} -> {r.content[:300]}")
            self.assertEqual(r.json().get("message"), message, path)

    # ---- destroy messages ----
    def test_destroy_messages(self):
        feature = Feature.objects.create(name="DelF")
        template = PromptTemplate.objects.create(name="DelT", content="c")
        conversation = Conversation.objects.create(assistant=self.assistant)
        integration = Integration.objects.create(name="DelI", assistant=self.assistant)
        package = PricingPackage.objects.create(name="DelP", price=1, request_count=1, duration_days=1)
        txn = Transaction.objects.create(amount=2, status=PaymentStatuses.SUCCESS.value)
        cases = [
            (f"/features/{feature.id}/", "Feature deleted"),
            (f"/prompts/{template.id}/", "Prompt template deleted successfully"),
            (f"/conversations/{conversation.id}/", "Conversation deleted successfully"),
            (f"/integrations/{integration.id}/", "Integration deleted successfully"),
            (f"/pricingpackages/{package.id}/", "Pricing package deleted"),
            (f"/transactions/{txn.id}/", "Transaction deleted successfully"),
        ]
        for path, message in cases:
            r = self.client.delete(f"{BASE}{path}")
            self.assertEqual(r.status_code, 200, f"{path} -> {r.content[:300]}")
            self.assertEqual(r.json().get("message"), message, path)

    # ---- bespoke endpoints that were NOT converted ----
    def test_untouched_endpoints_still_answer(self):
        for path in ["/dashboard/", "/dashboard/enhanced/", "/statistics/",
                     "/statistics/ai-costs/", "/search/?q=sm", "/users/",
                     "/leads/stats/"]:
            self.get(path)

    def test_pricing_package_update_returns_stats_serializer(self):
        r = self.client.patch(
            f"{BASE}/pricingpackages/{self.package.id}/", {"name": "P9"}, format="json",
        )
        self.assertEqual(r.status_code, 200, r.content[:300])
        body = r.json()
        self.assertEqual(body["message"], "Pricing package updated")
        self.assertIn("subscribers_count", body["data"])

    def test_conversation_detail_get_is_unwrapped(self):
        """This view never had a retrieve() override — DRF's bare body is the contract."""
        r = self.client.get(f"{BASE}/conversations/{self.conversation.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("thread_id", r.json())

    def test_csv_exports(self):
        for path in ["/users/export/", "/transactions/export/", "/leads/export/"]:
            r = self.client.get(f"{BASE}{path}")
            self.assertEqual(r.status_code, 200, path)
            self.assertEqual(r["Content-Type"], "text/csv", path)
