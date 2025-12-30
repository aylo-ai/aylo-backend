from django.utils import timezone

from celery import shared_task

from apps.shared.ai_service.assistant import assistant_service
from shared.addons.validations import raise_validation_error
from apps.assistant.models import AssistantFileUpload, Assistant, Message
from apps.integration.models import TelegramGroupIntegration
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
    assistant_id, code = assistant_service.create_assistant_and_vector_id(data)
    if code == 400:
        raise_validation_error(message=assistant_id)
    assistant.assistant_id = assistant_id
    assistant.save()
    print(f"Assistant ID: {assistant.assistant_id} created successfully")


@shared_task
def daily_statistics_assistant():
    assistants = Assistant.objects.all()
    current_date = timezone.now().date()
    for assistant in assistants:
        print(f"Assistant: {assistant.name}")
        telegram_integrations = assistant.integrations.filter(integration_type=IntegrationTypes.TELEGRAM.value)
        
        if not telegram_integrations.exists():
            print(f"No Telegram integration found for assistant: {assistant.name}")
            continue
        daily_lead_instagram, daily_lead_telegram, phone_number_leave = get_daily_lead_statistics(assistant.id, current_date)
        new_conversations, existing_conversations = get_daily_conversation_statistics(assistant.id, current_date)

        message = f"""
📊 **Kunlik Statistika** ({current_date.strftime("%d.%m.%Y")})

💬 **Suhbatlar:**
🆕 **Yangi:** {new_conversations}
🔄 **Davom etgan:** {existing_conversations}
📊 **Jami:** {new_conversations + existing_conversations}


✅ **Umumiy leadlar:** {daily_lead_instagram + daily_lead_telegram}
---
📱 **Instagram:** {daily_lead_instagram}
🔹 **Telegram:** {daily_lead_telegram}

📞 **Telefon qoldirganlar:** {phone_number_leave}
"""
        print(f"Message: {message}")
        
        for telegram_integration in telegram_integrations:
            telegram_groups = TelegramGroupIntegration.objects.filter(integration=telegram_integration).all()
            
            if not telegram_groups.exists():
                print(f"No Telegram groups found for integration: {telegram_integration.id}")
                continue
            
            for telegram_group in telegram_groups:
                try:
                    send_telegram_message(telegram_group.group_id, message, telegram_integration.api_token)
                    print(f"Message sent to telegram group: {telegram_group.group_id} (Group: {telegram_group.group_title})")
                except Exception as e:
                    print(f"Error sending message to group {telegram_group.group_id}: {e}")

def get_daily_lead_statistics(assistant_id, target_date):
    assistant = Assistant.objects.get(id=assistant_id)
    daily_lead_instagram = assistant.leads.filter(
        created_time__date=target_date, 
        platform=ConversationPlatforms.INSTAGRAM.value
    ).count()
    daily_lead_telegram = assistant.leads.filter(
        created_time__date=target_date, 
        platform=ConversationPlatforms.TELEGRAM.value
    ).count()
    phone_number_leave = assistant.leads.filter(
        created_time__date=target_date, 
        phone_number__isnull=False
    ).count()

    return daily_lead_instagram, daily_lead_telegram, phone_number_leave


def get_daily_conversation_statistics(assistant_id, target_date):
    assistant = Assistant.objects.get(id=assistant_id)
    
    new_conversations = assistant.conversations.filter(
        created_time__date=target_date
    ).count()
    
    conversations_before_today = assistant.conversations.filter(
        created_time__date__lt=target_date
    )
    
    existing_conversations = Message.objects.filter(
        conversation__in=conversations_before_today,
        created_time__date=target_date
    ).values_list('conversation_id', flat=True).distinct().count()
    
    return new_conversations, existing_conversations