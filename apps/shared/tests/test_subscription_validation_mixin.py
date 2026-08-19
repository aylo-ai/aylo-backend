from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.payment.models import Subscription
from apps.shared.addons.enums import SubscriptionStatuses
from apps.shared.addons.validations import CustomValidationError
from apps.shared.mixins import SubscriptionValidationMixin


class _Validator(SubscriptionValidationMixin):
    pass


class SubscriptionValidationMixinTests(TestCase):
    def setUp(self):
        self.validator = _Validator()

    def test_no_subscription_reports_choose_a_plan(self):
        with self.assertRaises(CustomValidationError) as ctx:
            self.validator.validate_subscription(None)
        self.assertIn("obuna paketini tanlang", str(ctx.exception.detail))

    def test_cancelled_subscription_is_blocked_even_with_tokens_left(self):
        subscription = Subscription.objects.create(
            status=SubscriptionStatuses.CANCELLED.value,
            remained_request_count=500,
            next_payment_date=timezone.now().date() + timedelta(days=10),
        )
        with self.assertRaises(CustomValidationError) as ctx:
            self.validator.validate_subscription(subscription)
        self.assertIn("bekor qilingan", str(ctx.exception.detail))

    def test_inactive_never_paid_reports_payment_not_processed(self):
        subscription = Subscription.objects.create(
            status=SubscriptionStatuses.INACTIVE.value,
            remained_request_count=1000,
            last_payment_date=None,
        )
        with self.assertRaises(CustomValidationError) as ctx:
            self.validator.validate_subscription(subscription)
        self.assertIn("To'lov hali amalga oshirilmagan", str(ctx.exception.detail))

    def test_inactive_previously_paid_reports_not_active(self):
        subscription = Subscription.objects.create(
            status=SubscriptionStatuses.INACTIVE.value,
            remained_request_count=0,
            last_payment_date=timezone.now().date() - timedelta(days=40),
        )
        with self.assertRaises(CustomValidationError) as ctx:
            self.validator.validate_subscription(subscription)
        self.assertIn("obunangiz faol emas", str(ctx.exception.detail))

    def test_active_but_exhausted_reports_tokens_used_up(self):
        subscription = Subscription.objects.create(
            status=SubscriptionStatuses.ACTIVE.value,
            remained_request_count=0,
            last_payment_date=timezone.now().date(),
            next_payment_date=timezone.now().date() + timedelta(days=10),
        )
        with self.assertRaises(CustomValidationError) as ctx:
            self.validator.validate_subscription(subscription)
        self.assertIn("tokeni tugagan", str(ctx.exception.detail))

    def test_active_but_past_due_reports_expired(self):
        subscription = Subscription.objects.create(
            status=SubscriptionStatuses.ACTIVE.value,
            remained_request_count=50,
            last_payment_date=timezone.now().date() - timedelta(days=40),
            next_payment_date=timezone.now().date() - timedelta(days=1),
        )
        with self.assertRaises(CustomValidationError) as ctx:
            self.validator.validate_subscription(subscription)
        self.assertIn("muddati tugagan", str(ctx.exception.detail))

    def test_active_with_tokens_and_future_date_passes(self):
        subscription = Subscription.objects.create(
            status=SubscriptionStatuses.ACTIVE.value,
            remained_request_count=50,
            last_payment_date=timezone.now().date(),
            next_payment_date=timezone.now().date() + timedelta(days=10),
        )
        result = self.validator.validate_subscription(subscription)
        self.assertEqual(result, subscription)

    def test_active_with_no_next_payment_date_passes(self):
        subscription = Subscription.objects.create(
            status=SubscriptionStatuses.ACTIVE.value,
            remained_request_count=50,
            last_payment_date=None,
            next_payment_date=None,
        )
        result = self.validator.validate_subscription(subscription)
        self.assertEqual(result, subscription)
