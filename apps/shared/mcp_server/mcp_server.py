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
    payload: dict = None,
    limit: int = 100,
    page: int = 1,
):
    """
    Performs an advanced product search using multiple filters (category_ids, brand_ids, price ranges, etc.). 
    The 'payload' must be a dictionary containing the specific filter parameters.
    If payload is not provided, it will be constructed from limit and page parameters.
    """
    if not access_token:
        return {"success": False, "message": "Billz access token missing."}
    
    # If payload is not provided, create an empty dict
    if payload is None:
        payload = {}
    
    # Ensure pagination is in the payload
    payload.update({"limit": limit, "page": page})

    try:
        base_url = "https://api-admin.billz.ai/v2/product-search-with-filters"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }
        
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

        response = requests.get(url=base_url, headers=headers, params=params, timeout=30)
        
        if response.status_code == 200:
            return {"success": True, "characteristics": response.json().get('product_characteristics', [])}
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
            return {"success": True, "units": response.json().get('measurement_units', [])}
        else:
            return {"success": False, "message": f"API error: {response.status_code} - {response.text}"}
            
    except requests.exceptions.RequestException as e:
        return {"success": False, "message": f"Error retrieving measurement units: {str(e)}"}

@server.tool()
async def get_categories(access_token: str, search: str = "", limit: int = 100):
    """
    Retrieves a list of product categories from Billz.
    """
    if not access_token:
        return {"success": False, "message": "Billz access token missing."}

    try:
        base_url = "https://api-admin.billz.ai/v2/category"
        params = {
            "limit": limit,
            "is_deleted": False,
        }
        headers = {"Authorization": f"Bearer {access_token}"}

        response = requests.get(url=base_url, headers=headers, params=params, timeout=10)
        
        if response.status_code == 200:
            return {"success": True, "categories": response.json().get('categories', [])}
        else:
            return {"success": False, "message": f"API error: {response.status_code} - {response.text}"}
            
    except requests.exceptions.RequestException as e:
        return {"success": False, "message": f"Error retrieving categories: {str(e)}"}

@server.tool()
async def get_brands(access_token: str, search: str = "", limit: int = 100, page: int = 1):
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
            return {"success": True, "brands": response.json().get("brands", [])}
        else:
            return {"success": False, "message": f"API error: {response.status_code} - {response.text}"}
            
    except requests.exceptions.RequestException as e:
        return {"success": False, "message": f"Error retrieving brands: {str(e)}"}



if __name__ == "__main__":
    server.run(transport="stdio")