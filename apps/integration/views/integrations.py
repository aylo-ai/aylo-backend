import functools

from django.db import transaction
from django.utils.translation import gettext_lazy as _
from rest_framework import generics, permissions

from apps.integration.gateways.instagram import instagram_service
from apps.integration.models import Integration
from apps.integration.serializers import (
    IntegrationCreateSerializer,
    IntegrationSerializer,
    SendIntegrationMessageSerializer,
    SendUserMessageSerializer,
)
from apps.integration.tasks import send_message_integration_task
from apps.integration.views.mixins import (
    IntegrationOwnedQuerysetMixin,
    owned_integrations,
)
from apps.shared.addons.enums import IntegrationTypes
from apps.shared.addons.validations import error_response, success_response
from apps.shared.ai_service import knowledge_base
from apps.shared.permissions import IsCustomer


def _discard_billz_catalogue(integration):
    file_id = (integration.metadata or {}).get('billz_products_file_id')
    store_id = getattr(integration.assistant, 'vector_id', None)
    if not file_id or not store_id:
        return
    knowledge_base.delete_file(store_id, file_id)


class IntegrationListView(IntegrationOwnedQuerysetMixin, generics.ListAPIView):
    queryset = Integration.objects.all()
    serializer_class = IntegrationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data, message="Integrations retrieved successfully", code=200)


class IntegrationListCreateView(IntegrationOwnedQuerysetMixin, generics.ListCreateAPIView):
    queryset = Integration.objects.all()
    serializer_class = IntegrationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return IntegrationCreateSerializer
        return IntegrationSerializer

    def get_queryset(self):
        return super().get_queryset().filter(assistant_id=self.kwargs.get('pk'))

    def create(self, request, *args, **kwargs):
        base_url = f"{request.scheme}://{request.get_host()}"
        assistant_id = self.kwargs.get('pk', None)
        context_data = {
            "base_url": base_url,
            "assistant_id": assistant_id,
            "request": request
        }
        serializer = self.get_serializer(data=request.data, context=context_data)
        serializer.is_valid(raise_exception=True)
        serializer.save(assistant_id=assistant_id)
        return success_response(message=_("Integration muvaffaqiyatli yaratildi"), data=serializer.data, code=201)


class IntegrationRetrieveUpdateDestroyView(IntegrationOwnedQuerysetMixin,
                                           generics.RetrieveUpdateDestroyAPIView):
    queryset = Integration.objects.all()
    serializer_class = IntegrationCreateSerializer
    permission_classes = [permissions.IsAuthenticated]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data, message=_("Integration muvaffaqiyatli olindi"), code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        base_url = f"{request.scheme}://{request.get_host()}"
        context_data = {
            "base_url": base_url,
            "request": request,
            "assistant_id": instance.assistant_id
        }
        serializer = self.get_serializer(instance, data=request.data, context=context_data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(message=_("Integration muvaffaqiyatli o'zgartirildi"), data=serializer.data, code=200)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.integration_type == IntegrationTypes.INSTAGRAM.value:
            instagram_service.unsubscribe_webhooks(instance.api_token)
        elif instance.integration_type == IntegrationTypes.BILLZ.value:
            _discard_billz_catalogue(instance)
        instance.delete()
        return success_response(message=_("Integration muvaffaqiyatli o'chirildi"), code=204)


class SendUserMessageView(generics.CreateAPIView):
    serializer_class = SendUserMessageSerializer
    permission_classes = [IsCustomer]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        response = serializer.save()
        return success_response(message=response.get("message"), code=200)


class SendIntegrationMessageView(generics.CreateAPIView):
    serializer_class = SendIntegrationMessageSerializer
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request, *args, **kwargs):
        integration_id = self.kwargs.get('pk')
        message = request.data.get("message")
        if not message:
            return error_response(message=_("Xabar mavjud emas"), code=400)
        if not integration_id:
            return error_response(message=_("Integration ID mavjud emas"), code=400)
        if not owned_integrations(request.user).filter(id=integration_id).exists():
            return error_response(message=_("Sizda bu integration mavjud emas"), code=400)
        transaction.on_commit(functools.partial(
            send_message_integration_task.delay, integration_id, message))
        return success_response(message=_("Xabar muvaffaqiyatli yuborildi"), code=200)
