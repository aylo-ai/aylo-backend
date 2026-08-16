"""Dashboard audit-log endpoints."""
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics

from apps.dashboard.filters import AuditLogFilter
from apps.dashboard.models import AuditLog
from apps.dashboard.serializers.audit import AuditLogSerializer
from apps.dashboard.views.mixins import DashboardListMixin
from apps.shared.pagination import StandardResultsSetPagination
from apps.shared.permissions import IsAdmin


class DashboardAuditLogList(DashboardListMixin, generics.ListAPIView):
    queryset = AuditLog.objects.select_related('user').all()
    serializer_class = AuditLogSerializer
    permission_classes = [IsAdmin]
    filterset_class = AuditLogFilter
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['target_repr', 'action', 'target_type']
    ordering_fields = ['created_time', 'action', 'target_type']
    pagination_class = StandardResultsSetPagination
    list_message = "Audit logs retrieved successfully"
