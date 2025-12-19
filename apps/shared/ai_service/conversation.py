import requests
import io
from shutil import which
from io import BytesIO
from pydub import AudioSegment
import json
import logging
from typing import Optional, Tuple
from google import genai
from google.genai import types
from django.conf import settings

from django.db import transaction
from django.utils.translation import gettext_lazy as _

from apps.assistant.models import Assistant, Message, Conversation, Lead
from shared.addons.enums import SubscriptionStatuses, ConversationPlatforms
from shared.addons.validations import error_response, success_response
from shared.ai_service.openai_client import client

from shared.ai_service.thread import thread_service
from shared.ai_service.assistant import assistant_service
from shared.addons.telegram import send_telegram_message
from shared.addons.redis import publish_message_to_ws_assistant


logger = logging.getLogger(__name__)


class ConversationService:
    def __init__(self, client):
        self.client = client

    def _recursion_ai_response(
        self, thread_id: str, message_content: str, assistant_id: str
    ) -> Tuple[Optional[str], Optional[object]]:
        
        active_runs = self.client.beta.threads.runs.list(thread_id=thread_id)
        if active_runs.data:
            for run in active_runs.data:
                thread_service.wait_on_run(run, thread_id)

        user_message = self.client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=f"User: {message_content}",
        )

        run = self.client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=assistant_id,
        )
        run_status = thread_service.wait_on_run(run, thread_id)

        messages = self.client.beta.threads.messages.list(
            thread_id=thread_id, order="asc", after=user_message.id
        )
        assistant_response = None

        for msg in messages.data:
            if msg.role == "assistant" and msg.content:
                for block in msg.content:
                    if block.type == "text":
                        if hasattr(block.text, "value"):
                            assistant_response = block.text.value
                            break
                        elif isinstance(block.text, str):
                            assistant_response = block.text
                            break

        if assistant_response is None:
            logger.error(
                "No assistant response found in messages for thread_id: %s",
                thread_id,
            )
            return None, run_status

        return assistant_response, run_status

    def get_assistant_response_ai(
        self,
        user_message: str,
        assistant_id: str,
        thread_id: Optional[str],
        conversation,
    ) -> Tuple[Optional[str], Optional[object], Optional[object]]:
        """
        High-level API used across the project.
        Returns (clean_response_text, run_status, response_data_or_lead).
        """
        assistant = Assistant.objects.get(assistant_id=assistant_id)

        # Subscription checks
        if assistant.user.subscription is None:
            return (
                error_response(
                    message=_(
                        "Sizning obunangiz tugadi. Iltimos, platformaga kirib, to'lovni qayta amalga oshiring."
                    ),
                    code=400,
                ),
                None,
                None,
            )

        subscription = assistant.user.subscription
        if (
            subscription.remained_request_count <= 0
            or subscription.status == SubscriptionStatuses.INACTIVE.value
        ):
            # Mirror previous behaviour: just no AI answer when exhausted
            return assistant.fallback_message, None, None

        if thread_id is None:
            return _("Sizda hali assistantga fayl yuklanmagan"), None, None

        try:
            raw_response, run_status = self._recursion_ai_response(
                thread_id=thread_id,
                message_content=user_message,
                assistant_id=assistant_id,
            )

            if not raw_response:
                logger.error(
                    "Failed to get assistant response: no runs found for thread_id: %s",
                    thread_id,
                )
                return None, None, None

            # Parse structured JSON if possible
            intent = None
            entities = None
            message = None

            try:
                parsed = json.loads(raw_response)
                intent = parsed.get("intent")
                message = parsed.get("reply")
                entities = parsed.get("entities")
                if parsed.get("properties"):
                    props = parsed["properties"]
                    intent = props.get("intent", intent)
                    message = props.get("reply", message)
                    entities = props.get("entities", entities)
            except Exception:
                # Fallback to raw string
                message = raw_response
                intent = None
                entities = None

            clean_response = assistant_service.check_response(message)

            # Notify unknown intent if needed

            response_data = None
            # Lead creation logic, same as before
            if intent == "order_confirmation" and entities:
                name = (
                    entities.get("name")
                    or entities.get("full_name")
                    or entities.get("customer_user")
                    or entities.get("customer_name")
                )
                phone_number = entities.get("phone_number") or entities.get(
                    "contact_number"
                )
                platform = conversation.platform if conversation.platform else None
                platform_map = {
                    ConversationPlatforms.INSTAGRAM.value: conversation.client_full_name,
                    ConversationPlatforms.TELEGRAM.value: conversation.username,
                }
                username = (
                    platform_map.get(conversation.platform)
                    if conversation.platform
                    else None
                )

                response_data = self.create_update_lead(
                    assistant=assistant,
                    full_name=name,
                    username=username,
                    platform=platform,
                    phone_number=phone_number,
                    email=entities.get("email", None),
                    product=entities.get("product", None),
                    metadata=entities,
                )

            return clean_response, run_status, response_data
        except Exception as e:
            logger.error("Error in get_assistant_response_ai: %s", e)
            return "", None, None

    def convert_ogg_to_mp3(self, audio_bytes: bytes) -> bytes:
        AudioSegment.converter = which("ffmpeg")    # mp3 konvertatsiyasi uchun
        AudioSegment.ffprobe = which("ffprobe")     # fayl formatini o'qish uchun
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format="ogg")
        print(f"Audio: {audio}")
        mp3_io = io.BytesIO()
        print(f"Mp3 io: {mp3_io}")
        audio.export(mp3_io, format="mp3")
        print(f"Mp3 io: {mp3_io}")
        return mp3_io.getvalue()


    def speech_to_text(self, audio_bytes: bytes, language: str = "uz") -> str:
        try:
            client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY)
            print(f"Client: {client}")
            prompt = f"""
                Transcribe the following audio in plain {language} text. 
                Do not include timestamps or any explanations. 
                Only return the raw transcription.
                """
            print(f"Prompt: {prompt}")
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    prompt,
                    types.Part.from_bytes(data=audio_bytes, mime_type="audio/mp3")
                ],
                config=types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(
                        include_thoughts=False
                    ),
                ),
            )
            input_tokens = response.usage_metadata.prompt_token_count
            output_tokens = response.usage_metadata.candidates_token_count

            print(f"[speech_to_text] Response received: {response}")
            result = response.text.strip()
            print(f"[speech_to_text] Final result: {result}")
            return result, input_tokens, output_tokens
        except Exception as e:
            print(f"[speech_to_text] Error: {str(e)}")
            print(f"[speech_to_text] Error type: {type(e)}")
            import traceback
            print(f"[speech_to_text] Traceback: {traceback.format_exc()}")
            return "Sorry, I couldn't understand the audio.", 0, 0

    def create_message(self, conversation, sender, content, audio_file=None, run_status=None, input_tokens=None, output_tokens=None):
        message_type = 'audio' if audio_file else 'text'
        if isinstance(audio_file, str) and audio_file.startswith("https://"):
            audio_file = self.get_audio_from_url(audio_file)
        
        if audio_file:
            input_tokens = input_tokens
            output_tokens = output_tokens
        else:
            input_tokens = run_status.usage.prompt_tokens if run_status and hasattr(run_status, 'usage') else 0
            output_tokens = run_status.usage.completion_tokens if run_status and hasattr(run_status, 'usage') else 0
        
        message = Message.objects.create(
            conversation=conversation,
            sender=sender,
            message_content=content,
            message_type=message_type,
            input_tokens=input_tokens,
            output_tokens=output_tokens
        )

        if audio_file:
            from django.core.files.base import ContentFile
            from django.utils.text import slugify

            file_name = f"audio_{slugify(conversation.id)}_{message.id}.mp3"
            message.audio_file.save(file_name, ContentFile(audio_file))
            message.save()
            return {
                "id": message.id,
                "audio_file": message.audio_file.url
            }
        else:
            return {
                "id": message.id,
                "audio_file": None
            }

    def create_update_lead(self, full_name, phone_number, email, product, assistant, platform, username, metadata=None):
        try:
            with transaction.atomic():
                lead = Lead.objects.create(
                    full_name=full_name,
                    phone_number=phone_number,
                    email=email,
                    product=product,
                    assistant=assistant,
                    platform=platform,
                    username=username,
                    metadata=metadata,
                )
                return lead
        except Exception as e:
            print(f"[create_lead] Error: {e}")
            return None
        
    def get_or_create_conversation(self, user_id, assistant, reset=False, token=None, platform='telegram', chat_username=None, username=None):
        conversation = Conversation.objects.filter(
            assistant=assistant,
            user_id=user_id,
            token=token).first()
        thread_id = None
        if conversation is None:
            thread_id = thread_service.get_thread_id(str(assistant.assistant_id), str(assistant.vector_id))
            print(f"conversation is None, creating new conversation with thread_id: {thread_id}")
            conversation = Conversation.objects.create(
                assistant=assistant,
                user_id=user_id,
                thread_id=thread_id,
                status='open',
                token=token,
                platform=platform,
                username=username if username else None,
                client_full_name=chat_username,
                client_phone_email=f"@{username}" if username else None
            )
            publish_message_to_ws_assistant(conversation)
            print(f"Conversation created: {conversation}")

        elif reset and conversation is not None:
            if assistant.ai_enabled:
                conversation.thread_id = thread_service.get_thread_id(str(assistant.assistant_id), str(assistant.vector_id))
            conversation.status = 'open'
            print(f"Resetting conversation with new thread_id: {conversation.thread_id}")
            conversation.save()
        elif conversation.thread_id and not thread_service.check_thread_exists(conversation.thread_id):
            thread_id = thread_service.get_thread_id(str(assistant.assistant_id), str(assistant.vector_id))
            conversation.thread_id = thread_id
            conversation.status = 'open'
            print(f"Thread id updated: {thread_id}")
            conversation.save()
            print(f"Conversation updated: {conversation}")
        else:
            print(f"Conversation already exists: {conversation}")
        return conversation
    
    def handle_start_command(self, chat_id, assistant, bot_token, chat_username, username):
        print(f"Handling start command for chat_id: {chat_id}, assistant: {assistant}, bot_token: {bot_token}")
        greeting_message = assistant.greeting_message
        print(f"Greeting message: {greeting_message}")
        send_telegram_message(chat_id, greeting_message, bot_token)

        # Start a new or reopen an existing conversation
        conversation = self.get_or_create_conversation(chat_id, assistant, reset=True, token=bot_token, chat_username=chat_username, username=username)
        print(f"Conversation get_create: {conversation}")
        return success_response(message=_("Salomlashish va yangi chat muvaffaqiyatli bajarildi"), code=200)
    
    def process_instagram_audio(self, audio_url: str, language: str = "uz") -> str:
        try:
            audio_bytes = self.get_audio_from_url(audio_url)
            if not audio_bytes:
                return "Sorry, I couldn't process the audio."
            
            data, input_tokens, output_tokens = self.speech_to_text(audio_bytes, language)
            return data, input_tokens, output_tokens
        except Exception as e:
            return "Sorry, I couldn't process the audio."
        
    def get_audio_from_url(url: str) -> bytes:
        try:
            response = requests.get(url)
            response.raise_for_status()
            audio = AudioSegment.from_file(BytesIO(response.content))
            mp3_buffer = BytesIO()
            audio.export(mp3_buffer, format="mp3")
            return mp3_buffer.getvalue()
        except Exception as e:
            print(f"[get_audio_from_url] Error: {e}")
            return None

conversation_service = ConversationService(client=client)