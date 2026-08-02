"""Dashboard transaction endpoints."""
import csv

from django.db.models import Q, Sum
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import generics, filters
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend

from apps.payment.models import Transaction
from apps.shared.permissions import IsAdmin, IsDashboardUser, CanManageFinance
from apps.shared.addons.enums import PaymentStatuses
from apps.shared.pagination import StandardResultsSetPagination
from apps.dashboard.filters import TransactionFilter
from apps.dashboard.models import AuditLog
from apps.dashboard.serializers.transactions import (
    DashboardTransactionSerializer,
    RefundSerializer,
    TransactionBulkActionSerializer,
)
from apps.dashboard.views.base import get_client_ip
from apps.dashboard.views.mixins import (
    DashboardDestroyMixin,
    DashboardPartialUpdateMixin,
    DashboardRetrieveMixin,
    DashboardStatsListMixin,
)
from apps.shared.addons.validations import success_response, error_response


class DashboardTransactionList(DashboardStatsListMixin, generics.ListAPIView):
    queryset = Transaction.objects.select_related('user').all()
    serializer_class = DashboardTransactionSerializer
    permission_classes = [IsDashboardUser]
    filterset_class = TransactionFilter
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    pagination_class = StandardResultsSetPagination
    search_fields = ["user__username", "user__email", "user__phone_number", "user__first_name", "user__last_name"]
    ordering_fields = ['amount', 'created_time', 'status', 'payment_method']
    list_message = "Transactions retrieved successfully"

    def get_list_stats(self, queryset):
        all_txns = Transaction.objects.all()
        successful = all_txns.filter(status=PaymentStatuses.SUCCESS.value)
        return {
            'total': all_txns.count(),
            'successful_total': float(successful.aggregate(total=Sum('amount'))['total'] or 0),
            'successful_count': successful.count(),
            'failed': all_txns.filter(status=PaymentStatuses.FAILED.value).count(),
        }


class DashboardTransactionDetail(
    DashboardRetrieveMixin,
    DashboardPartialUpdateMixin,
    DashboardDestroyMixin,
    generics.RetrieveUpdateDestroyAPIView,
):
    queryset = Transaction.objects.all()
    serializer_class = DashboardTransactionSerializer
    permission_classes = [IsDashboardUser]
    retrieve_message = "Transaction retrieved successfully"
    update_message = "Transaction updated successfully"
    destroy_message = "Transaction deleted successfully"

    def get_permissions(self):
        # PUT/PATCH/DELETE rewrite or erase a financial record — the same
        # ground the CanManageFinance-gated refund endpoint covers — so it
        # must not be reachable by every dashboard role.
        if self.request.method in ("PUT", "PATCH", "DELETE"):
            return [CanManageFinance()]
        return super().get_permissions()


class DashboardTransactionRefund(APIView):
    permission_classes = [CanManageFinance]

    def post(self, request, pk):
        try:
            transaction = Transaction.objects.get(id=pk)
        except Transaction.DoesNotExist:
            return error_response(message="Transaction not found", code=404)

        if transaction.status != PaymentStatuses.SUCCESS.value:
            return error_response(message="Only successful transactions can be refunded", code=400)

        serializer = RefundSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        refund_amount = serializer.validated_data.get('amount', transaction.amount)
        if refund_amount > transaction.amount:
            return error_response(message="Refund amount cannot exceed transaction amount", code=400)

        transaction.status = PaymentStatuses.REFUNDED.value
        transaction.refund_amount = refund_amount
        transaction.refund_date = timezone.now()
        transaction.save(update_fields=['status', 'refund_amount', 'refund_date'])

        AuditLog.log(
            user=request.user, action='refund', target_type='transaction',
            target_id=pk, target_repr=str(transaction),
            details={
                'refund_amount': float(refund_amount),
                'reason': serializer.validated_data.get('reason', ''),
            },
            ip_address=get_client_ip(request),
        )
        return success_response(message="Transaction refunded successfully", code=200)


class DashboardTransactionExport(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        qs = Transaction.objects.select_related('user').all().order_by('-created_time')

        # Same filter + search contract as the transactions list endpoint.
        filterset = TransactionFilter(request.query_params, queryset=qs)
        if not filterset.is_valid():
            return error_response(data=filterset.errors, message="Invalid filter parameters", code=400)
        qs = filterset.qs

        search = request.query_params.get('search', '')
        if search:
            qs = qs.filter(
                Q(user__username__icontains=search) |
                Q(user__email__icontains=search) |
                Q(user__phone_number__icontains=search) |
                Q(user__first_name__icontains=search) |
                Q(user__last_name__icontains=search)
            )

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="transactions_export.csv"'
        writer = csv.writer(response)
        writer.writerow(['ID', 'User', 'Amount', 'Currency', 'Status', 'Method', 'Type', 'Created'])
        for t in qs:
            writer.writerow([
                str(t.id),
                t.user.username if t.user else '',
                float(t.amount), t.currency, t.status,
                t.payment_method, t.transaction_type,
                t.created_time.isoformat()
            ])
        return response


class DashboardTransactionBulkAction(APIView):
    permission_classes = [CanManageFinance]

    def post(self, request):
        serializer = TransactionBulkActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action = serializer.validated_data['action']
        ids = serializer.validated_data['ids']

        transactions = Transaction.objects.filter(id__in=ids)
        count = transactions.filter(status=PaymentStatuses.SUCCESS.value).update(
            status=PaymentStatuses.REFUNDED.value,
            refund_date=timezone.now(),
        )

        AuditLog.log(
            user=request.user, action=f'bulk_{action}', target_type='transaction',
            details={'ids': [str(i) for i in ids], 'count': count},
            ip_address=get_client_ip(request),
        )
        return success_response(
            data={'affected': count},
            message=f'Bulk {action} completed for {count} transactions',
            code=200
        )
