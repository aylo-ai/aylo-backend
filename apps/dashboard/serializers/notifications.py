"""Notification serializers for the dashboard."""
from rest_framework import serializers

from apps.shared.addons.enums import NotificationTypes
from apps.dashboard.serializers.common import StrictCharField


class NotificationSendSerializer(serializers.Serializer):
    """Validates `notifications/send/` — types are checked, not coerced."""
    user_id = serializers.UUIDField()
    title = StrictCharField(max_length=255)
    content = StrictCharField()
    type = serializers.ChoiceField(
        choices=NotificationTypes.choices(),
        default=NotificationTypes.NEWS.value,
    )
