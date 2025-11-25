# import requests
# import logging
# from mcp.server.fastmcp import FastMCP

# server = FastMCP(name='Repli Product Search Tool')

# @server.tool()
# async def search_product(product_name: str, access_token: str):
#     if not product_name:
#         return {
#             "success": False,
#             "message": "Product name is required to search the catalog.",
#             "products": [],
#         }

#     if not access_token:
#         return {
#             "success": False,
#             "message": "Billz access token missing. Connect the Billz integration.",
#             "products": [],
#         }

#     try:
#         base_url = "https://api-admin.billz.ai/v2/products"
#         params = {
#             "search": product_name,
#             "limit": 5,
#         }
#         headers = {
#             "Content-Type": "application/json",
#             "Authorization": f"Bearer {access_token}"
#         }

#         response = requests.get(
#             url=base_url,
#             headers=headers,
#             params=params,
#             timeout=10
#         )
#         logging.info(f"response: {response.json()}")
        
#         if response.status_code == 200:
#             response_json = response.json()
#             products = response_json.get('products', [])
            
#             if not products:
#                 return {
#                     "success": False,
#                     "message": f"No products found matching '{product_name}'",
#                     "products": []
#                 }
            
            
#             return {
#                 "success": True,
#                 "message": f"Found {len(products)} product(s) matching '{products}'",
#                 "products": products,
#                 "total_found": len(products)
#             }
#         else:
#             return {
#                 "success": False,
#                 "message": f"API error: {response.status_code} - {response.text}",
#                 "products": []
#             }
            
#     except requests.exceptions.Timeout:
#         return {
#             "success": False,
#             "message": "Product search timed out. Please try again.",
#             "products": []
#         }
#     except Exception as e:
#         return {
#             "success": False,
#             "message": f"Error searching products: {str(e)}",
#             "products": []
#         }


tools = [
    {
        "type":"function",
        "function": {
            "name":"search_product",
            "description":"""
    Search for products in the external product catalog (Billz.ai).
    Use this tool when:
    - User asks about product availability
    - User wants to know product details (price, description, stock)
    - User asks "do you have [product]?"
    - User wants to browse products by category or name
    """,
    "parameters": {
                "type": "object",
                "properties": {
                    "access_token": {
                        "type": "string",
                        "description": "Bearer token for API authentication"
                },
                "product_name": {
                    "type": "string",
                    "description": "The name or keyword of the product to search for"
                },  
            },
            "required": ["product_name"]
            }
        }
    }
]


# if __name__ == "__main__":
#     server.run(transport="stdio")