import io
import json
import requests
from pydub.utils import which
from pydub import AudioSegment
from google import genai
from google.genai import types
from io import BytesIO

from django.utils.translation import gettext as _
from django.conf import settings

from apps.assistant.models import Message, Conversation, Lead, Assistant
from config.settings import client
from shared.addons.enums import SubscriptionStatuses, NotificationTypes
from shared.addons.telegram import send_telegram_message
from shared.addons.validations import success_response, raise_validation_error, error_response
from shared.addons.verification import send_sms_text
from shared.ai_service.helper import upload_knowledge_base_file
from shared.ai_service.assistant import check_response
from shared.ai_service.thread import wait_on_run
from config.settings import OPENAI_API_KEY
from shared.ai_service.helper import create_prompt
from shared.addons.payloads import valid_intents

def create_message(conversation, sender, content, audio_file=None, run_status=None):
    message_type = 'audio' if audio_file else 'text'
    print(f"Creating message: {conversation}, {sender}, {content}, {audio_file}")
    if audio_file and audio_file.startswith("https://"):
        audio_file = get_audio_from_url(audio_file)
    
    # Extract token usage from run_status if available
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
    print(f"Message created: {conversation}, {sender}")

    if audio_file:
        from django.core.files.base import ContentFile
        from django.utils.text import slugify

        file_name = f"audio_{slugify(conversation.id)}_{message.id}.mp3"
        print(f"File name: {file_name}")
        message.audio_file.save(file_name, ContentFile(audio_file))
        message.save()
        return message.audio_file
    else:
        return None

def get_or_create_conversation(user_id, assistant, reset=False, token=None, platform='telegram'):
    conversation = Conversation.objects.filter(
        assistant=assistant,
        user_id=user_id,
        token=token).first()
    print(f"Conversation: {conversation}")
    if conversation is None:
        thread_id = get_thread_id(str(assistant.assistant_id), str(assistant.vector_id))
        print(f"conversation is None, creating new conversation with thread_id: {thread_id}")
        conversation = Conversation.objects.create(
            assistant=assistant,
            user_id=user_id,
            thread_id=thread_id,
            status='open',
            token=token,
            platform=platform
        )
        print(f"Conversation created: {conversation}")

    elif reset and conversation is not None:
        conversation.thread_id = get_thread_id(str(assistant.assistant_id), str(assistant.vector_id))
        conversation.status = 'open'
        print(f"Resetting conversation with new thread_id: {conversation.thread_id}")
        conversation.save()
    else:
        print(f"Conversation already exists: {conversation}")
    return conversation


def handle_start_command(chat_id, assistant, bot_token):
    print(f"Handling start command for chat_id: {chat_id}, assistant: {assistant}, bot_token: {bot_token}")
    greeting_message = assistant.greeting_message
    print(f"Greeting message: {greeting_message}")
    send_telegram_message(chat_id, greeting_message, bot_token)

    # Start a new or reopen an existing conversation
    conversation = get_or_create_conversation(chat_id, assistant, reset=True, token=bot_token)
    print(f"Conversation get_create: {conversation}")
    return success_response(message=_("Greeting sent and conversation started"), code=200)


def notify_user_about_failed_payment(user):
    """Notify the user about payment failure."""
    message = _("Hurmatli {user.first_name}, sizning repli.uz dagi obuna to'lovingiz muvaffaqiyatsiz amalga oshirildi. "
                "Iltimos, platformaga kirib, to'lovni qayta amalga oshiring.")
    response = send_sms_text(user.phone_number, message)
    print(f"Payment failure notification response: {response.text}")


def restrict_user_account(user):
    """Restrict user's account due to failed payments."""
    subscription = user.subscription
    subscription.status = SubscriptionStatuses.INACTIVE.value
    subscription.save()

    # Send restriction notification
    message = _("Hurmatli {user.username}, sizning repli.uz dagi to'lovlaringiz bir necha marta muvaffaqiyatsiz "
                "amalga oshirilgani uchun sizning platformadagi obunangiz cheklab qo'yildi.")
    send_sms_text(user.phone_number, message)

def update_assistant(assistant_id, name,  assistant):
    print(f"Updating assistant with instructions")
    try:
        instruction = create_prompt(
            assistant.company_name,
            assistant.description,
            assistant.role,
            assistant.personality_style,
            assistant.language,
            valid_intents,
            assistant.fallback_message
        )
        assistant = client.beta.assistants.update(
            assistant_id=assistant_id,
            name=name,
            instructions=instruction,
            tools=[{"type": "file_search"}],
            model="gpt-4o",
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "chatbot_response",
                    "strict": False,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "intent": {"type": "string"},
                            "entities": {
                                "type": "object",
                                "properties": {
                                    "product": {"type": "string"},
                                    "quantity": {"type": "string"},
                                    "name": {"type": "string"},
                                    "phone_number": {"type": "string"},
                                    "email": {"type": "string"},
                                    "price": {"type": "string"},
                                    "total": {"type": "string"},
                                    "payment_method": {"type": "string"},
                                    "payment_status": {"type": "string"},
                                    "payment_date": {"type": "string"},
                                    "payment_amount": {"type": "string"},
                                    
                                },
                                "additionalProperties": False
                            },
                            "reply": {"type": "string"}
                        },
                        "required": ["intent", "reply"],
                        "additionalProperties": False
                    }
                }
            }
        )
        print(f"Assistant updated: {assistant}")
        if assistant is None:
            raise Exception("Assistant creation returned None unexpectedly.")
        return True, "Successfully updated assistant"
    except Exception as e:
        print(f"Error updating assistant: {e}")
        raise Exception(f"Error updating assistant: {e}")


