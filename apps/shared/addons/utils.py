from django.utils.translation import gettext as _
from apps.assistant.models import Message, Conversation
from shared.addons.ai_requests import get_thread_id
from shared.addons.telegram import send_telegram_message
from shared.addons.validations import success_response


def create_message(conversation, sender, content):
    Message.objects.create(
        conversation=conversation,
        sender=sender,
        message_content=content,
        message_type='text'
    )
    print(f"Message created: {conversation}, {sender}")


def get_or_create_conversation(chat_id, assistant, reset=False, token=None, platform='telegram'):
    conversation = Conversation.objects.filter(
        assistant=assistant,
        telegram_user_id=chat_id,
        token=token).first()
    print(f"Conversation: {conversation}")
    if conversation is None:
        thread_id = get_thread_id(str(assistant.assistant_id), str(assistant.vector_id))
        print(f"conversation is None, creating new conversation with thread_id: {thread_id}")
        conversation = Conversation.objects.create(
            assistant=assistant,
            telegram_user_id=chat_id,
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