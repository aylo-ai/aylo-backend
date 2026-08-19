from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics
from rest_framework.views import APIView

from apps.assistant.models import Conversation, Message
from apps.assistant.serializers import MessageSerializer
from apps.dashboard.filters import ConversationFilter
from apps.dashboard.models import AuditLog
from apps.dashboard.serializers.conversations import (
    DashboardConversationListSerializer,
    DashboardConversationSerializer,
)
from apps.dashboard.views.base import get_client_ip
from apps.dashboard.views.mixins import (
    DashboardDestroyMixin,
    DashboardListMixin,
    DashboardPartialUpdateMixin,
    DashboardStatsListMixin,
)
from apps.shared.addons.enums import ConversationStatuses
from apps.shared.addons.validations import error_response, success_response
from apps.shared.pagination import StandardResultsSetPagination
from apps.shared.permissions import IsDashboardUser


class DashboardConversationList(DashboardStatsListMixin, generics.ListAPIView):
    queryset = Conversation.objects.select_related('assistant', 'assistant__user').all()
    serializer_class = DashboardConversationListSerializer
    permission_classes = [IsDashboardUser]
    filterset_class = ConversationFilter
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['username', 'client_full_name', 'client_phone_email', 'assistant__name']
    ordering_fields = ['created_time', 'updated_time', 'status', 'platform']
    pagination_class = StandardResultsSetPagination
    list_message = "Conversations retrieved successfully"

    def get_list_stats(self, queryset):
        all_convos = Conversation.objects.all()
        return {
            'total': all_convos.count(),
            'open': all_convos.filter(status=ConversationStatuses.OPEN.value).count(),
            'escalated': all_convos.filter(status=ConversationStatuses.ESCALATED.value).count(),
            'total_messages': Message.objects.count(),
        }


class DashboardConversationDetail(
    DashboardPartialUpdateMixin,
    DashboardDestroyMixin,
    generics.RetrieveUpdateDestroyAPIView,
):
    queryset = Conversation.objects.all()
    serializer_class = DashboardConversationSerializer
    permission_classes = [IsDashboardUser]
    update_message = "Conversation updated successfully"
    destroy_message = "Conversation deleted successfully"

    def get_queryset(self):
        pk = self.kwargs.get("pk")
        return Conversation.objects.filter(id=pk)


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


class DashboardMessageList(DashboardListMixin, generics.ListAPIView):
    queryset = Message.objects.all()
    serializer_class = MessageSerializer
    permission_classes = [IsDashboardUser]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    pagination_class = StandardResultsSetPagination
    list_message = "Messages retrieved successfully"
