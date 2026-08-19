from rest_framework import serializers

from apps.dashboard.serializers.common import StrictCharField
from apps.shared.addons.enums import NotificationTypes


class NotificationSendSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    title = StrictCharField(max_length=255)
    content = StrictCharField()
    type = serializers.ChoiceField(
        choices=NotificationTypes.choices(),
        default=NotificationTypes.NEWS.value,
    )
