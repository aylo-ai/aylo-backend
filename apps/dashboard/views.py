import csv
from datetime import timedelta

from django.db.models import Count, Q
from django.http import HttpResponse
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.assistant.models import (
    Assistant,
    AssistantFileUpload,
    Conversation,
    Lead,
    Message,
    PromptTemplate,
)
from apps.assistant.serializers import (
    AssistantFileUploadSerializer,
    AssistantSerializer,
    MessageSerializer,
)
from apps.dashboard.filters import (
    AssistantFilter,
    AuditLogFilter,
    ConversationFilter,
    IntegrationFilter,
    LeadFilter,
    SubscriptionFilter,
    TransactionFilter,
    UserFilter,
)
from apps.dashboard.models import AuditLog
from apps.dashboard.serializers import (
    AssistantFileFilterSerializer,
    AuditLogSerializer,
    ChangeRoleSerializer,
    DashboardAssistantCreateSerializer,
    DashboardAssistantCreateUserSerializer,
    DashboardAssistantFileUploadSerializer,
    DashboardAssistantListSerializer,
    DashboardConversationListSerializer,
    DashboardConversationSerializer,
    DashboardEnhancedStatsSerializer,
    DashboardFeatureSerializer,
    DashboardIntegrationListSerializer,
    DashboardLeadSerializer,
    DashboardPricingPackageDetailSerializer,
    DashboardPromptTemplateSerializer,
    DashboardSendOtpLoginSerializer,
    DashboardSerializer,
    DashboardStatisticsSerializer,
    DashboardSubscriptionSerializer,
    DashboardSubscriptionUpdateSerializer,
    DashboardTransactionSerializer,
    DashboardUserListSerializer,
    DashboardUserSerializer,
    DashboardVerifyOtpLoginSerializer,
    NotificationSendSerializer,
    RefundSerializer,
    SubscriptionExtendSerializer,
    TransactionBulkActionSerializer,
    UserBulkActionSerializer,
)
from apps.integration.models import InstagramCommentResponse, Integration
from apps.integration.serializers import InstagramCommentResponseSerializer, IntegrationSerializer
from apps.payment.models import Balance, Card, Feature, PricingPackage, Subscription, Transaction
from apps.payment.serializers import (
    BalanceSerializer,
    CardSerializer,
    PricingPackageSerializer,
)
from apps.shared.addons.enums import (
    ConversationStatuses,
    PaymentStatuses,
    SenderTypes,
    SubscriptionStatuses,
    UserRoles,
)
from apps.shared.addons.validations import error_response, success_response
from apps.shared.addons.verification import send_code, verify_code_cache
from apps.shared.pagination import StandardResultsSetPagination
from apps.shared.permissions import CanManageFinance, CanManageUsers, IsAdmin, IsDashboardUser
from apps.user.models import Notification, User
from apps.user.serializers import NotificationSerializer


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0]
    return request.META.get('REMOTE_ADDR')


def subscription_repr(subscription):
    """Audit-log label for a subscription.

    `Subscription.__str__` dereferences the nullable `pricing_package` FK, so it
    raises for package-less rows; audit logging must never be what takes an
    endpoint down.
    """
    package = subscription.pricing_package
    name = package.name if package else "no package"
    return f"{name} - {subscription.start_date} - {subscription.end_date}"


# ──────────────────────────────────────────────
# AUTH
# ──────────────────────────────────────────────

class DashboardSendOtpLoginView(APIView):
    serializer_class = DashboardSendOtpLoginSerializer
    throttle_classes = (AnonRateThrottle,)

    def post(self, request, *args, **kwargs):
        from apps.shared.permissions import DASHBOARD_ROLES
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone_number = serializer.data.get("phone_number")
        user = User.objects.filter(phone_number=phone_number).first()
        if user:
            if user.user_role in DASHBOARD_ROLES:
                success, message = send_code(phone_number)
            else:
                return error_response(message="Siz admin emassiz", code=400)
        else:
            return error_response(message="Bizda bunday foydalanuvchi topilmadi", code=400)

        if success:
            return success_response(data=serializer.data, message=message, code=200)
        return error_response(message=message, code=400)


class DashboardVerifyOtpLoginView(APIView):
    serializer_class = DashboardVerifyOtpLoginSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone_number = serializer.data.get("phone_number")
        code = serializer.data.get("code")

        if phone_number:
            success, message = verify_code_cache(phone_number, code)
        else:
            return error_response(message="Telefon raqam yoki email kiritilmagan", code=400)
        if success:
            return success_response(data=serializer.data, message=message, code=200)
        return error_response(message=message, code=400)


# ──────────────────────────────────────────────
# DASHBOARD & STATISTICS
# ──────────────────────────────────────────────

