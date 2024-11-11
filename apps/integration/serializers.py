from shared.addons.enums import IntegrationTypes
from shared.addons.telegram import telegram_get_me
from shared.addons.validations import raise_validation_error
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
        if integration_type == IntegrationTypes.TELEGRAM.value:
            success, code = telegram_get_me(api_token)
            if not success or code == 401:
                raise_validation_error(message=_("Invalid Telegram API token"))
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