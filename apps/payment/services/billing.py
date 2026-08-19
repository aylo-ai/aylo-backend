import logging
import random
from datetime import datetime, timedelta

from apps.payment.models import Balance, Transaction
from apps.shared import http
from apps.shared.addons.enums import (
    NotificationTypes,
    PaymentStatuses,
    SubscriptionStatuses,
    TransactionTypes,
)
from apps.user.models import Notification
from config import settings

logger = logging.getLogger(__name__)


def _json_body(response):
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _payme_body(response, method):
    body = _json_body(response)
    if response.status_code != 200:
        logger.error("Payme %s returned HTTP %s", method, response.status_code)
        return None
    if body.get("error"):
        logger.error("Payme %s was refused: %s", method, body["error"])
        return None
    return body or None


def payme_error_message(body, default="Payme bilan bog'lanishda xatolik yuz berdi"):
    message = (body.get("error") or {}).get("message") if isinstance(body, dict) else None
    if isinstance(message, dict):
        message = message.get("uz") or message.get("en") or next(iter(message.values()), None)
    return message or default


def check_payme_card_token(token):
    param_data = {"method": "cards.check", "params": {"token": token}}
    headers = {"X-Auth": f"{settings.PAYME_ID}:{settings.PAYME_KEY}"}
    response = http.post(
        settings.PAYME_API_URL, json=param_data, headers=headers
    )
    return response if _payme_body(response, "cards.check") is not None else None


def remove_payme_card(card_token):
    param_data = {
        "method": "cards.remove",
        "params": {"token": card_token},
    }
    headers = {"X-Auth": f"{settings.PAYME_ID}:{settings.PAYME_KEY}"}
    response = http.post(
        settings.PAYME_API_URL, json=param_data, headers=headers
    )
    return response if _payme_body(response, "cards.remove") is not None else None


def create_payme_receipt(amount):
    payload = {
        "method": "receipts.create",
        "params": {
            "amount": int(amount) * 100,
            "account": {"order_id": random.randint(10000, 100000)},
        },
    }

    headers = {"X-Auth": f"{settings.PAYME_ID}"}
    response = http.post(
        settings.PAYME_API_URL, json=payload, headers=headers
    )
    body = _payme_body(response, "receipts.create")
    receipt_id = (((body or {}).get("result") or {}).get("receipt") or {}).get("_id")
    if not receipt_id:
        return False, payme_error_message(_json_body(response)), None
    return True, "successfull", receipt_id


def send_create_card_request(card_number, card_expiry):
    payload = {
        "method": "cards.create",
        "params": {
            "card":{
                "number": card_number,
                "expire": card_expiry},
            "save": True,
        }
    }
    headers = {"X-Auth": f"{settings.PAYME_ID}"}
    response = http.post(
        settings.PAYME_API_URL, json=payload, headers=headers
    )
    return _json_body(response)


def send_verify_code_request(card_token):
    payload = {
        "method": "cards.get_verify_code",
        "params": {"token": card_token}
    }
    headers = {"X-Auth": f"{settings.PAYME_ID}"}
    response = http.post(
        settings.PAYME_API_URL, json=payload, headers=headers
    )
    return _json_body(response)

def verify_payme_card_token(card_token, verify_code):
    payload = {
        "method": "cards.verify",
        "params": {"token": card_token, "code": verify_code}
    }
    headers = {"X-Auth": f"{settings.PAYME_ID}"}
    response = http.post(
        settings.PAYME_API_URL, json=payload, headers=headers
    )
    return _json_body(response)


def commit_payme_receipt(card_token, receipt_id):
    payload = {
        "method": "receipts.pay",
        "params": {
            "id": receipt_id,
            "short_response": True,
            "token": card_token,
        },
    }
    headers = {"X-Auth": f"{settings.PAYME_ID}:{settings.PAYME_KEY}"}
    response = http.post(
        settings.PAYME_API_URL, json=payload, headers=headers
    )
    body = _payme_body(response, "receipts.pay")
    receipt_id = (((body or {}).get("result") or {}).get("receipt") or {}).get("_id")
    if not receipt_id:
        return False, payme_error_message(_json_body(response)), None
    return True, "successfull", receipt_id


def update_user_balance(user, amount):
    balance, _ = Balance.objects.get_or_create(user=user)
    balance.amount += amount
    balance.save()
    return balance


def process_subscription_payment(user):
    pricing_package = user.subscription.pricing_package
    if not pricing_package:
        return False, "No pricing package assigned."

    card = user.cards.filter(is_verified=True, is_default=True).first()
    if not card:
        return False, "No valid card available for payment."

    success, message, receipt_id = create_payme_receipt(pricing_package.price)
    if not success:
        return False, message

    success, message, _ = commit_payme_receipt(card.card_token, receipt_id)
    if not success:
        return False, message

    transaction = Transaction.objects.create(
        user=user,
        amount=pricing_package.price,
        currency=pricing_package.currency,
        transaction_type=TransactionTypes.WITHDRAW.value,
        status=PaymentStatuses.SUCCESS.value
    )
    transaction.save()

    subscription = transaction.user.subscription
    subscription.status = SubscriptionStatuses.ACTIVE.value
    subscription.remained_request_count += pricing_package.request_count
    subscription.retry_count = 0
    subscription.last_payment_date = datetime.now().date()
    subscription.next_payment_date = datetime.now().date() + timedelta(days=pricing_package.duration_days)
    subscription.end_date = datetime.now().date() + timedelta(days=pricing_package.duration_days)
    subscription.save()

    return True, "Payment successful."


def create_notification(user, message):
    Notification.objects.create(
        user=user,
        title="Obuna tarifingiz tugadi. Iltimos, platformaga kirib, to'lovni qo'lda kiriting.",
        content=message,
        type=NotificationTypes.WARNING.value
    )
