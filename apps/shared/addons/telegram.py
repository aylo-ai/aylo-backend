import re
from bs4 import BeautifulSoup

import requests


def escape_markdown_v2(text):
    text = re.sub(r'[_*[\]()~>#\+\-=|{}.!]', lambda x: '\\' + x.group(), text)
    return text


def clean_html(input_html, allowed_tags=None):
    """
    Clean HTML by removing tags not in the allowed list.

    :param input_html: The HTML string to clean.
    :param allowed_tags: List of allowed tags. Example: ['b', 'i', 'u', 'a']
    :return: A sanitized HTML string containing only the allowed tags.
    """
    if allowed_tags is None:
        allowed_tags = ['b', 'i', 'u', 'a']

    soup = BeautifulSoup(input_html, 'html.parser')

    # Remove disallowed tags while keeping their content
    for tag in soup.find_all(True):  # Find all tags
        if tag.name not in allowed_tags:
            tag.unwrap()  # Remove the tag but keep its content

    # Validate 'a' tag attributes (keep only 'href')
    for tag in soup.find_all('a'):
        allowed_attrs = {'href'}
        for attr in list(tag.attrs):
            if attr not in allowed_attrs:
                del tag.attrs[attr]

    return str(soup)


def telegram_get_me(token):
    url = f"https://api.telegram.org/bot{token}/getMe"
    response = requests.get(url)
    code = response.status_code
    success = response.json().get("ok")
    return success, code


def send_telegram_message(chat_id, text, token):
    print(f"Sending message to chat_id: {chat_id}, text: {text}")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    cleaned_html = clean_html(text)
    print(f"Cleaned HTML: {cleaned_html}")
    data = {
        "chat_id": chat_id,
        "text": cleaned_html,
        "parse_mode": "html"
    }
    print(f"send telegram message data: {data}, url: {url}")
    response = requests.post(url, json=data)
    print(f"Message sent to Telegram: {response.status_code}, {response.json()}")
    return response


def delete_telegram_message(chat_id, message_id, token):
    url = f"https://api.telegram.org/bot{token}/deleteMessage"
    data = {"chat_id": chat_id, "message_id": message_id}
    response = requests.post(url, json=data).json()
    return response


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