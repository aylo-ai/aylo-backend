import requests
import logging
from mcp.server.fastmcp import FastMCP

server = FastMCP(name='Repli Product Search Tool')

@server.tool()
async def search_product(product_name: str, access_token: str):
    if not product_name:
        return {
            "success": False,
            "message": "Product name is required to search the catalog.",
            "products": [],
        }

    if not access_token:
        return {
            "success": False,
            "message": "Billz access token missing. Connect the Billz integration.",
            "products": [],
        }

    try:
        base_url = "https://api-admin.billz.ai/v2/products"
        params = {
            "search": product_name,
            "limit": 5,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }

        response = requests.get(
            url=base_url,
            headers=headers,
            params=params,
            timeout=10
        )
        logging.info(f"response: {response.json()}")
        
        if response.status_code == 200:
            response_json = response.json()
            products = response_json.get('products', [])
            
            if not products:
                return {
                    "success": False,
                    "message": f"No products found matching '{product_name}'",
                    "products": []
                }
            
            
            return {
                "success": True,
                "message": f"Found {len(products)} product(s) matching '{products}'",
                "products": products,
                "total_found": len(products)
            }
        else:
            return {
                "success": False,
                "message": f"API error: {response.status_code} - {response.text}",
                "products": []
            }
            
    except requests.exceptions.Timeout:
        return {
            "success": False,
            "message": "Product search timed out. Please try again.",
            "products": []
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error searching products: {str(e)}",
            "products": []
        }

@server.tool()
async def search_products_with_filters(
    access_token: str, 
    payload: dict,
    limit: int = 10, 
):
    """
    Performs an advanced product search using multiple filters (category_ids, brand_ids, price ranges, etc.). 
    The 'payload' must be a dictionary containing the specific filter parameters.
    """
    if not access_token:
        return {"success": False, "message": "Billz access token missing."}
    if not payload:
        return {"success": False, "message": "Payload is required for advanced product search."}

    try:
        base_url = "https://api-admin.billz.ai/v2/product-search-with-filters"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }

        # Ensure pagination is in the payload
        payload.update({"limit": limit})
        
        response = requests.post(url=base_url, headers=headers, json=payload, timeout=20)
        
        if response.status_code == 200:
            response_json = response.json()
            products = response_json.get('products', [])
            total_found = response_json.get('count', 0)
            
            return {
                "success": True,
                "message": f"Found {len(products)} product(s). Total: {total_found}",
                "products": products,   
                "total_found": total_found
            }
        else:
            return {
                "success": False,
                "message": f"API error: {response.status_code} - {response.text}",
                "products": []
            }
            
    except requests.exceptions.RequestException as e:
        return {"success": False, "message": f"Error during advanced product search: {str(e)}"}
@server.tool()
async def get_product_characteristics(access_token: str, limit: int = 1000):
    """
    Retrieves a list of all product characteristics (attributes and custom fields) from Billz.
    """
    if not access_token:
        return {"success": False, "message": "Billz access token missing."}

    try:
        base_url = "https://api-admin.billz.ai/v2/product-characteristic"
        params = {"limit": limit}
        headers = {"Authorization": f"Bearer {access_token}"}

        response = requests.get(url=base_url, headers=headers, params=params, timeout=10)
        
        if response.status_code == 200:
            return {"success": True, "characteristics": response.json()}
        else:
            return {"success": False, "message": f"API error: {response.status_code} - {response.text}"}
            
    except requests.exceptions.RequestException as e:
        return {"success": False, "message": f"Error retrieving product characteristics: {str(e)}"}

