import hashlib
import hmac
import logging
import re
from bs4 import BeautifulSoup
import json
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from apps.shared import http
from datetime import datetime
from apps.integration.models import Integration, TelegramGroupIntegration
from apps.shared.addons.crypto import mask_secret
from apps.shared.addons.validations import error_response

logger = logging.getLogger(__name__)

USER_INFO_REGEX = r"#registered_user_info\s*" \
                  r"Ism-familiya:\s*(.*?)\s*\n" \
                  r"Telefon raqam:\s*(.*?)\s*\n" \
                  r"Qo'?shimcha telefon:\s*(.*?)\s*\n" \
                  r"Mahsulot/Xizmat/Kurs:\s*(.*?)\s*\n" \
                  r"Bizni qayerdan eshitd(?:ingiz|i):\s*(.*?)(?:\s*\n|$)"


def escape_markdown_v2(text):
    text = re.sub(r'[_*[\]()~>#\+\-=|{}.!]', lambda x: '\\' + x.group(), text)
    return text


def clean_html(input_html, allowed_tags=None):
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

def extract_reply(text):
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and "reply" in parsed:
            return parsed["reply"]
        else:
            return text
    except json.JSONDecodeError:
        pass
    return text


def telegram_get_me(token):
    url = f"https://api.telegram.org/bot{token}/getMe"
    response = http.get(url)
    code = response.status_code
    success = response.json().get("ok")
    return success, code

def send_telegram_action(chat_id,token):
    url = f"https://api.telegram.org/bot{token}/sendChatAction"
    data = {
        "chat_id": chat_id,
        "action": 'typing'
    }
    response = http.post(url, json=data)
    return response

def send_telegram_message(chat_id, text, token, entities=None):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    # cleaned_html = clean_html(text)
    text_reply = extract_reply(text)
    data = {
        "chat_id": chat_id,
        "text": text_reply,
        "parse_mode": "html",
        "disable_web_page_preview": True,
    }
    
    response = http.post(url, json=data)
    response_data = response.json()
    if not response_data.get("ok"):
        if "migrate_to_chat_id" in response_data.get("parameters", {}):
            new_chat_id = response_data["parameters"]["migrate_to_chat_id"]
            try:
                group_integration = TelegramGroupIntegration.objects.filter(group_id=chat_id).first()
                if group_integration:
                    group_integration.group_id = new_chat_id
                    group_integration.save()
                    print(f"[+] Updated TelegramGroupIntegration: {group_integration}")
                else:
                    print(f"[-] No TelegramGroupIntegration entry found for chat_id: {chat_id}")
            except Exception as e:
                print(f"[-] Error updating TelegramGroupIntegration: {e}")

            # Retry sending the message with the new chat ID
            data["chat_id"] = new_chat_id
            response = http.post(url, json=data)
            response_data = response.json()

            if response_data.get("ok"):
                print("[+] Message sent successfully after migration.")
            else:
                print(f"[-] Failed to send message after migration: {response_data}")
        elif response_data.get("error_code") == 403:
            print(f"[-] Failed to send message (403 - bot kicked): {response_data}")
            try:
                group = TelegramGroupIntegration.objects.filter(group_id=chat_id).first()
                if group:
                    group.is_approved = False
                    group.save(update_fields=["is_approved"])
                    print(f"[!] Auto-disabled group {chat_id} due to 403 error")
            except Exception as e:
                print(f"[-] Error auto-disabling group: {e}")
        else:
            print(f"[-] Failed to send message: {response_data}")
    else:
        print("[+] Message sent successfully.")
    return response


def check_bot_in_group(chat_id, token):
    """Telegram API orqali bot haqiqatan guruhda borligini tekshirish"""
    url = f"https://api.telegram.org/bot{token}/getChat"
    response = http.get(url, params={"chat_id": chat_id})
    return response.json().get("ok", False)


def send_telegram_photo(chat_id, photo_url, token, caption=None):
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    data = {
        "chat_id": chat_id,
        "photo": photo_url,
    }
    if caption:
        data["caption"] = extract_reply(caption)
        data["parse_mode"] = "html"
    response = http.post(url, json=data)
    return response


def delete_telegram_message(chat_id, message_id, token):
    url = f"https://api.telegram.org/bot{token}/deleteMessage"
    data = {"chat_id": chat_id, "message_id": message_id}
    response = http.post(url, json=data).json()
    return response


