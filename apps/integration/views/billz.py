import functools

from django.db import transaction
from django.utils.translation import gettext_lazy as _
from rest_framework import generics, permissions
from rest_framework.views import APIView

from apps.assistant.utils import owned_assistants
from apps.integration.gateways import billz as billz_client
from apps.integration.models import Integration
from apps.integration.serializers import IntegrationSerializer
from apps.shared.addons.enums import BillzSyncStatuses, IntegrationTypes
from apps.shared.addons.validations import error_response, success_response


def billz_status(integration=None) -> dict:
    if integration is None:
        return {
            "connected": False,
            "id": None,
            "name": None,
            "is_active": False,
            "sync_status": BillzSyncStatuses.NEVER_SYNCED.value,
            "last_synced_at": None,
            "product_count": None,
        }

    metadata = integration.metadata or {}
    return {
        "connected": True,
        "id": str(integration.id),
        "name": integration.name,
        "is_active": integration.is_active,
        "sync_status": metadata.get(
            'billz_sync_status', BillzSyncStatuses.NEVER_SYNCED.value
        ),
        "last_synced_at": metadata.get('billz_last_synced_at'),
        "product_count": metadata.get('billz_product_count'),
    }


def _queue_sync(integration: Integration) -> None:
    from apps.integration.tasks.billz import record_sync_status

    record_sync_status(integration, BillzSyncStatuses.SYNCING.value)

    from apps.integration.tasks import fetch_and_save_billz_products
    transaction.on_commit(
        functools.partial(fetch_and_save_billz_products.delay, str(integration.id))
    )


class BillzSecretTokenHandlerView(generics.CreateAPIView):
    serializer_class = IntegrationSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = Integration.objects.all()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['assistant_id'] = self.kwargs.get('pk')
        return context

    def _assistant(self):
        return owned_assistants(self.request.user).filter(id=self.kwargs.get('pk')).first()

    @staticmethod
    def _payload(request) -> dict:
        payload = {key: value for key, value in request.data.items()}
        payload['integration_type'] = IntegrationTypes.BILLZ.value
        if not payload.get('name'):
            payload['name'] = 'Billz'
        return payload

    def get(self, request, *args, **kwargs):
        assistant = self._assistant()
        if assistant is None:
            return error_response(message=_("Assistant topilmadi"), code=404)
        integration = Integration.objects.filter(
            assistant=assistant, integration_type=IntegrationTypes.BILLZ.value,
        ).first()
        return success_response(
            data=billz_status(integration),
            message=_("Billz holati muvaffaqiyatli olindi"),
            code=200,
        )

    def create(self, request, *args, **kwargs):
        secret_token = request.data.get('api_token')
        assistant = self._assistant()
        if assistant is None:
            return error_response(message=_("Assistant topilmadi"), code=404)
        if not secret_token:
            return error_response(message=_("Billz API token kerak"), code=400)

        access_token = billz_client.login(secret_token)
        if not access_token:
            return error_response(message=_("Billz API token yaroqli emas"), code=400)

        existing = Integration.objects.filter(
            assistant=assistant, integration_type=IntegrationTypes.BILLZ.value,
        ).first()
        serializer = self.get_serializer(
            existing, data=self._payload(request), partial=existing is not None,
        )
        serializer.is_valid(raise_exception=True)

        integration = serializer.save(
            assistant=assistant,
            api_token=access_token,
            refresh_token=secret_token,
            integration_type=IntegrationTypes.BILLZ.value,
        )

        _queue_sync(integration)

        return success_response(
            message=_("Billz secret token muvaffaqiyatli yaratildi"),
            data=billz_status(integration),
            code=201,
        )


class BillzSyncView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        integration = Integration.objects.filter(
            id=kwargs.get('pk'),
            integration_type=IntegrationTypes.BILLZ.value,
            assistant__in=owned_assistants(request.user),
        ).first()
        if integration is None:
            return error_response(message=_("Billz integration topilmadi"), code=404)

        _queue_sync(integration)

        return success_response(
            data=billz_status(integration),
            message=_("Billz sinxronizatsiyasi boshlandi"),
            code=202,
        )
