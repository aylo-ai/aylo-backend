import hmac
import logging
import os
import requests
from apps.shared import http
from random import randint

from config.settings import redis_connection
from apps.shared.addons.payloads import get_playmobile_payload

from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)

PLAY_MOBILE_URL: str = os.environ['PLAY_MOBILE_URL']
PLAY_MOBILE_LOGIN: str = os.environ['PLAY_MOBILE_LOGIN']
PLAY_MOBILE_PASSWORD: str = os.environ['PLAY_MOBILE_PASSWORD']
originator: str = os.environ['PLAY_MOBILE_ORIGINATOR']

# After this many wrong guesses the code is thrown away, so a leaked or
# brute-forced OTP cannot be tried indefinitely within its validity window.
MAX_VERIFY_ATTEMPTS = 5

# Minimum gap between two codes sent to the same identifier. The SMS path is
# already covered by its 60s code TTL; email codes live for 5 minutes, so
# without this an attacker could flood a victim's inbox (and our sending
# reputation) with one request per second.
RESEND_COOLDOWN = 60


def generate_code():
    return randint(100000, 999999)


def _codes_match(stored, supplied):
    """Compare an OTP without leaking its contents through timing."""
    if stored is None:
        return False
    if isinstance(stored, bytes):
        stored = stored.decode("utf-8")
    return hmac.compare_digest(str(stored), str(supplied))


def _register_failed_attempt(key):
    """Count a wrong guess; drop the code once too many have piled up.

    Returns True if the code is still live, False if this attempt exhausted it.
    """
    attempts_key = f"{key}_attempts"
    attempts = redis_connection.incr(attempts_key)
    if attempts == 1:
        # Tie the counter's lifetime to the code so it cannot outlive it.
        redis_connection.expire(attempts_key, time=300)
    if attempts >= MAX_VERIFY_ATTEMPTS:
        redis_connection.delete(key)
        redis_connection.delete(attempts_key)
        return False
    return True


def _clear_attempts(key):
    redis_connection.delete(f"{key}_attempts")


def send_playmobile_sms(phone_number, message):
    # Send SMS
    message_id = f"aylo_{randint(100000, 999999)}"
    payload = get_playmobile_payload(phone_number, message_id, originator, message)
    try:
        response = http.post(
            PLAY_MOBILE_URL,
            json=payload,
            auth=(PLAY_MOBILE_LOGIN, PLAY_MOBILE_PASSWORD),
            timeout=(30, 60)  # 10s connect timeout, 30s read timeout
        )
        logger.info("SMS provider responded with status %s", response.status_code)
        if response.status_code == 200:
            return True, "SMS successfully sent"
        return False, f"Failed with status: {response.status_code}"
    except requests.exceptions.ConnectTimeout:
        logger.warning("Connect timeout to SMS provider %s", PLAY_MOBILE_URL)
        return False, "Connection timed out"
    except Exception as e:
        logger.exception("Unexpected error during SMS sending")
        return False, f"Unexpected error: {str(e)}"

def send_code(phone_number):
    if redis_connection.get(phone_number):
        return False, "Code already sent"
    code = generate_code()
    message = f"Aylo.uz! Sizning tasdiqlash kodingiz - {code}\n"
    success, message = send_playmobile_sms(phone_number, message)
    # success, message = True, "Code sent successfully"
    if not success:
        return False, message
    redis_connection.set(phone_number, code)
    redis_connection.expire(phone_number, time=60)
    return True, "Code sent successfully"


def check_verification_status(phone_number):
    verified_phone = redis_connection.get(f"{phone_number}_verified")
    if not verified_phone:
        return False, "Phone number must be verified first"
    if verified_phone.decode('utf-8') != "True":
        return False, "Phone number is not verified"
    return True, "Phone number is verified"


def verify_code_cache(phone_number, code):
    data = redis_connection.get(phone_number)
    if not data:
        return False, "Code expired"
    if _codes_match(data, code):
        redis_connection.set(f"{phone_number}_verified", "True")
        redis_connection.expire(f"{phone_number}_verified", time=180)
        redis_connection.delete(phone_number)
        _clear_attempts(phone_number)
        return True, "Code verified successfully"
    if not _register_failed_attempt(phone_number):
        return False, "Too many incorrect attempts, request a new code"
    return False, "Code is incorrect"


<<<<<<< HEAD
def send_sms_text(phone_number, text):
    message_id = f"aylo_{randint(100000, 999999)}"
    payload = get_playmobile_payload(phone_number, message_id, originator, text)
    response = http.post(
        PLAY_MOBILE_URL,
        json=payload,
        auth=(PLAY_MOBILE_LOGIN, PLAY_MOBILE_PASSWORD),
        timeout=60
    )
    return response if response.status_code == 200 else None


=======
>>>>>>> 473f4c3bed1052b8f0214fd63847c983cff0e728
EMAIL_CODE_TTL = 300  # seconds the emailed code stays valid


def send_email_code(email):
    """Email a fresh OTP. Returns (ok, user-facing message).

    The code is only stored once delivery has succeeded, so a failed send never
    replaces a code the user already holds with one they will never receive.
    """
    cooldown_key = f"{email}_cooldown"
    if redis_connection.get(cooldown_key):
        return False, _("Verification code already sent")

    code = generate_code()
    try:
        html_message = render_to_string(
            'verification_email.html',
            {
                'code': code,
                'expiry_minutes': EMAIL_CODE_TTL // 60,
                'year': timezone.now().year,
                'subject': "Verification Code",
            }
        )

        send_mail(
            subject=_("Verification Code"),
            message=_("Your verification code is: {}").format(code),
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[email],
            html_message=html_message,
            fail_silently=False,
        )
    except Exception:
        # The exception text can carry SMTP host/credential detail, so it is
        # logged rather than returned to the caller.
        logger.exception("Failed to send the verification email")
        return False, _("Failed to send verification code")

    redis_connection.setex(email, EMAIL_CODE_TTL, code)
    redis_connection.setex(cooldown_key, RESEND_COOLDOWN, "1")
    return True, _("Verification code sent to your email")


def verify_email_code(email, code):
    try:
        stored_code = redis_connection.get(email)

        if not stored_code:
            return False, _("Verification code expired or not found")

        if _codes_match(stored_code, code):
            # Mark the address verified for as long as the code would have lived,
            # then burn the code so it cannot be replayed.
            redis_connection.setex(f"{email}_verified", EMAIL_CODE_TTL, "true")
            redis_connection.delete(email)
            _clear_attempts(email)
            return True, _("Email verified successfully")

        if not _register_failed_attempt(email):
            return False, _("Too many incorrect attempts, request a new code")
        return False, _("Invalid verification code")

    except Exception:
        logger.exception("Failed to verify the email code")
        return False, _("Failed to verify code")


def is_email_verified(email):
    try:
        return bool(redis_connection.get(f"{email}_verified"))
    except Exception:
        return False