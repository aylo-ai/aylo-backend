import logging
import os
import requests
from random import randint

from config.settings import redis_connection
from shared.addons.payloads import get_playmobile_payload

import random
import string
from django.core.mail import send_mail
from django.conf import settings
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)

PLAY_MOBILE_URL: str = os.environ['PLAY_MOBILE_URL']
PLAY_MOBILE_LOGIN: str = os.environ['PLAY_MOBILE_LOGIN']
PLAY_MOBILE_PASSWORD: str = os.environ['PLAY_MOBILE_PASSWORD']
originator: str = os.environ['PLAY_MOBILE_ORIGINATOR']

# After this many wrong guesses the code is thrown away, so a leaked or
# brute-forced OTP cannot be tried indefinitely within its validity window.
MAX_VERIFY_ATTEMPTS = 5


def generate_code():
    return randint(100000, 999999)


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


def clear_verified_flag(identifier):
    """Drop the 'verified' marker once it has been consumed by registration."""
    redis_connection.delete(f"{identifier}_verified")


def send_playmobile_sms(phone_number, message):
    # Send SMS
    message_id = f"repliuz_{randint(100000, 999999)}"
    payload = get_playmobile_payload(phone_number, message_id, originator, message)
    try:
        response = requests.post(
            PLAY_MOBILE_URL,
            json=payload,
            auth=(PLAY_MOBILE_LOGIN, PLAY_MOBILE_PASSWORD),
            timeout=(30, 60)  # 10s connect timeout, 30s read timeout
        )
        print(f"+] Response: {response.status_code} — {response.text}")
        if response.status_code == 200:
            return True, "SMS successfully sent"
        return False, f"Failed with status: {response.status_code}"
    except requests.exceptions.ConnectTimeout:
        print(f"[+] Connect timeout to {PLAY_MOBILE_URL}")
        return False, "Connection timed out"
    except Exception as e:
        print(f"[+] Unexpected error during SMS sending: {str(e)}")
        return False, f"Unexpected error: {str(e)}"

def send_code(phone_number):
    if redis_connection.get(phone_number):
        return False, "Code already sent"
    code = generate_code()
    message = f"Repli.uz! Sizning tasdiqlash kodingiz - {code}\n"
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
    stored_code = data.decode('utf-8')
    if stored_code == str(code):
        redis_connection.set(f"{phone_number}_verified", "True")
        redis_connection.expire(f"{phone_number}_verified", time=180)
        redis_connection.delete(phone_number)
        _clear_attempts(phone_number)
        return True, "Code verified successfully"
    if not _register_failed_attempt(phone_number):
        return False, "Too many incorrect attempts, request a new code"
    return False, "Code is incorrect"


def send_sms_text(phone_number, text):
    message_id = f"repliuz_{randint(100000, 999999)}"
    payload = get_playmobile_payload(phone_number, message_id, originator, text)
    response = requests.post(
        PLAY_MOBILE_URL,
        json=payload,
        auth=(PLAY_MOBILE_LOGIN, PLAY_MOBILE_PASSWORD),
        timeout=60
    )
    return response if response.status_code == 200 else None


def send_email_code(email):
    try:
        code = generate_code()
        # Store code in Redis with 5 minute expiration
        redis_connection.setex(email, 300, code)

        subject = _("Verification Code")
        message = _("Your verification code is: {}").format(code)
        from_email = settings.EMAIL_HOST_USER
        from django.template.loader import render_to_string

        html_message = render_to_string(
            'verification_email.html',
            {
                'code': code,
                'expiry_minutes': 5,
                'year': 2024,
                'subject': "Verification Code"
            }
        )

        send_mail(
            subject=subject,
            message=message,
            from_email=from_email,
            recipient_list=[email],
            html_message=html_message,
            fail_silently=False,
        )
        
        return True, _("Verification code sent to your email")
        
    except Exception as e:
        return False, _("Failed to send verification code: {}").format(str(e))


def verify_email_code(email, code):
    try:
        # Get stored code from Redis
        stored_code = redis_connection.get(email)
        
        if not stored_code:
            return False, _("Verification code expired or not found")
            
        # Compare codes
        if stored_code.decode('utf-8') == str(code):
            # Mark email as verified
            redis_connection.setex(
                f"{email}_verified",
                300,  # 1 hour in seconds
                "true"
            )
            # Delete the code
            redis_connection.delete(email)
            _clear_attempts(email)
            return True, _("Email verified successfully")

        if not _register_failed_attempt(email):
            return False, _("Too many incorrect attempts, request a new code")
        return False, _("Invalid verification code")
        
    except Exception as e:
        return False, _("Failed to verify code: {}").format(str(e))


def is_email_verified(email):
    try:
        return bool(redis_connection.get(f"{email}_verified"))
    except Exception:
        return False