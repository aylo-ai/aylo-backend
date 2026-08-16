"""Billz sync tasks: mirror the merchant's product catalogue into the AI knowledge base."""
import json
import logging
import time

from celery import shared_task

from apps.integration.gateways import billz as billz_client
from apps.shared.addons.enums import IntegrationTypes
from apps.shared.ai_service import knowledge_base

from ..models import Integration

logger = logging.getLogger(__name__)


@shared_task(name="apps.integration.tasks.fetch_and_save_billz_products")
def fetch_and_save_billz_products(integration_id: str):
    """Fetch all Billz products and save them to the assistant's vector store.

    Called when a Billz integration is created/updated, and hourly by
    ``update_billz_products_hourly``.
    """
    try:
        integration = Integration.objects.filter(id=integration_id).first()
        if not integration or integration.integration_type != IntegrationTypes.BILLZ.value:
            logger.warning("Integration %s not found or not Billz type", integration_id)
            return

        if not integration.api_token or not integration.assistant:
            logger.warning("Integration %s missing api_token or assistant", integration_id)
            return

        assistant = integration.assistant

        all_products = billz_client.fetch_all_products(integration.api_token)
        if not all_products:
            logger.warning("No products fetched for integration %s", integration_id)
            return

        logger.info("Fetched %s products for integration %s", len(all_products), integration_id)

        products_json = json.dumps(all_products, ensure_ascii=False, indent=2)

        store_id = knowledge_base.ensure_store(assistant)

        # Drop last run's catalogue so the store holds one copy, not a growing pile.
        metadata = integration.metadata or {}
        previous_file_id = metadata.get('billz_products_file_id')
        if previous_file_id:
            knowledge_base.delete_file(store_id, previous_file_id)

        filename = f"billz_products_{assistant.id}.json"
        file_id = knowledge_base.add_text(store_id, products_json, filename)

        if not file_id:
            logger.warning("Failed to index Billz products for integration %s", integration_id)
            return

        integration.metadata = {
            **metadata,
            'billz_products_file_id': file_id,
            'billz_products_updated_at': time.time(),
        }
        integration.save(update_fields=['metadata'])
        logger.info("Indexed %s Billz products for assistant %s as %s",
                    len(all_products), assistant.id, file_id)

    except Exception:
        logger.exception("Error in fetch_and_save_billz_products")


@shared_task(name="apps.integration.tasks.update_billz_products_hourly")
def update_billz_products_hourly():
    """Beat task (hourly): re-sync products for every active Billz integration."""
    try:
        billz_integrations = Integration.objects.filter(
            integration_type=IntegrationTypes.BILLZ.value,
            is_active=True,
            assistant__isnull=False
        ).select_related('assistant')

        logger.info("Found %s active Billz integrations to update", billz_integrations.count())

        for integration in billz_integrations:
            if integration.api_token and integration.assistant:
                logger.info("Updating products for integration %s (assistant %s)",
                            integration.id, integration.assistant.id)
                fetch_and_save_billz_products.delay(str(integration.id))
            else:
                logger.warning("Skipping integration %s - missing api_token or assistant",
                               integration.id)

    except Exception:
        logger.exception("Error in update_billz_products_hourly")
