from celery import shared_task

from shared.addons.ai_requests import get_assistant_response
from shared.addons.telegram import send_telegram_message, check_register_info, delete_telegram_message
from shared.addons.utils import handle_start_command, get_or_create_conversation, create_message
from .models import Assistant, TelegramGroupIntegration


@shared_task
def process_message_task(chat_id, user_message, bot_token):
    print(f"celery task is started with chat_id: {chat_id}, user_message: {user_message}, bot_token: {bot_token}")
    assistant = Assistant.objects.filter(integrations__api_token=bot_token).first()
    if not assistant:
        return  # No assistant found, skip processing

    # Handle `/start` command
    if user_message == '/start':
        handle_start_command(chat_id, assistant, bot_token)
        return

    # Handle regular messages
    conversation = get_or_create_conversation(chat_id, assistant, token=bot_token)
    print(f"Conversation: {conversation}")
    if conversation.status == "ESCALATED" or not assistant.is_active:
        create_message(conversation, 'user', user_message)
        return

    # Wait message handling
    wait_message_id = None
    if assistant.wait_message:
        response = send_telegram_message(chat_id, assistant.wait_message, bot_token)
        wait_message_id = response.json().get("result").get("message_id")

    create_message(conversation, 'user', user_message)
    response_message = get_assistant_response(user_message, assistant.assistant_id, conversation.thread_id)
    print(f"Response message: {response_message}")
    user_register_message = check_register_info(response_message)

    # Remove wait message
    if wait_message_id:
        delete_telegram_message(chat_id, wait_message_id, bot_token)

    # Send response to user
    if user_register_message:
        telegram_groups = TelegramGroupIntegration.objects.filter(
            integration=assistant.integrations.first()
        ).all()
        for telegram_group in telegram_groups:
            send_telegram_message(telegram_group.group_id, user_register_message, bot_token)
            telegram_group.lead_count += 1
            telegram_group.save()
        send_telegram_message(chat_id, user_register_message, bot_token)
        create_message(conversation, 'assistant', response_message)
    else:
        send_telegram_message(chat_id, response_message, bot_token)
        create_message(conversation, 'assistant', response_message)
