"""Telegram channel tasks: text, voice and photo messages from bot webhooks."""
import logging

from apps.shared import http
from celery import shared_task

from apps.assistant.models import Assistant
from apps.assistant.utils import cancel_pending_follow_ups
from apps.shared.ai_service import media
from apps.shared.ai_service.agent import respond
from apps.assistant.services.conversation import conversation_service
from apps.shared.addons.enums import ConversationStatuses, SenderTypes
from apps.shared.addons.redis import publish_message_to_ws
from apps.integration.gateways.telegram import send_telegram_action, send_telegram_message

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=5,
             name="apps.integration.tasks.process_message_task")
def process_message_task(self, chat_id, user_message, bot_token, chat_username=None, username=None,
                         audio_file=None, input_tokens=None, output_tokens=None):
    """Store an incoming Telegram text message and answer it with the agent.

    Escalated conversations and inactive assistants only store the message (a
    human operator takes over); otherwise the agent's reply is sent back.
    """
    assistant = Assistant.objects.filter(integrations__api_token=bot_token).first()
    if not assistant:
        # The bot token is the credential for the customer's bot — log that a
        # delivery went unmatched, never the token that would let a reader take
        # the bot over.
        logger.warning("[-] No assistant found for the bot token on this delivery")
        return

    if user_message == '/start':
        conversation_service.handle_start_command(chat_id, assistant, bot_token, chat_username, username)
        return

    conversation = conversation_service.get_or_create_conversation(
        chat_id, assistant, token=bot_token, chat_username=chat_username, username=username
    )
    if conversation.status == ConversationStatuses.ESCALATED.value or not assistant.is_active:
        data = conversation_service.create_message(
            conversation=conversation, sender=SenderTypes.USER.value, content=user_message,
            audio_file=audio_file, input_tokens=input_tokens, output_tokens=output_tokens
        )
        publish_message_to_ws(conversation.id, user_message, sender="user", data=data, assistant_id=assistant.id)
        return

    # Show "typing…" while the agent thinks.
    send_telegram_action(chat_id, bot_token)

    data = conversation_service.create_message(
        conversation=conversation, sender=SenderTypes.USER.value, content=user_message,
        audio_file=audio_file, input_tokens=input_tokens, output_tokens=output_tokens
    )
    publish_message_to_ws(conversation_id=conversation.id, message=user_message, sender='user',
                          data=data, assistant_id=assistant.id)

    # Cancel any pending follow-ups since the user responded.
    cancel_pending_follow_ups(conversation.id)

    response_message = respond(assistant, conversation, user_message)
    logger.info("[+] Response message: %s", response_message)

    if response_message:
        send_telegram_message(chat_id, response_message, bot_token)


@shared_task(bind=True, max_retries=3, default_retry_delay=5,
             name="apps.integration.tasks.process_voice_task")
def process_voice_task(self, chat_id, voice_file_id, bot_token):
    """Download a Telegram voice note, transcribe it, and hand the text to
    ``process_message_task`` as a normal message (with the audio attached)."""
    assistant = Assistant.objects.filter(integrations__api_token=bot_token).first()
    if not assistant:
        logger.warning("[+] Assistant not found")
        return

    file_info_url = f"https://api.telegram.org/bot{bot_token}/getFile?file_id={voice_file_id}"
    file_info_resp = http.get(file_info_url)
    file_path = file_info_resp.json()["result"]["file_path"]
    file_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"

    audio_bytes_ogg = http.get(file_url).content
    audio_bytes_mp3 = conversation_service.convert_ogg_to_mp3(audio_bytes_ogg)

    transcribed_text, input_tokens, output_tokens = media.transcribe_audio(audio_bytes_mp3)
    if transcribed_text == media.TRANSCRIBE_FAILED:
        send_telegram_message(chat_id, "I couldn't hear that clearly. Could you try again?", bot_token)
        return

    process_message_task.delay(chat_id=chat_id, user_message=transcribed_text, bot_token=bot_token,
                               audio_file=audio_bytes_mp3, input_tokens=input_tokens,
                               output_tokens=output_tokens)


@shared_task(bind=True, max_retries=3, default_retry_delay=5,
             name="apps.integration.tasks.process_photo_task")
def process_photo_task(self, chat_id, photo_file_id, bot_token, chat_username=None, username=None):
    """Describe a Telegram photo with vision and answer based on the description."""
    assistant = Assistant.objects.filter(integrations__api_token=bot_token).first()
    if not assistant:
        logger.warning("[+] Assistant not found")
        return

    try:
        # Resolve the file URL from Telegram, then let vision describe it.
        file_info_url = f"https://api.telegram.org/bot{bot_token}/getFile?file_id={photo_file_id}"
        file_info_resp = http.get(file_info_url)
        file_info_resp.raise_for_status()
        file_path = file_info_resp.json()["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"

        image_analysis = media.analyze_image(file_url)

        if image_analysis == media.IMAGE_FAILED:
            send_telegram_message(chat_id, "I couldn't analyze the image. Please try again.", bot_token)
            return

        conversation = conversation_service.get_or_create_conversation(
            chat_id, assistant, token=bot_token, chat_username=chat_username, username=username
        )

        if conversation.status == ConversationStatuses.ESCALATED.value or not assistant.is_active:
            data = conversation_service.create_message(
                conversation=conversation,
                sender=SenderTypes.USER.value,
                content=f"[Image] {image_analysis}"
            )
            publish_message_to_ws(conversation.id, image_analysis, sender="user", data=data,
                                  assistant_id=assistant.id)
            return

        send_telegram_action(chat_id, bot_token)

        data = conversation_service.create_message(
            conversation=conversation,
            sender=SenderTypes.USER.value,
            content=f"[Image] {image_analysis}"
        )
        publish_message_to_ws(conversation_id=conversation.id, message=image_analysis, sender='user',
                              data=data, assistant_id=assistant.id)

        response_message = respond(assistant, conversation, image_analysis)
        logger.info("[+] Photo response message: %s", response_message)

        if response_message:
            send_telegram_message(chat_id, response_message, bot_token)

    except Exception:
        # Fail soft: apologise to the customer instead of dying silently.
        logger.exception("Error processing photo")
        send_telegram_message(chat_id, "I encountered an error while processing the image. Please try again.", bot_token)
