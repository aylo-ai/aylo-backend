"""Billz REST API client.

Fetches the merchant's product catalogue, simplified down to the fields the
assistant's knowledge base actually needs. Used by the Billz sync tasks in
``apps/integration/tasks/billz.py``.
"""
import logging

import requests
from apps.shared import http

logger = logging.getLogger(__name__)

PRODUCTS_URL = 'https://api-admin.billz.ai/v2/products'
PAGE_LIMIT = 1000  # Maximum items per page allowed by the Billz API


def _extract_relevant_fields(product):
    """Reduce a raw Billz product payload to the fields useful for the AI KB."""
    # Extract color/size from custom_fields
    color = None
    size = None
    for field in product.get('custom_fields', []):
        if field.get('custom_field_system_name') == 'ЦВЕТ':
            color = field.get('custom_field_value')
        elif field.get('custom_field_system_name') == 'РАЗМЕР':
            size = field.get('custom_field_value')

    # Extract shop names and prices
    shops = []
    for shop_price in product.get('shop_prices', []):
        shops.append({
            'shop_name': shop_price.get('shop_name', ''),
            'retail_price': shop_price.get('retail_price', 0),
            'retail_currency': shop_price.get('retail_currency', 'UZS')
        })

    # Extract category names
    categories = [cat.get('name', '') for cat in product.get('categories', [])]

    return {
        'id': product.get('id', ''),
        'name': product.get('name', ''),
        'product_name': product.get('name', ''),  # Alias for name
        'sku': product.get('sku', ''),
        'color': color,
        'size': size,
        'categories': categories,
        'brand_name': product.get('brand_name', ''),
        'shops': shops,
        'description': product.get('description', ''),
        'barcode': product.get('barcode', ''),
        'main_image_url': product.get('main_image_url', ''),
        'main_image_url_full': product.get('main_image_url_full', ''),
        'photos': product.get('photos', []),
    }


def fetch_all_products(access_token):
    """Fetch every product from the Billz API, following pagination.

    Fail-soft: a network error on any page stops the walk and returns whatever
    was collected so far.
    """
    all_products = []
    page = 1
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    logger.info("Fetching all Billz products...")

    while True:
        params = {"limit": PAGE_LIMIT, "page": page}
        try:
            response = http.get(PRODUCTS_URL, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as e:
            logger.warning("Error fetching Billz page %s: %s", page, e)
            break

        products = data.get('products', [])
        if not products:
            break

        all_products.extend(_extract_relevant_fields(product) for product in products)
        logger.info("Fetched page %s: %s products (Total: %s)", page, len(products), len(all_products))

        # Fewer products than the limit means this was the last page.
        if len(products) < PAGE_LIMIT:
            break
        page += 1

    return all_products
