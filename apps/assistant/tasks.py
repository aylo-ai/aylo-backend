import logging
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.db.models import Exists, OuterRef, Subquery
from django.utils import timezone
from django.utils.timezone import now

from apps.assistant.models import (
    Assistant,
    Conversation,
    FollowUpConfig,
    FollowUpLog,
    Lead,
    Message,
)
from apps.integration.gateways.instagram import instagram_service
from apps.integration.gateways.telegram import send_telegram_message
from apps.integration.models import TelegramGroupIntegration
from apps.shared.addons.enums import (
    ConversationPlatforms,
    FollowUpLogStatus,
    IntegrationTypes,
    LeadStatuses,
    MessageTypes,
    SenderTypes,
)
from apps.shared.addons.redis import publish_message_to_ws

logger = logging.getLogger(__name__)


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


@shared_task
def process_follow_ups():
    """Runs every 30 minutes. Schedules and sends follow-up messages for idle conversations."""
    _schedule_follow_ups()
    _send_due_follow_ups()


def _schedule_follow_ups():
    """Find idle conversations and create FollowUpLog entries for their next stage."""
    configs = FollowUpConfig.objects.filter(is_enabled=True).prefetch_related('stages')

    for config in configs:
        active_stages = config.stages.filter(is_active=True).order_by('stage_number')
        if not active_stages.exists():
            continue

        target_statuses = config.target_statuses or ['open', 'pending']

        # Get last message sender and time per conversation
        last_msg_sender = Message.objects.filter(
            conversation=OuterRef('pk')
        ).order_by('-created_time').values('sender')[:1]

        last_msg_time = Message.objects.filter(
            conversation=OuterRef('pk')
        ).order_by('-created_time').values('created_time')[:1]

        # Exclude conversations where user has a qualified lead
        qualified_lead_exists = Lead.objects.filter(
            assistant=config.assistant,
            username=OuterRef('username'),
            status=LeadStatuses.QUALIFIED.value,
        )

        conversations = Conversation.objects.filter(
            assistant=config.assistant,
            status__in=target_statuses,
        ).annotate(
            last_sender=Subquery(last_msg_sender),
            last_message_time=Subquery(last_msg_time),
        ).filter(
            last_sender=SenderTypes.ASSISTANT.value,
            last_message_time__isnull=False,
        ).exclude(
            Exists(qualified_lead_exists)
        )

        # Check subscription tokens
        user = config.assistant.user
        if hasattr(user, 'subscription') and user.subscription:
            if user.subscription.remained_request_count <= 0:
                continue

        for conversation in conversations:
            # Find the next stage that hasn't been logged yet
            existing_stages = FollowUpLog.objects.filter(
                conversation=conversation,
                stage__config=config,
            ).values_list('stage__stage_number', flat=True)

            for stage in active_stages:
                if stage.stage_number in existing_stages:
                    continue

                scheduled_at = conversation.last_message_time + timedelta(hours=stage.delay_hours)
                FollowUpLog.objects.get_or_create(
                    conversation=conversation,
                    stage=stage,
                    defaults={
                        'scheduled_at': scheduled_at,
                        'status': FollowUpLogStatus.PENDING.value,
                    }
                )
                # Only schedule the next pending stage, not all at once
                break


def _send_due_follow_ups():
    """Send follow-up messages that are due."""
    due_logs = FollowUpLog.objects.filter(
        status=FollowUpLogStatus.PENDING.value,
        scheduled_at__lte=now(),
    ).select_related(
        'conversation__assistant__user__subscription',
        'stage__config',
    )

    for log in due_logs:
        try:
            with transaction.atomic():
                # Re-lock the row to prevent double-send
                locked_log = FollowUpLog.objects.select_for_update(
                    skip_locked=True
                ).filter(pk=log.pk, status=FollowUpLogStatus.PENDING.value).first()

                if not locked_log:
                    continue

                conversation = locked_log.conversation
                assistant = conversation.assistant
                stage = locked_log.stage

                # Re-check eligibility
                if not _is_conversation_eligible(conversation, stage.config):
                    locked_log.status = FollowUpLogStatus.CANCELLED.value
                    locked_log.cancelled_at = now()
                    locked_log.save(update_fields=['status', 'cancelled_at'])
                    continue

                # Check subscription tokens
                subscription = getattr(assistant.user, 'subscription', None)
                if subscription and subscription.remained_request_count <= 0:
                    locked_log.status = FollowUpLogStatus.CANCELLED.value
                    locked_log.cancelled_at = now()
                    locked_log.save(update_fields=['status', 'cancelled_at'])
                    continue

                # Render message template
                message_text = _render_template(
                    stage.message_template, conversation, assistant
                )

                # Send message
                success = _send_follow_up_message(conversation, message_text)

                if success:
                    # Create message record in conversation history
                    Message.objects.create(
                        conversation=conversation,
                        sender=SenderTypes.ASSISTANT.value,
                        message_content=message_text,
                        message_type=MessageTypes.TEXT.value,
                    )
                    locked_log.status = FollowUpLogStatus.SENT.value
                    locked_log.sent_at = now()
                    locked_log.save(update_fields=['status', 'sent_at'])
                else:
                    locked_log.status = FollowUpLogStatus.FAILED.value
                    locked_log.save(update_fields=['status'])

        except Exception as e:
            logger.error(f"Error sending follow-up for log {log.id}: {e}")


def _is_conversation_eligible(conversation, config):
    """Check if a conversation is still eligible for follow-up."""
    target_statuses = config.target_statuses or ['open', 'pending']
    if conversation.status not in target_statuses:
        return False

    # Check if the last message is still from assistant (user hasn't replied)
    last_message = Message.objects.filter(
        conversation=conversation
    ).order_by('-created_time').first()

    if not last_message or last_message.sender != SenderTypes.ASSISTANT.value:
        return False

    # Check for qualified lead
    has_qualified_lead = Lead.objects.filter(
        assistant=conversation.assistant,
        username=conversation.username,
        status=LeadStatuses.QUALIFIED.value,
    ).exists()

    if has_qualified_lead:
        return False

    return True


def _render_template(template, conversation, assistant):
    """Render follow-up message template with context variables."""
    return template.format(
        username=conversation.client_full_name or conversation.username or '',
        assistant_name=assistant.name or '',
        company_name=assistant.company_name or '',
    )


def _send_follow_up_message(conversation, text):
    """Send follow-up message via the appropriate platform."""
    assistant = conversation.assistant
    platform = conversation.platform

    try:
        if platform == ConversationPlatforms.TELEGRAM.value:
            integration = assistant.integrations.filter(
                integration_type=IntegrationTypes.TELEGRAM.value, is_active=True
            ).first()
            if integration:
                send_telegram_message(conversation.user_id, text, integration.api_token)
                return True

        elif platform == ConversationPlatforms.INSTAGRAM.value:
            integration = assistant.integrations.filter(
                integration_type=IntegrationTypes.INSTAGRAM.value, is_active=True
            ).first()
            if integration:
                instagram_service.send_message(
                    integration.instagram_account_id,
                    integration.api_token,
                    conversation.user_id,
                    text,
                    tag="HUMAN_AGENT",
                )
                return True

        elif platform == ConversationPlatforms.WEBSITE.value:
            publish_message_to_ws(
                conversation_id=conversation.id,
                message=text,
                sender="assistant",
                data=None,
                assistant_id=assistant.id,
            )
            return True

        logger.warning(f"No active integration for platform={platform}, conv={conversation.id}")
        return False

    except Exception as e:
        logger.error(f"Failed to send follow-up message for conv={conversation.id}: {e}")
        return False
