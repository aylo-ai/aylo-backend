"""Assistant, assistant-file and prompt-template serializers for the dashboard."""
from rest_framework import serializers

from apps.assistant.models import Assistant, AssistantFileUpload, PromptTemplate
from apps.shared.addons.enums import IntegrationTypes


class DashboardPromptTemplateSerializer(serializers.ModelSerializer):
    assistants_count = serializers.SerializerMethodField()

    class Meta:
        model = PromptTemplate
        fields = [
            'id', 'name', 'description', 'content', 'is_default',
            'is_active', 'assistants_count', 'created_time', 'updated_time'
        ]
        read_only_fields = ['created_time', 'updated_time']

    def get_assistants_count(self, obj):
        return obj.assistants.count()


class DashboardAssistantListSerializer(serializers.ModelSerializer):
    """Assistant serializer with owner contact info for dashboard."""
    owner_phone = serializers.SerializerMethodField()
    owner_email = serializers.SerializerMethodField()
    owner_name = serializers.SerializerMethodField()
    integrations = serializers.SerializerMethodField()

    class Meta:
        model = Assistant
        fields = [
            'id', 'name', 'description', 'user', 'company_name', 'role',
            'language', 'personality_style', 'greeting_message',
            'fallback_message', 'wait_message', 'created_time', 'updated_time',
            'is_active', 'ai_enabled', 'prompt_template',
            'owner_phone', 'owner_email', 'owner_name', 'integrations',
        ]

    def get_owner_phone(self, obj):
        return obj.user.phone_number if obj.user else None

    def get_owner_email(self, obj):
        return obj.user.email if obj.user else None

    def get_owner_name(self, obj):
        if not obj.user:
            return None
        name = f"{obj.user.first_name or ''} {obj.user.last_name or ''}".strip()
        return name or obj.user.username

    def get_integrations(self, obj):
        return {
            'is_telegram_integration': obj.integrations.filter(
                integration_type=IntegrationTypes.TELEGRAM.value).exists(),
            'is_instagram_integration': obj.integrations.filter(
                integration_type=IntegrationTypes.INSTAGRAM.value).exists(),
            'is_widget_integration': obj.integrations.filter(
                integration_type=IntegrationTypes.WEBSITE.value).exists(),
        }


class DashboardAssistantFileUploadSerializer(serializers.ModelSerializer):
    """Serializer for admin file uploads (no subscription check)."""

    class Meta:
        model = AssistantFileUpload
        fields = [
            'id', 'assistant', 'filename', 'file', 'file_type',
            'website_url', 'created_time', 'updated_time',
        ]
        read_only_fields = ['created_time', 'updated_time']

    def validate(self, attrs):
        file = attrs.get('file')
        if file and hasattr(file, 'size') and file.size > 30 * 1024 * 1024:
            raise serializers.ValidationError("File exceeds the 30MB size limit.")
        return attrs


class DashboardAssistantCreateSerializer(serializers.ModelSerializer):
    """Serializer for admin to create assistants for any user (no subscription check)."""

    class Meta:
        model = Assistant
        fields = [
            'name', 'description', 'user', 'company_name', 'role',
            'language', 'personality_style', 'greeting_message',
            'fallback_message', 'wait_message',
        ]

    def validate(self, attrs):
        company_name = attrs.get('company_name')
        role = attrs.get('role')
        if company_name and len(company_name) > 100:
            raise serializers.ValidationError("Company nomi 100 ta belgidan kam bo'lishi kerak")
        if role and len(role) > 100:
            raise serializers.ValidationError("Role 100 ta belgidan kam bo'lishi kerak")
        return attrs


class DashboardAssistantCreateUserSerializer(serializers.Serializer):
    """Validates the `user` FK that `assistants/` POST resolves before creating."""
    user = serializers.UUIDField()


class AssistantFileFilterSerializer(serializers.Serializer):
    """Validates the `?assistant=` query param of `assistantfiles/`."""
    assistant = serializers.UUIDField(required=False)
