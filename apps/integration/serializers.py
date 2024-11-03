import telegram

from shared.addons.enums import IntegrationTypes
from shared.addons.validations import raise_validation_error
from .models import Integration
from rest_framework import serializers


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

    def validate(self, attrs):
        integration_type = attrs.get("integration_type")
        api_token = attrs.get("api_token")
        if integration_type == IntegrationTypes.TELEGRAM.value:
            try:
                bot = telegram.Bot(token=api_token)
                bot.get_me()
            except telegram.error.InvalidToken:
                raise_validation_error(message="Invalid Telegram API token")


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