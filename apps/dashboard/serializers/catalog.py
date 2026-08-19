from django.db.models import Sum
from rest_framework import serializers

from apps.assistant.models import Assistant, Conversation, Message
from apps.dashboard.serializers.common import StrictCharField
from apps.payment.models import Feature, PricingPackage
from apps.payment.serializers import FeatureSerializer
from apps.shared.addons.enums import SenderTypes, SubscriptionStatuses
from apps.user.models import User


class DashboardPricingPackageDetailSerializer(serializers.ModelSerializer):
    subscribers_count = serializers.SerializerMethodField()
    active_subscribers = serializers.SerializerMethodField()
    total_assistants = serializers.SerializerMethodField()
    total_conversations = serializers.SerializerMethodField()
    total_messages = serializers.SerializerMethodField()
    total_tokens_used = serializers.SerializerMethodField()
    features = serializers.SerializerMethodField()

    class Meta:
        model = PricingPackage
        fields = [
            'id', 'name', 'price', 'discount_price', 'type', 'currency',
            'description', 'request_count', 'duration_days',
            'is_active', 'is_popular',
            'subscribers_count', 'active_subscribers',
            'total_assistants', 'total_conversations', 'total_messages',
            'total_tokens_used', 'features',
            'created_time', 'updated_time',
        ]

    def _get_users_for_package(self, obj):
        return User.objects.filter(subscription__pricing_package=obj)

    def get_subscribers_count(self, obj):
        return self._get_users_for_package(obj).count()

    def get_active_subscribers(self, obj):
        return User.objects.filter(
            subscription__pricing_package=obj,
            subscription__status=SubscriptionStatuses.ACTIVE.value
        ).count()

    def get_total_assistants(self, obj):
        users = self._get_users_for_package(obj)
        return Assistant.objects.filter(user__in=users).count()

    def get_total_conversations(self, obj):
        users = self._get_users_for_package(obj)
        return Conversation.objects.filter(assistant__user__in=users).count()

    def get_total_messages(self, obj):
        users = self._get_users_for_package(obj)
        return Message.objects.filter(conversation__assistant__user__in=users).count()

    def get_total_tokens_used(self, obj):
        users = self._get_users_for_package(obj)
        result = Message.objects.filter(
            conversation__assistant__user__in=users,
            sender=SenderTypes.ASSISTANT.value
        ).aggregate(
            inp=Sum('input_tokens'),
            out=Sum('output_tokens'),
        )
        return (result['inp'] or 0) + (result['out'] or 0)

    def get_features(self, obj):
        return [
            {'id': str(f.id), 'name': f.name, 'icon': f.icon}
            for f in obj.features.all()
        ]


class DashboardFeatureSerializer(FeatureSerializer):
    name = StrictCharField(max_length=100)
    icon = StrictCharField(max_length=50, required=False, allow_null=True, allow_blank=True)

    class Meta(FeatureSerializer.Meta):
        model = Feature