class DashboardView(APIView):
    serializer_class = DashboardSerializer
    permission_classes = [IsDashboardUser]

    def get(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        return success_response(data=serializer.data, message="Dashboard data retrieved successfully", code=200)


class DashboardEnhancedStatsView(APIView):
    """Enhanced dashboard stats with period comparison, alerts, and recent activity."""
    permission_classes = [IsDashboardUser]

    def get(self, request, *args, **kwargs):
        serializer = DashboardEnhancedStatsSerializer(data={})
        serializer.is_valid(raise_exception=True)
        return success_response(
            data=serializer.to_representation(None),
            message="Enhanced dashboard stats retrieved",
            code=200
        )


class DashboardStatisticsView(APIView):
    serializer_class = DashboardStatisticsSerializer
    permission_classes = [IsDashboardUser]

    def get(self, request, *args, **kwargs):
        date_filter = request.query_params.get("date_filter")
        type_filter = request.query_params.get("type_filter")
        serializer = self.serializer_class(
            data=request.data,
            context={"date_filter": date_filter, "type_filter": type_filter}
        )
        serializer.is_valid(raise_exception=True)
        return success_response(data=serializer.data, message="Dashboard statistics retrieved successfully", code=200)


# ──────────────────────────────────────────────
# USERS
# ──────────────────────────────────────────────

class DashboardUserList(generics.ListAPIView):
    queryset = User.objects.all()
    serializer_class = DashboardUserListSerializer
    permission_classes = [IsDashboardUser]
    filterset_class = UserFilter
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["username", "email", "phone_number", 'first_name', 'last_name']
    ordering_fields = ['created_time', 'first_name', 'last_name', 'email', 'user_role']
    pagination_class = StandardResultsSetPagination

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            response = {
                "data": serializer.data,
                "total_users": queryset.count(),
                "active_users": queryset.filter(is_active=True).count(),
                "admin_users": queryset.filter(user_role__in=[UserRoles.ADMIN.value, UserRoles.SUPER_ADMIN.value]).count(),
                "customer_users": queryset.filter(user_role=UserRoles.CUSTOMER.value).count(),
            }
            return self.get_paginated_response(response)
        serializer = self.get_serializer(queryset, many=True)
        response = {
            "data": serializer.data,
            "total_users": queryset.count(),
            "active_users": queryset.filter(is_active=True).count(),
            "admin_users": queryset.filter(user_role__in=[UserRoles.ADMIN.value, UserRoles.SUPER_ADMIN.value]).count(),
            "customer_users": queryset.filter(user_role=UserRoles.CUSTOMER.value).count(),
        }
        return success_response(data=response, message="Users retrieved successfully", code=200)


class DashboardUserDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = User.objects.all()
    serializer_class = DashboardUserSerializer
    permission_classes = [IsDashboardUser]

    def get_queryset(self):
        pk = self.kwargs.get("pk")
        return User.objects.filter(id=pk)

    def retrieve(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_object())
        return success_response(data=serializer.data, message="User retrieved successfully", code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=kwargs.get('partial', False))
        serializer.is_valid(raise_exception=True)
        serializer.save()
        AuditLog.log(
            user=request.user, action='update', target_type='user',
            target_id=instance.id,
            target_repr=str(instance),
            details={'changes': request.data},
            ip_address=get_client_ip(request),
        )
        return success_response(data=serializer.data, message="User updated successfully", code=200)

    def destroy(self, request, *args, **kwargs):
        user = self.get_object()
        AuditLog.log(
            user=request.user, action='delete', target_type='user',
            target_id=self.kwargs.get("pk"),
            target_repr=str(user),
            ip_address=get_client_ip(request),
        )
        user.delete()
        return success_response(message="User deleted successfully", code=200)


class DashboardUserToggleActive(APIView):
    permission_classes = [CanManageUsers]

    def post(self, request, pk):
        try:
            user = User.objects.get(id=pk)
        except User.DoesNotExist:
            return error_response(message="User not found", code=404)

        user.is_active = not user.is_active
        user.save(update_fields=['is_active'])

        AuditLog.log(
            user=request.user,
            action='block' if not user.is_active else 'unblock',
            target_type='user',
            target_id=pk,
            target_repr=str(user),
            details={'is_active': user.is_active},
            ip_address=get_client_ip(request),
        )
        return success_response(
            data={'is_active': user.is_active},
            message=f"User {'activated' if user.is_active else 'deactivated'} successfully",
            code=200
        )


class DashboardUserChangeRole(APIView):
    permission_classes = [CanManageUsers]

    def post(self, request, pk):
        try:
            user = User.objects.get(id=pk)
        except User.DoesNotExist:
            return error_response(message="User not found", code=404)

        serializer = ChangeRoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        old_role = user.user_role
        user.user_role = serializer.validated_data['user_role']
        user.save(update_fields=['user_role'])

        AuditLog.log(
            user=request.user, action='change_role', target_type='user',
            target_id=pk, target_repr=str(user),
            details={'old_role': old_role, 'new_role': user.user_role},
            ip_address=get_client_ip(request),
        )
        return success_response(
            data={'user_role': user.user_role},
            message="User role changed successfully",
            code=200
        )


class DashboardUserExport(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        qs = User.objects.all().order_by('-created_time')

        # Apply filters from query params. An invalid filter must fail loudly:
        # silently dropping it would export every user instead of the subset
        # the operator asked for.
        filterset = UserFilter(request.query_params, queryset=qs)
        if not filterset.is_valid():
            return error_response(data=filterset.errors, message="Invalid filter parameters", code=400)
        qs = filterset.qs

        # Apply search
        search = request.query_params.get('search', '')
        if search:
            qs = qs.filter(
                Q(username__icontains=search) |
                Q(email__icontains=search) |
                Q(phone_number__icontains=search) |
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search)
            )

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="users_export.csv"'
        writer = csv.writer(response)
        writer.writerow(['ID', 'Username', 'First Name', 'Last Name', 'Phone', 'Email', 'Role', 'Active', 'Created'])
        for u in qs:
            writer.writerow([
                str(u.id), u.username, u.first_name, u.last_name,
                u.phone_number, u.email, u.user_role, u.is_active,
                u.created_time.isoformat()
            ])
        AuditLog.log(
            user=request.user, action='export', target_type='user',
            details={'count': qs.count(), 'filters': dict(request.query_params)},
            ip_address=get_client_ip(request),
        )
        return response


# ──────────────────────────────────────────────
# ASSISTANTS
# ──────────────────────────────────────────────

class DashboardAssistantList(generics.ListCreateAPIView):
    queryset = Assistant.objects.select_related('user').all()
    serializer_class = DashboardAssistantListSerializer
    permission_classes = [IsDashboardUser]
    pagination_class = StandardResultsSetPagination
    filterset_class = AssistantFilter
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "user__username", "user__phone_number", "user__email", "company_name"]
    ordering_fields = ['name', 'created_time', 'company_name', 'is_active', 'language', 'personality_style']

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return DashboardAssistantCreateSerializer
        return DashboardAssistantListSerializer

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        # Global stats (independent of pagination/filters)
        all_assistants = Assistant.objects.all()
        total_count = all_assistants.count()
        active_count = all_assistants.filter(is_active=True).count()
        ai_enabled_count = all_assistants.filter(ai_enabled=True).count()
        with_integrations_count = all_assistants.filter(
            integrations__isnull=False
        ).distinct().count()

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            response = self.get_paginated_response(serializer.data)
            response.data['stats'] = {
                'total': total_count,
                'active': active_count,
                'ai_enabled': ai_enabled_count,
                'with_integrations': with_integrations_count,
            }
            return response
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data, message="Assistants retrieved successfully", code=200)

    def create(self, request, *args, **kwargs):
        user_serializer = DashboardAssistantCreateUserSerializer(data=request.data)
        user_serializer.is_valid(raise_exception=True)
        try:
            target_user = User.objects.get(id=user_serializer.validated_data['user'])
        except User.DoesNotExist:
            return error_response(message="User not found", code=404)

        serializer = DashboardAssistantCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        assistant = serializer.save(user=target_user, created_by=request.user)

        AuditLog.log(
            user=request.user, action='create', target_type='assistant',
            target_id=assistant.id, target_repr=assistant.name,
            details={'user': str(target_user.id), 'data': request.data},
            ip_address=get_client_ip(request),
        )
        return success_response(data=AssistantSerializer(assistant).data, message="Assistant created successfully", code=201)


class DashboardAssistantDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Assistant.objects.all()
    serializer_class = AssistantSerializer
    permission_classes = [IsDashboardUser]

    def get_queryset(self):
        pk = self.kwargs.get("pk")
        return Assistant.objects.filter(id=pk)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        AuditLog.log(
            user=request.user, action='update', target_type='assistant',
            target_id=instance.id, target_repr=instance.name,
            details={'changes': request.data},
            ip_address=get_client_ip(request),
        )
        return success_response(data=serializer.data, message="Assistant updated successfully", code=200)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        AuditLog.log(
            user=request.user, action='delete', target_type='assistant',
            target_id=instance.id, target_repr=instance.name,
            ip_address=get_client_ip(request),
        )
        instance.delete()
        return success_response(message="Assistant deleted successfully", code=200)


class DashboardAssistantToggleActive(APIView):
    permission_classes = [IsAdmin]

    def post(self, request, pk):
        try:
            assistant = Assistant.objects.get(id=pk)
        except Assistant.DoesNotExist:
            return error_response(message="Assistant not found", code=404)

        assistant.is_active = not assistant.is_active
        assistant.save(update_fields=['is_active'])

        AuditLog.log(
            user=request.user,
            action='activate' if assistant.is_active else 'deactivate',
            target_type='assistant',
            target_id=pk, target_repr=assistant.name,
            details={'is_active': assistant.is_active},
            ip_address=get_client_ip(request),
        )
        return success_response(
            data={'is_active': assistant.is_active},
            message=f"Assistant {'activated' if assistant.is_active else 'deactivated'}",
            code=200
        )


