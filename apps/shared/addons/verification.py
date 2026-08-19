import hmac
import logging
import os
from random import randint

import requests
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.shared import http
from apps.shared.addons.payloads import get_playmobile_payload
from config.settings import redis_connection

logger = logging.getLogger(__name__)

PLAY_MOBILE_URL: str = os.environ['PLAY_MOBILE_URL']
PLAY_MOBILE_LOGIN: str = os.environ['PLAY_MOBILE_LOGIN']
PLAY_MOBILE_PASSWORD: str = os.environ['PLAY_MOBILE_PASSWORD']
originator: str = os.environ['PLAY_MOBILE_ORIGINATOR']

MAX_VERIFY_ATTEMPTS = 5

RESEND_COOLDOWN = 60


def generate_code():
    return randint(100000, 999999)


def _codes_match(stored, supplied):
    if stored is None:
        return False
    if isinstance(stored, bytes):
        stored = stored.decode("utf-8")
    return hmac.compare_digest(str(stored), str(supplied))


def _register_failed_attempt(key):
    attempts_key = f"{key}_attempts"
    attempts = redis_connection.incr(attempts_key)
    if attempts == 1:
        redis_connection.expire(attempts_key, time=300)
    if attempts >= MAX_VERIFY_ATTEMPTS:
        redis_connection.delete(key)
        redis_connection.delete(attempts_key)
        return False
    return True


def _clear_attempts(key):
    redis_connection.delete(f"{key}_attempts")


def send_playmobile_sms(phone_number, message):
    message_id = f"aylo_{randint(100000, 999999)}"
    payload = get_playmobile_payload(phone_number, message_id, originator, message)
    try:
        response = http.post(
            PLAY_MOBILE_URL,
            json=payload,
            auth=(PLAY_MOBILE_LOGIN, PLAY_MOBILE_PASSWORD),
            timeout=(30, 60)
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


EMAIL_CODE_TTL = 300


def send_email_code(email):
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
