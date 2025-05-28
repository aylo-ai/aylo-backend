import random
from datetime import timedelta, datetime

import requests
from django.template.defaulttags import now

from apps.payment.models import Balance, Transaction
from config import settings
from shared.addons.enums import TransactionTypes, PaymentStatuses, SubscriptionStatuses


def check_payme_card_token(token):
    """Call Payme API to verify card token."""
    param_data = {"method": "cards.check", "params": {"token": token}}
    headers = {"X-Auth": f"{settings.PAYME_ID}:{settings.PAYME_KEY}"}
    print(param_data, headers)
    response = requests.post(
        settings.PAYME_API_URL, json=param_data, headers=headers
    )
    print(f"check_payme_card_token: {response.json()}")
    return response if response.status_code == 200 else None


def remove_payme_card(card_token):
    """Call Payme API to remove a card."""
    param_data = {
        "method": "cards.remove",
        "params": {"token": card_token},
    }
    headers = {"X-Auth": f"{settings.PAYME_ID}:{settings.PAYME_KEY}"}
    response = requests.post(
        settings.PAYME_API_URL, json=param_data, headers=headers
    )
    print(f"remove_payme_card: {response.json()}")
    return response if response.status_code == 200 else None


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
    response = requests.post(
        settings.PAYME_API_URL, json=payload, headers=headers
    )
    print(f"create_payme_receipt: {response.json()}")
    try:
        return True, "successfull", response.json()["result"]["receipt"]["_id"]
    except Exception:
        return False, response.json()["error"]["message"], None
    
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
    print(payload, headers)
    response = requests.post(
        settings.PAYME_API_URL, json=payload, headers=headers
    )
    print(f"send_create_card_request: {response.json()}")

    return response.json()

    
def send_verify_code_request(card_token):
    """Verify a card code in Payme."""
    payload = {
        "method": "cards.get_verify_code",
        "params": {"token": card_token}
    }
    headers = {"X-Auth": f"{settings.PAYME_ID}"}
    response = requests.post(
        settings.PAYME_API_URL, json=payload, headers=headers
    )
    print(f"send_verify_code_request: {response.json()}")

    return response.json()
    
def verify_payme_card_token(card_token, verify_code):
    """Verify a card in Payme."""
    payload = {
        "method": "cards.verify",
        "params": {"token": card_token, "code": verify_code}
    }
    headers = {"X-Auth": f"{settings.PAYME_ID}"}
    response = requests.post(
        settings.PAYME_API_URL, json=payload, headers=headers
    )
    print(f"verify_payme_card_token: {response.json()}")
    return response.json()
    

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
    response = requests.post(
        settings.PAYME_API_URL, json=payload, headers=headers
    )
    print(f"commit_payme_receipt: {response.json()}")
    try:
        return True, "successfull", response.json()["result"]["receipt"]["_id"]
    except Exception:
        return False, response.json()["error"]["message"], None


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

    card = user.cards.filter(is_verified=True).first()
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
