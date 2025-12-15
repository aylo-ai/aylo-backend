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


def get_assistant_response_ai_mcp(
    *,
    assistant_id: str,
    thread_id: Optional[str],
    message_content: str,
    billz_api_token: str,
    conversation=None,
) -> Tuple[Optional[str], Optional[object], Optional[object]]:
    assistant = Assistant.objects.get(assistant_id=assistant_id)
    if assistant.user.subscription is None:
        return error_response(message=_("Sizning obunangiz tugadi. Iltimos, platformaga kirib, to'lovni qayta amalga oshiring."), code=400), None, None
    subscription = assistant.user.subscription
    if subscription.remained_request_count <= 0 or subscription.status == SubscriptionStatuses.INACTIVE.value:
        return assistant.fallback_message, None, None, None, None
    else:
        if thread_id is None:
            # Return tuple format: (response_message, run_status, response_data)
            return _("Sizda hali assistantga fayl yuklanmagan"), None, None, None, None
        try:
            # Check if an active run exists for the given thread_id
            active_runs = client.beta.threads.runs.list(thread_id=thread_id)
            if active_runs.data:
                # Wait for all active runs to complete
                for run in active_runs.data:
                    wait_on_run(run, thread_id)

            # Send the user's message to the assistant
            user_message = client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=f"User: {message_content}",
            )
            # Start a new assistant run
            run = client.beta.threads.runs.create(
                thread_id=thread_id,
                assistant_id=assistant_id,
            )
            run_status = wait_on_run(run, thread_id)

            # Retrieve the assistant's response
            messages = client.beta.threads.messages.list(
                thread_id=thread_id, order="asc", after=user_message.id
            )
            assistant_response = None

            # Iterate over all messages
            print(f"Messages in get_assistant_response_ai: {messages.data}")
            for msg in messages.data:
                if msg.role == "assistant" and msg.content:
                    for block in msg.content:
                        if block.type == "text":
                            if hasattr(block.text, "value"):
                                assistant_response = block.text.value
                                break  # Found the response, break the inner loop
                            elif isinstance(block.text, str):
                                assistant_response = block.text
                                break

            if assistant_response:
                entities = None
                intent = None
                print(f"Assistant response: {assistant_response}")
                try:
                    assistant_response = json.loads(assistant_response)
                    intent = assistant_response.get("intent", None)
                    message = assistant_response.get("reply", None)
                    entities = assistant_response.get("entities", None)
                    if assistant_response.get("properties",None):
                        response_json = assistant_response.get("properties")
                        intent = response_json.get("intent", None)
                        message = response_json.get("reply", None)
                        entities = response_json.get("entities", None)
                except Exception as e:
                    print(f"Error loading assistant response: {e}")
                    message = assistant_response
                    intent = None

                clean_response = check_response(message)
                handle_unknown_intent(intent, message_content, assistant, conversation)
                        
                response_data = None
                if intent == "order_confirmation":
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

                    username = platform_map.get(conversation.platform) or None
                    response_data = create_update_lead(
                        assistant=assistant,
                        full_name=name,
                        username=username,
                        platform=platform,
                        phone_number=phone_number,
                        email=entities.get('email', None),
                        product=entities.get('product', None),
                        metadata=entities
                    )
                    print("[+] Lead created from Telegram message")
                return clean_response, run_status, response_data, entities, intent
            else:
                print(f"Failed to get assistant response: no runs found for thread_id: {thread_id}")
                return None, None, None, None, None
        except Exception as e:
            print(f"[-] Error  in get_assistant_response_ai: {str(e)}")
            return "", None, None, None, None


def run_assistant_response_ai_mcp_sync(
    *,
    assistant_id: str,
    thread_id: Optional[str],
    message_content: str,
    billz_api_token: str,
    conversation=None,
) -> Tuple[Optional[str], Optional[object], Optional[object], Optional[object], Optional[str]]:
    """
    Synchronous wrapper for get_assistant_response_ai_mcp.
    Returns tuple: (response_message, run_status, response_data)
    """
    return get_assistant_response_ai_mcp(
            assistant_id=assistant_id,
            thread_id=thread_id,
            message_content=message_content,
            billz_api_token=billz_api_token,
            conversation=conversation,
        )
    

