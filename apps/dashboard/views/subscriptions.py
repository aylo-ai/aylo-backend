from datetime import timedelta

from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics
from rest_framework.views import APIView

from apps.dashboard.filters import SubscriptionFilter
from apps.dashboard.models import AuditLog
from apps.dashboard.serializers.subscriptions import (
    DashboardSubscriptionSerializer,
    DashboardSubscriptionUpdateSerializer,
    SubscriptionExtendSerializer,
)
from apps.dashboard.views.base import get_client_ip, subscription_repr
from apps.dashboard.views.mixins import DashboardRetrieveMixin, DashboardStatsListMixin
from apps.payment.models import Subscription
from apps.shared.addons.enums import SubscriptionStatuses
from apps.shared.addons.validations import error_response, success_response
from apps.shared.pagination import StandardResultsSetPagination
from apps.shared.permissions import CanManageFinance, IsDashboardUser


class DashboardSubscriptionList(DashboardStatsListMixin, generics.ListAPIView):
    queryset = Subscription.objects.all()
    serializer_class = DashboardSubscriptionSerializer
    permission_classes = [IsDashboardUser]
    pagination_class = StandardResultsSetPagination
    filterset_class = SubscriptionFilter
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    ordering_fields = ['start_date', 'end_date', 'created_time', 'status']
    list_message = "Subscriptions retrieved successfully"

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(users__username__icontains=search).distinct()
        return queryset

    def get_list_stats(self, queryset):
        all_subs = Subscription.objects.all()
        today = timezone.now().date()
        return {
            'total': all_subs.count(),
            'active': all_subs.filter(status=SubscriptionStatuses.ACTIVE.value).count(),
            'expiring_soon': all_subs.filter(
                status=SubscriptionStatuses.ACTIVE.value,
                end_date__lte=today + timedelta(days=7),
                end_date__gte=today,
            ).count(),
            'cancelled': all_subs.filter(status=SubscriptionStatuses.CANCELLED.value).count(),
        }


class DashboardSubscriptionDetail(DashboardRetrieveMixin, generics.RetrieveUpdateDestroyAPIView):
    queryset = Subscription.objects.all()
    serializer_class = DashboardSubscriptionSerializer
    permission_classes = [IsDashboardUser]
    retrieve_message = "Subscription retrieved successfully"

    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH", "DELETE"):
            return [CanManageFinance()]
        return super().get_permissions()

    def _audit_snapshot(self, instance):
        return {
            'pricing_package': str(instance.pricing_package_id) if instance.pricing_package_id else None,
            'start_date': str(instance.start_date) if instance.start_date else None,
            'end_date': str(instance.end_date) if instance.end_date else None,
            'status': instance.status,
            'remained_request_count': instance.remained_request_count,
            'auto_renew': instance.auto_renew,
        }

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        old_data = self._audit_snapshot(instance)

        write_serializer = DashboardSubscriptionUpdateSerializer(
            instance, data=request.data, partial=True,
        )
        write_serializer.is_valid(raise_exception=True)
        instance = write_serializer.save()

        AuditLog.log(
            user=request.user, action='update', target_type='subscription',
            target_id=instance.id,
            target_repr=subscription_repr(instance),
            details={'old': old_data, 'new': self._audit_snapshot(instance), 'changes': request.data},
            ip_address=get_client_ip(request),
        )
        return success_response(
            data=self.get_serializer(instance).data,
            message="Subscription updated successfully",
            code=200,
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        AuditLog.log(
            user=request.user, action='delete', target_type='subscription',
            target_id=instance.id,
            target_repr=subscription_repr(instance),
            ip_address=get_client_ip(request),
        )
        instance.delete()
        return success_response(message="Subscription deleted successfully", code=200)


class DashboardSubscriptionCancel(APIView):
    permission_classes = [CanManageFinance]

    def post(self, request, pk):
        try:
            subscription = Subscription.objects.get(id=pk)
        except Subscription.DoesNotExist:
            return error_response(message="Subscription not found", code=404)

        reason = request.data.get('reason', '')
        subscription.status = SubscriptionStatuses.CANCELLED.value
        subscription.cancellation_reason = reason
        subscription.save(update_fields=['status', 'cancellation_reason'])

        AuditLog.log(
            user=request.user, action='cancel', target_type='subscription',
            target_id=pk, target_repr=subscription_repr(subscription),
            details={'reason': reason},
            ip_address=get_client_ip(request),
        )
        return success_response(message="Subscription cancelled", code=200)


class DashboardSubscriptionExtend(APIView):
    permission_classes = [CanManageFinance]

    def post(self, request, pk):
        try:
            subscription = Subscription.objects.get(id=pk)
        except Subscription.DoesNotExist:
            return error_response(message="Subscription not found", code=404)

        serializer = SubscriptionExtendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        days = serializer.validated_data['days']

        base_date = subscription.end_date or timezone.now().date()
        subscription.end_date = base_date + timedelta(days=days)
        subscription.status = SubscriptionStatuses.ACTIVE.value
        subscription.save(update_fields=['end_date', 'status'])

        AuditLog.log(
            user=request.user, action='extend', target_type='subscription',
            target_id=pk, target_repr=subscription_repr(subscription),
            details={'days': days, 'new_end_date': str(subscription.end_date)},
            ip_address=get_client_ip(request),
        )
        return success_response(
            data={'end_date': str(subscription.end_date)},
            message="Subscription extended",
            code=200
        )
