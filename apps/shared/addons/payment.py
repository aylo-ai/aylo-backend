import random

from django.conf import settings
import requests

from apps.payment.models import Balance


def check_payme_card_token(token):
    """Call Payme API to verify card token."""
    param_data = {"method": "cards.check", "params": {"token": token}}
    headers = {"X-Auth": f"{settings.PAYME_ID}:{settings.PAYME_KEY}"}
    response = requests.post(
        settings.PAYME_API_URL, json=param_data, headers=headers
    )
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