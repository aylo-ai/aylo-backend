"""User notification helpers.

This module used to also hold the Assistants-API chat pipeline. That has been
replaced by `shared.ai_service.agent`; only the notification helpers remain.
"""
import logging

from django.utils.translation import gettext_lazy as _
from django.conf import settings
from django.core.mail import send_mail

from apps.shared.addons.enums import SubscriptionStatuses, NotificationTypes
from apps.shared.addons.verification import send_playmobile_sms

# Re-exported: several modules import send_telegram_message from here.
from apps.integration.gateways.telegram import send_telegram_message  # noqa: F401

logger = logging.getLogger(__name__)


def notify_user_about_failed_payment(user):
    message = (
        f"Hurmatli {user.first_name}, sizning aylo.uz dagi obuna tugadi. "
        "Iltimos, platformaga kirib, to'lovni qayta amalga oshiring."
    ).format(user=user)
    logger.info("Sending payment failure notification to user %s", user.id)

    if user.phone_number:
        response = send_playmobile_sms(user.phone_number, message)
        logger.info("Sms response: %s", response)
    elif user.email:
        response = send_email_message(user.email, user)
        logger.info("Email response: %s", response)


def send_email_message(email, user):
    try:
        logger.info("Sending subscription warning email to user %s", user.id)
        subject = _("Warning: Your subscription has expired")
        message = _(
            "Hurmatli {user.first_name}, sizning aylo.uz dagi obuna to'lovingiz "
            "muvaffaqiyatsiz amalga oshirildi. Iltimos, platformaga kirib, "
            "to'lovni qayta amalga oshiring."
        ).format(user=user)
        from_email = settings.EMAIL_HOST_USER
        from django.template.loader import render_to_string

        html_message = render_to_string('warning_notification.html', {'user': user})

        send_mail(
            subject=subject,
            message=message,
            from_email=from_email,
            recipient_list=[email],
            html_message=html_message,
            fail_silently=False,
        )

        return True, _("Warning message sent to your email")

    except Exception as e:
        return False, _("Failed to send warning message: {}").format(str(e))


def restrict_user_account(user):
    """Restrict user's account due to failed payments."""
    subscription = user.subscription
    subscription.status = SubscriptionStatuses.INACTIVE.value
    subscription.save()


def notify_user_about_low_tokens(user, count):
    from apps.user.models import Notification

    Notification.objects.create(
        user=user,
        title=_("Low Token Count Warning"),
        content=_(
            f"Hurmatli {user.first_name}, sizning aylo.uz dagi so'rovlar soningiz "
            f"{count} tadan kam qoldi. Iltimos, platformaga kirib, obunangizni yangilang."
        ),
        type=NotificationTypes.WARNING.value,
    )
    logger.info("Low request token notification created for user %s", user.id)