def telegram_webhook_secret(bot_token):
    """Per-bot value for Telegram's ``secret_token`` handshake.

    Telegram does not sign webhook payloads; the only authenticity control it
    offers is a shared secret registered with ``setWebhook`` and echoed back in
    the ``X-Telegram-Bot-Api-Secret-Token`` header of every delivery.

    The secret is derived — HMAC(server key, bot token) — rather than stored, so
    every bot gets a distinct value with no new column and no state to keep in
    sync: the webhook can recompute it from the token in its own URL path.
    Returns "" when no server key is configured, which makes the webhook fail
    closed instead of accepting forged updates.
    """
    server_key = getattr(settings, "TELEGRAM_WEBHOOK_SECRET", "")
    if not server_key or not bot_token:
        return ""
    return hmac.new(
        server_key.encode("utf-8"), str(bot_token).encode("utf-8"), hashlib.sha256,
    ).hexdigest()


def set_telegram_webhook(bot_token, webhook_url):
    url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
    payload = {
        'url': webhook_url
    }
    secret_token = telegram_webhook_secret(bot_token)
    if secret_token:
        payload['secret_token'] = secret_token
    else:
        # Registering without a secret leaves the webhook unauthenticated, and
        # the view rejects every delivery — surface it at registration time.
        logger.error(
            "TELEGRAM_WEBHOOK_SECRET is not configured; the registered webhook "
            "will reject every update"
        )
    # The webhook URL embeds the bot token in its path — never log it.
    response = http.post(url, data=payload)
    if response.status_code == 200:
        logger.info("Telegram webhook set successfully")
        return 200
    else:
        logger.warning("Failed to set Telegram webhook, status code: %s", response.status_code)
        return 400


def get_webhook_info(bot_token):
    url = f"https://api.telegram.org/bot{bot_token}/getWebhookInfo"
    response = http.get(url)
    # The response body carries the registered webhook URL, which embeds the
    # bot token in its path — log the status only.
    if response.status_code == 200:
        logger.info("Fetched Telegram webhook info")
        return 200
    else:
        logger.warning("Failed to get Telegram webhook info, status code: %s", response.status_code)
        return 400


def handle_bot_added_to_group(chat_id, chat_title, bot_token):
    logger.info("Bot added to group %s (%s)", chat_title, chat_id)
    # `api_token` is encrypted at rest; the manager rewrites this onto the
    # deterministic `api_token_hash` column (apps/shared/fields.py).
    integration = Integration.objects.filter(api_token=bot_token).first()
    if not integration:
        # The bot token is a live credential — log a masked suffix only.
        logger.warning("No integration found for bot token %s", mask_secret(bot_token))
        return error_response(message=_("Integration topilmadi"), code=404)

    if not TelegramGroupIntegration.objects.filter(integration=integration, group_id=chat_id).exists():
        TelegramGroupIntegration.objects.create(
            integration=integration, group_id=chat_id, group_title=chat_title
        )
        logger.info("Created Telegram group %s (%s)", chat_title, chat_id)
    else:
        logger.info("Telegram group %s (%s) already registered", chat_title, chat_id)


def handle_bot_removed_from_group(chat_id, chat_title):
    logger.info("Bot removed from group %s (%s)", chat_title, chat_id)
    TelegramGroupIntegration.objects.filter(group_id=chat_id).delete()


def check_register_info(message):
    registered_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Checking message for registration info: {message}")
    # Check if the message contains the registration tag
    if '#registered_user_info' in message.lower():
        print("Found '#registered_user_info' in the message.")  # Log if the tag is found

        # Match the message against the regex pattern
        match = re.search(USER_INFO_REGEX, message, re.DOTALL | re.IGNORECASE)
        print(f"match: {match}")
        if match:
            print("Regex match successful!")  # Log if regex matches

            # Extract information from the message
            full_name, phone_number, additional_phone, course, referral_source = match.groups()

            # Create a formatted notification
            register_message = (
                f"\U00002705 Yangi foydalanuvchi ro'yxatdan o'tdi!\n\n"
                f"\U0001F464 Ism-familiya: {full_name}\n"
                f"\U0001F4DE Telefon raqam: {phone_number}\n"
                f"\U0001F4F2 Qo'shimcha telefon: {additional_phone}\n"
                f"\U0001F3EB Mahsulot/Xizmat/Kurs: {course}\n"
                f"\U0001F4F0 Bizni qayerdan eshitdingiz: {referral_source}\n"
                f"\U0001F4C5 Ro'yhatdan o'tish vaqti: {registered_date}"
            )
            return register_message
        else:
            print("Regex match failed.")  # Log if regex doesn't match

    return None
