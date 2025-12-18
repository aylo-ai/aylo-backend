from django.utils import timezone

from celery import shared_task

from shared.addons.ai_requests import create_assistant_and_vector_id
from shared.addons.validations import raise_validation_error
from .models import AssistantFileUpload, Assistant
from shared.addons.enums import IntegrationTypes, ConversationPlatforms
from shared.addons.utils import send_telegram_message


@shared_task
def save_uploaded_file(assistant, file_data, filename):
    AssistantFileUpload.objects.create(
        assistant=assistant,
        file=file_data,
        filename=filename
    )
    print(f"File uploaded successfully for assistant_id: {assistant.id}")


@shared_task
def finalize_assistant_files(assistant_id):
    assistant = Assistant.objects.get(id=assistant_id)
    data = {
        "name": assistant.name,
        "company_name": assistant.company_name,
        "company_description": assistant.description,
        "assistant_role": assistant.role,
        "conversation_style": assistant.personality_style,
        "assistant_language": assistant.language,
        "file_links": [file.file.url for file in assistant.files.all()]
    }
    assistant_id, code = create_assistant_and_vector_id(data)
    if code == 400:
        raise_validation_error(message=assistant_id)
    assistant.assistant_id = assistant_id
    assistant.save()
    print(f"Assistant ID: {assistant.assistant_id} created successfully")


@shared_task
def daily_statistics_assistant():
    assistants = Assistant.objects.all()
    for assistant in assistants:
        print(f"Assistant: {assistant.name}")
        instagram_integration = assistant.integrations.filter(integration_type=IntegrationTypes.INSTAGRAM.value).first()
        telegram_integration = assistant.integrations.filter(integration_type=IntegrationTypes.TELEGRAM.value).first()
        print(f"Instagram integration: {instagram_integration}")
        print(f"Telegram integration: {telegram_integration}")
        if telegram_integration:
            telegram_group = telegram_integration.telegram_group
            print(f"Telegram group: {telegram_group}")
            daily_lead_instagram, daily_lead_telegram, phone_number_leave = get_daily_lead_statistics(assistant.id)
            message = f"""Kunlik statistika ({timezone.now().date().strftime("%Y.%m.%d")}):\n\nUmumiy leadlar: {daily_lead_instagram + daily_lead_telegram}\nInstagramdan kelgan leadlar: {daily_lead_instagram}\nTelegramdan kelgan leadlar: {daily_lead_telegram}\nTelefon raqam qoldirgan leadlar: {phone_number_leave}\n"""
            print(f"Message: {message}")
            if telegram_group and telegram_group.group_id:
                send_telegram_message(telegram_group.group_id, message, telegram_integration.api_token)
                print(f"Message sent to telegram group: {telegram_group.group_id}")


def get_daily_lead_statistics(assistant_id):
    assistant = Assistant.objects.get(id=assistant_id)
    daily_lead_instagram = assistant.leads.filter(created_time__date=timezone.now().date(), platform=ConversationPlatforms.INSTAGRAM.value).count()
    daily_lead_telegram = assistant.leads.filter(created_time__date=timezone.now().date(), platform=ConversationPlatforms.TELEGRAM.value).count()
    phone_number_leave = assistant.leads.filter(created_time__date=timezone.now().date(), phone_number__isnull=False).count()

    return daily_lead_instagram, daily_lead_telegram, phone_number_leave