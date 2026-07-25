"""Instagram comment tasks: template/flow replies and AI-powered comment answers.

Two modes exist per integration:
- Template mode: an ``InstagramCommentResponse`` decides whether to reply publicly,
  by private DM, or by starting a button flow (postback).
- AI mode (``integration.is_comment_response``): the comment is answered by the
  assistant through ``process_instagram_comment_message``.
"""
import logging
from datetime import datetime

import pytz
import requests
from celery import shared_task

from apps.shared.ai_service.agent import respond
from apps.shared.ai_service.conversation import conversation_service
from shared.addons.instagram import instagram_service

from ..models import Flow, InstagramCommentResponse, InstagramMedia, Integration

logger = logging.getLogger(__name__)


def _matches_trigger(response, comment_text):
    """True when the comment text exactly matches one of the configured trigger words."""
    trigger_words = [tw.trigger_word.lower() for tw in response.trigger_words.all()]
    matched = comment_text.strip().lower() in trigger_words
    if matched:
        logger.info("Media-specific trigger match: %s", trigger_words)
    return matched


def _dispatch_comment_response(integration, response, account_id, comment_id, commenter_id):
    """Send the configured reactions for one comment: public reply, private DM, or flow.

    Rules (kept from the original inline logic):
    - Public comment reply only when the integration is NOT in AI comment mode.
    - When a flow exists, the flow postback replaces the plain private DM.
    """
    flow = Flow.objects.filter(comment_response=response)

    if response.comment_message_template and not integration.is_comment_response:
        instagram_service.send_comment_reply(
            integration.api_token, comment_id, response.comment_message_template
        )
    if response.private_message_template and not flow.exists():
        instagram_service.send_private_reply(
            integration.api_token, account_id, comment_id, response.private_message_template
        )
    if flow.exists():
        logger.info("Flow exists for comment response %s — sending postback", response.id)
        instagram_service.send_postback(
            account_id=account_id,
            access_token=integration.api_token,
            recipient_comment_id=comment_id,
            data=flow.first(),
            commenter_id=commenter_id,
        )


def _fetch_latest_media(access_token):
    """Fetch the account's most recent media item from the Instagram API, or None."""
    url = "https://graph.instagram.com/v23.0/me/media"
    params = {
        "access_token": access_token,
        "fields": "id,media_type,media_url,username,timestamp,caption,comments_count,"
                  "like_count,permalink,thumbnail_url,children{media_type,media_url}"
    }
    response = requests.get(url, params=params)
    if response.status_code != 200:
        return None
    data = response.json().get('data') or []
    return data[0] if data else None


