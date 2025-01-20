import random
from datetime import timedelta

import requests
from django.template.defaulttags import now

from apps.payment.models import Balance, Transaction
from config import settings
from shared.addons.enums import TransactionTypes, PaymentStatuses


def check_payme_card_token(token):
    """Call Payme API to verify card token."""
    param_data = {"method": "cards.check", "params": {"token": token}}
    headers = {"X-Auth": f"{settings.PAYME_ID}:{settings.PAYME_KEY}"}
    print(param_data, headers)
    response = requests.post(
        settings.PAYME_API_URL, json=param_data, headers=headers
    )
    print(response.text)
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
    return response if response.status_code == 200 else None


def create_payme_receipt(amount):
    """Create a receipt in Payme."""
    payload = {
        "method": "receipts.create",
        "params": {
            "amount": amount * 100,
            "account": {"order_id": random.randint(10000, 100000)},
        },
    }

    headers = {"X-Auth": f"{settings.PAYME_ID}:{settings.PAYME_KEY}"}
    response = requests.post(
        settings.PAYME_API_URL, json=payload, headers=headers
    )

    if response.status_code == 200:
        result = response.json().get("result", {})
        return True, "", result.get("receipt", {}).get("id")
    return False, response.json().get("error", {}).get("message"), None


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
    if response.status_code == 200:
        return True, "", receipt_id
    return False, response.json().get("error", {}).get("message"), None


def update_user_balance(user, amount):
    """Update the user's balance."""
    balance, _ = Balance.objects.get_or_create(user=user)
    balance.amount += amount
    balance.save()
    return balance


def process_subscription_payment(user):
    """Process subscription payment for the user."""
    pricing_package = user.pricing_package
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
    Transaction.objects.create(
        user=user,
        amount=pricing_package.price,
        currency=pricing_package.currency,
        transaction_type=TransactionTypes.WITHDRAW.value,
        status=PaymentStatuses.SUCCESS.value,
    )

    # Step 4: Reset retry count and set next payment date
    user.retry_count = 0
    user.next_payment_date = now().date() + timedelta(days=30)
    user.save()

    return True, "Payment successful."
