from apps.assistant.models import Assistant, Conversation, Message, Settings, AssistantFileUpload
from rest_framework import serializers


class AssistantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Assistant
        fields = [
            "id",
            "name",
            "description",
            "user",
            "company_name",
            "role",
            "pricing_package",
            "language",
            "personality_style",
            "greeting_message",
            "fallback_message",
            "created_time",
            "updated_time",
        ]
        read_only_fields = ["created_time", "updated_time"]


class ConversationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversation
        fields = [
            "id",
            "assistant",
            "status",
            "session_id",
            "start_time",
            "end_time",
            "created_time",
            "updated_time",
        ]
        read_only_fields = ["created_time", "updated_time"]


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = [
            "id",
            "conversation",
            "sender",
            "message_content",
            "message_type",
            "created_time",
            "updated_time",
        ]
        read_only_fields = ["created_time", "updated_time"]


class SettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Settings
        fields = [
            "id",
            "assistant",
            "timezone",
            "language",
            "notification_preferences",
            "escalation_rules",
            "created_time",
            "updated_time",
        ]
        read_only_fields = ["created_time", "updated_time"]


class AssistantFileUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssistantFileUpload
        fields = [
            "id",
            "assistant",
            "filename",
            "file",
            "created_time",
            "updated_time",
        ]
        read_only_fields = ["created_time", "updated_time"]
        extra_kwargs = {
            "assistant": {"required": False},
        }

    def validate(self, attrs):
        if attrs.get("file"):
            if attrs["file"].size > 30 * 1024 * 1024:  # 30MB
                raise serializers.ValidationError("File size should not exceed 30MB")
        return attrs