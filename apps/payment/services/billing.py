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
    """The decoded JSON of a reply, or `{}` when there isn't any."""
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _payme_body(response, method):
    """Return the JSON-RPC body of a Payme reply, or `None` if it failed.

    Payme is JSON-RPC over HTTP: a refusal comes back as HTTP 200 with an
    `error` member, so the status code on its own says nothing about whether
    the call succeeded.
    """
    body = _json_body(response)
    if response.status_code != 200:
        logger.error("Payme %s returned HTTP %s", method, response.status_code)
        return None
    if body.get("error"):
        logger.error("Payme %s was refused: %s", method, body["error"])
        return None
    return body or None


def payme_error_message(body, default="Payme bilan bog'lanishda xatolik yuz berdi"):
    """Extract a readable message from a Payme JSON-RPC error body.

    Payme localises `error.message`: it is sometimes a plain string and
    sometimes `{"ru": ..., "uz": ..., "en": ...}`. Falls back to `default`
    rather than raising when the body has no usable error at all.
    """
    message = (body.get("error") or {}).get("message") if isinstance(body, dict) else None
    if isinstance(message, dict):
        message = message.get("uz") or message.get("en") or next(iter(message.values()), None)
    return message or default


def check_payme_card_token(token):
    """Call Payme API to verify card token."""
    param_data = {"method": "cards.check", "params": {"token": token}}
    headers = {"X-Auth": f"{settings.PAYME_ID}:{settings.PAYME_KEY}"}
    response = http.post(
        settings.PAYME_API_URL, json=param_data, headers=headers
    )
    return response if _payme_body(response, "cards.check") is not None else None


def remove_payme_card(card_token):
    """Call Payme API to remove a card.

    Returns the response only when Payme actually removed the card. Trusting
    the HTTP status alone used to let the caller delete the local row while the
    recurrent token stayed live and chargeable on Payme's side.
    """
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
    """Create a receipt in Payme."""
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
    """Create a card token in Payme."""
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
    """Verify a card code in Payme."""
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
    """Verify a card in Payme."""
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
    """Commit a receipt in Payme."""
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
    """Update the user's balance."""
    balance, _ = Balance.objects.get_or_create(user=user)
    balance.amount += amount
    balance.save()
    return balance


def process_subscription_payment(user):
    """Process subscription payment for the user."""
    pricing_package = user.subscription.pricing_package
    if not pricing_package:
        return False, "No pricing package assigned."

    card = user.cards.filter(is_verified=True, is_default=True).first()
    if not card:
        return False, "No valid card available for payment."

    # Step 1: Create Payme receipt
    success, message, receipt_id = create_payme_receipt(pricing_package.price)
    if not success:
        return False, message

    # Step 2: Commit Payme receipt
    success, message, _ = commit_payme_receipt(card.card_token, receipt_id)
    if not success:
        return False, message

    # Step 3: Log transaction
    transaction = Transaction.objects.create(
        user=user,
        amount=pricing_package.price,
        currency=pricing_package.currency,
        transaction_type=TransactionTypes.WITHDRAW.value,
        status=PaymentStatuses.SUCCESS.value
    )
    transaction.save()

    # Step 4: Reset retry count and set next payment date
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
    """Create a notification for the user."""
    Notification.objects.create(
        user=user,
        title="Obuna tarifingiz tugadi. Iltimos, platformaga kirib, to'lovni qo'lda kiriting.",
        content=message,
        type=NotificationTypes.WARNING.value
    )