# ──────────────────────────────────────────────
# CONVERSATIONS
# ──────────────────────────────────────────────

class DashboardConversationList(generics.ListAPIView):
    queryset = Conversation.objects.select_related('assistant', 'assistant__user').all()
    serializer_class = DashboardConversationListSerializer
    permission_classes = [IsDashboardUser]
    filterset_class = ConversationFilter
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    # `client_full_name` / `client_phone_email` are encrypted at rest and
    # cannot be matched in SQL; `username` still covers the common case.
    search_fields = ['username', 'assistant__name']
    ordering_fields = ['created_time', 'updated_time', 'status', 'platform']
    pagination_class = StandardResultsSetPagination

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        all_convos = Conversation.objects.all()
        stats = {
            'total': all_convos.count(),
            'open': all_convos.filter(status=ConversationStatuses.OPEN.value).count(),
            'escalated': all_convos.filter(status=ConversationStatuses.ESCALATED.value).count(),
            'total_messages': Message.objects.count(),
        }

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            response = self.get_paginated_response(serializer.data)
            response.data['stats'] = stats
            return response
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data, message="Conversations retrieved successfully", code=200)


class DashboardConversationDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Conversation.objects.all()
    serializer_class = DashboardConversationSerializer
    permission_classes = [IsDashboardUser]

    def get_queryset(self):
        pk = self.kwargs.get("pk")
        return Conversation.objects.filter(id=pk)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message="Conversation updated successfully", code=200)

    def destroy(self, request, *args, **kwargs):
        self.get_object().delete()
        return success_response(message="Conversation deleted successfully", code=200)


class DashboardConversationClose(APIView):
    permission_classes = [IsDashboardUser]

    def post(self, request, pk):
        try:
            conversation = Conversation.objects.get(id=pk)
        except Conversation.DoesNotExist:
            return error_response(message="Conversation not found", code=404)

        conversation.status = ConversationStatuses.CLOSED.value
        conversation.end_time = timezone.now()
        conversation.save(update_fields=['status', 'end_time'])

        AuditLog.log(
            user=request.user, action='close', target_type='conversation',
            target_id=pk, target_repr=str(conversation),
            ip_address=get_client_ip(request),
        )
        return success_response(message="Conversation closed", code=200)


class DashboardConversationEscalate(APIView):
    permission_classes = [IsDashboardUser]

    def post(self, request, pk):
        try:
            conversation = Conversation.objects.get(id=pk)
        except Conversation.DoesNotExist:
            return error_response(message="Conversation not found", code=404)

        conversation.status = ConversationStatuses.ESCALATED.value
        conversation.save(update_fields=['status'])

        AuditLog.log(
            user=request.user, action='escalate', target_type='conversation',
            target_id=pk, target_repr=str(conversation),
            ip_address=get_client_ip(request),
        )
        return success_response(message="Conversation escalated", code=200)


# ──────────────────────────────────────────────
# TRANSACTIONS
# ──────────────────────────────────────────────

class DashboardTransactionList(generics.ListAPIView):
    queryset = Transaction.objects.select_related('user').all()
    serializer_class = DashboardTransactionSerializer
    permission_classes = [IsDashboardUser]
    filterset_class = TransactionFilter
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    pagination_class = StandardResultsSetPagination
    search_fields = ["user__username", "user__email", "user__phone_number", "user__first_name", "user__last_name"]
    ordering_fields = ['amount', 'created_time', 'status', 'payment_method']

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        from django.db.models import Sum
        all_txns = Transaction.objects.all()
        successful = all_txns.filter(status=PaymentStatuses.SUCCESS.value)
        stats = {
            'total': all_txns.count(),
            'successful_total': float(successful.aggregate(total=Sum('amount'))['total'] or 0),
            'successful_count': successful.count(),
            'failed': all_txns.filter(status=PaymentStatuses.FAILED.value).count(),
        }

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            response = self.get_paginated_response(serializer.data)
            response.data['stats'] = stats
            return response
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data, message="Transactions retrieved successfully", code=200)


class DashboardTransactionDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Transaction.objects.all()
    serializer_class = DashboardTransactionSerializer
    permission_classes = [IsDashboardUser]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data, message="Transaction retrieved successfully", code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message="Transaction updated successfully", code=200)

    def destroy(self, request, *args, **kwargs):
        self.get_object().delete()
        return success_response(message="Transaction deleted successfully", code=200)


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


# ──────────────────────────────────────────────
# SUBSCRIPTIONS
# ──────────────────────────────────────────────

class DashboardSubscriptionList(generics.ListAPIView):
    queryset = Subscription.objects.all()
    serializer_class = DashboardSubscriptionSerializer
    permission_classes = [IsDashboardUser]
    pagination_class = StandardResultsSetPagination
    filterset_class = SubscriptionFilter
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    ordering_fields = ['start_date', 'end_date', 'created_time', 'status']

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(users__username__icontains=search).distinct()
        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        all_subs = Subscription.objects.all()
        today = timezone.now().date()
        stats = {
            'total': all_subs.count(),
            'active': all_subs.filter(status=SubscriptionStatuses.ACTIVE.value).count(),
            'expiring_soon': all_subs.filter(
                status=SubscriptionStatuses.ACTIVE.value,
                end_date__lte=today + timedelta(days=7),
                end_date__gte=today,
            ).count(),
            'cancelled': all_subs.filter(status=SubscriptionStatuses.CANCELLED.value).count(),
        }

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            response = self.get_paginated_response(serializer.data)
            response.data['stats'] = stats
            return response
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data, message="Subscriptions retrieved successfully", code=200)


class DashboardSubscriptionDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Subscription.objects.all()
    serializer_class = DashboardSubscriptionSerializer
    permission_classes = [IsDashboardUser]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data, message="Subscription retrieved successfully", code=200)

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

        # Every field goes through the serializer: a bad UUID, an unknown
        # package or a non-numeric counter is a 400, never a stored value.
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


# ──────────────────────────────────────────────
# INTEGRATIONS
# ──────────────────────────────────────────────

class DashboardIntegrationList(generics.ListAPIView):
    queryset = Integration.objects.select_related('assistant', 'assistant__user', 'user').all()
    serializer_class = DashboardIntegrationListSerializer
    permission_classes = [IsDashboardUser]
    filterset_class = IntegrationFilter
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    pagination_class = StandardResultsSetPagination
    search_fields = ["name", "assistant__name", "assistant__user__username", "assistant__company_name", "integration_type"]
    ordering_fields = ['name', 'created_time', 'integration_type', 'is_active']

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        all_integrations = Integration.objects.all()
        stats = {
            'total': all_integrations.count(),
            'active': all_integrations.filter(is_active=True).count(),
            'total_conversations': Conversation.objects.filter(
                assistant__integrations__isnull=False
            ).distinct().count(),
            'total_leads': Lead.objects.filter(
                assistant__integrations__isnull=False
            ).distinct().count(),
        }

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            response = self.get_paginated_response(serializer.data)
            response.data['stats'] = stats
            return response
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data, message="Integrations retrieved successfully", code=200)


class DashboardIntegrationDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Integration.objects.all()
    serializer_class = IntegrationSerializer
    permission_classes = [IsDashboardUser]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data, message="Integration retrieved successfully", code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message="Integration updated successfully", code=200)

    def destroy(self, request, *args, **kwargs):
        self.get_object().delete()
        return success_response(message="Integration deleted successfully", code=200)


# ──────────────────────────────────────────────
# LEADS
# ──────────────────────────────────────────────

class DashboardLeadList(generics.ListAPIView):
    queryset = Lead.objects.select_related('assistant').all()
    serializer_class = DashboardLeadSerializer
    permission_classes = [IsDashboardUser]
    filterset_class = LeadFilter
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['full_name', 'phone_number', 'email', 'product', 'username']
    ordering_fields = ['created_time', 'status', 'full_name']
    pagination_class = StandardResultsSetPagination

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data, message="Leads retrieved successfully", code=200)


class DashboardLeadDetail(generics.RetrieveUpdateAPIView):
    queryset = Lead.objects.all()
    serializer_class = DashboardLeadSerializer
    permission_classes = [IsDashboardUser]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data, message="Lead retrieved successfully", code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message="Lead updated successfully", code=200)


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


# ──────────────────────────────────────────────
# AUDIT LOGS
# ──────────────────────────────────────────────

class DashboardAuditLogList(generics.ListAPIView):
    queryset = AuditLog.objects.select_related('user').all()
    serializer_class = AuditLogSerializer
    permission_classes = [IsAdmin]
    filterset_class = AuditLogFilter
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['target_repr', 'action', 'target_type']
    ordering_fields = ['created_time', 'action', 'target_type']
    pagination_class = StandardResultsSetPagination

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data, message="Audit logs retrieved successfully", code=200)


