import logging

from django.db.models import Q
from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from apps.user.models import User
from apps.shared.addons.enums import PricingPackageType
from apps.payment.services.billing import process_subscription_payment, create_notification
from apps.user.services.notifications import notify_user_about_failed_payment, restrict_user_account
from apps.payment.models import RetryPayment
from django.db import transaction

logger = logging.getLogger(__name__)


@shared_task
def process_monthly_subscriptions():
    """Process subscription payments for all active users."""
    users = User.objects.filter(Q(subscription__next_payment_date__lte=timezone.now().date()))
    logger.info(f"Found {len(users)} users to process monthly subscriptions")

    for user in users:
        try:
            with transaction.atomic():
                if user.subscription and user.subscription.pricing_package.type == PricingPackageType.FREE.value:
                    subscription = user.subscription
                    subscription.end_date = timezone.now() + timedelta(days=30)
                    subscription.remained_request_count = user.subscription.pricing_package.request_count
                    subscription.save()
                    continue
                subscription = user.subscription
                if subscription.auto_renew == False:
                    if subscription.retry_count <= 3:
                        create_notification(user, "Obuna tarifingiz tugadi. Iltimos, platformaga kirib, to'lovni qo'lda kiriting.")
                else:
                    success, message = process_subscription_payment(user)
                    logger.info(f"Subscription payment result for user {user.id}: success={success}, message={message}")
                    if not success:
                        if subscription.retry_count > 3:
                            restrict_user_account(user)
                        if subscription.retry_count <= 3:
                            notify_user_about_failed_payment(user)
                            logger.warning(f"Failed to process subscription payment for user {user.id}")
                            create_notification(user, f"Obuna tarifingiz tugadi. Sizda {message} xatolik yuz berdi.")
                            subscription.retry_count += 1
                            subscription.save()

                            RetryPayment.objects.create(
                                subscription=subscription,
                                amount=subscription.pricing_package.price,
                                status='failed',
                                retry_date=timezone.now(),
                                error_message=message
                            )
                    else:
                        logger.info(f"Successfully processed subscription payment for user {user.id}")
                        create_notification(user, "Obuna tarifingiz muvaffaqiyatli amalga oshirildi.")
        except Exception as e:
            logger.error(f"Error processing subscription for user {user.id}: {e}", exc_info=True)
            # Optionally, notify admin or log error
