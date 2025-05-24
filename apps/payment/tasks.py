from datetime import timedelta

from celery import shared_task
from django.template.defaulttags import now

from apps.user.models import User
from shared.addons.payment import process_subscription_payment
from shared.addons.utils import notify_user_about_failed_payment, restrict_user_account
from shared.addons.enums import PricingPackageType


@shared_task
def process_monthly_subscriptions():
    """Process subscription payments for all active users."""
    users = User.objects.filter(subscription__is_subscription_active=True, subscription__next_payment_date__lte=now().date())

    for user in users:
        success, message = process_subscription_payment(user)
        if not success:
            # Increment retry count and set next payment date to the next day
            subscription = user.subscription
            subscription.retry_count += 1
            subscription.next_payment_date = now().date() + timedelta(days=1)
            subscription.save()

            notify_user_about_failed_payment(user)

            # Restrict account after 3 failed attempts
            if subscription.retry_count >= 3:
                restrict_user_account(user)
@shared_task
def process_daily_used_request_token():
    print("Process daily used request token")
    users = User.objects.filter(subscription__is_subscription_active=True)
    for user in users:
        if user.subscription.pricing_package.type == PricingPackageType.FREE.value:
            user.subscription.used_request_count = 0
        elif user.subscription.pricing_package.type == PricingPackageType.CUSTOM.value:
            user.subscription.used_request_count = 0
        elif user.subscription.pricing_package.type == PricingPackageType.PRO.value:
            user.subscription.used_request_count = 0
        user.subscription.save()