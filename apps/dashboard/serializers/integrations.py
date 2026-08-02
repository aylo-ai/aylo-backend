"""Integration serializers for the dashboard."""
from rest_framework import serializers

from apps.assistant.models import Conversation, Message, Lead
from apps.integration.models import Integration
from apps.shared.addons.enums import ConversationPlatforms, IntegrationTypes


class DashboardIntegrationListSerializer(serializers.ModelSerializer):
    """Rich integration serializer with all operational data."""
    assistant_name = serializers.SerializerMethodField()
    owner_name = serializers.SerializerMethodField()
    integration_type_display = serializers.SerializerMethodField()
    conversation_count = serializers.SerializerMethodField()
    message_count = serializers.SerializerMethodField()
    lead_count = serializers.SerializerMethodField()
    last_message_time = serializers.SerializerMethodField()
    telegram_groups = serializers.SerializerMethodField()

    class Meta:
        model = Integration
        fields = [
            'id', 'name', 'description', 'is_active', 'integration_type',
            'integration_type_display', 'is_comment_response',
            'assistant', 'assistant_name', 'owner_name',
            'conversation_count', 'message_count', 'lead_count',
            'last_message_time', 'telegram_groups',
            'instagram_username',
            'created_time', 'updated_time',
        ]

    # An integration type maps to a conversation platform only when the channel
    # actually carries conversations; the CRM connectors do not, so their
    # counts are not platform-scoped.
    PLATFORM_MAP = {
        IntegrationTypes.TELEGRAM.value: ConversationPlatforms.TELEGRAM.value,
        IntegrationTypes.INSTAGRAM.value: ConversationPlatforms.INSTAGRAM.value,
        IntegrationTypes.WHATSAPP.value: ConversationPlatforms.WHATSAPP.value,
        IntegrationTypes.WEBSITE.value: ConversationPlatforms.WEBSITE.value,
        IntegrationTypes.BITRIX24.value: None,
        IntegrationTypes.AMOCRM.value: None,
        IntegrationTypes.BILLZ.value: None,
    }

    TYPE_LABELS = {
        IntegrationTypes.TELEGRAM.value: 'Telegram Bot',
        IntegrationTypes.INSTAGRAM.value: 'Instagram',
        IntegrationTypes.WHATSAPP.value: 'WhatsApp',
        IntegrationTypes.WEBSITE.value: 'Web Widget',
        IntegrationTypes.BITRIX24.value: 'Bitrix24 CRM',
        IntegrationTypes.AMOCRM.value: 'amoCRM',
        IntegrationTypes.BILLZ.value: 'Billz',
    }

    def get_assistant_name(self, obj):
        return obj.assistant.name if obj.assistant else None

    def get_owner_name(self, obj):
        user = obj.assistant.user if obj.assistant else obj.user
        if user:
            return f"{user.first_name or ''} {user.last_name or ''}".strip() or user.username
        return None

    def get_integration_type_display(self, obj):
        return self.TYPE_LABELS.get(obj.integration_type, obj.integration_type)

    def get_conversation_count(self, obj):
        if not obj.assistant:
            return 0
        platform = self.PLATFORM_MAP.get(obj.integration_type)
        qs = Conversation.objects.filter(assistant=obj.assistant)
        if platform:
            qs = qs.filter(platform=platform)
        return qs.count()

    def get_message_count(self, obj):
        if not obj.assistant:
            return 0
        platform = self.PLATFORM_MAP.get(obj.integration_type)
        qs = Message.objects.filter(conversation__assistant=obj.assistant)
        if platform:
            qs = qs.filter(conversation__platform=platform)
        return qs.count()

    def get_lead_count(self, obj):
        if not obj.assistant:
            return 0
        platform = self.PLATFORM_MAP.get(obj.integration_type)
        qs = Lead.objects.filter(assistant=obj.assistant)
        if platform:
            qs = qs.filter(platform=platform)
        return qs.count()

    def get_last_message_time(self, obj):
        if not obj.assistant:
            return None
        platform = self.PLATFORM_MAP.get(obj.integration_type)
        qs = Message.objects.filter(conversation__assistant=obj.assistant)
        if platform:
            qs = qs.filter(conversation__platform=platform)
        last = qs.order_by('-created_time').first()
        return last.created_time.isoformat() if last else None

    def get_telegram_groups(self, obj):
        if obj.integration_type != IntegrationTypes.TELEGRAM.value:
            return None
        groups = obj.telegram_group.all()
        if not groups.exists():
            return None
        return [
            {
                'group_title': g.group_title,
                'lead_count': g.lead_count,
                'is_approved': g.is_approved,
            }
            for g in groups
        ]