def _handle_new_media_comment(integration, account_id, comment_id, comment_text, commenter_id):
    """Comment on a post we haven't recorded yet.

    If the latest comment-response config has no media attached, it is meant for
    the *next* post — so if the account's newest post is newer than the config,
    apply the config to it and record the post as ``InstagramMedia``.
    """
    latest_response = InstagramCommentResponse.objects.filter(
        integration=integration
    ).order_by("-created_time").first()
    logger.info("Incoming comment for an unrecorded post")

    if not latest_response or latest_response.instagram_media.exists():
        return

    media_first = _fetch_latest_media(integration.api_token)
    if not media_first:
        return

    # The config only applies to posts published after it was created.
    media_ts = datetime.strptime(media_first["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
    media_ts_tashkent = media_ts.astimezone(pytz.timezone("Asia/Tashkent"))
    logger.info("Time %s and %s", media_ts_tashkent, latest_response.created_time)
    if media_ts_tashkent <= latest_response.created_time:
        return

    if latest_response.is_respond_to_all_comments or _matches_trigger(latest_response, comment_text):
        _dispatch_comment_response(integration, latest_response, account_id, comment_id, commenter_id)

    # Record the post and attach it so future comments hit the fast path.
    media_data = InstagramMedia.objects.create(
        media_id=media_first.get('id'),
        media_type=media_first.get('media_type', None),
        media_url=media_first.get('media_url', None),
        username=media_first.get('username', None),
        timestamp=media_first.get('timestamp', None),
        caption=media_first.get('caption', None),
        comments_count=media_first.get('comments_count', None),
        like_count=media_first.get('like_count', None),
        children=media_first.get('children', None)
    )
    latest_response.instagram_media.add(media_data)


@shared_task(bind=True, max_retries=2, default_retry_delay=10,
             name="apps.integration.tasks.process_instagram_comment")
def process_instagram_comment(self, account_id, comment_data):
    """Entry point for Instagram comment webhooks."""
    logger.info("[+] Processing Instagram comment for account_id: %s", account_id)

    integration = Integration.objects.filter(instagram_account_id=account_id).first()
    if not integration:
        logger.warning("[-] Integration not found")
        return

    media_id = comment_data.get("media", {}).get("id")
    comment_id = comment_data.get("id")
    comment_text = comment_data.get("text", "").strip()
    commenter_id = comment_data.get("from", {}).get("id")
    parent_id = comment_data.get("parent_id", None)

    if not all([media_id, comment_id, comment_text, commenter_id]):
        logger.warning("[-] Missing required comment data")
        return

    # Replies to comments (threaded) are ignored — only top-level comments react.
    if parent_id is not None:
        logger.info("Media %s has parent_id: %s — skipping reply comment", media_id, parent_id)
        return

    media_record = InstagramMedia.objects.filter(media_id=media_id).first()
    if media_record:
        # Known post: use its configured comment response, if any.
        response = InstagramCommentResponse.objects.filter(instagram_media=media_record).first()
        if response is None:
            logger.info("No comment response configured for media %s", media_id)
        elif response.is_respond_to_all_comments:
            logger.info("Media-specific: respond to all comments")
            _dispatch_comment_response(integration, response, account_id, comment_id, commenter_id)
        elif _matches_trigger(response, comment_text):
            _dispatch_comment_response(integration, response, account_id, comment_id, commenter_id)
    else:
        _handle_new_media_comment(integration, account_id, comment_id, comment_text, commenter_id)

    if integration.is_comment_response:
        # AI comment mode: the assistant writes the reply.
        logger.info("Integration is in AI comment mode — handing off to the assistant")
        process_instagram_comment_message.delay(
            account_id=account_id, message=comment_text, comment_id=comment_id,
            integration_id=integration.id, media_id=media_id
        )


@shared_task(name="apps.integration.tasks.process_instagram_comment_message")
def process_instagram_comment_message(account_id, message, comment_id, integration_id, media_id=None):
    """Answer a comment with the AI assistant via private reply (AI comment mode)."""
    logger.info("Process instagram comment message")
    integration = Integration.objects.filter(id=integration_id).first()
    if not integration:
        logger.warning("Integration not found")
        return

    try:
        assistant = integration.assistant
        if not assistant:
            logger.warning("No assistant found for integration")
            return

        # Each comment thread gets its own conversation keyed by the comment id.
        conversation = conversation_service.get_or_create_conversation(
            user_id=comment_id,
            assistant=assistant,
            platform="instagram",
            chat_username=None
        )

        # Public template reply still applies in AI mode when one is configured.
        if media_id:
            comment_response = InstagramCommentResponse.objects.filter(
                instagram_media__media_id=media_id
            ).first()
            if comment_response:
                instagram_service.send_comment_reply(
                    access_token=integration.api_token, comment_id=comment_id,
                    message=comment_response.comment_message_template
                )

        if assistant.ai_enabled and assistant.is_active:
            response_message = respond(assistant, conversation, message)
            instagram_service.send_private_reply(
                access_token=integration.api_token, account_id=account_id,
                comment_id=comment_id, message=response_message
            )

    except Exception:
        logger.exception("Error processing Instagram comment")
