from rest_framework import serializers

from apps.payment.models import Feature, PricingPackage
from shared.addons.validations import raise_validation_error


class FeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feature
        fields = [
            "id",
            "name",
            "description",
        ]


class PricingPackageSerializer(serializers.ModelSerializer):
    class Meta:
        model = PricingPackage
        fields = [
            "id",
            "name",
            "price",
            "description",
            "features",
        ]

    def validate(self, attrs):
        if attrs["price"] < 0:
            raise_validation_error(message="Price cannot be negative")
        return attrs