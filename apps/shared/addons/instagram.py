import requests
import time
from config.settings import INSTAGRAM_CLIENT_ID

from apps.integration.models import InstagramCommentResponse, Flow, InstagramUserState, Step
from shared.addons.enums import ActionType

def get_long_lived_access_token(short_lived_access_token):
    """Get long-lived access token from short-lived access token"""
    CLIENT_SECRET = "dc12159193e69625fd27281997b28f4f"
    grant_type = "ig_exchange_token"
    url = f"https://graph.instagram.com/access_token?grant_type={grant_type}&" \
          f"client_secret={CLIENT_SECRET}&access_token={short_lived_access_token}"

    response = requests.get(url)
    if response.status_code == 200:
        access_token = response.json().get("access_token")
        refreshed_new_token = instagram_refresh_token(access_token)
        print(f"refresh_token: {refreshed_new_token}")
        return access_token
    return None

def instagram_refresh_token(access_token):
    grant_type = "ig_refresh_token"
    url = f"https://graph.instagram.com/refresh_access_token?grant_type={grant_type}&access_token={access_token}"

    response = requests.get(url)
    if response.status_code == 200:
        access_token = response.json().get("access_token")
        return access_token
    return None

def get_user_profile(access_token):
    """Get user profile from access token"""
    url = f"https://graph.instagram.com/me?" \
          f"fields=id,user_id,username&" \
          f"access_token={access_token}"
    response = requests.get(url)
    print(f"get_user_profile response: {response.text}")
    if response.status_code == 200:
        user_profile = response.json()
        user_data = {
            "instagram_user_id": user_profile.get("id"),
            "instagram_account_id": user_profile.get("user_id"),
            "instagram_username": user_profile.get("username"),
        }
        return user_data
    return None

def send_instagram_message(account_id, access_token, recipient_id, message):
    """Send message to Instagram user, splitting if message is over 1000 characters"""

    url = f"https://graph.instagram.com/v22.0/{account_id}/messages"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
    }

    # Split message if it's longer than 1000 characters
    MAX_LENGTH = 1000
    message_parts = [message[i:i + MAX_LENGTH] for i in range(0, len(message), MAX_LENGTH)]

    success = True
    for part in message_parts:
        payload = {
            "recipient": {
                "id": recipient_id
            },
            "message": {
                "text": part
            }
        }

        response = requests.post(url, json=payload, headers=headers)
        print(f"send_instagram_message response: {response.text}")

        if response.status_code != 200:
            success = False  # agar bitta qismi yuborilmasa, false qaytaramiz

    return success

def send_instagram_private_reply(access_token, account_id, comment_id, message):
    """Send private reply to an Instagram comment"""
    url = f"https://graph.instagram.com/v23.0/{account_id}/messages"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
    }

    success = True
    payload = {
             "recipient":{ 
                 "comment_id": comment_id 
             },
             "message": { 
                 "text": message 
             }
    }

    response = requests.post(url, json=payload, headers=headers)
    print(f"send_instagram_private_reply response: {response.text}")

    if response.status_code != 200:
        success = False

    return success

def send_instagram_comment_reply(access_token, comment_id, message):
    """Send comment reply to an Instagram comment"""
    url = f"https://graph.instagram.com/v23.0/{comment_id}/replies"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
    }
    payload = {
        "message": message
    }
    response = requests.post(url, json=payload, headers=headers)
    print(f"send_instagram_comment_reply response: {response.text}")

def build_button_payload(btn):
    """
    btn: CommentResponseButton instance or dict with keys text, url, id, type
    returns dict suitable for the IG template buttons
    """
    if getattr(btn, "type", None) == "web_url" or (isinstance(btn, dict) and btn.get("type") == "web_url"):
        return {
            "type": "web_url",
            "url": btn.url if hasattr(btn, "url") else btn.get("url"),
            "title": btn.text if hasattr(btn, "text") else btn.get("text"),
        }
    # default is postback (inline)
    btn_id = btn.id if hasattr(btn, "id") else btn.get("id")
    return {
        "type": "postback",
        "title": btn.text if hasattr(btn, "text") else btn.get("text"),
        "payload": f"inline_button:{btn_id}"
    }



def send_instagram_postback(account_id: str, access_token: str, recipient_comment_id: str, data: Flow,commenter_id:str):
    url = "https://graph.instagram.com/v23.0/me/messages"  # keep version consistent with your integration
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
    }
    first_step = Step.objects.filter(flow=data, action=ActionType.MESSAGE.value, start_point=True).first()
    # Build buttons list
    if first_step:
        btns_payload = []
        for b in first_step.extra_button.all():
            btns_payload.append(build_button_payload(b))

        print(f"All buttons are ready{btns_payload}")
        image_url = None
        if first_step.message_image:
            image_url = first_step.message_image.url
        event = {
            "recipient": {
                "comment_id": recipient_comment_id
            },
            "message": {
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": "generic",
                        "elements": [
                            {
                                "title": first_step.message_content,
                                "image_url": image_url,
                                "buttons": btns_payload
                            },
                        ]
                                }
                            }
                        },
                        "tag": "HUMAN_AGENT"
                }

        resp = requests.post(url, json=event, headers=headers)
        if resp.status_code == 200:
            obj, created = InstagramUserState.objects.update_or_create(
                                                        account_id=account_id,
                                                        user_id=commenter_id,
                                                        defaults={"current_step": first_step}
                                                    )
        print(resp.json())
        print("[+] handling instagram message for postback")
        print(resp)

def checking_instagram_followers(access_token:str, recicipient_id:str):
    url = f"https://graph.instagram.com/v23.0/{recicipient_id}?fields=name,username,is_user_follow_business"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
    }
    response = requests.get(url, headers=headers)
    return response.json()