def create_assistant(instructions, name, vector_store_id):
    print("Creating assistant with instructions")
    tools = [{"type": "file_search"}]
    tool_resources = {"file_search": {"vector_store_ids": [vector_store_id]}}
    default_model = "gpt-4o"

    try:
        my_assistant = client.beta.assistants.create(
            instructions=instructions,
            name=name,
            tools=tools,
            tool_resources=tool_resources,
            model=default_model,
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "chatbot_response",
                    "strict": False,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "intent": {"type": "string"},
                            "entities": {
                                "type": "object",
                                "properties": {
                                    "product": {"type": "string"},
                                    "quantity": {"type": "string"},
                                    "name": {"type": "string"},
                                    "phone_number": {"type": "string"},
                                    "email": {"type": "string"},
                                    "price": {"type": "string"},
                                    "total": {"type": "string"},
                                    "payment_method": {"type": "string"},
                                    "payment_status": {"type": "string"},
                                    "payment_date": {"type": "string"},
                                    "payment_amount": {"type": "string"},
                                    
                                },
                                "additionalProperties": False
                            },
                            "reply": {"type": "string"}
                        },
                        "required": ["intent", "reply"],
                        "additionalProperties": False
                    }
                }
            }
        )

        # Check the response type before returning
        if my_assistant is None:
            raise Exception("Assistant creation returned None unexpectedly.")
        print(f"Assistant created: {my_assistant}")
        return my_assistant
    except Exception as e:
        print(f"Error creating assistant: {e}")
        raise Exception(f"Error creating assistant: {e}")
    
def create_vector_store(file_urls):
    file_ids = []

    # Upload each file and collect valid file IDs
    for file_url in file_urls:
        file_id = upload_knowledge_base_file(file_url)
        if file_id:
            file_ids.append(file_id)

    # Ensure there are valid files for vector store creation
    if not file_ids:
        print("No valid files available for vector store creation.")
        return None

    try:
        # Create a vector store from collected file IDs
        vector_store = client.beta.vector_stores.create(
            file_ids=file_ids
        )
        print(f"Vector store created with ID: {vector_store.id}")
        return vector_store.id

    except Exception as e:
        print(f"Error creating vector store: {e}")
        return None
    
def get_assistant_response_ai(message, assistant_id, thread_id):
    print(f"Getting assistant response from AI: {message}, {assistant_id}, {thread_id}")
    assistant = Assistant.objects.get(assistant_id=assistant_id)
    subscription = assistant.user.subscription
    if subscription.remained_request_count <= 0:
        return assistant.fallback_message, None, None
    else:
        if thread_id is None:
            return "Thread not initialized. Please create an assistant first."

        # Check if an active run exists for the given thread_id
        active_run = client.beta.threads.runs.list(thread_id=thread_id)
        if active_run.data:
            print(f"active run found")
            # Wait for the active run to complete
            wait_on_run(active_run.data[0], thread_id) 

        # Send the user's message to the assistant
        user_message = client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=f"User: {message}",
        )
        print(f"User message: {user_message}")

        # Start a new assistant run
        run = client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=assistant_id,
        )
        # thread_obj = client.beta.threads.retrieve(thread_id)
        run_status = wait_on_run(run, thread_id)     # Retrieve the assistant's response
        messages = client.beta.threads.messages.list(
            thread_id=thread_id, order="asc", after=user_message.id
        )
        print(f"Assistant response: {messages.data}, messages: {messages}, input_tokens: {run_status.usage.prompt_tokens}, output_tokens: {run_status.usage.completion_tokens}")

        # Get the response text or a fallback message if empty
        assistant_response_str = messages.data[0].content[0].text.value if messages.data else "No response received."
        print(f"Assistant response: {assistant_response_str}")
        assistant_response = json.loads(assistant_response_str)
        intent = assistant_response.get("intent", None)
        message = assistant_response.get("reply", None)
        entities = assistant_response.get("entities", None)
        clean_response = check_response(message)

        response_data = None
        if intent == "create_order":
            name = (
                    entities.get('name') or 
                    entities.get('full_name') or 
                    entities.get('customer_user') or 
                    entities.get('customer_name') or 
                    None
                    )
            phone_number = (
                    entities.get('phone_number') or 
                    entities.get('contact_number') or 
                    None
                )
                
            response_data = create_lead(
                full_name=name,
                phone_number=phone_number,
                email=entities.get('email', None),
                product=entities.get('product', None),
                metadata=entities
            )
            print("✅ Lead created from Telegram message")
        return clean_response, run_status, response_data

