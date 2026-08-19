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
    return timezone.now().astimezone(dt_timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def record_sync_status(integration: Integration, status: str, **extra) -> None:
    metadata = {
        **(integration.metadata or {}),
        'billz_sync_status': status,
        **extra,
    }
    metadata.pop('billz_products_updated_at', None)
    integration.metadata = metadata
    integration.save(update_fields=['metadata'])


def _fetch_products(integration: Integration) -> Optional[list]:
    try:
        return billz_client.fetch_all_products(integration.api_token)
    except billz_client.BillzAuthError as exc:
        logger.info("Billz access token expired for integration %s: %s", integration.id, exc)

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

    integration.api_token = access_token
    integration.save(update_fields=['api_token'])
    logger.info("Re-authenticated Billz integration %s", integration.id)

    try:
        return billz_client.fetch_all_products(access_token)
    except billz_client.BillzAuthError as exc:
        logger.warning(
            "Billz refused a freshly issued access token for integration %s: %s",
            integration.id, exc,
        )
        return None


@shared_task(name="apps.integration.tasks.fetch_and_save_billz_products")
def fetch_and_save_billz_products(integration_id: str):
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
            record_sync_status(integration, BillzSyncStatuses.AUTH_FAILED.value)
            logger.warning("Billz authentication failed for integration %s", integration_id)
            return

        if not all_products:
            record_sync_status(integration, BillzSyncStatuses.FAILED.value)
            logger.warning("No products fetched for integration %s", integration_id)
            return

        logger.info("Fetched %s products for integration %s", len(all_products), integration_id)

        products_json = json.dumps(all_products, ensure_ascii=False, indent=2)

        store_id = knowledge_base.ensure_store(assistant)

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
        if integration is not None:
            try:
                record_sync_status(integration, BillzSyncStatuses.FAILED.value)
            except Exception:
                logger.exception("Could not record the Billz failure for %s", integration_id)


@shared_task(name="apps.integration.tasks.update_billz_products_hourly")
def update_billz_products_hourly():
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
