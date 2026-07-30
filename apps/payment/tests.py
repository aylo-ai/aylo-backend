"""Payment endpoint tests.

Two groups:

* Cross-tenant scoping — regressions for the 2026-07-22 investigation: P1 (card
  delete IDOR), P2 (default-card IDOR), P3 (retry-payment list enumeration) and
  the unscoped auto-renew update. Every mutation and read must be limited to
  `request.user`'s own billing objects.
* Plan selection — the pricing-package list and `subscriptions/create/` that the
  post-sign-up "choose a plan" step drives.
"""
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from apps.payment.models import Card, PricingPackage, RetryPayment, Subscription
from apps.user.models import User
from apps.shared.addons.enums import (
    PaymentStatuses,
    PricingPackageType,
    SubscriptionStatuses,
    UserRoles,
)


class CardScopingTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create(username="card-owner", auth_type="email")
        self.attacker = User.objects.create(username="card-attacker", auth_type="email")
        self.card = Card.objects.create(
            user=self.owner,
            card_token="payme-token",
            card_number="8600123412341234",
            expiry_date="12/30",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.attacker)

    def test_cannot_delete_another_users_card(self):
        with mock.patch("apps.payment.views.remove_payme_card") as remove:
            response = self.client.delete(f"/api/v1/payment/cards/{self.card.id}/remove/")
        self.assertEqual(response.status_code, 400)
        remove.assert_not_called()
        self.assertTrue(Card.objects.filter(id=self.card.id).exists())

    def test_owner_can_delete_their_own_card(self):
        self.client.force_authenticate(self.owner)
        with mock.patch("apps.payment.views.remove_payme_card", return_value=True):
            response = self.client.delete(f"/api/v1/payment/cards/{self.card.id}/remove/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Card.objects.filter(id=self.card.id).exists())

    def test_cannot_set_another_users_card_as_default(self):
        response = self.client.post(f"/api/v1/payment/cards/{self.card.id}/set-default/")
        self.assertEqual(response.status_code, 400)


class RetryPaymentScopingTests(TestCase):
    def setUp(self):
        self.subscription = Subscription.objects.create(
            status=SubscriptionStatuses.ACTIVE.value,
        )
        self.owner = User.objects.create(
            username="sub-owner", auth_type="email", subscription=self.subscription,
        )
        self.attacker = User.objects.create(username="sub-attacker", auth_type="email")
        self.retry = RetryPayment.objects.create(
            subscription=self.subscription,
            amount=100000,
            status=PaymentStatuses.FAILED.value,
        )
        self.client = APIClient()

    def url(self):
        return f"/api/v1/payment/retry-payments/subscription/{self.subscription.id}/"

    def test_stranger_sees_no_retry_payments(self):
        self.client.force_authenticate(self.attacker)
        response = self.client.get(self.url())
        self.assertNotContains(response, str(self.retry.id), status_code=response.status_code)

    def test_owner_sees_their_retry_payments(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get(self.url())
        self.assertContains(response, str(self.retry.id))


class AutoRenewScopingTests(TestCase):
    def setUp(self):
        self.subscription = Subscription.objects.create(
            status=SubscriptionStatuses.ACTIVE.value, auto_renew=True,
        )
        self.owner = User.objects.create(
            username="renew-owner", auth_type="email", subscription=self.subscription,
        )
        self.attacker = User.objects.create(username="renew-attacker", auth_type="email")
        self.client = APIClient()

    def test_stranger_cannot_flip_auto_renew(self):
        self.client.force_authenticate(self.attacker)
        response = self.client.patch(
            f"/api/v1/payment/subscriptions/{self.subscription.id}/",
            {"auto_renew": False},
            format="json",
        )
        self.assertEqual(response.status_code, 404)
        self.subscription.refresh_from_db()
        self.assertTrue(self.subscription.auto_renew)


CREATE_URL = "/api/v1/payment/subscriptions/create/"


class PlanSelectionTests(TestCase):
    """`subscriptions/create/` — the step a new user lands on after sign-up."""

    def setUp(self):
        self.free = PricingPackage.objects.create(
            name="Free", type=PricingPackageType.FREE.value, price=0,
            request_count=100, duration_days=30,
        )
        self.paid = PricingPackage.objects.create(
            name="Basic", type=PricingPackageType.CUSTOM.value, price=199000,
            request_count=2000, duration_days=30,
        )
        self.user = User.objects.create(username="new-signup", auth_type="email")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def select(self, package):
        return self.client.post(
            CREATE_URL, {"pricing_package": str(package.id)}, format="json",
        )

    def test_the_package_list_is_readable_before_signing_in(self):
        response = APIClient().get("/api/v1/payment/pricing-packages/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Free", [package["name"] for package in response.data])

    def test_choosing_a_free_plan_activates_it_immediately(self):
        response = self.select(self.free)

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        subscription = self.user.subscription
        self.assertIsNotNone(subscription)
        self.assertEqual(subscription.status, SubscriptionStatuses.ACTIVE.value)
        self.assertEqual(subscription.remained_request_count, 100)
        self.assertFalse(subscription.auto_renew)
        self.assertIsNone(subscription.next_payment_date)

    def test_choosing_a_paid_plan_waits_for_payment(self):
        response = self.select(self.paid)

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        subscription = self.user.subscription
        self.assertEqual(subscription.status, SubscriptionStatuses.INACTIVE.value)
        self.assertTrue(subscription.auto_renew)
        self.assertIsNotNone(subscription.next_payment_date)

    def test_the_response_names_the_plan_that_was_chosen(self):
        """The write-only UUID has to come back resolved, or the confirmation
        screen would need a second round-trip to name the plan."""
        response = self.select(self.paid)

        self.assertEqual(response.data["data"]["pricing_package"]["name"], "Basic")

    def test_a_second_plan_cannot_be_stacked_on_an_active_one(self):
        self.select(self.free)

        response = self.select(self.paid)

        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.subscription.pricing_package, self.free)

    def test_an_unpaid_plan_can_still_be_swapped(self):
        """Picking a paid plan and not paying must not trap the account."""
        self.select(self.paid)

        response = self.select(self.free)

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.subscription.pricing_package, self.free)
        self.assertEqual(
            self.user.subscription.status, SubscriptionStatuses.ACTIVE.value
        )

    def test_an_unknown_package_is_a_clean_400(self):
        response = self.client.post(
            CREATE_URL,
            {"pricing_package": "00000000-0000-0000-0000-000000000000"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.subscription)

    def test_a_retired_package_cannot_be_chosen(self):
        self.paid.is_active = False
        self.paid.save()

        response = self.select(self.paid)

        self.assertEqual(response.status_code, 400)

    def test_choosing_a_plan_requires_authentication(self):
        response = APIClient().post(
            CREATE_URL, {"pricing_package": str(self.free.id)}, format="json",
        )

        self.assertEqual(response.status_code, 401)


class PricingPackageValidationTests(TestCase):
    """Regressions for the `PricingPackageSerializer.validate` defects: it
    indexed `attrs` for optional fields (a 500 on any partial payload) and
    compared the discount the wrong way round (rejecting every real discount).
    """

    def setUp(self):
        self.admin = User.objects.create(
            username="pricing-admin", auth_type="email",
            user_role=UserRoles.ADMIN.value,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def payload(self, **overrides):
        data = {"name": "Starter", "price": 100000, "request_count": 500,
                "duration_days": 30}
        data.update(overrides)
        return data

    def test_a_package_without_a_discount_is_accepted(self):
        response = self.client.post(
            "/api/v1/payment/pricing-packages/", self.payload(), format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(PricingPackage.objects.filter(name="Starter").exists())

    def test_a_discount_below_the_price_is_accepted(self):
        response = self.client.post(
            "/api/v1/payment/pricing-packages/",
            self.payload(discount_price=80000),
            format="json",
        )

        self.assertEqual(response.status_code, 201)

    def test_a_discount_above_the_price_is_rejected(self):
        response = self.client.post(
            "/api/v1/payment/pricing-packages/",
            self.payload(discount_price=120000),
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_a_negative_price_is_rejected(self):
        response = self.client.post(
            "/api/v1/payment/pricing-packages/",
            self.payload(price=-1),
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_a_partial_update_does_not_need_the_price_resent(self):
        package = PricingPackage.objects.create(
            name="Starter", price=100000, request_count=500, duration_days=30,
        )

        response = self.client.patch(
            f"/api/v1/payment/pricing-packages/{package.id}/",
            {"description": "renamed"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
