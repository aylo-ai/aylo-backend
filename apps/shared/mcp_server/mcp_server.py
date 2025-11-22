# import json
# import requests

# from mcp import ClientSession
# from mcp.server.fastmcp import FastMCP
# from mcp.client.stdio import StdioServerParameters, stdio_client

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
        
#         if response.status_code == 200:
#             response_json = response.json()
#             products = response_json.get('results', [])
            
#             if not products:
#                 return {
#                     "success": False,
#                     "message": f"No products found matching '{product_name}'",
#                     "products": []
#                 }
            
#             formatted_products = []
#             for product in products[:5]:  # Limit to top 5 results
#                 formatted_products.append({
#                     "id": product.get("id"),
#                     "name": product.get("name"),
#                     "price": product.get("price"),
#                     "description": product.get("description", ""),
#                     "in_stock": product.get("in_stock", True),
#                     "category": product.get("category", ""),
#                 })
            
#             return {
#                 "success": True,
#                 "message": f"Found {len(formatted_products)} product(s) matching '{product_name}'",
#                 "products": formatted_products,
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


# tools = [
#     {
#         "type":"function",
#         "function": {
#             "name":"search_product",
#             "description":"""
#     Search for products in the external product catalog (Billz.ai).
#     Use this tool when:
#     - User asks about product availability
#     - User wants to know product details (price, description, stock)
#     - User asks "do you have [product]?"
#     - User wants to browse products by category or name
#     """,
#     "parameters": {
#                 "type": "object",
#                 "properties": {
#                     "access_token": {
#                         "type": "string",
#                         "description": "Bearer token for API authentication"
#                 },
#                 "product_name": {
#                     "type": "string",
#                     "description": "The name or keyword of the product to search for"
#                 },  
#             },
#             "required": ["product_name"]
#             }
#         }
#     }
# ]

# async def get_assistant_response_ai_mcp(thread_id, run_status, run_obj, client, api_token):
#     required_action = getattr(run_status, "required_action", None)
#     if not required_action or not getattr(required_action, "submit_tool_outputs", None):
#         return

#     server_parameters = StdioServerParameters(
#         command="python",
#         args=['-m', 'apps.shared.mcp_server.mcp_server']
#     )
#     async with stdio_client(server_parameters) as (read_stream, write_stream):
#         async with ClientSession(read_stream, write_stream) as session:
#             await session.initialize()
#             tool_calls = required_action.submit_tool_outputs.tool_calls
#             if not tool_calls:
#                 return

#             tool_outputs = []
#             token_error_message = None
#             if not api_token:
#                 token_error_message = (
#                     "Billz integration is not configured. "
#                     "Please add a Billz secret token to this assistant."
#                 )

#             for tool_call in tool_calls:
#                 try:
#                     arguments = json.loads(tool_call.function.arguments)
#                 except json.JSONDecodeError:
#                     tool_outputs.append(
#                         {
#                             "tool_call_id": tool_call.id,
#                             "output": "Invalid arguments supplied for Billz search.",
#                         }
#                     )
#                     continue

#                 if token_error_message:
#                     tool_outputs.append(
#                         {
#                             "tool_call_id": tool_call.id,
#                             "output": token_error_message,
#                         }
#                     )
#                     continue

#                 product_name = arguments.get("product_name")
#                 if not product_name:
#                     tool_outputs.append(
#                         {
#                             "tool_call_id": tool_call.id,
#                             "output": "Product name is required for the Billz search tool.",
#                         }
#                     )
#                     continue

#                 try:
#                     result = await session.call_tool(
#                         tool_call.function.name,
#                         arguments={
#                             **arguments,
#                             "access_token": api_token,
#                             "product_name": product_name,
#                         },
#                     )
#                     output_payload = (
#                         result
#                         if isinstance(result, str)
#                         else json.dumps(result, ensure_ascii=False)
#                     )
#                     tool_outputs.append(
#                         {"tool_call_id": tool_call.id, "output": output_payload}
#                     )
#                 except Exception as e:
#                     tool_outputs.append(
#                         {
#                             "tool_call_id": tool_call.id,
#                             "output": f"Tool error: {e}",
#                         }
#                     )

#             client.beta.threads.runs.submit_tool_outputs(
#                 thread_id=thread_id,
#                 run_id=run_obj.id,
#                 tool_outputs=tool_outputs,
#             )

# if __name__ == "__main__":
#     server.get_assistant_response_ai_mcp(transport="stdio")