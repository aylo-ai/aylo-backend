"""Instagram DM tasks: direct messages and shared-post messages."""
import logging

from celery import shared_task

from apps.assistant.utils import cancel_pending_follow_ups
from apps.shared.ai_service.agent import respond
from apps.shared.ai_service.conversation import conversation_service
from apps.shared.addons.enums import ConversationStatuses, SenderTypes
from apps.shared.addons.instagram import instagram_service
from apps.shared.addons.redis import publish_message_to_ws

from ..models import Integration

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=5,
             name="apps.integration.tasks.process_instagram_message")
def process_instagram_message(self, account_id, combined_message, user_message, audio_file=None):
    """Store an incoming Instagram DM and answer it with the agent.

    ``combined_message`` is the (possibly debounced) text; ``user_message`` is the
    raw webhook messaging payload used to resolve the sender. Voice notes arrive
    as ``audio_file`` and are transcribed here.
    """
    integration = Integration.instagram_by_id(account_id).first()
    if not integration:
        logger.warning("[-] No Instagram integration found for account_id %s", account_id)
        return

    assistant = integration.assistant
    if not assistant:
        return

    sender_id = user_message[0].get("sender", {}).get("id")
    logger.info("Sender id: %s", sender_id)
    if not sender_id:
        return

    input_tokens = 0
    output_tokens = 0
    if audio_file:
        combined_message, input_tokens, output_tokens = conversation_service.process_instagram_audio(
            audio_file, assistant.language
        )
    if not combined_message:
        logger.info("[-] No message content to process")
        return

    conversation = conversation_service.get_or_create_conversation(
        sender_id, assistant, platform="instagram", chat_username=None
    )
    if conversation.client_full_name is None:
        conversation.client_full_name = instagram_service.get_user_info(
            integration.api_token, sender_id
        ).get("username", None)
        conversation.save()

    if conversation.status == ConversationStatuses.ESCALATED.value or not assistant.is_active:
        data = conversation_service.create_message(
            conversation=conversation, sender=SenderTypes.USER.value, content=combined_message,
            audio_file=audio_file, input_tokens=input_tokens, output_tokens=output_tokens
        )
        publish_message_to_ws(conversation.id, combined_message, sender="user", data=data,
                              assistant_id=assistant.id)
        return

    data = conversation_service.create_message(
        conversation=conversation, sender=SenderTypes.USER.value, content=combined_message,
        audio_file=audio_file, input_tokens=input_tokens, output_tokens=output_tokens
    )
    publish_message_to_ws(conversation.id, combined_message, sender="user", data=data,
                          assistant_id=assistant.id)

    # Cancel any pending follow-ups since the user responded.
    cancel_pending_follow_ups(conversation.id)

    if assistant.ai_enabled:
        response_message = respond(assistant, conversation, combined_message)
        if response_message:
            instagram_service.send_message(integration.instagram_send_id, integration.api_token, sender_id, response_message)


@shared_task(bind=True, max_retries=3, default_retry_delay=5,
             name="apps.integration.tasks.process_shared_post_message")
def process_shared_post_message(self, account_id, shared_url, user_text, messaging):
    """Process a shared Instagram post in DM — fetch post details and include as context for AI."""
    integration = Integration.instagram_by_id(account_id).first()
    if not integration:
        logger.warning("[-] No Instagram integration found for account_id: %s", account_id)
        return

    assistant = integration.assistant
    if not assistant:
        logger.warning("[-] No assistant found for account_id: %s", account_id)
        return

    sender_id = messaging[0].get("sender", {}).get("id")
    if not sender_id:
        return

    # Try to fetch post details so the agent knows what the client is asking about.
    post_context = ""
    if shared_url and integration.api_token:
        media_id = instagram_service.extract_media_id_from_url(
            shared_url, integration.api_token, integration.instagram_send_id
        )
        if media_id:
            media_details = instagram_service.get_media_details(integration.api_token, media_id)
            if media_details:
                caption = media_details.get("caption", "")
                media_type = media_details.get("media_type", "")
                post_context = (
                    f"\n\n[Klient quyidagi Instagram postni yubordi]\n"
                    f"Post turi: {media_type}\nPost matni: {caption}\nPost havolasi: {shared_url}"
                )

    # Build the combined message from whatever context we managed to gather.
    if user_text and post_context:
        combined_message = f"{user_text}{post_context}"
    elif post_context:
        combined_message = f"Klient quyidagi post haqida so'ramoqda.{post_context}"
    elif user_text:
        combined_message = user_text
    else:
        combined_message = f"Klient Instagram post yubordi: {shared_url}"

    conversation = conversation_service.get_or_create_conversation(
        sender_id, assistant, platform="instagram", chat_username=None
    )
    if conversation.client_full_name is None:
        conversation.client_full_name = instagram_service.get_user_info(
            integration.api_token, sender_id
        ).get("username", None)
        conversation.save()

    if conversation.status == ConversationStatuses.ESCALATED.value or not assistant.is_active:
        data = conversation_service.create_message(
            conversation=conversation, sender=SenderTypes.USER.value, content=combined_message
        )
        publish_message_to_ws(conversation.id, combined_message, sender="user", data=data,
                              assistant_id=assistant.id)
        return

    data = conversation_service.create_message(
        conversation=conversation, sender=SenderTypes.USER.value, content=combined_message
    )
    publish_message_to_ws(conversation.id, combined_message, sender="user", data=data,
                          assistant_id=assistant.id)

    if assistant.ai_enabled:
        response_message = respond(assistant, conversation, combined_message)
        if response_message:
            instagram_service.send_message(integration.instagram_send_id, integration.api_token, sender_id, response_message)
