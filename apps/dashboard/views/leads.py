"""Dashboard lead endpoints."""
import csv
from datetime import timedelta

from django.db.models import Count
from django.http import HttpResponse
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics
from rest_framework.views import APIView

from apps.assistant.models import Lead
from apps.dashboard.filters import LeadFilter
from apps.dashboard.serializers.leads import DashboardLeadSerializer
from apps.dashboard.views.mixins import (
    DashboardListMixin,
    DashboardPartialUpdateMixin,
    DashboardRetrieveMixin,
)
from apps.shared.addons.validations import success_response
from apps.shared.pagination import StandardResultsSetPagination
from apps.shared.permissions import IsDashboardUser


class DashboardLeadList(DashboardListMixin, generics.ListAPIView):
    queryset = Lead.objects.select_related('assistant').all()
    serializer_class = DashboardLeadSerializer
    permission_classes = [IsDashboardUser]
    filterset_class = LeadFilter
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['full_name', 'phone_number', 'email', 'product', 'username']
    ordering_fields = ['created_time', 'status', 'full_name']
    pagination_class = StandardResultsSetPagination
    list_message = "Leads retrieved successfully"


class DashboardLeadDetail(
    DashboardRetrieveMixin,
    DashboardPartialUpdateMixin,
    generics.RetrieveUpdateAPIView,
):
    queryset = Lead.objects.all()
    serializer_class = DashboardLeadSerializer
    permission_classes = [IsDashboardUser]
    retrieve_message = "Lead retrieved successfully"
    update_message = "Lead updated successfully"


class DashboardLeadStats(APIView):
    permission_classes = [IsDashboardUser]

    def get(self, request):
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=today_start.weekday())
        month_start = today_start.replace(day=1)
        prev_month_start = (month_start - timedelta(days=1)).replace(day=1)

        qs = Lead.objects.all()
        total = qs.count()

        status_counts = dict(qs.values_list('status').annotate(count=Count('id')))

        platform_counts = dict(qs.values_list('platform').annotate(count=Count('id')))

        contacted_count = qs.filter(contacted=True).count()

        today_count = qs.filter(created_time__gte=today_start).count()
        week_count = qs.filter(created_time__gte=week_start).count()
        month_count = qs.filter(created_time__gte=month_start).count()
        prev_month_count = qs.filter(
            created_time__gte=prev_month_start,
            created_time__lt=month_start,
        ).count()

        # Growth percentage
        if prev_month_count > 0:
            month_growth = round(((month_count - prev_month_count) / prev_month_count) * 100, 1)
        else:
            month_growth = 100.0 if month_count > 0 else 0.0

        contacted_rate = round((contacted_count / total) * 100, 1) if total > 0 else 0.0

        data = {
            'total': total,
            'status_counts': status_counts,
            'platform_counts': platform_counts,
            'contacted_count': contacted_count,
            'contacted_rate': contacted_rate,
            'today_count': today_count,
            'week_count': week_count,
            'month_count': month_count,
            'month_growth': month_growth,
        }
        return success_response(data=data, message="Lead stats retrieved successfully")


class DashboardLeadExport(APIView):
    permission_classes = [IsDashboardUser]

    def get(self, request):
        qs = Lead.objects.select_related('assistant').all().order_by('-created_time')

        # Apply filters
        lead_status = request.query_params.get('status')
        if lead_status:
            qs = qs.filter(status=lead_status)
        platform = request.query_params.get('platform')
        if platform:
            qs = qs.filter(platform=platform)
        contacted = request.query_params.get('contacted')
        if contacted is not None:
            qs = qs.filter(contacted=contacted.lower() == 'true')

        now_str = timezone.now().strftime('%Y-%m-%d')
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="leads_export_{now_str}.csv"'
        writer = csv.writer(response)
        writer.writerow(['Name', 'Phone', 'Email', 'Product', 'Platform', 'Status', 'Assistant', 'Contacted', 'Username', 'Created'])
        for lead in qs:
            writer.writerow([
                lead.full_name or '',
                lead.phone_number or '',
                lead.email or '',
                lead.product or '',
                lead.platform,
                lead.status,
                lead.assistant.name if lead.assistant else '',
                'Yes' if lead.contacted else 'No',
                lead.username or '',
                lead.created_time.isoformat(),
            ])
        return response
