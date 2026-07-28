import logging

import requests

from django.conf import settings
from django.db import transaction

from apps.integration.models import Flow, InstagramUserState, Step
from shared.addons.enums import ActionType

logger = logging.getLogger(__name__)


class InstagramService:
    GRAPH_BASE = "https://graph.instagram.com"

    def __init__(self):
        pass

    # ---- Auth / profile ----

    def get_long_lived_access_token(self, short_lived_access_token: str) -> str | None:
        """Get long-lived access token from short-lived access token."""
        client_secret = settings.INSTAGRAM_CLIENT_SECRET
        if not client_secret:
            logger.error("INSTAGRAM_CLIENT_SECRET is not configured; cannot exchange token")
            return None
        grant_type = "ig_exchange_token"
        url = (
            f"{self.GRAPH_BASE}/access_token?grant_type={grant_type}&"
            f"client_secret={client_secret}&access_token={short_lived_access_token}"
        )

        response = requests.get(url)
        if response.status_code == 200:
            access_token = response.json().get("access_token")
            # Optionally refresh right away
            self.instagram_refresh_token(access_token)
            return access_token
        return None

    def instagram_refresh_token(self, access_token: str) -> str | None:
        """Refresh a long-lived access token."""
        grant_type = "ig_refresh_token"
        url = f"{self.GRAPH_BASE}/refresh_access_token?grant_type={grant_type}&access_token={access_token}"

        response = requests.get(url)
        if response.status_code == 200:
            return response.json().get("access_token")
        return None

    def get_user_info(self, access_token: str, user_id: str) -> dict:
        """Fetch a user's public info (id, username) by user ID.

        Fail-soft: returns {} on any request/parse error so a message-processing
        task never dies just because the profile lookup failed.
        """
        url = f"{self.GRAPH_BASE}/v23.0/{user_id}"
        params = {
            "access_token": access_token,
            "fields": "id, username",
        }
        try:
            response = requests.get(url, params=params)
            return response.json()
        except (requests.RequestException, ValueError) as e:
            logger.warning("Instagram get_user_info failed for %s: %s", user_id, e)
            return {}

    def get_user_profile(self, access_token: str) -> dict | None:
        """Get user profile from access token."""
        url = (
            f"{self.GRAPH_BASE}/me?"
            f"fields=id,user_id,username&"
            f"access_token={access_token}"
        )
        response = requests.get(url)
        if response.status_code == 200:
            user_profile = response.json()
            return {
                "instagram_user_id": user_profile.get("id"),
                "instagram_account_id": user_profile.get("user_id"),
                "instagram_username": user_profile.get("username"),
            }
        return None

    def unsubscribe_webhooks(self, access_token: str) -> bool:
        """Drop this app's webhook subscription for the token's account.

        Fail-soft: without this, Meta keeps delivering events for accounts whose
        integration has been removed and every one is logged as unroutable.
        """
        if not access_token:
            return False
        url = f"{self.GRAPH_BASE}/v22.0/me/subscribed_apps"
        try:
            response = requests.delete(url, params={"access_token": access_token})
            if response.status_code != 200:
                logger.warning(
                    "Instagram webhook unsubscribe returned %s", response.status_code
                )
                return False
            return True
        except requests.RequestException as e:
            logger.warning("Instagram webhook unsubscribe failed: %s", e)
            return False

    # ---- Messaging ----

    def send_message(
        self, account_id: str, access_token: str, recipient_id: str, message: str, tag: str = None
    ) -> bool:
        url = f"{self.GRAPH_BASE}/v22.0/{account_id}/messages"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        }

        MAX_LENGTH = 1000
        message_parts = [
            message[i : i + MAX_LENGTH] for i in range(0, len(message), MAX_LENGTH)
        ]

        success = True
        for part in message_parts:
            payload = {"recipient": {"id": recipient_id}, "message": {"text": part}}
            if tag:
                payload["tag"] = tag
            response = requests.post(url, json=payload, headers=headers)

            if response.status_code != 200:
                success = False
                logger.warning("Instagram send_message failed with status %s", response.status_code)
        return success

    def send_photo(
        self, account_id: str, access_token: str, recipient_id: str, photo_url: str
    ):
        """Send a photo message to an Instagram user."""
        url = f"{self.GRAPH_BASE}/v22.0/{account_id}/messages"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        }
        payload = {
            "recipient": {"id": recipient_id},
            "message": {
                "attachment": {
                    "type": "image",
                    "payload": {"url": photo_url},
                }
            },
        }
        return requests.post(url, json=payload, headers=headers)

    def send_private_reply(
        self, access_token: str, account_id: str, comment_id: str, message: str
    ) -> bool:
        """Send a private reply to a comment via Instagram messaging."""
        url = f"{self.GRAPH_BASE}/v23.0/{account_id}/messages"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        }

        success = True
        payload = {
            "recipient": {"comment_id": comment_id},
            "message": {"text": message},
        }

        response = requests.post(url, json=payload, headers=headers)

        if response.status_code != 200:
            success = False
            logger.warning("Instagram send_private_reply failed with status %s", response.status_code)

        return success

    def send_comment_reply(self, access_token: str, comment_id: str, message: str):
        """Reply to a comment publicly."""
        url = f"{self.GRAPH_BASE}/v23.0/{comment_id}/replies"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        }
        payload = {"message": message}
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            logger.warning("Instagram send_comment_reply failed with status %s", response.status_code)
        return response

    # ---- Buttons / postbacks ----

    def build_button_payload(self, btn):
        """Build a payload for an Instagram button (web_url or postback)."""
        if getattr(btn, "type", None) == "web_url" or (
            isinstance(btn, dict) and btn.get("type") == "web_url"
        ):
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
            "payload": f"inline_button:{btn_id}",
        }

    def send_postback(
        self,
        account_id: str,
        access_token: str,
        recipient_comment_id: str,
        data: Flow,
        commenter_id: str,
    ):
        """Send a generic template postback with buttons and optional image."""
        url = f"{self.GRAPH_BASE}/v23.0/me/messages"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        }
        first_step = Step.objects.filter(
            flow=data, action=ActionType.MESSAGE.value, start_point=True
        ).first()
        if not first_step:
            return None

        btns_payload = [
            self.build_button_payload(b) for b in first_step.extra_button.all()
        ]

        image_url = first_step.message_image.url if first_step.message_image else None
        event = {
            "recipient": {"comment_id": recipient_comment_id},
            "message": {
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": "generic",
                        "elements": [
                            {
                                "title": first_step.message_content,
                                "image_url": image_url,
                                "buttons": btns_payload,
                            },
                        ],
                    },
                }
            },
            "tag": "HUMAN_AGENT",
        }

        resp = requests.post(url, json=event, headers=headers)
        if resp.status_code == 200:
            try:
                with transaction.atomic():
                    InstagramUserState.objects.update_or_create(
                        account_id=account_id,
                        user_id=commenter_id,
                        defaults={"current_step": first_step},
                    )
                    first_step.count += 1
                    first_step.save()
                    first_step.flow.total_count += 1
                    first_step.flow.save()
            except Exception:
                logger.exception("Error updating Instagram user state")
        else:
            logger.warning("Instagram postback send failed with status %s", resp.status_code)
        return resp

    def send_step_template(self, access_token: str, recipient_id: str, step: Step):
        """Send a flow step as a generic template (title, image, buttons) via DM.

        Pure HTTP — persisting the user's new flow position is the caller's job
        (see ``send_step_message_task``). Returns the response, or None on error.
        """
        url = f"{self.GRAPH_BASE}/v23.0/me/messages"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        }

        btns_payload = [self.build_button_payload(b) for b in step.extra_button.all()]
        logger.info("All buttons are ready %s", btns_payload)

        image_url = step.message_image.url if step.message_image else None
        event = {
            "recipient": {"id": recipient_id},
            "message": {
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": "generic",
                        "elements": [
                            {
                                "title": step.message_content,
                                "image_url": image_url,
                                "buttons": btns_payload,
                            },
                        ],
                    },
                }
            },
        }

        try:
            resp = requests.post(url, json=event, headers=headers)
            logger.info("send_step_template response: %s", resp.text)
            return resp
        except requests.RequestException as e:
            logger.warning("Instagram send_step_template failed: %s", e)
            return None

    # ---- Media details ----

    def get_media_details(self, access_token: str, media_id: str) -> dict | None:
        """Fetch media details (caption, media_type, etc.) by media ID."""
        url = f"{self.GRAPH_BASE}/v23.0/{media_id}"
        params = {
            "fields": "id,caption,media_type,media_url,timestamp,permalink",
            "access_token": access_token,
        }
        response = requests.get(url, params=params)
        if response.status_code == 200:
            return response.json()
        return None

    def extract_media_id_from_url(self, shared_url: str, access_token: str, account_id: str) -> str | None:
        """Extract the media ID from a shared Instagram post URL using oEmbed or searching recent media."""
        # Try to get media ID from the URL via the Instagram API
        # First, search user's recent media to match permalink
        url = f"{self.GRAPH_BASE}/v23.0/{account_id}/media"
        params = {
            "fields": "id,permalink",
            "limit": 50,
            "access_token": access_token,
        }
        response = requests.get(url, params=params)
        if response.status_code == 200:
            for media in response.json().get("data", []):
                if media.get("permalink") and shared_url and media["permalink"].rstrip("/") in shared_url.rstrip("/"):
                    return media["id"]
        return None

    # ---- Followers / metadata ----

    def checking_followers(self, access_token: str, recipient_id: str) -> dict:
        """Check if a user follows the business account."""
        url = f"{self.GRAPH_BASE}/v23.0/{recipient_id}?fields=name,username,is_user_follow_business"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        }
        response = requests.get(url, headers=headers)
        return response.json()


instagram_service = InstagramService()

