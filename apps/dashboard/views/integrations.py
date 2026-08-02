"""Dashboard integration endpoints."""
from rest_framework import generics, filters
from django_filters.rest_framework import DjangoFilterBackend

from apps.assistant.models import Conversation, Lead
from apps.integration.models import Integration
from apps.integration.serializers import IntegrationSerializer
from apps.shared.permissions import IsDashboardUser
from apps.shared.pagination import StandardResultsSetPagination
from apps.dashboard.filters import IntegrationFilter
from apps.dashboard.serializers.integrations import DashboardIntegrationListSerializer
from apps.dashboard.views.mixins import (
    DashboardDestroyMixin,
    DashboardPartialUpdateMixin,
    DashboardRetrieveMixin,
    DashboardStatsListMixin,
)


class DashboardIntegrationList(DashboardStatsListMixin, generics.ListAPIView):
    queryset = Integration.objects.select_related('assistant', 'assistant__user', 'user').all()
    serializer_class = DashboardIntegrationListSerializer
    permission_classes = [IsDashboardUser]
    filterset_class = IntegrationFilter
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    pagination_class = StandardResultsSetPagination
    search_fields = ["name", "assistant__name", "assistant__user__username", "assistant__company_name", "integration_type"]
    ordering_fields = ['name', 'created_time', 'integration_type', 'is_active']
    list_message = "Integrations retrieved successfully"

    def get_list_stats(self, queryset):
        all_integrations = Integration.objects.all()
        return {
            'total': all_integrations.count(),
            'active': all_integrations.filter(is_active=True).count(),
            'total_conversations': Conversation.objects.filter(
                assistant__integrations__isnull=False
            ).distinct().count(),
            'total_leads': Lead.objects.filter(
                assistant__integrations__isnull=False
            ).distinct().count(),
        }


class DashboardIntegrationDetail(
    DashboardRetrieveMixin,
    DashboardPartialUpdateMixin,
    DashboardDestroyMixin,
    generics.RetrieveUpdateDestroyAPIView,
):
    queryset = Integration.objects.all()
    serializer_class = IntegrationSerializer
    permission_classes = [IsDashboardUser]
    retrieve_message = "Integration retrieved successfully"
    update_message = "Integration updated successfully"
    destroy_message = "Integration deleted successfully"
