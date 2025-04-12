from django.utils.translation import gettext as _
from apps.assistant.models import Message, Conversation
from shared.addons.ai_requests import get_thread_id
from shared.addons.telegram import send_telegram_message
from shared.addons.validations import success_response
from shared.addons.verification import send_sms_text


def create_message(conversation, sender, content):
    Message.objects.create(
        conversation=conversation,
        sender=sender,
        message_content=content,
        message_type='text'
    )
    print(f"Message created: {conversation}, {sender}")


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
    user.subscription_active = False
    user.save()

    # Send restriction notification
    message = _("Hurmatli {user.username}, sizning repli.uz dagi to'lovlaringiz bir necha marta muvaffaqiyatsiz "
                "amalga oshirilgani uchun sizning platformadagi obunangiz cheklab qo'yildi.")
    send_sms_text(user.phone_number, message)
