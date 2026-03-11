from rest_framework import serializers
from landing.models import LandingLead


class LandingLeadSerializer(serializers.ModelSerializer):
    class Meta:
        model = LandingLead
        fields = ["id", "full_name", "phone_number", "telegram_username", "source_page"]

    def validate_phone_number(self, value):
        cleaned = value.strip().replace(" ", "").replace("-", "")
        if len(cleaned) < 9:
            raise serializers.ValidationError("Telefon raqam kamida 9 ta raqamdan iborat bo'lishi kerak.")
        return cleaned
