import requests


def telegram_get_me(token):
    url = f"https://api.telegram.org/bot{token}/getMe"
    response = requests.get(url)
    code = response.status_code
    success = response.json().get("ok")
    return success, code


def send_telegram_message(chat_id, text, token):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {"chat_id": chat_id, "text": text}
    requests.post(url, json=data)