from django.db.models import Q
from celery import shared_task
from django.utils import timezone

from apps.user.models import User
from apps.shared.addons.enums import PricingPackageType
from shared.addons.payment import process_subscription_payment
from shared.addons.utils import notify_user_about_failed_payment, restrict_user_account
from apps.payment.models import RetryPayment


@shared_task
def process_monthly_subscriptions():
    """Process subscription payments for all active users."""
    users = User.objects.filter(Q(subscription__next_payment_date__lte=timezone.now().date()) & 
                                ~Q(subscription__pricing_package__type=PricingPackageType.FREE.value))
    print(f"[+] Found {len(users)} users to process monthly subscriptions")

    for user in users:
        success, message = process_subscription_payment(user)
        print(f"Success: {success}, Message: {message}")
        if not success:
            print("Failed to process subscription payment")
            # Increment retry count and set next payment date to the next day
            subscription = user.subscription
            subscription.retry_count += 1
            subscription.save()

            RetryPayment.objects.create(
                subscription=subscription,
                amount=subscription.pricing_package.price,
                status='failed',
                retry_date=timezone.now(),
                error_message=message
            )
            if subscription.retry_count >= 3:
                restrict_user_account(user)
            else:
                notify_user_about_failed_payment(user)
