import asyncio
import logging
import json
from typing import Optional, Tuple

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from asgiref.sync import sync_to_async

from config.settings import client
from apps.assistant.models import Assistant
from shared.addons.enums import SubscriptionStatuses, ConversationPlatforms
from shared.addons.validations import error_response
from shared.ai_service.assistant import check_response
from shared.ai_service.thread import wait_on_run
from shared.addons.utils import handle_unknown_intent, create_update_lead
from django.utils.translation import gettext_lazy as _

BILLZ_SERVER_MODULE = "apps.shared.mcp_server.mcp_server"


def get_thread_id() -> str:
    thread = client.beta.threads.create()
    return thread.id


async def get_assistant_response_ai_mcp(
    *,
    assistant_id: str,
    thread_id: Optional[str],
    message_content: str,
    billz_api_token: str,
    conversation=None,
) -> Tuple[Optional[str], Optional[object], Optional[object]]:
    """
    Get assistant response using MCP server.
    Returns tuple: (response_message, run_status, response_data)
    """
    if not billz_api_token:
        raise ValueError("Billz API token is required to execute product searches.")

    # Check assistant exists and subscription status
    @sync_to_async
    def get_assistant_and_check_subscription():
        try:
            assistant = Assistant.objects.select_related('user__subscription').get(assistant_id=assistant_id)
        except Assistant.DoesNotExist:
            return None, None, None, None
        
        if assistant.user.subscription is None:
            error_msg = error_response(message=_("Sizning obunangiz tugadi. Iltimos, platformaga kirib, to'lovni qayta amalga oshiring."), code=400)
            return None, error_msg, None, None
        
        subscription = assistant.user.subscription
        if subscription.remained_request_count <= 0 or subscription.status == SubscriptionStatuses.INACTIVE.value:
            return assistant, None, assistant.fallback_message, None
        
        return assistant, None, None, None
    
    assistant, error_msg, fallback_msg, _ = await get_assistant_and_check_subscription()
    
    if assistant is None:
        logging.error(f"Assistant with id {assistant_id} not found")
        return "", None, None
    
    # Check thread_id
    if thread_id is None:
        return _("Sizda hali assistantga fayl yuklanmagan"), None, None

    try:
        # Check if an active run exists for the given thread_id
        active_runs = client.beta.threads.runs.list(thread_id=thread_id)
        if active_runs.data:
            # Wait for all active runs to complete
            for run in active_runs.data:
                wait_on_run(run, thread_id)

        server_params = StdioServerParameters(
            command="python",
            args=["-m", BILLZ_SERVER_MODULE],
        )

        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                # Send the user's message to the assistant
                user_message = client.beta.threads.messages.create(
                    thread_id=thread_id,
                    role="user",
                    content=f"User: {message_content}",
                )

                # Start a new assistant run
                run_obj = client.beta.threads.runs.create(
                    thread_id=thread_id,
                    assistant_id=assistant_id,
                )

                while True:
                    run_status = client.beta.threads.runs.retrieve(
                        thread_id=thread_id,
                        run_id=run_obj.id,
                    )

                    if run_status.status == "completed":
                        # Retrieve the assistant's response
                        messages = client.beta.threads.messages.list(
                            thread_id=thread_id,
                            order="asc",
                            after=user_message.id,
                        )
                        
                        assistant_response = None
                        # Iterate over all messages
                        print(f"Messages in get_assistant_response_ai_mcp: {messages}")
                        for msg in messages.data:
                            if msg.role == "assistant" and msg.content:
                                # Extract text content blocks
                                for block in msg.content:
                                    if block.type == "text" and hasattr(block.text, "value"):
                                        assistant_response = block.text.value

                        if assistant_response:
                            print(f"Assistant response: {assistant_response}")
                            try:
                                assistant_response = json.loads(assistant_response)
                                intent = assistant_response.get("intent", None)
                                message = assistant_response.get("reply", None)
                                entities = assistant_response.get("entities", None)
                                if assistant_response.get("properties", None):
                                    response_json = assistant_response.get("properties")
                                    intent = response_json.get("intent", None)
                                    message = response_json.get("reply", None)
                                    entities = response_json.get("entities", None)
                            except Exception as e:
                                print(f"Error loading assistant response: {e}")
                                message = assistant_response
                                intent = None
                                entities = None

                            clean_response = check_response(message)
                            
                            # Handle unknown intent if conversation is provided
                            if conversation:
                                @sync_to_async
                                def handle_intent():
                                    handle_unknown_intent(intent, message_content, assistant, conversation)
                                await handle_intent()
                            
                            response_data = None
                            if intent == "order_confirmation" and conversation and entities:
                                @sync_to_async
                                def create_lead():
                                    name = (
                                        entities.get('name') or 
                                        entities.get('full_name') or 
                                        entities.get('customer_user') or 
                                        entities.get('customer_name') or 
                                        None
                                    )
                                    phone_number = (
                                        entities.get('phone_number') or 
                                        entities.get('contact_number') or 
                                        None
                                    )
                                    platform = conversation.platform if conversation.platform else None
                                    platform_map = {
                                        ConversationPlatforms.INSTAGRAM.value: conversation.client_full_name,
                                        ConversationPlatforms.TELEGRAM.value: conversation.username,
                                    }
                                    username = platform_map.get(conversation.platform) if conversation.platform else None
                                    
                                    return create_update_lead(
                                        assistant=assistant,
                                        full_name=name,
                                        username=username,
                                        platform=platform,
                                        phone_number=phone_number,
                                        email=entities.get('email', None),
                                        product=entities.get('product', None),
                                        metadata=entities
                                    )
                                
                                response_data = await create_lead()
                                print("[+] Lead created from MCP message")
                            
                            return clean_response, run_status, response_data
                        
                        return None, run_status, None

                    if run_status.status == "requires_action":
                        required = run_status.required_action.submit_tool_outputs
                        tool_calls = required.tool_calls if required else []
                        tool_outputs = []

                        for tool_call in tool_calls:
                            tool_name = tool_call.function.name
                            try:
                                arguments = json.loads(tool_call.function.arguments)
                            except json.JSONDecodeError:
                                arguments = {}

                            arguments["access_token"] = billz_api_token

                            try:
                                result = await session.call_tool(
                                    tool_name,
                                    arguments=arguments,
                                )
                                print(f"[+] Tool result: {result} and tool name: {tool_name}")
                                
                            except Exception as exc:
                                result = f"Tool error: {exc}"

                            tool_outputs.append(
                                {"tool_call_id": tool_call.id, "output": str(result)}
                            )

                        client.beta.threads.runs.submit_tool_outputs(
                            thread_id=thread_id,
                            run_id=run_obj.id,
                            tool_outputs=tool_outputs,
                        )
                        continue

                    await asyncio.sleep(1)
                    
    except Exception as e:
        print(f"[-] Error in get_assistant_response_ai_mcp: {str(e)}")
        logging.error(f"Error in get_assistant_response_ai_mcp: {str(e)}")
        return "", None, None


def run_assistant_response_ai_mcp_sync(
    *,
    assistant_id: str,
    thread_id: Optional[str],
    message_content: str,
    billz_api_token: str,
    conversation=None,
) -> Tuple[Optional[str], Optional[object], Optional[object]]:
    """
    Synchronous wrapper for get_assistant_response_ai_mcp.
    Returns tuple: (response_message, run_status, response_data)
    """
    return asyncio.run(
        get_assistant_response_ai_mcp(
            assistant_id=assistant_id,
            thread_id=thread_id,
            message_content=message_content,
            billz_api_token=billz_api_token,
            conversation=conversation,
        )
    )

