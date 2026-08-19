"""Billz sync tasks: mirror the merchant's product catalogue into the AI knowledge base.

Sync state lives in `Integration.metadata` under three keys the frontend reads
through `GET /integration/assistant/<id>/billz/`:

    billz_sync_status      one of `BillzSyncStatuses`
    billz_last_synced_at   ISO 8601 UTC, set only on a successful sync
    billz_product_count    products in the last successful sync

`auth_failed` means the merchant's secret token no longer authenticates, so a
retry inside one run cannot recover it and the UI has to ask them to reconnect.
Every other failure is transient; the hourly beat retries both.
"""
import json
import logging
from datetime import timezone as dt_timezone
from typing import Optional

from celery import shared_task
from django.utils import timezone

from apps.integration.gateways import billz as billz_client
from apps.shared.addons.enums import BillzSyncStatuses, IntegrationTypes
from apps.shared.ai_service import knowledge_base

from ..models import Integration

logger = logging.getLogger(__name__)


def _utc_iso() -> str:
    """Now, as the `2026-08-19T06:10:00Z` form the API contract specifies."""
    return timezone.now().astimezone(dt_timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def record_sync_status(integration: Integration, status: str, **extra) -> None:
    """Merge sync state into `metadata` without dropping the other keys.

    `metadata` is one encrypted JSON column shared with `billz_products_file_id`
    and the amoCRM credentials, so it is merged, never replaced. Saved with
    `update_fields` so a concurrent write of `api_token` is not clobbered — and
    because a bare `save()` would rewrite every encrypted column on every status
    tick.
    """
    metadata = {
        **(integration.metadata or {}),
        'billz_sync_status': status,
        **extra,
    }
    # Superseded by `billz_last_synced_at`, which is a readable ISO string rather
    # than a bare epoch float and is what the API exposes. Popped instead of just
    # left alone so rows written by the old task stop carrying a second, stale
    # "last updated" value that disagrees with the one the UI shows.
    metadata.pop('billz_products_updated_at', None)
    integration.metadata = metadata
    integration.save(update_fields=['metadata'])


def _fetch_products(integration: Integration) -> Optional[list]:
    """Fetch the catalogue, re-authenticating once if the access token expired.

    Returns the products, or None when authentication is unrecoverable — the
    caller turns that into `auth_failed`. Billz access tokens expire, so this
    retry is the normal path, not an edge case.
    """
    try:
        return billz_client.fetch_all_products(integration.api_token)
    except billz_client.BillzAuthError as exc:
        logger.info("Billz access token expired for integration %s: %s", integration.id, exc)

    # `refresh_token` holds the merchant's long-lived Billz secret token: the only
    # credential that can mint a new access token. Rows created before the connect
    # view persisted it have nothing to recover with.
    secret_token = integration.refresh_token
    if not secret_token:
        logger.warning(
            "Integration %s has no stored Billz secret token to re-authenticate with",
            integration.id,
        )
        return None

    access_token = billz_client.login(secret_token)
    if not access_token:
        logger.warning("Billz re-login failed for integration %s", integration.id)
        return None

    # Persist before retrying: even if the retry fails, the next run starts from
    # the fresh token. `save()` appends `api_token_hash` to `update_fields` itself.
    integration.api_token = access_token
    integration.save(update_fields=['api_token'])
    logger.info("Re-authenticated Billz integration %s", integration.id)

    try:
        return billz_client.fetch_all_products(access_token)
    except billz_client.BillzAuthError as exc:
        # A brand-new token being refused means the secret token itself is dead.
        logger.warning(
            "Billz refused a freshly issued access token for integration %s: %s",
            integration.id, exc,
        )
        return None


@shared_task(name="apps.integration.tasks.fetch_and_save_billz_products")
def fetch_and_save_billz_products(integration_id: str):
    """Fetch all Billz products and save them to the assistant's vector store.

    Called when a Billz integration is created, on a manual re-sync, and hourly
    by ``update_billz_products_hourly``. Idempotent: the previous catalogue file
    is removed from the store before the new one is indexed, so re-running only
    replaces one file.
    """
    integration = None
    try:
        integration = Integration.objects.filter(id=integration_id).first()
        if not integration or integration.integration_type != IntegrationTypes.BILLZ.value:
            logger.warning("Integration %s not found or not Billz type", integration_id)
            return

        if not integration.api_token or not integration.assistant:
            logger.warning("Integration %s missing api_token or assistant", integration_id)
            return

        assistant = integration.assistant
        record_sync_status(integration, BillzSyncStatuses.SYNCING.value)

        all_products = _fetch_products(integration)
        if all_products is None:
            # The secret token no longer works; only the user can fix this.
            record_sync_status(integration, BillzSyncStatuses.AUTH_FAILED.value)
            logger.warning("Billz authentication failed for integration %s", integration_id)
            return

        if not all_products:
            # Either a partial page walk that failed soft, or a genuinely empty
            # catalogue. Both are reported as `failed` rather than overwriting a
            # good catalogue with nothing.
            record_sync_status(integration, BillzSyncStatuses.FAILED.value)
            logger.warning("No products fetched for integration %s", integration_id)
            return

        logger.info("Fetched %s products for integration %s", len(all_products), integration_id)

        products_json = json.dumps(all_products, ensure_ascii=False, indent=2)

        store_id = knowledge_base.ensure_store(assistant)

        # Drop last run's catalogue so the store holds one copy, not a growing pile.
        previous_file_id = (integration.metadata or {}).get('billz_products_file_id')
        if previous_file_id:
            knowledge_base.delete_file(store_id, previous_file_id)

        filename = f"billz_products_{assistant.id}.json"
        file_id = knowledge_base.add_text(store_id, products_json, filename)

        if not file_id:
            record_sync_status(integration, BillzSyncStatuses.FAILED.value)
            logger.warning("Failed to index Billz products for integration %s", integration_id)
            return

        record_sync_status(
            integration,
            BillzSyncStatuses.SYNCED.value,
            billz_products_file_id=file_id,
            billz_last_synced_at=_utc_iso(),
            billz_product_count=len(all_products),
        )
        logger.info("Indexed %s Billz products for assistant %s as %s",
                    len(all_products), assistant.id, file_id)

    except Exception:
        logger.exception("Error in fetch_and_save_billz_products")
        # A crash must not leave the card stuck on "syncing" forever.
        if integration is not None:
            try:
                record_sync_status(integration, BillzSyncStatuses.FAILED.value)
            except Exception:
                logger.exception("Could not record the Billz failure for %s", integration_id)


@shared_task(name="apps.integration.tasks.update_billz_products_hourly")
def update_billz_products_hourly():
    """Beat task (hourly): re-sync products for every active Billz integration.

    `auth_failed` rows are deliberately retried rather than skipped. That status
    is also what a Billz outage answering 403 produces, and skipping would park
    such an integration permanently until a human noticed; the cost of retrying
    is one login round trip per hour, so the self-healing is worth more.
    """
    try:
        billz_integrations = Integration.objects.filter(
            integration_type=IntegrationTypes.BILLZ.value,
            is_active=True,
            assistant__isnull=False
        ).select_related('assistant')

        logger.info("Found %s active Billz integrations to update", billz_integrations.count())

        for integration in billz_integrations:
            if not integration.api_token or not integration.assistant:
                logger.warning("Skipping integration %s - missing api_token or assistant",
                               integration.id)
                continue
            logger.info("Updating products for integration %s (assistant %s)",
                        integration.id, integration.assistant.id)
            fetch_and_save_billz_products.delay(str(integration.id))

    except Exception:
        logger.exception("Error in update_billz_products_hourly")
