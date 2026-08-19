from django.db.models import Q
from django.utils.timezone import now


def owned_assistants(user):
    from apps.assistant.models import Assistant

    q = Q(user=user)
    if user.created_by_id:
        q |= Q(user=user.created_by)
    return Assistant.objects.filter(q).distinct()


def cancel_pending_follow_ups(conversation_id):
    from apps.assistant.models import FollowUpLog
    from apps.shared.addons.enums import FollowUpLogStatus

    FollowUpLog.objects.filter(
        conversation_id=conversation_id,
        status=FollowUpLogStatus.PENDING.value,
    ).update(status=FollowUpLogStatus.CANCELLED.value, cancelled_at=now())
