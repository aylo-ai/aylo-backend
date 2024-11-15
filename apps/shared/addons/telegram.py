import re

import requests


def escape_markdown_v2(text):
    """
    Escapes special characters for Telegram MarkdownV2 formatting.
    """
    # Characters to escape as per MarkdownV2 requirements
    special_characters = r'[_*[\]()~`>#+-=|{}.!,"\\]'
    # Escape each instance of these characters
    return re.sub(f'([{special_characters}])', r'\\\1', text)


def telegram_get_me(token):
    url = f"https://api.telegram.org/bot{token}/getMe"
    response = requests.get(url)
    code = response.status_code
    success = response.json().get("ok")
    return success, code


def send_telegram_message(chat_id, text, token):
    print(f"Sending message to chat_id: {chat_id}, text: {text}")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    escaped_text = escape_markdown_v2(text)
    print(f"Escaped text: {escaped_text}")
    data = {
        "chat_id": chat_id,
        "text": escaped_text,
        "parse_mode": "MarkdownV2"
    }
    response = requests.post(url, json=data)
    print(f"Message sent to Telegram: {response.status_code}, {response.json()}")


# Function to set the webhook
def set_telegram_webhook(bot_token, webhook_url):
    url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
    payload = {
        'url': webhook_url
    }
    print(f"Setting webhook to: {webhook_url}")
    response = requests.post(url, data=payload)
    if response.status_code == 200:
        print(f"Webhook set successfully, Status code: {response.status_code}")
        return 200
    else:
        print(f"Failed to set webhook: {response.json()}, Status code: {response.status_code}")
        return 400


# Function to check webhook information
def get_webhook_info(bot_token):
    url = f"https://api.telegram.org/bot{bot_token}/getWebhookInfo"
    response = requests.get(url)
    if response.status_code == 200:
        print(f"Webhook info: {response.json()}, Status code: {response.status_code}")
        return 200
    else:
        print("Failed to get webhook info:", response.json())
        return 400