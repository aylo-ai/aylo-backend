"""User notification helpers.

This module used to also hold the Assistants-API chat pipeline. That has been
replaced by `shared.ai_service.agent`; only the notification helpers remain.
"""
from django.utils.translation import gettext_lazy as _
from django.conf import settings
from django.core.mail import send_mail

from shared.addons.enums import SubscriptionStatuses, NotificationTypes
from shared.addons.verification import send_playmobile_sms

# Re-exported: several modules import send_telegram_message from here.
from shared.addons.telegram import send_telegram_message  # noqa: F401


def notify_user_about_failed_payment(user):
    message = (
        f"Hurmatli {user.first_name}, sizning repli.uz dagi obuna tugadi. "
        "Iltimos, platformaga kirib, to'lovni qayta amalga oshiring."
    )
    print(f"Payment failure notification message: {user.phone_number} or {user.email}, {message}")

    if user.phone_number:
        response = send_playmobile_sms(user.phone_number, message)
        print(f"Sms response: {response}")
    elif user.email:
        response = send_email_message(user.email, user)
        print(f"Email response: {response}")


def send_email_message(email, user):
    try:
        print(f"Sending email message to: {email}")
        subject = _("Warning: Your subscription has expired")
        message = _(
            "Hurmatli {user.first_name}, sizning repli.uz dagi obuna to'lovingiz "
            "muvaffaqiyatsiz amalga oshirildi. Iltimos, platformaga kirib, "
            "to'lovni qayta amalga oshiring."
        ).format(user=user)
        from_email = settings.EMAIL_HOST_USER
        print(f"from_email: {from_email}")
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
            f"Hurmatli {user.first_name}, sizning repli.uz dagi so'rovlar soningiz "
            f"{count} tadan kam qoldi. Iltimos, platformaga kirib, obunangizni yangilang."
        ),
        type=NotificationTypes.WARNING.value,
    )
    print("Notification created to notify user about low request token count")