def create_and_run_thread(assistant_id, vector_store_id):
    try:
        run = client.beta.threads.create_and_run(
            assistant_id=assistant_id,
            tool_resources={"file_search": {"vector_store_ids": [vector_store_id]}},
            tools=[{"type": "file_search"}],
        )
        thread_id = run.thread_id
        return thread_id, run
    except Exception as e:
        print(f"Error while creating a run: {e}")
        raise Exception("Thread creation failed")

def get_thread_id(assistant_id, vector_id):
    if assistant_id is None or vector_id is None:
        raise_validation_error(message=_(f"Assistant or vector id is not found: {assistant_id}"))
    thread_id, _ = create_and_run_thread(assistant_id, vector_id)
    if thread_id is not None:
        return thread_id
    else:
        raise_validation_error(message=_(f"Failed to initialize thread for error: {assistant_id}"))

def delete_assistant_by_id(assistant_id):
    BASE_URL = "https://api.openai.com/v1/assistants"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
        "OpenAI-Beta": "assistants=v2",
    }
    url = f"{BASE_URL}/{assistant_id}"

    # Make the DELETE request
    response = requests.delete(url, headers=headers)
    print(f"Delete assistant response: {response.text}")
    if response.status_code == 200:
        return response.json()
    elif response.status_code == 404:
        raise_validation_error(message="Assistant not found.")
    else:
        raise_validation_error(
            message=f"Failed to delete assistant: {response.text}",
        )


def convert_ogg_to_mp3(audio_bytes: bytes) -> bytes:
    AudioSegment.converter = which("ffmpeg")    # mp3 konvertatsiyasi uchun
    AudioSegment.ffprobe = which("ffprobe")     # fayl formatini o‘qish uchun
    audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format="ogg")
    print(f"Audio: {audio}")
    mp3_io = io.BytesIO()
    print(f"Mp3 io: {mp3_io}")
    audio.export(mp3_io, format="mp3")
    print(f"Mp3 io: {mp3_io}")
    return mp3_io.getvalue()


def speech_to_text(audio_bytes: bytes, language: str = "uz") -> str:
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
            model="gemini-2.5-flash-preview-04-17",
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
        
        print(f"[speech_to_text] Response received: {response}")
        result = response.text.strip()
        print(f"[speech_to_text] Final result: {result}")
        return result
    except Exception as e:
        print(f"[speech_to_text] Error: {str(e)}")
        print(f"[speech_to_text] Error type: {type(e)}")
        import traceback
        print(f"[speech_to_text] Traceback: {traceback.format_exc()}")
        return "Sorry, I couldn't understand the audio."
    
def create_lead(full_name, phone_number, email, product, metadata=None):  
    try:
        lead = Lead.objects.create(
            full_name=full_name,
            phone_number=phone_number,
            email=email,
            product=product,
            metadata=metadata
        )
        return lead
    except Exception as e:
        print(f"[create_lead] Error: {e}")
        return error_response(message=_("Failed to create lead"), code=500)

def notify_user_about_low_tokens(user, count):
    """Notify the user when their token count is low."""
    from apps.user.models import Notification
    
    # Create notification instance
    Notification.objects.create(
        user=user,
        title=_("Low Token Count Warning"),
        content=_(f"Hurmatli {user.first_name}, sizning repli.uz dagi so'rovlar soningiz {count} tadan kam qoldi. "
                 "Iltimos, platformaga kirib, obunangizni yangilang."),
        type=NotificationTypes.WARNING.value
    )
    print(f"Notification created to notify user about low request token count")
    
def get_audio_from_url(url: str) -> bytes:
    """Download audio from URL and convert to MP3 bytes."""
    try:
        # Download the audio file
        response = requests.get(url)
        response.raise_for_status()
        # Convert to MP3 if needed
        audio = AudioSegment.from_file(BytesIO(response.content))
        mp3_buffer = BytesIO()
        audio.export(mp3_buffer, format="mp3")
        return mp3_buffer.getvalue()
    except Exception as e:
        print(f"[get_audio_from_url] Error: {e}")
        return None

def process_instagram_audio(audio_url: str, language: str = "uz") -> str:
    """Process Instagram audio URL and convert to text."""
    try:
        print(f"[process_instagram_audio] Starting processing with URL: {audio_url}")
        # Get audio bytes from URL
        audio_bytes = get_audio_from_url(audio_url)
        if not audio_bytes:
            print("[process_instagram_audio] Failed to get audio bytes from URL")
            return "Sorry, I couldn't process the audio."
        
        # Convert to text using speech_to_text
        print(f"[process_instagram_audio] Attempting to convert audio to text with language: {language}")
        data = speech_to_text(audio_bytes, language)
        print(f"[process_instagram_audio] Speech to text result: {data}")
        return data
    except Exception as e:
        print(f"[process_instagram_audio] Error: {str(e)}")
        print(f"[process_instagram_audio] Error type: {type(e)}")
        import traceback
        print(f"[process_instagram_audio] Traceback: {traceback.format_exc()}")
        return "Sorry, I couldn't process the audio."
    