# ──────────────────────────────────────────────
# MESSAGES
# ──────────────────────────────────────────────

class DashboardMessageList(generics.ListAPIView):
    queryset = Message.objects.all()
    serializer_class = MessageSerializer
    permission_classes = [IsDashboardUser]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    pagination_class = StandardResultsSetPagination

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data, message="Messages retrieved successfully", code=200)


# ──────────────────────────────────────────────
# OTHER EXISTING VIEWS (kept for backward compat)
# ──────────────────────────────────────────────

class DashboardCommentResponseList(generics.ListAPIView):
    queryset = InstagramCommentResponse.objects.all()
    serializer_class = InstagramCommentResponseSerializer
    permission_classes = [IsDashboardUser]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    pagination_class = StandardResultsSetPagination

    def list(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset(), many=True)
        return success_response(data=serializer.data, message="Comment responses retrieved successfully", code=200)


class DashboardNotificationList(generics.ListAPIView):
    queryset = Notification.objects.all()
    serializer_class = NotificationSerializer
    permission_classes = [IsDashboardUser]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    pagination_class = StandardResultsSetPagination

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data, message="Notifications retrieved successfully", code=200)


class DashboardBalanceList(generics.ListAPIView):
    queryset = Balance.objects.all()
    serializer_class = BalanceSerializer
    permission_classes = [IsDashboardUser]
    pagination_class = StandardResultsSetPagination

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data, message="Balances retrieved successfully", code=200)


class DashboardAssistantFileUploadList(generics.ListCreateAPIView):
    queryset = AssistantFileUpload.objects.all()
    serializer_class = DashboardAssistantFileUploadSerializer
    permission_classes = [IsDashboardUser]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        queryset = super().get_queryset()
        assistant_id = self.request.query_params.get('assistant')
        if assistant_id:
            # A raw, unvalidated UUID reaching the ORM is a 500, not a 400.
            filter_serializer = AssistantFileFilterSerializer(data={'assistant': assistant_id})
            filter_serializer.is_valid(raise_exception=True)
            queryset = queryset.filter(assistant_id=filter_serializer.validated_data['assistant'])
        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data, message="Assistant file uploads retrieved successfully", code=200)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        AuditLog.log(
            user=request.user, action='create', target_type='assistant_file',
            target_id=instance.id, target_repr=str(instance),
            details={'assistant': str(request.data.get('assistant'))},
            ip_address=get_client_ip(request),
        )
        return success_response(data=serializer.data, message="File uploaded successfully", code=201)


class DashboardAssistantFileUploadDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = AssistantFileUpload.objects.all()
    serializer_class = AssistantFileUploadSerializer
    permission_classes = [IsDashboardUser]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data, message="File retrieved", code=200)

    def destroy(self, request, *args, **kwargs):
        self.get_object().delete()
        return success_response(message="File deleted", code=200)


# ──────────────────────────────────────────────
# SYSTEM HEALTH
# ──────────────────────────────────────────────

class DashboardSystemHealthView(APIView):
    """System health check — DB, Redis, Celery."""
    permission_classes = [IsAdmin]

    def get(self, request, *args, **kwargs):
        import redis as redis_lib
        from django.conf import settings
        from django.db import connection

        health = {
            'database': {'status': 'unknown', 'detail': ''},
            'redis': {'status': 'unknown', 'detail': ''},
            'celery': {'status': 'unknown', 'detail': ''},
            'storage': {'status': 'unknown', 'detail': ''},
        }

        # Database check
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            health['database'] = {'status': 'healthy', 'detail': 'PostgreSQL connected'}
        except Exception as e:
            health['database'] = {'status': 'unhealthy', 'detail': str(e)}

        # Redis check
        try:
            r = redis_lib.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                password=settings.REDIS_PASSWORD,
                socket_timeout=3,
            )
            r.ping()
            info = r.info('memory')
            used_memory = info.get('used_memory_human', 'N/A')
            health['redis'] = {'status': 'healthy', 'detail': f'Connected, memory: {used_memory}'}
        except Exception as e:
            health['redis'] = {'status': 'unhealthy', 'detail': str(e)}

        # Celery check
        try:
            from config.celery import app as celery_app
            inspector = celery_app.control.inspect(timeout=3)
            active = inspector.active()
            if active is not None:
                worker_count = len(active)
                task_count = sum(len(tasks) for tasks in active.values())
                health['celery'] = {
                    'status': 'healthy',
                    'detail': f'{worker_count} worker(s), {task_count} active task(s)',
                    'workers': list(active.keys()),
                }
            else:
                health['celery'] = {'status': 'unhealthy', 'detail': 'No workers responding'}
        except Exception as e:
            health['celery'] = {'status': 'unhealthy', 'detail': str(e)}

        # Storage check
        try:
            from django.core.files.storage import default_storage
            health['storage'] = {'status': 'healthy', 'detail': type(default_storage).__name__}
        except Exception as e:
            health['storage'] = {'status': 'unhealthy', 'detail': str(e)}

        overall = 'healthy' if all(s['status'] == 'healthy' for s in health.values()) else 'degraded'
        return success_response(
            data={'overall': overall, 'services': health},
            message='System health check completed',
            code=200
        )


