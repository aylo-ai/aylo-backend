from django.utils.timezone import now


def cancel_pending_follow_ups(conversation_id):
    """Cancel all pending follow-up logs for a conversation when user responds."""
    from apps.assistant.models import FollowUpLog
    from apps.shared.addons.enums import FollowUpLogStatus

    FollowUpLog.objects.filter(
        conversation_id=conversation_id,
        status=FollowUpLogStatus.PENDING.value,
    ).update(status=FollowUpLogStatus.CANCELLED.value, cancelled_at=now())
