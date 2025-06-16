import requests, time
from celery import shared_task

from apps.shared.addons.enums import SenderTypes, ConversationStatuses
from shared.addons.instagram import send_instagram_message, send_instagram_private_reply
from shared.addons.telegram import send_telegram_message, check_register_info, delete_telegram_message
from shared.addons.utils import get_assistant_response_ai, handle_start_command, get_or_create_conversation, create_message, \
    speech_to_text, convert_ogg_to_mp3, process_instagram_audio
from apps.assistant.models import Assistant
from .models import TelegramGroupIntegration
from shared.addons.redis import publish_message_to_ws, redis_client

WAIT_SECONDS = 5

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
    if conversation.status == ConversationStatuses.ESCALATED.value or not assistant.is_active:
        data = create_message(conversation, 'user', user_message, audio_file)
        publish_message_to_ws(conversation.id, user_message, sender="user", data=data, assistant_id=assistant.id)
        print(f"Message created for user: {user_message}")
        return

    # Wait message handling
    wait_message_id = None
    if assistant.wait_message:
        response = send_telegram_message(chat_id, assistant.wait_message, bot_token)
        wait_message_id = response.json().get("result").get("message_id")

    data = create_message(conversation, 'user', user_message, audio_file)
    publish_message_to_ws(conversation_id=conversation.id, message=user_message, sender='user', data=data, assistant_id=assistant.id)
    response_message, run_status, response_data = get_assistant_response_ai(user_message, assistant.assistant_id, conversation.thread_id)
    print(f"Response message: {response_message}")
    # user_register_message = check_register_info(response_message)
    
    # Remove wait message
    if wait_message_id:
        delete_telegram_message(chat_id, wait_message_id, bot_token)

    # Send response to user
    print(f"Response data: {response_data}")
    if response_data:
        response_text = f"""
            🎉 *New Lead Created!*

            👤 *Full Name:* {response_data.full_name}  
            📞 *Phone Number:* {response_data.phone_number}  
            📧 *Email:* {response_data.email}  
            📦 *Interested Product:* {response_data.product}

            ✅ Please follow up accordingly.
            """
        telegram_integration = assistant.integrations.filter(integration_type="telegram").first()
        telegram_groups = TelegramGroupIntegration.objects.filter(
            integration=telegram_integration
        ).all()
        for telegram_group in telegram_groups:
            send_telegram_message(telegram_group.group_id, response_text, bot_token)
            telegram_group.lead_count += 1
            telegram_group.save()
        # data = create_message(conversation=conversation, sender=SenderTypes.ASSISTANT.value, content=response_message, run_status=run_status)
        # publish_message_to_ws(conversation.id, response_message, sender="assistant", assistant_id=assistant.id,data=data)
    if response_message:
        send_telegram_message(chat_id, response_message, bot_token)
        data = create_message(conversation=conversation, sender=SenderTypes.ASSISTANT.value, content=response_message, run_status=run_status)
        publish_message_to_ws(conversation.id, response_message, sender="assistant", assistant_id=assistant.id,data=data)

@shared_task
def process_instagram_message(account_id, combined_message, user_message, audio_file=None):
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
    # message_text = user_message[0].get("message", {}).get("text")
    if audio_file:
        message_text = process_instagram_audio(audio_file, assistant.language)
    print(f"Message text: {combined_message}")
    if not combined_message:
        return
    conversation = get_or_create_conversation(sender_id, assistant, platform="instagram")
    print(f"Conversation: {conversation}, thread_id: {conversation.thread_id}")
    if conversation.status == ConversationStatuses.ESCALATED.value or not assistant.is_active:
        data = create_message(conversation, 'user', combined_message, audio_file)
        print("publish message to web socket")
        publish_message_to_ws(conversation.id, combined_message, sender="user", data=data, assistant_id=assistant.id)
        return
    print("Sending message to web socket")
    data = create_message(conversation, 'user', combined_message, audio_file)
    publish_message_to_ws(conversation.id, combined_message, sender="user", data=data, assistant_id=assistant.id)
    if assistant.wait_message:
        send_instagram_message(account_id, integration.api_token, sender_id, assistant.wait_message)
        print(f"Sent wait message to Instagram user: {sender_id} with message: {assistant.wait_message}")
    response_message, run_status, response_data = get_assistant_response_ai(combined_message, assistant.assistant_id, conversation.thread_id)
    print(f"Assistant response in Instagram: {response_message}")
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
    # handling wait message
    
    # send response to user
    send_instagram_message(account_id, integration.api_token, sender_id, response_message)
    print(f"starting to create message: {response_message}, conversation: {conversation}")
    data = create_message(conversation=conversation, sender=SenderTypes.ASSISTANT.value, content=response_message, run_status=run_status)
    print(f"Sent message to Instagram user: {sender_id} with message: {response_message}")
    publish_message_to_ws(conversation.id, response_message, sender="assistant", assistant_id=assistant.id, data=data)
    print("Sent message to web socket")

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

@shared_task
def process_instagram_comment(account_id, comment_data):
    """Process Instagram comment and send private reply"""
    print(f"Processing Instagram comment for account_id: {account_id}")
    assistant = Assistant.objects.filter(integrations__instagram_account_id=account_id).first()
    print(f"Assistant: {assistant}")
    if not assistant:
        return
    
    integration = assistant.integrations.filter(integration_type="instagram", instagram_account_id=account_id).first()
    print(f"Integration: {integration}")
    if not integration:
        return

    # Extract comment information
    comment_id = comment_data.get("id")
    comment_text = comment_data.get("text")
    commenter_id = comment_data.get("from", {}).get("id")
    print(f"Comment ID: {comment_id}, Comment Text: {comment_text}, Commenter ID: {commenter_id}")
    if not all([comment_id, comment_text, commenter_id]):
        print("Missing required comment data")
        return

    response_message = "Thank you for your comment!, It was done by Repli AI"
    # Send private reply to the comment
    send_instagram_private_reply(integration.api_token, account_id, comment_id, response_message)


@shared_task
def process_collected_messages(chat_id, bot_token=None, messaging=None):
    user_key = f"messages:{chat_id}"
    last_seen_key = f"last_seen:{chat_id}"

    # Check if we should wait longer
    last_seen = float(redis_client.get(last_seen_key) or 0)
    if time.time() - last_seen < WAIT_SECONDS:
        return  # Another message came in recently, skip for now

    messages = redis_client.lrange(user_key, 0, -1)
    if not messages:
        return

    combined_message = ", ".join(m for m in messages)
    print(f"Combined message: {combined_message}")

    # Clean up Redis
    redis_client.delete(user_key)
    redis_client.delete(last_seen_key)

    # Call your existing task
    if bot_token:
        process_message_task.delay(chat_id, combined_message, bot_token)
    else:
        process_instagram_message.delay(account_id = chat_id, combined_message = combined_message, user_message = messaging)