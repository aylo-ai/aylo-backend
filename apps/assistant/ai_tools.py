import logging
from datetime import timedelta
from typing import Any, Dict

from django.utils import timezone

from apps.shared.ai_service.tools import MAX_SUMMARY_MESSAGES, register

logger = logging.getLogger(__name__)


CREATE_LEAD_SCHEMA = {
    "type": "function",
    "name": "create_lead",
    "description": (
        "Record a sales lead. Call this only after the customer has confirmed the "
        "details you read back to them. Do not call it for general questions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "full_name": {"type": "string", "description": "The customer's full name."},
            "phone_number": {"type": "string", "description": "Contact phone number."},
            "product": {"type": "string", "description": "Product or service they want, with any details such as model or colour."},
            "note": {"type": "string", "description": "Anything else the team should know before calling. Optional."},
        },
        "required": ["full_name", "phone_number", "product"],
        "additionalProperties": False,
    },
}

ESCALATE_SCHEMA = {
    "type": "function",
    "name": "escalate_to_human",
    "description": (
        "Hand the conversation to a human colleague. Call this when the customer asks "
        "for a person, is upset, or you cannot help after genuinely trying."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "reason": {"type": "string", "description": "Short reason, for the colleague picking this up."},
        },
        "required": ["reason"],
        "additionalProperties": False,
    },
}

SUMMARY_SCHEMA = {
    "type": "function",
    "name": "get_conversation_summary",
    "description": (
        "Read the recent messages in this conversation. Use it when you have lost "
        "track of what was already discussed, instead of asking the customer to repeat."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": f"How many recent messages to read, up to {MAX_SUMMARY_MESSAGES}."},
        },
        "required": [],
        "additionalProperties": False,
    },
}

FOLLOW_UP_SCHEMA = {
    "type": "function",
    "name": "schedule_follow_up",
    "description": (
        "Schedule a follow-up message for later. Call this when the customer says "
        "they need time to think or will decide later."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "reason": {"type": "string", "description": "Why we are following up."},
        },
        "required": ["reason"],
        "additionalProperties": False,
    },
}


def handle_create_lead(assistant, conversation, args: Dict[str, Any]) -> Dict[str, Any]:
    from apps.assistant.models import Lead

    lead = Lead.objects.create(
        assistant=assistant,
        full_name=args.get("full_name"),
        phone_number=args.get("phone_number"),
        product=args.get("product"),
        metadata=args,
        platform=conversation.platform,
        username=conversation.username or conversation.client_full_name,
    )
    logger.info("Lead %s created for conversation %s", lead.id, conversation.id)

    notify_lead(assistant, conversation, lead)

    return {
        "status": "recorded",
        "lead_id": str(lead.id),
        "full_name": lead.full_name,
        "phone_number": lead.phone_number,
        "product": lead.product,
    }


def notify_lead(assistant, conversation, lead) -> None:
    from apps.integration.gateways.telegram import send_telegram_message
    from apps.integration.models import TelegramGroupIntegration
    from apps.shared.addons.enums import IntegrationTypes

    integration = assistant.integrations.filter(
        integration_type=IntegrationTypes.TELEGRAM.value
    ).first()
    if integration is None or not integration.api_token:
        logger.info("Assistant %s has no Telegram integration; lead %s not broadcast", assistant.id, lead.id)
        return

    groups = TelegramGroupIntegration.objects.filter(integration=integration, is_approved=True)
    if not groups.exists():
        return

    handle = _customer_handle(conversation)
    text = (
        "New Lead 📢\n\n"
        f"👤 {lead.full_name}\n"
        f"📞 {lead.phone_number}\n"
        f"📦 {lead.product}\n"
        f"🔗 {handle or '—'}\n"
        f"🌐 {lead.platform}"
    )
    for group in groups:
        try:
            send_telegram_message(group.group_id, text, integration.api_token)
        except Exception as exc:
            logger.warning("Failed to notify group %s about lead %s: %s", group.group_id, lead.id, exc)


def _customer_handle(conversation):
    platform = (conversation.platform or "").lower()
    if platform == "telegram" and conversation.username:
        return f"@{conversation.username}"
    if platform == "instagram" and conversation.client_full_name:
        return f"https://www.instagram.com/{conversation.client_full_name}"
    return None


def handle_escalate_to_human(assistant, conversation, args: Dict[str, Any]) -> Dict[str, Any]:
    from apps.shared.addons.enums import ConversationStatuses
    from apps.shared.addons.redis import publish_message_to_ws_assistant

    reason = args.get("reason") or "Customer asked for a human"

    conversation.status = ConversationStatuses.ESCALATED.value
    conversation.save(update_fields=["status", "updated_time"])
    logger.info("Conversation %s escalated: %s", conversation.id, reason)

    try:
        publish_message_to_ws_assistant(conversation)
    except Exception as exc:
        logger.warning("Failed to publish escalation for %s: %s", conversation.id, exc)

    return {
        "status": "escalated",
        "message": "A human colleague has been notified and will take over this chat.",
    }


def handle_get_conversation_summary(assistant, conversation, args: Dict[str, Any]) -> Dict[str, Any]:
    limit = args.get("limit") or MAX_SUMMARY_MESSAGES
    try:
        limit = max(1, min(int(limit), MAX_SUMMARY_MESSAGES))
    except (TypeError, ValueError):
        limit = MAX_SUMMARY_MESSAGES

    messages = conversation.messages.order_by("-created_time")[:limit]
    history = [
        {"sender": m.sender, "content": m.message_content}
        for m in reversed(list(messages))
    ]
    return {"messages": history}


def handle_schedule_follow_up(assistant, conversation, args: Dict[str, Any]) -> Dict[str, Any]:
    from apps.assistant.models import FollowUpLog, FollowUpStage

    config = getattr(assistant, "follow_up_config", None)
    if config is None or not config.is_enabled:
        return {"error": "Follow-ups are not enabled for this assistant."}

    stage = FollowUpStage.objects.filter(
        config=config, is_active=True
    ).order_by("stage_number").first()
    if stage is None:
        return {"error": "No follow-up stage is configured."}

    scheduled_at = timezone.now() + timedelta(hours=stage.delay_hours)
    log = FollowUpLog.objects.create(
        conversation=conversation, stage=stage, scheduled_at=scheduled_at
    )
    logger.info("Follow-up %s scheduled for conversation %s at %s", log.id, conversation.id, scheduled_at)

    return {"status": "scheduled", "in_hours": stage.delay_hours}


def _follow_up_enabled(assistant) -> bool:
    config = getattr(assistant, "follow_up_config", None)
    return bool(config and config.is_enabled)


def register_tools() -> None:
    register("create_lead", CREATE_LEAD_SCHEMA, handle_create_lead)
    register("escalate_to_human", ESCALATE_SCHEMA, handle_escalate_to_human)
    register("get_conversation_summary", SUMMARY_SCHEMA, handle_get_conversation_summary)
    register("schedule_follow_up", FOLLOW_UP_SCHEMA, handle_schedule_follow_up,
             available=_follow_up_enabled)
