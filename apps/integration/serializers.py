from apps.assistant.models import Conversation
from shared.addons.enums import IntegrationTypes, ConversationPlatforms, ConversationStatuses
from shared.addons.telegram import telegram_get_me, set_telegram_webhook, get_webhook_info, send_telegram_message
from shared.addons.utils import create_message
from shared.addons.validations import raise_validation_error, success_response
from .models import Integration
from rest_framework import serializers
from django.utils.translation import gettext as _


class IntegrationCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Integration
        fields = [
            "id",
            "assistant",
            "name",
            "description",
            "is_active",
            "api_token",
            "integration_type",
        ]
        extra_kwargs = {
            "assistant": {"required": False},
        }

    def validate(self, attrs):
        integration_type = attrs.get("integration_type")
        api_token = attrs.get("api_token")
        base_url = self.context.get("base_url")
        if integration_type == IntegrationTypes.TELEGRAM.value:
            success, code = telegram_get_me(api_token)
            if not success or code == 401:
                raise_validation_error(message=_("Invalid Telegram API token"))
            set_telegram_webhook(api_token, f"{base_url}/api/v1/integration/telegram/webhook/{api_token}/")
            code = get_webhook_info(api_token)
            if code == 400:
                raise_validation_error(message=_("Failed to set Telegram webhook"))
        return attrs


class IntegrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Integration
        fields = [
            "id",
            "assistant",
            "name",
            "description",
            "is_active",
            "integration_type",
        ]


class SendUserMessageSerializer(serializers.Serializer):  # noqa
    conversation_id = serializers.UUIDField()
    message = serializers.CharField()

    def validate(self, attrs):
        conversation_id = attrs.get("conversation_id")
        message = attrs.get("message")
        if not conversation_id or not message:
            raise_validation_error(message=_("Conversation ID and message are required"))
        conversation = Conversation.objects.filter(id=conversation_id).first()
        if not conversation:
            raise_validation_error(message=_("Conversation not found"))
        if conversation.status != ConversationStatuses.ESCALATED.value:
            raise_validation_error(message=_("Conversation is not escalated"))
        platform = conversation.platform
        attrs["platform"] = platform
        attrs["conversation"] = conversation
        if platform == ConversationPlatforms.TELEGRAM.value and \
                conversation.status == ConversationStatuses.ESCALATED.value:
            telegram_user_id = getattr(conversation, "telegram_user_id", None)
            bot_token = getattr(conversation, "token", None)
            if not telegram_user_id:
                raise_validation_error(message=_("Telegram user ID not found"))
            attrs["telegram_user_id"] = telegram_user_id
            if not bot_token:
                raise_validation_error(message=_("Telegram bot token not found"))
            attrs["bot_token"] = bot_token

        return attrs

    def create(self, validated_data):
        platform = validated_data.get("platform")
        conversation = validated_data.get("conversation")
        if platform == ConversationPlatforms.TELEGRAM.value:
            telegram_user_id = validated_data.get("telegram_user_id")
            bot_token = validated_data.get("bot_token")
            message = validated_data.get("message")
            send_telegram_message(telegram_user_id, message, bot_token)
            create_message(conversation, "admin", message)

        if platform == ConversationPlatforms.WEBSITE.value:
            message = validated_data.get("message")
            create_message(conversation, "admin", message)

        return success_response(message=_("Message sent successfully"), code=200)


