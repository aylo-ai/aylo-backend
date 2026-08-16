"""Conversation and message plumbing that sits between the platforms and the agent.

This is the Django-model side of the AI service: it turns webhook payloads into
`Conversation` and `Message` rows, converts voice notes to a format Whisper can
read, and hands transcription off to `media`. The agent itself lives in
`agent.py`; this module never calls the model directly except through `media`.
"""
import io
import logging
from io import BytesIO
from shutil import which

from django.core.files.base import ContentFile
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from pydub import AudioSegment

from apps.assistant.models import Conversation, Message
from apps.integration.gateways.telegram import send_telegram_message
from apps.shared import http
from apps.shared.addons.enums import ConversationStatuses, MessageTypes
from apps.shared.addons.redis import publish_message_to_ws_assistant
from apps.shared.addons.validations import success_response
from apps.shared.ai_service import media

logger = logging.getLogger(__name__)


class ConversationService:

    # -- audio -----------------------------------------------------------

    def convert_ogg_to_mp3(self, audio_bytes: bytes) -> bytes:
        """Transcode an OGG voice note to MP3 so Whisper can read it."""
        AudioSegment.converter = which("ffmpeg")
        AudioSegment.ffprobe = which("ffprobe")
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format="ogg")
        out = io.BytesIO()
        audio.export(out, format="mp3")
        return out.getvalue()

    def get_audio_from_url(self, url: str):
        """Download an audio file and return it as MP3 bytes, or None on failure.

        The URL comes off a webhook payload, so it goes through `fetch_external`,
        which refuses internal addresses, re-checks every redirect hop and caps
        the download size. A plain `http.get` here was an SSRF into the worker's
        own network.
        """
        try:
            content = http.fetch_external(url)
            audio = AudioSegment.from_file(BytesIO(content))
            out = BytesIO()
            audio.export(out, format="mp3")
            return out.getvalue()
        except Exception as exc:
            # Query string omitted: for our own presigned URLs it is a bearer
            # credential, and for webhook URLs it carries platform tokens.
            logger.warning("Could not fetch audio from %s: %s", url.split("?")[0], exc)
            return None

    def process_instagram_audio(self, audio_url: str, language: str = "uz"):
        """Transcribe an Instagram voice note. Returns (text, input_tokens, output_tokens)."""
        audio_bytes = self.get_audio_from_url(audio_url)
        if not audio_bytes:
            return media.TRANSCRIBE_FAILED, 0, 0
        return media.transcribe_audio(audio_bytes)

    # -- messages --------------------------------------------------------

    def create_message(self, conversation, sender, content, audio_file=None,
                       input_tokens=None, output_tokens=None):
        """Persist one message and return its id (and audio url, if any)."""
        if isinstance(audio_file, str) and audio_file.startswith("https://"):
            audio_file = self.get_audio_from_url(audio_file)

        message = Message.objects.create(
            conversation=conversation,
            sender=sender,
            message_content=content,
            message_type=MessageTypes.AUDIO.value if audio_file else MessageTypes.TEXT.value,
            input_tokens=input_tokens or 0,
            output_tokens=output_tokens or 0,
        )

        if not audio_file:
            return {"id": message.id, "audio_file": None}

        file_name = f"audio_{slugify(conversation.id)}_{message.id}.mp3"
        message.audio_file.save(file_name, ContentFile(audio_file))
        return {"id": message.id, "audio_file": message.audio_file.url}

    # -- conversations ---------------------------------------------------

    def get_or_create_conversation(self, user_id, assistant, reset=False, token=None,
                                  platform="telegram", chat_username=None, username=None):
        """Return the open conversation for this user, creating one if needed.

        `reset=True` (a `/start`) begins a genuinely fresh chat on an existing
        conversation: the agent's memory is dropped and a closed chat is reopened.
        """
        conversation = Conversation.objects.filter(
            assistant=assistant, user_id=user_id, token=token
        ).first()
        if conversation is not None:
            if reset:
                self.reset_conversation(conversation)
            return conversation

        conversation = Conversation.objects.create(
            assistant=assistant,
            user_id=user_id,
            status=ConversationStatuses.OPEN.value,
            token=token,
            platform=platform,
            username=username or None,
            client_full_name=chat_username,
            client_phone_email=f"@{username}" if username else None,
        )
        logger.info("Created conversation %s for assistant %s", conversation.id, assistant.id)

        try:
            publish_message_to_ws_assistant(conversation)
        except Exception as exc:
            logger.warning("Failed to publish new conversation %s: %s", conversation.id, exc)

        return conversation

    def reset_conversation(self, conversation):
        """Start the conversation over: drop the agent chain and reopen it.

        Called on `/start`. Clearing the chain (`previous_response_id`) is what
        makes the next message a fresh context with the latest instructions,
        rather than a continuation of the old one. An escalated chat is left
        alone so a human colleague keeps ownership.
        """
        from apps.shared.ai_service.agent import clear_chain

        clear_chain(conversation)

        if conversation.status == ConversationStatuses.CLOSED.value:
            conversation.status = ConversationStatuses.OPEN.value
            conversation.save(update_fields=["status", "updated_time"])
            logger.info("Reopened conversation %s on /start", conversation.id)

    def handle_start_command(self, chat_id, assistant, bot_token, chat_username, username):
        """Greet the customer and open (or reopen) their conversation."""
        send_telegram_message(chat_id, assistant.greeting_message, bot_token)
        self.get_or_create_conversation(
            chat_id, assistant, reset=True, token=bot_token,
            chat_username=chat_username, username=username,
        )
        return success_response(
            message=_("Salomlashish va yangi chat muvaffaqiyatli bajarildi"), code=200
        )


conversation_service = ConversationService()
