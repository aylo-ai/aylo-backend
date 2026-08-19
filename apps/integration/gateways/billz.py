import logging
from typing import Optional

import requests

from apps.shared import http

logger = logging.getLogger(__name__)

LOGIN_URL = 'https://api-admin.billz.ai/v1/auth/login'
PRODUCTS_URL = 'https://api-admin.billz.ai/v2/products'
PAGE_LIMIT = 1000

AUTH_STATUS_CODES = (401, 403)


class BillzAuthError(Exception):
    pass


def login(secret_token: str) -> Optional[str]:
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
    color = None
    size = None
    for field in product.get('custom_fields', []):
        if field.get('custom_field_system_name') == 'ЦВЕТ':
            color = field.get('custom_field_value')
        elif field.get('custom_field_system_name') == 'РАЗМЕР':
            size = field.get('custom_field_value')

    shops = []
    for shop_price in product.get('shop_prices', []):
        shops.append({
            'shop_name': shop_price.get('shop_name', ''),
            'retail_price': shop_price.get('retail_price', 0),
            'retail_currency': shop_price.get('retail_currency', 'UZS')
        })

    categories = [cat.get('name', '') for cat in product.get('categories', [])]

    return {
        'id': product.get('id', ''),
        'name': product.get('name', ''),
        'product_name': product.get('name', ''),
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

        if len(products) < PAGE_LIMIT:
            break
        page += 1

    return all_products
