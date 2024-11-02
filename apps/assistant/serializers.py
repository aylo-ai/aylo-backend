from apps.assistant.models import Assistant, Conversation, Message
from rest_framework import serializers


class AssistantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Assistant
        fields = [
            "id",
            "name",
            "company",
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
            "message",
            "created_time",
            "updated_time",
        ]
        read_only_fields = ["created_time", "updated_time"]