@server.tool()
async def get_measurement_units(access_token: str):
    """
    Retrieves a list of measurement units (e.g., штука, шт) from Billz.
    """
    if not access_token:
        return {"success": False, "message": "Billz access token missing."}

    try:
        base_url = "https://api-admin.billz.ai/v2/measurement-unit"
        headers = {"Authorization": f"Bearer {access_token}"}

        response = requests.get(url=base_url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            return {"success": True, "units": response.json()}
        else:
            return {"success": False, "message": f"API error: {response.status_code} - {response.text}"}
            
    except requests.exceptions.RequestException as e:
        return {"success": False, "message": f"Error retrieving measurement units: {str(e)}"}

@server.tool()
async def get_categories(access_token: str, search: str = "", limit: int = 50):
    """
    Retrieves a list of product categories from Billz.
    """
    if not access_token:
        return {"success": False, "message": "Billz access token missing."}

    try:
        base_url = "https://api-admin.billz.ai/v2/category"
        params = {
            "limit": limit,
            "search": search,
            "is_deleted": False,
        }
        headers = {"Authorization": f"Bearer {access_token}"}

        response = requests.get(url=base_url, headers=headers, params=params, timeout=10)
        
        if response.status_code == 200:
            return {"success": True, "categories": response.json()}
        else:
            return {"success": False, "message": f"API error: {response.status_code} - {response.text}"}
            
    except requests.exceptions.RequestException as e:
        return {"success": False, "message": f"Error retrieving categories: {str(e)}"}

@server.tool()
async def get_brands(access_token: str, search: str = "", limit: int = 10, page: int = 1):
    """
    Retrieves a list of product brands from Billz.
    """
    if not access_token:
        return {"success": False, "message": "Billz access token missing."}

    try:
        base_url = "https://api-admin.billz.ai/v2/brand"
        params = {
            "limit": limit,
            "page": page,
            "search": search,
        }
        headers = {"Authorization": f"Bearer {access_token}"}

        response = requests.get(url=base_url, headers=headers, params=params, timeout=10)
        
        if response.status_code == 200:
            return {"success": True, "brands": response.json()}
        else:
            return {"success": False, "message": f"API error: {response.status_code} - {response.text}"}
            
    except requests.exceptions.RequestException as e:
        return {"success": False, "message": f"Error retrieving brands: {str(e)}"}
tools = [
    {
        "type": "function",
        "function": {
            "name": "search_product",
            "description": "Search for products in the external product catalog (Billz.ai) using a simple keyword.",
            "parameters": {
                "type": "object",
                "properties": {
                    "access_token": {"type": "string", "description": "Bearer token for API authentication"},
                    "product_name": {"type": "string", "description": "The name or keyword of the product to search for"}
                },
                "required": ["product_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_categories",
            "description": "Retrieves a paginated list of product categories from the Billz catalog. Useful for asking 'What categories do you have?'",
            "parameters": {
                "type": "object",
                "properties": {
                    "access_token": {"type": "string", "description": "Bearer token for API authentication"},
                    "search": {"type": "string", "description": "Optional: Keyword to filter categories."},
                    "limit": {"type": "integer", "description": "Optional: Number of items per page (default 10)."},
                    "page": {"type": "integer", "description": "Optional: Page number for results (default 1)."}
                },
                "required": ["access_token"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_brands",
            "description": "Retrieves a paginated list of product brands from the Billz catalog.",
            "parameters": {
                "type": "object",
                "properties": {
                    "access_token": {"type": "string", "description": "Bearer token for API authentication"},
                    "search": {"type": "string", "description": "Optional: Keyword to filter brands."},
                    "limit": {"type": "integer", "description": "Optional: Number of items per page (default 10)."},
                    "page": {"type": "integer", "description": "Optional: Page number for results (default 1)."}
                },
                "required": ["access_token"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_measurement_units",
            "description": "Retrieves a list of all defined measurement units (e.g., 'pcs', 'kg') from Billz.",
            "parameters": {
                "type": "object",
                "properties": {
                    "access_token": {"type": "string", "description": "Bearer token for API authentication"}
                },
                "required": ["access_token"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_characteristics",
            "description": "Retrieves all available product characteristics (attributes and custom fields) which are necessary for advanced filtering.",
            "parameters": {
                "type": "object",
                "properties": {
                    "access_token": {"type": "string", "description": "Bearer token for API authentication"},
                    "limit": {"type": "integer", "description": "Optional: Maximum number of characteristics to return (default 1000)."}
                },
                "required": ["access_token"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_products_with_filters",
            "description": "Performs a highly detailed product search using complex filters like category_ids, brand_ids, price ranges, SKUs, and custom attributes. This uses a POST request with a required payload.",
            "parameters": {
                "type": "object",
                "properties": {
                    "access_token": {"type": "string", "description": "Bearer token for API authentication"},
                    "payload": {
                        "type": "object",
                        "description": "A dictionary containing the filter parameters (e.g., category_ids, retail_price_from, product_field_filters, etc.). Must conform to the API's POST body structure."
                    },
                    "limit": {"type": "integer", "description": "Optional: Number of products per page (default 10)."},
                    "page": {"type": "integer", "description": "Optional: Page number for results (default 1)."}
                },
                "required": ["access_token", "payload"]
            }
        }
    }
]


if __name__ == "__main__":
    server.run(transport="stdio")