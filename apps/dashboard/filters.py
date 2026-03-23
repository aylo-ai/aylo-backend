from django_filters import rest_framework as filters

from apps.user.models import User
from apps.payment.models import Subscription, Transaction
from apps.assistant.models import Assistant, Conversation, Lead
from apps.integration.models import Integration
from apps.dashboard.models import AuditLog
from shared.addons.enums import (
    PaymentMethods, PaymentStatuses, UserRoles,
    ConversationStatuses, ConversationPlatforms, IntegrationTypes,
    LeadStatuses, SubscriptionStatuses,
)


class UserFilter(filters.FilterSet):
    date_range = filters.DateRangeFilter(field_name='created_time')
    user_role = filters.ChoiceFilter(choices=UserRoles.choices())
    is_active = filters.BooleanFilter()
    has_subscription = filters.BooleanFilter(method='filter_has_subscription')

    class Meta:
        model = User
        fields = ['created_time', 'user_role', 'is_active']

    def filter_has_subscription(self, queryset, name, value):
        if value:
            return queryset.filter(subscription__isnull=False)
        return queryset.filter(subscription__isnull=True)


class SubscriptionFilter(filters.FilterSet):
    status = filters.ChoiceFilter(choices=SubscriptionStatuses.choices())
    pricing_package = filters.UUIDFilter(field_name='pricing_package__id')
    auto_renew = filters.BooleanFilter()
    expiring_before = filters.DateFilter(field_name='end_date', lookup_expr='lte')
    expiring_after = filters.DateFilter(field_name='end_date', lookup_expr='gte')

    class Meta:
        model = Subscription
        fields = ['status', 'pricing_package', 'auto_renew']


class TransactionFilter(filters.FilterSet):
    status = filters.ChoiceFilter(choices=PaymentStatuses.choices())
    payment_method = filters.ChoiceFilter(choices=PaymentMethods.choices())
    date_from = filters.DateFilter(field_name='created_time', lookup_expr='gte')
    date_to = filters.DateFilter(field_name='created_time', lookup_expr='lte')
    amount_min = filters.NumberFilter(field_name='amount', lookup_expr='gte')
    amount_max = filters.NumberFilter(field_name='amount', lookup_expr='lte')
    currency = filters.CharFilter()
    transaction_type = filters.CharFilter()

    class Meta:
        model = Transaction
        fields = ['status', 'payment_method', 'currency', 'transaction_type']


class AssistantFilter(filters.FilterSet):
    is_active = filters.BooleanFilter()
    user = filters.UUIDFilter(field_name='user__id')
    language = filters.CharFilter(method='filter_language')
    has_integrations = filters.BooleanFilter(method='filter_has_integrations')

    class Meta:
        model = Assistant
        fields = ['is_active', 'user']

    def filter_language(self, queryset, name, value):
        return queryset.filter(language__contains=[value])

    def filter_has_integrations(self, queryset, name, value):
        if value:
            return queryset.filter(integrations__isnull=False).distinct()
        return queryset.filter(integrations__isnull=True)


class ConversationFilter(filters.FilterSet):
    status = filters.ChoiceFilter(choices=ConversationStatuses.choices())
    platform = filters.ChoiceFilter(choices=ConversationPlatforms.choices())
    assistant = filters.UUIDFilter(field_name='assistant__id')
    date_from = filters.DateFilter(field_name='created_time', lookup_expr='gte')
    date_to = filters.DateFilter(field_name='created_time', lookup_expr='lte')

    class Meta:
        model = Conversation
        fields = ['status', 'platform', 'assistant']


class IntegrationFilter(filters.FilterSet):
    integration_type = filters.ChoiceFilter(choices=IntegrationTypes.choices())
    is_active = filters.BooleanFilter()
    assistant = filters.UUIDFilter(field_name='assistant__id')

    class Meta:
        model = Integration
        fields = ['integration_type', 'is_active', 'assistant']


class LeadFilter(filters.FilterSet):
    status = filters.ChoiceFilter(choices=LeadStatuses.choices())
    platform = filters.ChoiceFilter(choices=ConversationPlatforms.choices())
    assistant = filters.UUIDFilter(field_name='assistant__id')
    contacted = filters.BooleanFilter()
    date_from = filters.DateFilter(field_name='created_time', lookup_expr='gte')
    date_to = filters.DateFilter(field_name='created_time', lookup_expr='lte')

    class Meta:
        model = Lead
        fields = ['status', 'platform', 'assistant', 'contacted']


class AuditLogFilter(filters.FilterSet):
    action = filters.CharFilter()
    target_type = filters.CharFilter()
    user = filters.UUIDFilter(field_name='user__id')
    date_from = filters.DateFilter(field_name='created_time', lookup_expr='gte')
    date_to = filters.DateFilter(field_name='created_time', lookup_expr='lte')

    class Meta:
        model = AuditLog
        fields = ['action', 'target_type', 'user']
