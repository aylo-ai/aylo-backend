import requests
from celery import shared_task

from apps.shared.addons.enums import SenderTypes
from shared.addons.instagram import send_instagram_message
from shared.addons.telegram import send_telegram_message, check_register_info, delete_telegram_message
from shared.addons.utils import get_assistant_response_ai, handle_start_command, get_or_create_conversation, create_message, \
    speech_to_text, convert_ogg_to_mp3
from apps.assistant.models import Assistant
from .models import TelegramGroupIntegration


@shared_task
def process_message_task(chat_id, user_message, bot_token, audio_file=None):
    print(f"celery task is started with chat_id: {chat_id}, user_message: {user_message}, bot_token: {bot_token}")
    assistant = Assistant.objects.filter(integrations__api_token=bot_token).first()
    print(f"Assistant: {assistant}")
    if not assistant:
        print("No assistant found, skipping processing")
        return  # No assistant found, skip processing

    # Handle `/start` command
    if user_message == '/start':
        print(f"Handling start command for assistant: {assistant}")
        handle_start_command(chat_id, assistant, bot_token)
        return

    # Handle regular messages
    conversation = get_or_create_conversation(chat_id, assistant, token=bot_token)
    print(f"Conversation: {conversation}")
    if conversation.status == "ESCALATED" or not assistant.is_active:
        create_message(conversation, 'user', user_message, audio_file)
        print(f"Message created for user: {user_message}")
        return

    # Wait message handling
    wait_message_id = None
    if assistant.wait_message:
        response = send_telegram_message(chat_id, assistant.wait_message, bot_token)
        wait_message_id = response.json().get("result").get("message_id")

    create_message(conversation, 'user', user_message, audio_file)
    response_message, run_status, response_data = get_assistant_response_ai(user_message, assistant.assistant_id, conversation.thread_id)
    print(f"Response message: {response_message}")
    # user_register_message = check_register_info(response_message)
    
    # Remove wait message
    if wait_message_id:
        delete_telegram_message(chat_id, wait_message_id, bot_token)

    # Send response to user
    print(f"Response data: {response_data}")
    if response_data:
        response_text= f"""
            New lead created:
            Full name: {response_data.full_name}
            Phone number: {response_data.phone_number}
            Email: {response_data.email}
            Product: {response_data.product}
        """
        telegram_integration = assistant.integrations.filter(integration_type="telegram").first()
        telegram_groups = TelegramGroupIntegration.objects.filter(
            integration=telegram_integration
        ).all()
        for telegram_group in telegram_groups:
            send_telegram_message(telegram_group.group_id, response_text, bot_token)
            telegram_group.lead_count += 1
            telegram_group.save()
        create_message(conversation=conversation, sender=SenderTypes.ASSISTANT.value, content=response_message, run_status=run_status)
    elif response_message:
        send_telegram_message(chat_id, response_message, bot_token)
        create_message(conversation=conversation, sender=SenderTypes.ASSISTANT.value, content=response_message, run_status=run_status)


@shared_task
def process_instagram_message(account_id, user_message):
    print(f"celery task is started with account_id: {account_id}, user_message: {user_message}")
    assistant = Assistant.objects.filter(integrations__instagram_account_id=account_id).first()
    print(f"Assistant: {assistant}")
    if not assistant:
        return
    integration = assistant.integrations.filter(integration_type="instagram", instagram_account_id=account_id).first()
    print(f"Integration: {integration}")
    if not integration:
        return
    sender_id = user_message[0].get("sender", {}).get("id")
    print(f"Sender ID: {sender_id}")
    if not sender_id:
        return
    message_text = user_message[0].get("message", {}).get("text")
    print(f"Message text: {message_text}")
    if not message_text:
        return
    conversation = get_or_create_conversation(sender_id, assistant, platform="instagram")
    print(f"Conversation: {conversation}, thread_id: {conversation.thread_id}")
    if conversation.status == "ESCALATED" or not assistant.is_active:
        create_message(conversation, 'user', message_text)
        return
    create_message(conversation, 'user', message_text)
    response_message, run_status, response_data = get_assistant_response_ai(message_text, assistant.assistant_id, conversation.thread_id)
    print(f"Response message: {response_message}")

    # Handle lead creation if response_data exists
    if response_data:
        response_text = f"""
            New lead created:
            Full name: {response_data.full_name}
            Phone number: {response_data.phone_number}
            Email: {response_data.email}
            Product: {response_data.product}
        """
        # Send lead notification to Telegram groups if configured
        telegram_integration = assistant.integrations.filter(integration_type="telegram").first()
        telegram_groups = TelegramGroupIntegration.objects.filter(
            integration=telegram_integration
        ).all()
        for telegram_group in telegram_groups:
            send_telegram_message(telegram_group.group_id, response_text, telegram_integration.api_token)
            telegram_group.lead_count += 1
            telegram_group.save()
            print(f"Lead sent to telegram group: {telegram_group.group_id}")
    # send response to user
    send_instagram_message(account_id, integration.api_token, sender_id, response_message)
    print(f"starting to create message: {response_message}, conversation: {conversation}")
    create_message(conversation=conversation, sender=SenderTypes.ASSISTANT.value, content=response_message, run_status=run_status)
    print(f"Sent message to Instagram user: {sender_id} with message: {response_message}")


@shared_task
def process_voice_task(chat_id, voice_file_id, bot_token):
    print(f"Voice task started: {chat_id}, file_id: {voice_file_id}")

    assistant = Assistant.objects.filter(integrations__api_token=bot_token).first()
    if not assistant:
        return

    # Step 1: Get Telegram file URL
    file_info_url = f"https://api.telegram.org/bot{bot_token}/getFile?file_id={voice_file_id}"
    file_info_resp = requests.get(file_info_url)
    file_path = file_info_resp.json()["result"]["file_path"]

    file_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
    print(f"File URL: {file_url}, file_path: {file_path}")
    # Step 2: Download the audio file in ogg format
    audio_bytes_ogg = requests.get(file_url).content
    print(f"Audio bytes ogg: {audio_bytes_ogg}")
    audio_bytes_mp3 = convert_ogg_to_mp3(audio_bytes_ogg)
    print(f"Audio bytes mp3: {audio_bytes_mp3}")

    # Step 3: Use Gemini API (or any speech_to_text service)
    language_code = assistant.language or "uz"  # fallback
    print(f"Language code: {language_code}")
    transcribed_text = speech_to_text(audio_bytes_mp3, language=language_code)
    print(f"transcribed_text: {transcribed_text}")
    print(f"Transcribed text: {transcribed_text}")

    # Step 4: Trigger the regular message processor
    process_message_task.delay(chat_id, transcribed_text, bot_token, audio_bytes_mp3)
        
