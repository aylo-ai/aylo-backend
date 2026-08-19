import logging
import time
from datetime import timedelta

from celery import shared_task
from django.utils.timezone import now

from apps.assistant.models import Conversation
from apps.integration.gateways.instagram import instagram_service
from apps.integration.gateways.telegram import send_telegram_message
from apps.shared.addons.enums import BroadcastStatuses, IntegrationTypes

from ..models import Broadcast, Integration

logger = logging.getLogger(__name__)


def get_broadcast_recipients(integration):
    if integration.assistant:
        conversations = Conversation.objects.filter(
            assistant=integration.assistant,
            platform=integration.integration_type
        )
    else:
        conversations = Conversation.objects.filter(
            assistant__integrations__instagram_account_id=integration.instagram_account_id,
            platform='instagram'
        )

    if integration.integration_type == IntegrationTypes.INSTAGRAM.value:
        seven_days_ago = now() - timedelta(days=7)
        conversations = conversations.filter(updated_time__gte=seven_days_ago)

    return conversations


@shared_task(bind=True, max_retries=2, default_retry_delay=10,
             name="apps.integration.tasks.send_broadcast_task")
def send_broadcast_task(self, broadcast_id):
    try:
        broadcast = Broadcast.objects.select_related('integration').get(id=broadcast_id)
    except Broadcast.DoesNotExist:
        logger.error("[-] Broadcast not found: %s", broadcast_id)
        return

    integration = broadcast.integration
    broadcast.status = BroadcastStatuses.SENDING.value
    broadcast.save(update_fields=['status'])

    conversations = get_broadcast_recipients(integration)

    sent = 0
    failed = 0
    for conversation in conversations:
        try:
            if integration.integration_type == IntegrationTypes.TELEGRAM.value:
                send_telegram_message(conversation.user_id, broadcast.message, integration.api_token)
                sent += 1
                time.sleep(0.04)
            elif integration.integration_type == IntegrationTypes.INSTAGRAM.value:
                success = instagram_service.send_message(
                    account_id=integration.instagram_account_id,
                    access_token=integration.api_token,
                    recipient_id=conversation.user_id,
                    message=broadcast.message,
                    tag="HUMAN_AGENT",
                )
                if success:
                    sent += 1
                else:
                    failed += 1
                time.sleep(0.1)
        except Exception as e:
            logger.error("Broadcast send failed for %s: %s", conversation.user_id, e)
            failed += 1

        if (sent + failed) % 10 == 0:
            broadcast.sent_count = sent
            broadcast.failed_count = failed
            broadcast.save(update_fields=['sent_count', 'failed_count'])

    broadcast.sent_count = sent
    broadcast.failed_count = failed
    broadcast.status = BroadcastStatuses.COMPLETED.value
    broadcast.save(update_fields=['sent_count', 'failed_count', 'status'])


@shared_task(name="apps.integration.tasks.send_message_integration_task")
def send_message_integration_task(integration_id, message):
    integration = Integration.objects.get(id=integration_id)
    conversations = Conversation.objects.filter(
        assistant=integration.assistant, platform=integration.integration_type
    )
    if integration.integration_type == IntegrationTypes.TELEGRAM.value:
        for conversation in conversations:
            send_telegram_message(conversation.user_id, message, integration.api_token)
    if integration.integration_type == IntegrationTypes.INSTAGRAM.value:
        for conversation in conversations:
            instagram_service.send_message(
                account_id=conversation.user_id,
                access_token=integration.api_token,
                recipient_id=conversation.user_id,
                message=message,
            )
