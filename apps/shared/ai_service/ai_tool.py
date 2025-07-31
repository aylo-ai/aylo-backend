import asyncio
import json
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from apps.shared.mcp_tools.server import get_connection_to_database
from config.settings import client



tools = [
    {
        "type": "function",
        "function": {
            "name": "list_schemas",
            "description": "List all schemas in the database",
            "parameters": {
                "type": "object",
                "properties": {},
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_objects",
            "description": "List objects in a schema",
            "parameters": {
                "type": "object",
                "properties": {
                    "schema_name": {"type": "string", "description": "Schema name"},
                    "object_type": {"type": "string", "description": "Object type: 'table', 'view', 'sequence', or 'extension'"}
                },
                "required": ["schema_name", "object_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_object_details",
            "description": "Show detailed information about a database object",
            "parameters": {
                "type": "object",
                "properties": {
                    "schema_name": {"type": "string", "description": "Schema name"},
                    "object_name": {"type": "string", "description": "Object name"},
                    "object_type": {"type": "string", "description": "Object type: 'table', 'view', 'sequence', or 'extension'"}
                },
                "required": ["schema_name", "object_name", "object_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_sql",
            "description": "Execute a SQL query against the database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "query execute"}
                },
                "required": ["query"]
            }
        }
    },
    {"type": "file_search"}
]

async def assistant_response_mcp(project_database_url,thread_id, message_content, assistant_id):
    server_params = StdioServerParameters(
        command="python",
        args=["-m", "apps.shared.mcp_tools.server"],
    )
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                client.beta.threads.messages.create(
                    thread_id=thread_id,
                    role="user",
                    content=message_content
                )

                # Step 2: Run the assistant
                run_obj = client.beta.threads.runs.create(
                    thread_id=thread_id,
                    assistant_id=assistant_id
                )

                # Step 3: Poll status and handle tools
                while True:
                    run_status = client.beta.threads.runs.retrieve(
                        thread_id=thread_id,
                        run_id=run_obj.id
                    )

                    if run_status.status == "completed":
                        # Assistant finished answering
                        messages = client.beta.threads.messages.list(thread_id=thread_id)
                        assistant_reply = next(
                            (m for m in messages.data if m.role == "assistant"), None
                        )
                        print("\n🧠 Assistant’s Response:")
                        print(assistant_reply.content[0].text.value)
                        print("==================================\n")
                        print("Assistant type", type(assistant_reply.content[0].text.value))
                        response = assistant_reply.content[0].text.value
                        return response, run_status, None

                    elif run_status.status == "requires_action":
                        # Assistant wants to call tools
                        tool_calls = run_status.required_action.submit_tool_outputs.tool_calls
                        tool_outputs = []

                        for tool_call in tool_calls:
                            tool_name = tool_call.function.name
                            arguments = json.loads(tool_call.function.arguments)

                            try:
                                # Run tool via MCP server
                                result = await session.call_tool(tool_name, arguments={**arguments, "database_url": str(project_database_url)})
                                tool_outputs.append({
                                    "tool_call_id": tool_call.id,
                                    "output": str(result)
                                })
                            except Exception as e:
                                tool_outputs.append({
                                    "tool_call_id": tool_call.id,
                                    "output": f"Tool error: {e}"
                                })

                        # Send tool results back to assistant
                        client.beta.threads.runs.submit_tool_outputs(
                            thread_id=thread_id,
                            run_id=run_obj.id,
                            tool_outputs=tool_outputs
                        )

                    else:
                        await asyncio.sleep(1)

