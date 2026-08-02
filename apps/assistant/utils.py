from django.db.models import Q
from django.utils.timezone import now


def owned_assistants(user):
    """Assistants the requesting user may access: their own and, for staff
    accounts, those of the customer who created them. `Assistant.user` is
    nullable, so the created_by leg is only added when it is set — otherwise
    `Q(user=None)` would match ownerless assistants for every customer.

    Lives here rather than in `views.py` so serializers and other apps can
    resolve ownership through the same single definition.
    """
    from apps.assistant.models import Assistant

    q = Q(user=user)
    if user.created_by_id:
        q |= Q(user=user.created_by)
    return Assistant.objects.filter(q).distinct()


def cancel_pending_follow_ups(conversation_id):
    """Cancel all pending follow-up logs for a conversation when user responds."""
    from apps.assistant.models import FollowUpLog
    from apps.shared.addons.enums import FollowUpLogStatus

    FollowUpLog.objects.filter(
        conversation_id=conversation_id,
        status=FollowUpLogStatus.PENDING.value,
    ).update(status=FollowUpLogStatus.CANCELLED.value, cancelled_at=now())
