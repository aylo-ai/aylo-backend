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

from django.core.cache import cache
from django.test import TestCase, override_settings
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


class SubscriptionCancellationTests(TestCase):
    """`subscriptions/cancel/` used to set INACTIVE, the same status a never-paid
    or lapsed subscription has — so `validate_subscription()` couldn't tell a
    self-cancelled user apart from one who simply hasn't paid yet, and reported
    the wrong reason. It must set CANCELLED, matching the dashboard's admin
    cancel path (`DashboardSubscriptionCancel`).
    """

    def setUp(self):
        self.subscription = Subscription.objects.create(
            status=SubscriptionStatuses.ACTIVE.value,
            remained_request_count=500,
        )
        self.user = User.objects.create(
            username="cancel-me", auth_type="email", subscription=self.subscription,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_cancelling_sets_cancelled_not_inactive(self):
        response = self.client.post(
            "/api/v1/payment/subscriptions/cancel/",
            {"cancellation_reason": "too expensive"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, SubscriptionStatuses.CANCELLED.value)

    def test_cancelling_without_a_reason_is_a_clean_400(self):
        response = self.client.post("/api/v1/payment/subscriptions/cancel/", {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, SubscriptionStatuses.ACTIVE.value)


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


# Throttling keeps its history in the default cache, which the test runner does
# not reset between tests; the payment endpoints below are now scope-throttled,
# so make the limit a no-op wherever the rate itself is not what's under test.
NO_THROTTLE = override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}
)


@NO_THROTTLE
class CardTokenBindingTests(TestCase):
    """`POST /payment/payme/card/add/` takes a Payme card token straight from
    the request body. Payme's `cards.check` only answers "is this token live
    and rebillable" — never "does it belong to the caller" — so without a local
    ownership check anyone holding a token could bind the victim's card to
    their own account and then charge it through `PayWithCardSerializer`, which
    authorises on the local `Card.user` row alone.
    """

    URL = "/api/v1/payment/payme/card/add/"

    def setUp(self):
        self.victim = User.objects.create(username="token-victim", auth_type="email")
        self.attacker = User.objects.create(username="token-attacker", auth_type="email")
        self.victim_card = Card.objects.create(
            user=self.victim,
            card_token="victim-payme-token",
            card_number="8600111122223333",
            expiry_date="12/30",
            is_verified=True,
        )
        self.client = APIClient()

    @staticmethod
    def payme_reply(number="8600444455556666", token="fresh-payme-token"):
        reply = mock.Mock()
        reply.json.return_value = {
            "result": {
                "card": {
                    "number": number,
                    "expire": "1230",
                    "token": token,
                    "verify": True,
                    "recurrent": True,
                }
            }
        }
        return reply

    def test_a_token_already_bound_to_someone_else_is_refused(self):
        self.client.force_authenticate(self.attacker)
        with mock.patch(
            "apps.payment.serializers.check_payme_card_token",
            return_value=self.payme_reply(token="victim-payme-token"),
        ) as check:
            response = self.client.post(
                self.URL, {"card_token": "victim-payme-token"}, format="json",
            )

        self.assertEqual(response.status_code, 400)
        check.assert_not_called()
        self.assertFalse(Card.objects.filter(user=self.attacker).exists())
        self.assertEqual(Card.objects.filter(card_token="victim-payme-token").count(), 1)

    def test_the_owner_can_still_save_a_card(self):
        self.client.force_authenticate(self.victim)
        with mock.patch(
            "apps.payment.serializers.check_payme_card_token",
            return_value=self.payme_reply(),
        ):
            response = self.client.post(
                self.URL, {"card_token": "fresh-payme-token", "name": "Salary"},
                format="json",
            )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            Card.objects.filter(user=self.victim, card_token="fresh-payme-token").exists()
        )

    def test_the_response_never_echoes_the_card_token(self):
        self.client.force_authenticate(self.victim)
        with mock.patch(
            "apps.payment.serializers.check_payme_card_token",
            return_value=self.payme_reply(),
        ):
            response = self.client.post(
                self.URL, {"card_token": "fresh-payme-token"}, format="json",
            )

        self.assertEqual(response.status_code, 201)
        self.assertNotIn("card_token", response.data["data"])
        self.assertNotIn("fresh-payme-token", str(response.data))


@NO_THROTTLE
class CardWriteProtectionTests(TestCase):
    """`is_verified` is the gate `PayWithCardSerializer.validate()` and
    `process_subscription_payment()` both check before charging a card, and
    `card_number` is the masked PAN shown against a transaction. Neither may be
    settable by the client that owns the row.
    """

    def setUp(self):
        self.owner = User.objects.create(username="patch-owner", auth_type="email")
        self.attacker = User.objects.create(username="patch-attacker", auth_type="email")
        self.card = Card.objects.create(
            user=self.owner,
            card_token="patch-token",
            card_number="8600123412341234",
            expiry_date="12/30",
            is_verified=False,
            name="Old",
        )
        self.url = f"/api/v1/payment/cards/{self.card.id}/"
        self.client = APIClient()

    def test_a_client_cannot_mark_its_own_card_verified(self):
        self.client.force_authenticate(self.owner)
        response = self.client.patch(
            self.url, {"is_verified": True, "card_number": "9999888877776666"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.card.refresh_from_db()
        self.assertFalse(self.card.is_verified)
        self.assertEqual(self.card.card_number, "8600********1234")

    def test_the_owner_can_still_rename_their_card(self):
        self.client.force_authenticate(self.owner)
        response = self.client.patch(self.url, {"name": "Salary"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.card.refresh_from_db()
        self.assertEqual(self.card.name, "Salary")

    def test_another_user_cannot_read_the_card(self):
        self.client.force_authenticate(self.attacker)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("8600", str(response.data["data"]))

    def test_another_user_cannot_patch_the_card(self):
        self.client.force_authenticate(self.attacker)
        response = self.client.patch(self.url, {"name": "stolen"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.card.refresh_from_db()
        self.assertEqual(self.card.name, "Old")

    def test_the_owner_can_read_their_own_card(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["id"], str(self.card.id))


class PaymentThrottleTests(TestCase):
    """`payme/get-verify-token/` makes Payme SMS a verification code to the
    phone registered against whatever PAN the caller typed — a third party's
    phone. `DEFAULT_THROTTLE_CLASSES` is `ScopedRateThrottle`, which is a no-op
    on any view that declares no `throttle_scope`, so before this scope existed
    the endpoint could be driven flat out.
    """

    URL = "/api/v1/payment/payme/get-verify-token/"

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create(username="throttled", auth_type="email")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_the_verify_code_endpoint_is_rate_limited(self):
        with mock.patch(
            "apps.payment.serializers.send_create_card_request",
            return_value={"result": {"card": {"token": "t"}}},
        ), mock.patch(
            "apps.payment.serializers.send_verify_code_request", return_value={},
        ):
            payload = {"number": "8600123412341234", "expire": "1230"}
            codes = [
                self.client.post(self.URL, payload, format="json").status_code
                for _ in range(12)
            ]

        self.assertIn(200, codes, "the endpoint must still work for a normal caller")
        self.assertIn(429, codes, "an unbounded caller must eventually be throttled")