# ──────────────────────────────────────────────
# AI COST BREAKDOWN
# ──────────────────────────────────────────────

class DashboardAICostBreakdownView(APIView):
    """AI cost breakdown by assistant and model."""
    permission_classes = [IsDashboardUser]

    def get(self, request, *args, **kwargs):
        from django.db.models import Count, F, Sum

        period = request.query_params.get('period', '30d')
        now = timezone.now().date()
        if period == '7d':
            start = now - timezone.timedelta(days=7)
        elif period == '6m':
            start = now - timezone.timedelta(days=180)
        elif period == '1y':
            start = now - timezone.timedelta(days=365)
        elif period == 'all':
            start = None
        else:
            start = now - timezone.timedelta(days=30)

        qs = Message.objects.filter(sender=SenderTypes.ASSISTANT.value)
        if start:
            qs = qs.filter(created_time__date__gte=start)

        by_assistant = (
            qs.values(
                assistant_name=F('conversation__assistant__name'),
                assistant_id=F('conversation__assistant__id'),
            )
            .annotate(
                total_input_tokens=Sum('input_tokens'),
                total_output_tokens=Sum('output_tokens'),
                message_count=Count('id'),
            )
            .order_by('-total_input_tokens')
        )

        results = []
        for row in by_assistant:
            inp = row['total_input_tokens'] or 0
            out = row['total_output_tokens'] or 0
            cost = (inp / 1000000 * 2.5) + (out / 1000000 * 10)
            results.append({
                'assistant_id': str(row['assistant_id']),
                'assistant_name': row['assistant_name'],
                'input_tokens': inp,
                'output_tokens': out,
                'message_count': row['message_count'],
                'estimated_cost': f'${cost:.2f}',
            })

        total_input = sum(r['input_tokens'] for r in results)
        total_output = sum(r['output_tokens'] for r in results)
        total_cost = (total_input / 1000000 * 2.5) + (total_output / 1000000 * 10)

        return success_response(
            data={
                'period': period,
                'total_input_tokens': total_input,
                'total_output_tokens': total_output,
                'total_estimated_cost': f'${total_cost:.2f}',
                'by_assistant': results,
            },
            message='AI cost breakdown retrieved',
            code=200
        )


# ──────────────────────────────────────────────
# BULK ACTIONS
# ──────────────────────────────────────────────

class DashboardUserBulkAction(APIView):
    permission_classes = [CanManageUsers]

    def post(self, request):
        serializer = UserBulkActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action = serializer.validated_data['action']
        ids = serializer.validated_data['ids']

        users = User.objects.filter(id__in=ids)
        count = users.count()

        if action == 'activate':
            users.update(is_active=True)
        elif action == 'deactivate':
            users.update(is_active=False)
        elif action == 'delete':
            users.delete()
        elif action == 'change_role':
            users.update(user_role=serializer.validated_data['role'])

        AuditLog.log(
            user=request.user, action=f'bulk_{action}', target_type='user',
            details={'ids': [str(i) for i in ids], 'count': count},
            ip_address=get_client_ip(request),
        )
        return success_response(
            data={'affected': count},
            message=f'Bulk {action} completed for {count} users',
            code=200
        )


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


# ──────────────────────────────────────────────
# NOTIFICATION SEND
# ──────────────────────────────────────────────

class DashboardNotificationSend(APIView):
    permission_classes = [IsAdmin]

    def post(self, request):
        serializer = NotificationSendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            target_user = User.objects.get(id=data['user_id'])
        except User.DoesNotExist:
            return error_response(message='User not found', code=404)

        notification = Notification.objects.create(
            user=target_user,
            title=data['title'],
            content=data['content'],
            type=data['type'],
        )

        AuditLog.log(
            user=request.user, action='send_notification', target_type='notification',
            target_id=notification.id, target_repr=data['title'],
            details={'user_id': str(data['user_id'])},
            ip_address=get_client_ip(request),
        )
        return success_response(message='Notification sent', code=201)


# ──────────────────────────────────────────────
# GLOBAL SEARCH
# ──────────────────────────────────────────────

