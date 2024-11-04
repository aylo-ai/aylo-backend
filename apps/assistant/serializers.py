from apps.assistant.models import Assistant, Conversation, Message, Settings, AssistantFileUpload
from rest_framework import serializers

from shared.addons.ai_requests import create_assistant_id, save_uploaded_file, send_assistant_data
from shared.addons.validations import raise_validation_error


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
        files = self.context.get("files")
        if not files:
            raise serializers.ValidationError("No files were uploaded.")

        for file in files:
            print(f"File size: {file.size}")
            if file.size > 30 * 1024 * 1024:  # 30MB limit
                raise serializers.ValidationError(f"File {file.name} exceeds the 30MB size limit.")
        return attrs

    def create(self, validated_data):
        files = self.context.get('files')
        assistant = self.context.get("assistant")
        for file in files:
            filename = file.name
            AssistantFileUpload.objects.create(
                assistant=assistant,
                file=file,
                filename=filename
            )
        send_assistant_data(assistant)

        return assistant