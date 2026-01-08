import requests
import io
from shutil import which
from io import BytesIO
from pydub import AudioSegment
import logging
from google import genai
from google.genai import types

from django.db import transaction
from django.utils.translation import gettext_lazy as _

from apps.assistant.models import  Message, Conversation, Lead
from shared.addons.validations import success_response
from config import settings

from shared.addons.telegram import send_telegram_message
from shared.addons.redis import publish_message_to_ws_assistant


logger = logging.getLogger(__name__)


class ConversationService:
    def __init__(self):
        self.client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY)


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

    def create_message(self, conversation, sender, content, audio_file=None, input_tokens=None, output_tokens=None):
        message_type = 'audio' if audio_file else 'text'
        if isinstance(audio_file, str) and audio_file.startswith("https://"):
            audio_file = self.get_audio_from_url(audio_file)
        
        if audio_file:
            input_tokens = input_tokens
            output_tokens = output_tokens
        else:
            input_tokens = input_tokens if input_tokens else 0
            output_tokens = output_tokens if output_tokens else 0
        
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
        if conversation is None:
            print(f"conversation is None, creating new conversation")
            conversation = Conversation.objects.create(
                assistant=assistant,
                user_id=user_id,
                status='open',
                token=token,
                platform=platform,
                username=username if username else None,
                client_full_name=chat_username,
                client_phone_email=f"@{username}" if username else None
            )
            publish_message_to_ws_assistant(conversation)
            print(f"Conversation created: {conversation}")

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

conversation_service = ConversationService()