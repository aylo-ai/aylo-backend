import re
from bs4 import BeautifulSoup
import json
from django.utils.translation import gettext_lazy as _
import requests
from datetime import datetime
from apps.integration.models import Integration, TelegramGroupIntegration
from shared.addons.validations import error_response

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
    response = requests.get(url)
    code = response.status_code
    success = response.json().get("ok")
    return success, code

def send_telegram_action(chat_id,token):
    url = f"https://api.telegram.org/bot{token}/sendChatAction"
    data = {
        "chat_id": chat_id,
        "action": 'typing'
    }
    response = requests.post(url, json=data)
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
    
    response = requests.post(url, json=data)
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
            response = requests.post(url, json=data)
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
    response = requests.get(url, params={"chat_id": chat_id})
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
    response = requests.post(url, json=data)
    return response


def delete_telegram_message(chat_id, message_id, token):
    url = f"https://api.telegram.org/bot{token}/deleteMessage"
    data = {"chat_id": chat_id, "message_id": message_id}
    response = requests.post(url, json=data).json()
    return response


def set_telegram_webhook(bot_token, webhook_url):
    url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
    payload = {
        'url': webhook_url
    }
    print(f"[+] Setting webhook to: {webhook_url}")
    response = requests.post(url, data=payload)
    if response.status_code == 200:
        print(f"[+] Webhook set successfully, Status code: {response.status_code}")
        return 200
    else:
        print(f"[-] Failed to set webhook: {response.json()}, Status code: {response.status_code}")
        return 400


def get_webhook_info(bot_token):
    url = f"https://api.telegram.org/bot{bot_token}/getWebhookInfo"
    response = requests.get(url)
    if response.status_code == 200:
        print(f"Webhook info: {response.json()}, Status code: {response.status_code}")
        return 200
    else:
        print("Failed to get webhook info:", response.json())
        return 400


def handle_bot_added_to_group(chat_id, chat_title, bot_token):
    print(f"Bot added to group: {chat_title} ({chat_id})")
    integration = Integration.objects.filter(api_token=bot_token).first()
    if not integration:
        print(f"No integration found for bot token: {bot_token}")
        return error_response(message=_("Integration topilmadi"), code=404)

    if not TelegramGroupIntegration.objects.filter(integration=integration, group_id=chat_id).exists():
        telegram_group = TelegramGroupIntegration(integration=integration, group_id=chat_id, group_title=chat_title)
        telegram_group.save()
        print(f"Created group: {chat_title} ({chat_id})")
    else:
        print(f"Group already exists for this integration: {chat_title} ({chat_id})")


def handle_bot_removed_from_group(chat_id, chat_title):
    print(f"Bot removed from group: {chat_title} ({chat_id})")
    TelegramGroupIntegration.objects.filter(group_id=chat_id).delete()
    print(f"Deleted group: {chat_title} ({chat_id})")


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
