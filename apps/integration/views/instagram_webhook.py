"""Instagram Messaging webhook receiver.

Called directly by Meta — the URL path, response codes and ack semantics are a
frozen external contract. Meta throttles and eventually disables a subscription
that keeps answering non-2xx, so unclaimed deliveries are ack'd and logged
rather than refused.
"""
import functools
import hashlib
import hmac
import logging
import time

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.utils.translation import gettext_lazy as _
from rest_framework.views import APIView

from apps.integration.models import Integration
from apps.integration.tasks import (
    WAIT_SECONDS,
    handle_postback_event_task,
    process_collected_messages,
    process_instagram_comment,
    process_instagram_message,
)
from apps.shared.addons.redis import redis_client
from apps.shared.addons.validations import error_response, success_response

try:
    from apps.integration.tasks import process_shared_post_message
except ImportError:
    process_shared_post_message = None

logger = logging.getLogger(__name__)


class InstagramWebhookView(APIView):

    def _verify_signature(self, request):
        """Verify Instagram X-Hub-Signature-256 header."""
        app_secret = settings.INSTAGRAM_APP_SECRET
        if not app_secret:
            # Fail closed: without a configured secret we cannot authenticate
            # the sender, so reject rather than accept forged events.
            logger.error("INSTAGRAM_APP_SECRET is not configured; rejecting webhook")
            return False

        signature_header = request.META.get('HTTP_X_HUB_SIGNATURE_256', '')
        if not signature_header:
            return False

        expected_signature = 'sha256=' + hmac.new(
            app_secret.encode('utf-8'),
            request.body,
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(signature_header, expected_signature)

    def get(self, request, *args, **kwargs):
        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge")

        if mode == "subscribe" and settings.INSTAGRAM_VERIFY_TOKEN and token == settings.INSTAGRAM_VERIFY_TOKEN:
            return HttpResponse(challenge, content_type="text/plain", status=200)

        return error_response(message=_("Token yaroqsiz"), code=403)

    def post(self, request, *args, **kwargs):  # noqa
        if not self._verify_signature(request):
            return error_response(message=_("Invalid signature"), code=403)

        data = request.data
        if not data:
            return error_response(message=_("Ma'lumot topilmadi"), code=400)

        entries = data.get("entry") or []
        if not entries:
            logger.warning("Instagram webhook carried no entry")
            return success_response(message=_("Ma'lumot topilmadi"), code=200)
        if len(entries) > 1:
            # Meta batches deliveries; only the first is handled below.
            logger.warning("Instagram webhook carried %s entries — only the first is processed", len(entries))

        entry = entries[0]
        account_id = entry.get("id")  # IG Professional Account ID (instagram_user_id)

        # Shape only — never the message body, which is customer content.
        logger.info(
            "Instagram webhook received for account %s: keys=%s changes=%s",
            account_id, sorted(entry.keys()),
            [c.get("field") for c in entry.get("changes", [])],
        )

        # Handle comments
        if "changes" in entry:
            for change in entry["changes"]:
                if change.get("field") == "comments":
                    comment_data = change.get("value", {})
                    if not comment_data:
                        logger.warning("Instagram comment change for %s had an empty value", account_id)
                        continue
                    # Get access token from integration
                    integration = Integration.instagram_by_id(account_id).first()
                    if not integration:
                        logger.warning("Instagram comment for unknown account %s", account_id)
                        continue
                    if not integration.api_token:
                        logger.warning("Instagram integration %s has no api_token; comment dropped", integration.id)
                        continue
                    transaction.on_commit(functools.partial(
                        process_instagram_comment.delay, account_id, comment_data))
                    return success_response(message=_("Comment webhook ma'lumotlar muvaffaqiyatli olindi"), code=200)

        # Instagram delivers DMs in one of two shapes. The classic one is
        # entry[].messaging[]; the Instagram-Login product instead sends a
        # changes[] entry with field "messages" whose `value` mirrors a
        # messaging item (sender / recipient / message). In that shape entry.id
        # is "0", so the account has to be read off the recipient.
        messaging = entry.get("messaging")
        if not messaging:
            messaging = [
                change.get("value")
                for change in entry.get("changes", [])
                if change.get("field") == "messages" and change.get("value")
            ]
        if messaging and account_id in (None, "", "0", 0):
            account_id = (messaging[0].get("recipient") or {}).get("id")
            logger.info("Instagram account resolved from the message recipient: %s", account_id)

        if messaging:
            # Handle postback events (button clicks)
            if "postback" in messaging[0]:
                integration = Integration.instagram_by_id(account_id).first()
                if integration and integration.api_token:
                    transaction.on_commit(functools.partial(
                        handle_postback_event_task.delay, messaging[0], integration.api_token))
                return success_response(message=_("Postback muvaffaqiyatli olindi"), code=200)

            # Deduplicate: check message ID to prevent processing the same webhook twice
            msg_mid = messaging[0].get("message", {}).get("mid")
            if msg_mid:
                dedup_key = f"ig_dedup:{msg_mid}"
                if redis_client.get(dedup_key):
                    logger.info("Duplicate Instagram message detected: %s", msg_mid)
                    return success_response(message=_("Duplicate message ignored"), code=200)
                redis_client.setex(dedup_key, 300, "1")  # 5 min TTL

            audio_file = None
            is_echo = messaging[0].get("message", {}).get("is_echo")
            reaction = messaging[0].get("reaction", {}).get("action", None)
            if reaction:
                return success_response(message=_("Reaction muvaffaqiyatli olindi"), code=200)
            attachment_type = messaging[0].get("message", {}).get("attachments", [{}])[0].get('type')
            if attachment_type == 'audio':
                audio_file = messaging[0].get("message", {}).get("attachments", [{}])[0].get("payload", {}).get("url", None)
            elif attachment_type == 'share':
                # User shared a post/reel in DM — extract post URL and process with context
                shared_url = messaging[0].get("message", {}).get("attachments", [{}])[0].get("payload", {}).get("url", None)
                user_text = messaging[0].get("message", {}).get("text", None)
                sender_id = messaging[0].get("sender", {}).get("id", None)
                if sender_id and not Integration.instagram_by_id(sender_id).exists():
                    if Integration.instagram_by_id(account_id).exists() and process_shared_post_message:
                        transaction.on_commit(functools.partial(
                            process_shared_post_message.delay, account_id, shared_url, user_text, messaging))
                return success_response(message=_("Shared post xabar muvaffaqiyatli olindi"), code=200)
            elif attachment_type in ['ig_reel', 'unsupported_type']:
                return success_response(message=_("Reel yoki qo'shimcha turdagi xabar muvaffaqiyatli olindi"), code=200)
            if is_echo:
                return success_response(message=_("Echo xabar muvaffaqiyatli olindi"), code=200)
            sender_id = messaging[0].get("sender", {}).get("id", None)
            if not Integration.instagram_by_id(sender_id).exists():
                if not Integration.instagram_by_id(account_id).exists():
                    # Ack unknown accounts: repeated non-2xx replies make Meta
                    # throttle and eventually disable the webhook subscription.
                    logger.warning("Integration not found for Instagram account %s", account_id)
                    return success_response(message=_("Integratsiya topilmadi"), code=200)
                # Start celery task to process the incoming message
                if audio_file:
                    transaction.on_commit(functools.partial(
                        process_instagram_message.delay, account_id, None, messaging, audio_file))
                else:
                    message = messaging[0].get("message", {}).get("text", None)
                    if message is not None:  # Only push if message is not None
                        # Buffer per end-user (sender_id) to avoid mixing conversations across users
                        redis_client.rpush(f"messages:{sender_id}", message)
                        redis_client.set(f"last_seen:{sender_id}", time.time())

                        # Schedule collector task only if not already scheduled for this sender
                        redis_client.setex(f"collecting:{sender_id}", WAIT_SECONDS + 1, "1")  # Prevent overlap
                        # Pass sender_id as chat_id, and include account_id for routing
                        transaction.on_commit(functools.partial(
                            process_collected_messages.apply_async,
                            (sender_id, None, messaging, None, None, account_id),
                            countdown=WAIT_SECONDS))
                return success_response(message=_("Xabar webhook ma'lumotlar muvaffaqiyatli olindi"), code=200)
            else:
                logger.info("Instagram sender %s is itself an integrated account; skipping", account_id)
                return success_response(message=_("Integratsiya boshqa foydalanuvchida ham topildi"), code=400)

        # Nothing above claimed this delivery. Ack it — Meta disables a
        # subscription that keeps failing — but say so, because this used to be
        # indistinguishable from a handled event in the logs.
        logger.warning(
            "Instagram webhook for %s was not handled: keys=%s changes=%s",
            account_id, sorted(entry.keys()),
            [c.get("field") for c in entry.get("changes", [])],
        )
        return success_response(message=_("Webhook ma'lumotlar muvaffaqiyatli olindi"), code=200)
