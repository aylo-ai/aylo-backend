"""Billz REST API client.

Both halves of talking to Billz live here: the token exchange and the product
fetch. Billz issues a long-lived **secret token** to the merchant, which is worth
nothing to the API on its own — it has to be exchanged at `/v1/auth/login` for a
short-lived **access token**, and that access token is the only credential
`/v2/products` accepts. It expires, so the exchange is not a one-off done at
connect time: `fetch_all_products` signals expiry with `BillzAuthError` and the
sync task in ``apps/integration/tasks/billz.py`` logs in again and retries.

Login used to sit inline in the connect view and nowhere else, which is why the
hourly sync had no way to re-authenticate and quietly served a stale catalogue
forever once the first access token aged out.
"""
import logging
from typing import Optional

import requests

from apps.shared import http

logger = logging.getLogger(__name__)

LOGIN_URL = 'https://api-admin.billz.ai/v1/auth/login'
PRODUCTS_URL = 'https://api-admin.billz.ai/v2/products'
PAGE_LIMIT = 1000  # Maximum items per page allowed by the Billz API

#: Statuses that mean the access token is no longer accepted. Anything else is
#: treated as transient and fails soft.
AUTH_STATUS_CODES = (401, 403)


class BillzAuthError(Exception):
    """The access token was rejected. Re-login and retry, do not fail soft.

    Distinct from every other failure on purpose: swallowing a 401 like a network
    blip is exactly what let the catalogue go stale in silence.
    """


def login(secret_token: str) -> Optional[str]:
    """Exchange the merchant's secret token for an access token.

    Fail-soft: returns None on a network error, a non-200, an unparseable body
    or a payload without `data.access_token`. Nothing about the token is logged.
    """
    if not secret_token:
        logger.warning("Billz login called without a secret token")
        return None

    try:
        response = http.post(LOGIN_URL, json={"secret_token": secret_token})
    except requests.exceptions.RequestException as exc:
        logger.warning("Billz login request failed: %s", exc)
        return None

    if response.status_code != 200:
        logger.warning("Billz login rejected with status %s", response.status_code)
        return None

    try:
        payload = response.json() or {}
    except ValueError as exc:
        logger.warning("Billz login returned an unparseable body: %s", exc)
        return None

    access_token = (payload.get('data') or {}).get('access_token')
    if not access_token:
        logger.warning("Billz login response carried no access_token")
        return None

    return access_token


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

    Raises `BillzAuthError` when Billz rejects the access token, so the caller
    can re-login instead of mistaking an expired credential for an empty
    catalogue. Every other failure stays fail-soft: the walk stops and whatever
    was collected so far is returned.
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
            # Checked before raise_for_status: an expired access token comes back
            # as a plain 401/403 and must not be lumped in with the fail-soft
            # RequestException branch below.
            if response.status_code in AUTH_STATUS_CODES:
                raise BillzAuthError(
                    f"Billz rejected the access token with status {response.status_code}"
                )
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
