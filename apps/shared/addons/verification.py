import os
import requests
from random import randint

from config.settings import redis_connection
from shared.addons.payloads import get_playmobile_payload

PLAY_MOBILE_URL = os.environ.get('PLAY_MOBILE_URL')
PLAY_MOBILE_LOGIN = os.environ.get('PLAY_MOBILE_LOGIN')
PLAY_MOBILE_PASSWORD = os.environ.get('PLAY_MOBILE_PASSWORD')
originator = os.environ.get('PLAY_MOBILE_ORIGINATOR')

send_sms = os.environ.get('SEND_SMS')


def generate_code():
    return randint(100000, 999999)


def send_phone_notification(phone, code):
    message = f"Repli.uz! Sizning tasdiqlash kodingiz - {code}\n"
    return send_playmobile_sms(phone, message)


def send_playmobile_sms(phone_number, message):
    message_id = f"repliuz_{randint(100000, 999999)}"
    redis_connection.set(f"{phone_number}_message_id", message_id)
    redis_connection.expire(f"{phone_number}_message_id", time=3600)
    payload = get_playmobile_payload(phone_number, message_id, originator, message)
    print(f"playmobile_url: {PLAY_MOBILE_URL}, login: {PLAY_MOBILE_LOGIN}, password: {PLAY_MOBILE_PASSWORD}")
    response = requests.post(
        PLAY_MOBILE_URL,
        json=payload,
        auth=(PLAY_MOBILE_LOGIN, PLAY_MOBILE_PASSWORD),
        timeout=60
    )
    if response.status_code == 200:
        return True, "SMS successfully sent"
    else:
        return False, f"Failed to send sms. Status code: {response.status_code}"


def send_code(phone_number):
    if redis_connection.get(phone_number):
        return False, "Code already sent"
    code = generate_code()
    if send_sms:
        send_phone_notification(phone_number, code)
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

