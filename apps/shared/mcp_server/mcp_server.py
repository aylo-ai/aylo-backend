from google import genai
from google.genai import types

from mcp.server.fastmcp import FastMCP

from config import settings

client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY)

server = FastMCP(name='Repli MCP')

@server.tool()
async def search_file_vectore_store(self, query: str, vectore_store_name: str):
        base_promt = f"""
        You are a Product Inventory Analyst. Use the knowledge base files to determine status.
        Analyze this query: {query}   
        RULES:
        1. Status mapping:
            - IN STOCK or LIMITED → "available"
            - DISCONTINUED → "unavailable"
            - Not mentioned or no close match found → "notproduced"
        2. For category queries (e.g., "phone cases"), if products exist in that category → "available"
        3. Return the EXACT product name from the knowledge base, correcting any user typos.
        4. If the information in the file is ambiguous, favor "notproduced".

        RESPONSE FORMAT (JSON only):
        {{
            "status": "available|unavailable|notproduced",
            "product_name": "Exact name from file",
            "reasoning": "Brief explanation"
        }}
                """
        
        response = client.models.generate_content(
            model = "gemini-2.5-pro",
            contents = base_promt,
            response_mime_type="application/json",
            config = types.GenerateContentConfig(
                    tools=[types.Tool(
                        file_search=types.FileSearch(
                            file_search_store_names=[vectore_store_name]
                        )
                    )]
                )
            )
        sources = []
        if response.candidates and response.candidates[0].grounding_metadata:
            grounding = response.candidates[0].grounding_metadata
            if grounding.grounding_chunks:
                sources = list({
                    chunk.retrieved_context.title 
                    for chunk in grounding.grounding_chunks 
                    if hasattr(chunk, 'retrieved_context')
                })
                print(f"   📚 Grounding sources: {sources}")

        response = self.clean_response(response.text)

        return response

if __name__ == "__main__":
    server.run(transport="stdio")