"""Billz POS integration onboarding."""
import functools

from django.db import transaction
from django.utils.translation import gettext_lazy as _
from rest_framework import generics, permissions

from apps.assistant.utils import owned_assistants
from apps.integration.models import Integration
from apps.integration.serializers import IntegrationSerializer
from apps.shared import http
from apps.shared.addons.validations import error_response, success_response


class BillzSecretTokenHandlerView(generics.CreateAPIView):
    serializer_class = IntegrationSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = Integration.objects.all()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['assistant_id'] = self.kwargs.get('pk')
        return context

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        api_token = request.data.get('api_token')
        assistant_id = self.kwargs.get('pk')
        # Ownership, not existence. The check was `Assistant.objects.filter(
        # id=...).exists()`, so any authenticated caller could bolt their Billz
        # catalogue onto another tenant's assistant — and because `assistant`
        # is a writable serializer field saved with a bare `serializer.save()`,
        # the request body could redirect it too. The assistant is now resolved
        # against the caller and forced on save.
        assistant = owned_assistants(request.user).filter(id=assistant_id).first()
        if assistant is None:
            return error_response(message=_("Assistant topilmadi"), code=404)
        if not api_token:
            return error_response(message=_("Billz API token kerak"), code=400)
        response = http.post("https://api-admin.billz.ai/v1/auth/login", json={"secret_token": api_token})
        if response.status_code != 200:
            return error_response(message=_("Billz API token yaroqli emas"), code=400)

        access_token = response.json().get('data').get('access_token')
        if not access_token:
            return error_response(message=_("Billz access token topilmadi"), code=400)
        request.data['refresh_token'] = api_token
        request.data['api_token'] = access_token
        serializer.is_valid(raise_exception=True)
        integration = serializer.save(assistant=assistant)

        # Trigger async task to fetch and save Billz products, once the
        # integration row this id points at is actually visible to the worker.
        from apps.integration.tasks import fetch_and_save_billz_products
        transaction.on_commit(
            functools.partial(fetch_and_save_billz_products.delay, str(integration.id))
        )

        return success_response(message=_("Billz secret token muvaffaqiyatli yaratildi"), data=serializer.data, code=201)
