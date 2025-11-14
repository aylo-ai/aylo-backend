# import requests
# import json

# from django.db.models import Q

# from mcp import ClientSession
# from mcp.server.fastmcp import FastMCP
# from mcp.client.stdio import StdioServerParameters, stdio_client

# server = FastMCP(name='Repli Product Search Tool')

# @server.tool()
# async def search_product(product_name: str, access_token: str):
#     try:
#         base_url = "https://api-admin.billz.ai/v2/"
#         params = {
#             "search": product_name
#         }
#         headers = {
#             "Content-Type": "application/json",
#             "Authorization": f"Bearer {access_token}"
#         }

#         response = requests.get(
#             url=f"{base_url}products/",
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
            
#             # Format product data for the assistant
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
#                 "message": f"API error: {response.status_code}",
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
#             }
#         }
#     }
# ]

# async def get_assistant_response_ai_mcp(thread_id, run_status, run_obj, client, api_token):
#     server_parameters = StdioServerParameters(
#         command="python",
#         args=['-m', 'apps.shared.mcp_server.mcp_server']
#     )
#     async with stdio_client(server_parameters) as (read_stream, write_stream):
#         async with ClientSession(read_stream, write_stream) as session:
#             await session.initialize()
#             tool_calls = (
#                 run_status.required_action.submit_tool_outputs.tool_calls
#             )
#             tool_outputs = []

#             for tool_call in tool_calls:
#                 tool_name = tool_call.function.name
#                 arguments = json.loads(tool_call.function.arguments)

#                 try:
#                     # Run tool via MCP server
#                     result = await session.call_tool(
#                         tool_name,
#                         arguments={
#                             **arguments,
#                             "access_token": api_token,
#                             "product_name": arguments.get("product_name"),
#                         },
#                     )
#                     tool_outputs.append(
#                         {"tool_call_id": tool_call.id, "output": str(result)}
#                     )
#                 except Exception as e:
#                     tool_outputs.append(
#                         {
#                             "tool_call_id": tool_call.id,
#                             "output": f"Tool error: {e}",
#                         }
#                     )

#             # Send tool results back to assistant
#             client.beta.threads.runs.submit_tool_outputs(
#                 thread_id=thread_id,
#                 run_id=run_obj.id,
#                 tool_outputs=tool_outputs,
#             )

# if __name__ == "__main__":
#     server.get_assistant_response_ai_mcp(transport="stdio")