class DashboardGlobalSearch(APIView):
    """Search across users, assistants, conversations, transactions."""
    permission_classes = [IsDashboardUser]

    def get(self, request):
        q = request.query_params.get('q', '').strip()
        if len(q) < 2:
            return success_response(data={'results': []}, message='Query too short', code=200)

        from django.db.models import Q
        results = []

        # Users
        users = User.objects.filter(
            Q(username__icontains=q) | Q(first_name__icontains=q) |
            Q(last_name__icontains=q) | Q(email__icontains=q) |
            Q(phone_number__icontains=q)
        )[:5]
        for u in users:
            results.append({
                'type': 'user',
                'id': str(u.id),
                'title': f'{u.first_name or ""} {u.last_name or ""}'.strip() or u.username,
                'subtitle': u.email or u.phone_number,
                'url': f'/users/{u.id}',
            })

        # Assistants
        assistants = Assistant.objects.filter(
            Q(name__icontains=q) | Q(company_name__icontains=q)
        )[:5]
        for a in assistants:
            results.append({
                'type': 'assistant',
                'id': str(a.id),
                'title': a.name,
                'subtitle': a.company_name,
                'url': f'/assistants/{a.id}',
            })

        # Conversations
        # `client_full_name` is encrypted at rest — not matchable in SQL.
        conversations = Conversation.objects.filter(
            Q(username__icontains=q) | Q(assistant__name__icontains=q)
        )[:5]
        for c in conversations:
            results.append({
                'type': 'conversation',
                'id': str(c.id),
                'title': c.client_full_name or c.username or 'Unknown',
                'subtitle': f'{c.assistant.name} - {c.platform}',
                'url': f'/conversations/{c.id}',
            })

        # Transactions (by user name or amount)
        transactions = Transaction.objects.filter(
            Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q) |
            Q(user__email__icontains=q) | Q(transaction_id__icontains=q)
        )[:5]
        for t in transactions:
            results.append({
                'type': 'transaction',
                'id': str(t.id),
                'title': f'{t.amount} {t.currency} - {t.status}',
                'subtitle': t.user.username if t.user else 'Unknown',
                'url': '/transactions',
            })

        return success_response(data={'results': results}, message='Search completed', code=200)


class DashboardCardList(generics.ListAPIView):
    queryset = Card.objects.all()
    serializer_class = CardSerializer
    permission_classes = [IsDashboardUser]
    pagination_class = StandardResultsSetPagination

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data, message="Cards retrieved successfully", code=200)


class DashboardFeatureList(generics.ListCreateAPIView):
    queryset = Feature.objects.all()
    serializer_class = DashboardFeatureSerializer
    permission_classes = [IsDashboardUser]
    pagination_class = StandardResultsSetPagination

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data, message="Features retrieved successfully", code=200)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message="Feature created", code=201)


class DashboardFeatureDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Feature.objects.all()
    serializer_class = DashboardFeatureSerializer
    permission_classes = [IsDashboardUser]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data, message="Feature retrieved", code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message="Feature updated", code=200)

    def destroy(self, request, *args, **kwargs):
        self.get_object().delete()
        return success_response(message="Feature deleted", code=200)


class DashboardPricingPackageList(generics.ListCreateAPIView):
    queryset = PricingPackage.objects.prefetch_related('features').all()
    serializer_class = DashboardPricingPackageDetailSerializer
    permission_classes = [IsAdmin]
    pagination_class = StandardResultsSetPagination

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data, message="Pricing packages retrieved successfully", code=200)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message="Pricing package created", code=201)


class DashboardPricingPackageDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = PricingPackage.objects.prefetch_related('features').all()
    serializer_class = DashboardPricingPackageDetailSerializer
    permission_classes = [IsAdmin]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data, message="Pricing package retrieved", code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = PricingPackageSerializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        AuditLog.log(
            user=request.user, action='update', target_type='pricing_package',
            target_id=instance.id, target_repr=instance.name,
            details={'changes': request.data},
            ip_address=get_client_ip(request),
        )
        return success_response(data=DashboardPricingPackageDetailSerializer(instance).data, message="Pricing package updated", code=200)

    def destroy(self, request, *args, **kwargs):
        self.get_object().delete()
        return success_response(message="Pricing package deleted", code=200)


class DashboardPromptTemplateList(generics.ListCreateAPIView):
    queryset = PromptTemplate.objects.all()
    serializer_class = DashboardPromptTemplateSerializer
    permission_classes = [IsDashboardUser]
    pagination_class = StandardResultsSetPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'description']

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data, message="Prompt templates retrieved successfully", code=200)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message="Prompt template created successfully", code=201)


class DashboardPromptTemplateDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = PromptTemplate.objects.all()
    serializer_class = DashboardPromptTemplateSerializer
    permission_classes = [IsDashboardUser]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data, message="Prompt template retrieved successfully", code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(data=serializer.data, message="Prompt template updated successfully", code=200)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return success_response(message="Prompt template deleted successfully", code=200)
