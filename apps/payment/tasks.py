from datetime import timedelta

from celery import shared_task
from django.template.defaulttags import now

from apps.user.models import User
from shared.addons.payment import process_subscription_payment
from shared.addons.utils import notify_user_about_failed_payment, restrict_user_account


@shared_task
def process_monthly_subscriptions():
    """Process subscription payments for all active users."""
    users = User.objects.filter(subscription__is_subscription_active=True, subscription__next_payment_date__lte=now().date())

    for user in users:
        success, message = process_subscription_payment(user)
        if not success:
            # Increment retry count and set next payment date to the next day
            user.subscription.retry_count += 1
            user.subscription.next_payment_date = now().date() + timedelta(days=1)
            user.subscription.save()

            notify_user_about_failed_payment(user)

            # Restrict account after 3 failed attempts
            if user.subscription.retry_count >= 3:
                restrict_user_account(user)
