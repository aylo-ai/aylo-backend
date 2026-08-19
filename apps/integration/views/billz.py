"""Billz POS integration: connect, status and manual re-sync.

All three endpoints answer with the same flat `data` object (`billz_status`), so
the frontend card renders from one shape whichever call it just made. Sync state
is read out of `Integration.metadata` — see `apps/integration/tasks/billz.py` for
who writes it.

Tokens never appear in a response. The request field is called `api_token` for
backwards compatibility with the frontend, but it carries the Billz **secret**
token, which is exchanged here for the access token everything else uses and kept
in `refresh_token` as the only way to re-authenticate later.
"""
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
    """The Billz card payload. Never includes a credential.

    `product_count` and `last_synced_at` stay null until the first sync finishes,
    so the UI can tell "connected, still working" from "connected, has data".
    """
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
    """Mark the integration syncing and dispatch the catalogue fetch after commit.

    ATOMIC_REQUESTS is on, so dispatching inline races the worker to the row and
    it can lose — `on_commit` is what makes the id the task receives resolvable.
    """
    from apps.integration.tasks.billz import record_sync_status

    record_sync_status(integration, BillzSyncStatuses.SYNCING.value)

    from apps.integration.tasks import fetch_and_save_billz_products
    transaction.on_commit(
        functools.partial(fetch_and_save_billz_products.delay, str(integration.id))
    )


class BillzSecretTokenHandlerView(generics.CreateAPIView):
    """`GET` the assistant's Billz connection state, `POST` a secret token to connect."""

    serializer_class = IntegrationSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = Integration.objects.all()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['assistant_id'] = self.kwargs.get('pk')
        return context

    def _assistant(self):
        # Ownership, not existence. The check was `Assistant.objects.filter(
        # id=...).exists()`, so any authenticated caller could bolt their Billz
        # catalogue onto another tenant's assistant — and because `assistant`
        # is a writable serializer field saved with a bare `serializer.save()`,
        # the request body could redirect it too. The assistant is now resolved
        # against the caller and forced on save.
        return owned_assistants(self.request.user).filter(id=self.kwargs.get('pk')).first()

    @staticmethod
    def _payload(request) -> dict:
        """Request body with the two fields this endpoint already knows filled in.

        `integration_type` is required by the serializer but is not the caller's
        to choose here — the URL is the Billz endpoint — and it is forced again on
        save. Sending the documented body (`api_token` + `name`) used to fail with
        a 400 on the missing type. Copied key by key because a form-encoded
        request arrives as an immutable QueryDict.
        """
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

        # Reconnecting reuses the row instead of stacking a second Billz
        # integration on the assistant: two rows would mean two catalogue files
        # in one vector store and two hourly syncs, and the dead row's
        # `auth_failed` would still be what a status read found.
        existing = Integration.objects.filter(
            assistant=assistant, integration_type=IntegrationTypes.BILLZ.value,
        ).first()
        serializer = self.get_serializer(
            existing, data=self._payload(request), partial=existing is not None,
        )
        serializer.is_valid(raise_exception=True)

        # The tokens are passed through `save()` rather than by mutating
        # `request.data`: that mutation raises on a form-encoded (immutable)
        # QueryDict, and `refresh_token` is not a serializer field, so the secret
        # token it tried to set was silently dropped — leaving the row with no way
        # to ever re-authenticate.
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
    """Re-sync the catalogue on demand, without waiting for the hourly beat.

    Takes no body, so it is a plain `APIView` like the amoCRM actions rather than
    a generic view with a serializer that would never be used.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        # Resolved through the caller's own assistants, exactly like connect:
        # filtering on the integration id alone would let any authenticated
        # account drive syncs against another tenant's Billz account.
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
