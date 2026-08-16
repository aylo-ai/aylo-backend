"""Dashboard notification endpoints."""
from rest_framework import filters, generics
from rest_framework.views import APIView

from apps.dashboard.models import AuditLog
from apps.dashboard.serializers.notifications import NotificationSendSerializer
from apps.dashboard.views.base import get_client_ip
from apps.dashboard.views.mixins import DashboardListMixin
from apps.shared.addons.validations import error_response, success_response
from apps.shared.pagination import StandardResultsSetPagination
from apps.shared.permissions import IsAdmin, IsDashboardUser
from apps.user.models import Notification, User
from apps.user.serializers import NotificationSerializer


class DashboardNotificationList(DashboardListMixin, generics.ListAPIView):
    queryset = Notification.objects.all()
    serializer_class = NotificationSerializer
    permission_classes = [IsDashboardUser]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    pagination_class = StandardResultsSetPagination
    list_message = "Notifications retrieved successfully"


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
