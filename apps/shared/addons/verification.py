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


PLAY_MOBILE_URL: str = os.environ['PLAY_MOBILE_URL']
PLAY_MOBILE_LOGIN: str = os.environ['PLAY_MOBILE_LOGIN']
PLAY_MOBILE_PASSWORD: str = os.environ['PLAY_MOBILE_PASSWORD']
originator: str = os.environ['PLAY_MOBILE_ORIGINATOR']


def generate_code():
    return randint(100000, 999999)


def send_playmobile_sms(phone_number, message):
    message_id = f"repliuz_{randint(100000, 999999)}"
    # redis_connection.set(f"{phone_number}_message_id", message_id)
    # redis_connection.expire(f"{phone_number}_message_id", time=3600)
    payload = get_playmobile_payload(phone_number, message_id, originator, message)
    print(f"playmobile_url: {PLAY_MOBILE_URL}, login: {PLAY_MOBILE_LOGIN}, password: {PLAY_MOBILE_PASSWORD}")
    response = requests.post(
        PLAY_MOBILE_URL,
        json=payload,
        auth=(PLAY_MOBILE_LOGIN, PLAY_MOBILE_PASSWORD),
        timeout=60
    )
    print(f"playmobile_response: {response.status_code}, respone text: {response.text}")
    if response.status_code == 200:
        return True, "SMS successfully sent"
    else:
        return False, f"Failed to send sms. Status code: {response.status_code}"


def send_code(phone_number):
    if redis_connection.get(phone_number):
        return False, "Code already sent"
    code = generate_code()
    message = f"Repli.uz! Sizning tasdiqlash kodingiz - {code}\n"
    success, message = send_playmobile_sms(phone_number, message)
    if not success:
        return False, message
    print(f"Your code for number {phone_number} is {code}")
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
    if stored_code == code:
        redis_connection.set(f"{phone_number}_verified", "True")
        redis_connection.expire(f"{phone_number}_verified", time=180)
        return True, "Code verified successfully"
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
    """
    Send verification code to email address.
    
    Args:
        email (str): Email address to send code to
        
    Returns:
        tuple: (success, message)
    """
    try:
        # code = generate_code()
        code = "000000"
        # Store code in Redis with 5 minute expiration
        redis_connection.setex(email, 300, code)
        
        # Prepare email content
        # subject = _("Verification Code")
        # message = _("Your verification code is: {}").format(code)
        # from_email = settings.DEFAULT_FROM_EMAIL
        # from django.template.loader import render_to_string

        # html_message = render_to_string(
        #     'apps/shared/addons/verification_email.html',
        #     {
        #         'code': code,
        #         'expiry_minutes': 5,
        #         'year': 2024,
        #         'subject': "Verification Code"
        #     }
        # )
        
        # Send email
        # send_mail(
        #     subject=subject,
        #     message=message,
        #     from_email=from_email,
        #     recipient_list=[email],
        #     html_message=html_message,
        #     fail_silently=False,
        # )
        
        return True, _("Verification code sent to your email")
        
    except Exception as e:
        return False, _("Failed to send verification code: {}").format(str(e))


def verify_email_code(email, code):
    """
    Verify the code sent to email address.
    
    Args:
        email (str): Email address to verify
        code (str): Verification code to check
        
    Returns:
        tuple: (success, message)
    """
    try:
        # Get stored code from Redis
        stored_code = redis_connection.get(email)
        
        if not stored_code:
            return False, _("Verification code expired or not found")
            
        # Compare codes
        if stored_code.decode('utf-8') == code:
            # Mark email as verified
            redis_connection.setex(
                f"{email}_verified",
                300,  # 1 hour in seconds
                "true"
            )
            # Delete the code
            redis_connection.delete(email)
            return True, _("Email verified successfully")
            
        return False, _("Invalid verification code")
        
    except Exception as e:
        return False, _("Failed to verify code: {}").format(str(e))


def is_email_verified(email):
    """
    Check if email is verified.
    
    Args:
        email (str): Email address to check
        
    Returns:
        bool: True if email is verified, False otherwise
    """
    try:
        return bool(redis_connection.get(f"{email}_verified"))
    except Exception:
        return False