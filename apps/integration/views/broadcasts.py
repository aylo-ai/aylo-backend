import functools

from django.db import transaction
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from rest_framework import generics, permissions
from rest_framework.views import APIView

from apps.integration.models import Broadcast, Integration
from apps.integration.serializers import BroadcastSerializer
from apps.shared.addons.validations import error_response, success_response


class BroadcastListCreateView(generics.ListCreateAPIView):
    serializer_class = BroadcastSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Broadcast.objects.none()
        return Broadcast.objects.filter(user=self.request.user)

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return success_response(message=_("Broadcast ro'yxati"), data=serializer.data, code=200)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        integration = serializer.validated_data['integration']
        owner = integration.user or (integration.assistant.user if integration.assistant else None)
        if owner != request.user:
            return error_response(message=_("Bu integratsiya sizga tegishli emas"), code=403)

        recipients_count = self._get_recipients_count(integration)
        if recipients_count == 0:
            return error_response(message=_("Xabar yuborish uchun qabul qiluvchilar topilmadi"), code=400)

        broadcast = serializer.save(user=request.user, total_recipients=recipients_count)

        from apps.integration.tasks import send_broadcast_task
        transaction.on_commit(functools.partial(send_broadcast_task.delay, str(broadcast.id)))

        return success_response(
            message=_("Broadcast muvaffaqiyatli yaratildi"),
            data=BroadcastSerializer(broadcast).data,
            code=201
        )

    def _get_recipients_count(self, integration):
        from apps.integration.tasks import get_broadcast_recipients
        return get_broadcast_recipients(integration).count()


class BroadcastRecipientsCountView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, integration_id, *args, **kwargs):
        try:
            integration = Integration.objects.get(
                Q(user=request.user) | Q(assistant__user=request.user),
                id=integration_id
            )
        except Integration.DoesNotExist:
            return error_response(message=_("Integratsiya topilmadi"), code=404)

        from apps.integration.tasks import get_broadcast_recipients
        recipients = get_broadcast_recipients(integration)

        return success_response(
            message=_("Qabul qiluvchilar soni"),
            data={"count": recipients.count()},
            code=200
        )


class BroadcastRecipientsListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, integration_id, *args, **kwargs):
        try:
            integration = Integration.objects.get(
                Q(user=request.user) | Q(assistant__user=request.user),
                id=integration_id
            )
        except Integration.DoesNotExist:
            return error_response(message=_("Integratsiya topilmadi"), code=404)

        from apps.integration.tasks import get_broadcast_recipients
        recipients = get_broadcast_recipients(integration).values(
            'id', 'user_id', 'username', 'client_full_name', 'platform', 'updated_time'
        )

        return success_response(
            message=_("Qabul qiluvchilar ro'yxati"),
            data=list(recipients),
            code=200
        )
