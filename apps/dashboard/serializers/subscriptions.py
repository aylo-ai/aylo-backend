"""Subscription serializers for the dashboard."""
from rest_framework import serializers

from apps.payment.models import Subscription, PricingPackage


class DashboardSubscriptionSerializer(serializers.ModelSerializer):
    pricing_package = serializers.SerializerMethodField()
    user = serializers.SerializerMethodField()

    class Meta:
        model = Subscription
        fields = [
            'id', 'user', 'pricing_package', 'start_date', 'end_date',
            'status', 'remained_request_count', 'next_payment_date',
            'auto_renew', 'cancellation_reason', 'last_payment_date',
            'grace_period_days', 'created_time', 'updated_time',
        ]
        read_only_fields = ['created_time', 'updated_time']

    def get_pricing_package(self, obj):
        if obj.pricing_package:
            return {
                "id": obj.pricing_package.id,
                "name": obj.pricing_package.name,
                "price": obj.pricing_package.price,
                "type": obj.pricing_package.type,
            }
        return None

    def get_user(self, obj):
        if obj.users.count() > 0:
            u = obj.users.first()
            return {
                "id": u.id,
                "username": u.username,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "email": u.email,
            }
        return None


class SubscriptionExtendSerializer(serializers.Serializer):
    days = serializers.IntegerField(min_value=1, default=30)


class DashboardSubscriptionUpdateSerializer(serializers.ModelSerializer):
    """Write serializer for `subscriptions/<id>/` — every field is validated.

    `pricing_package` is a real relation field, so a bad UUID or an unknown id
    becomes a 400 instead of an unhandled ORM error.
    """
    pricing_package = serializers.PrimaryKeyRelatedField(
        queryset=PricingPackage.objects.all(), required=False, allow_null=True,
    )

    class Meta:
        model = Subscription
        fields = [
            'pricing_package', 'start_date', 'end_date', 'status',
            'remained_request_count', 'auto_renew', 'next_payment_date',
        ]
