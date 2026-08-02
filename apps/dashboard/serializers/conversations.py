"""Conversation serializers for the dashboard."""
from rest_framework import serializers

from apps.assistant.models import Conversation
from apps.assistant.serializers import MessageSerializer
from apps.shared.addons.enums import SenderTypes


class DashboardConversationSerializer(serializers.ModelSerializer):
    message_price = serializers.SerializerMethodField(method_name="get_message_price")
    messages = serializers.SerializerMethodField(method_name="get_messages")
    assistant_name = serializers.CharField(source='assistant.name', read_only=True)
    message_count = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            'id', 'assistant', 'assistant_name', 'status', 'thread_id',
            'platform', 'start_time', 'end_time', 'username',
            'client_full_name', 'client_phone_email',
            'messages', 'message_count', 'created_time', 'updated_time',
            'message_price',
        ]
        read_only_fields = ['created_time', 'updated_time']

    def get_message_price(self, obj):
        message_count = obj.messages.count()
        assistant_msgs = obj.messages.filter(sender=SenderTypes.ASSISTANT.value)
        message_input = sum([m.input_tokens for m in assistant_msgs])
        message_output = sum([m.output_tokens for m in assistant_msgs])
        return {
            "message_price": f"${(message_input/1000000 * 5) + (message_output/1000000 * 20):.2f}",
            "message_count": message_count,
        }

    def get_messages(self, obj):
        return MessageSerializer(obj.messages.all(), many=True).data

    def get_message_count(self, obj):
        return obj.messages.count()


class DashboardConversationListSerializer(serializers.ModelSerializer):
    """Lighter serializer for list views without full message data."""
    assistant_name = serializers.CharField(source='assistant.name', read_only=True)
    owner_name = serializers.SerializerMethodField()
    message_count = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            'id', 'assistant', 'assistant_name', 'owner_name', 'status',
            'platform', 'username', 'client_full_name', 'client_phone_email',
            'message_count', 'start_time', 'end_time',
            'created_time', 'updated_time',
        ]

    def get_message_count(self, obj):
        return obj.messages.count()

    def get_owner_name(self, obj):
        user = obj.assistant.user
        if user:
            return f"{user.first_name or ''} {user.last_name or ''}".strip() or user.username
        return None
