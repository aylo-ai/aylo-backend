"""User serializers for the dashboard."""
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.assistant.models import Conversation, Message
from apps.assistant.serializers import AssistantSerializer
from apps.dashboard.serializers.common import serialize_subscription
from apps.dashboard.serializers.transactions import DashboardTransactionSerializer
from apps.integration.serializers import IntegrationSerializer
from apps.shared.addons.enums import SenderTypes, UserRoles
from apps.user.models import User


class DashboardUserSerializer(serializers.ModelSerializer):
    subscription = serializers.SerializerMethodField()
    assistants = serializers.SerializerMethodField()
    integrations = serializers.SerializerMethodField()
    transactions = serializers.SerializerMethodField()
    conversation_and_message = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'first_name', 'last_name', 'phone_number', 'username',
            'email', 'user_role', 'is_active', 'subscription', 'assistants',
            'integrations', 'transactions', 'created_time', 'updated_time',
            'conversation_and_message',
        ]
        read_only_fields = ['created_time', 'updated_time']

    def get_subscription(self, obj):
        return serialize_subscription(obj.subscription)

    def get_assistants(self, obj):
        return AssistantSerializer(obj.assistants.all(), many=True).data

    def get_integrations(self, obj):
        assistants = obj.assistants.all()
        integrations = []
        for assistant in assistants:
            integrations.extend(assistant.integrations.all())
        return IntegrationSerializer(integrations, many=True).data

    def get_transactions(self, obj):
        return DashboardTransactionSerializer(obj.transactions.all(), many=True).data

    def get_conversation_and_message(self, obj):
        conversations = Conversation.objects.filter(assistant__user=obj)
        conversation_count = conversations.count()
        assistant_msgs = Message.objects.filter(
            conversation__in=conversations, sender=SenderTypes.ASSISTANT.value
        )
        message_count = Message.objects.filter(conversation__in=conversations).count()
        message_input = sum([m.input_tokens for m in assistant_msgs])
        message_output = sum([m.output_tokens for m in assistant_msgs])
        return {
            "message_price": f"${(message_input/1000000 * 5) + (message_output/1000000 * 20):.2f}",
            "conversation_count": conversation_count,
            "message_count": message_count,
        }


class DashboardUserListSerializer(serializers.ModelSerializer):
    total_used_token_count = serializers.SerializerMethodField()
    subscription = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'first_name', 'last_name', 'phone_number',
            'email', 'user_role', 'is_active', 'total_used_token_count',
            'subscription', 'created_time', 'updated_time',
        ]
        read_only_fields = ['created_time', 'updated_time']

    def get_total_used_token_count(self, obj):
        subscription = obj.subscription
        # `pricing_package` is a nullable FK (SET_NULL) — a subscription can
        # outlive the package it was bought on.
        if subscription and subscription.pricing_package:
            return subscription.pricing_package.request_count - subscription.remained_request_count
        return 0

    def get_subscription(self, obj):
        return serialize_subscription(obj.subscription)


class ChangeRoleSerializer(serializers.Serializer):
    user_role = serializers.ChoiceField(choices=UserRoles.choices())


class UserBulkActionSerializer(serializers.Serializer):
    """Validates `users/bulk-action/` — ids must be real UUIDs before they reach the ORM."""
    ACTIONS = ('activate', 'deactivate', 'delete', 'change_role')

    action = serializers.ChoiceField(choices=ACTIONS)
    ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False)
    role = serializers.ChoiceField(choices=UserRoles.choices(), required=False)

    def validate(self, attrs):
        if attrs['action'] == 'change_role' and not attrs.get('role'):
            raise serializers.ValidationError(
                {'role': _("role is required for change_role action")}
            )
        return attrs
