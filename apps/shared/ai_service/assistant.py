import re

import requests

from config import settings
from shared.addons.validations import error_response, success_response
from shared.ai_service.helper import create_prompt, create_vector_store
from shared.ai_service.openai_client import client
from shared.ai_service.thread import wait_on_run
from shared.addons.payloads import valid_intents
from django.utils.translation import gettext_lazy as _

def check_response(response):
    if "*" in response:
        response = response.replace("*", "")

    pattern = r'【[^【】]*?】'
    response = re.sub(pattern, '', response)

    return response


def create_payload_and_assistant(assistant, request=None):
    file_urls = [
        request.build_absolute_uri(file.file.url) if request else file.file.url
        for file in assistant.files.all()
    ]

    instruction = create_prompt(
        assistant.name,
        assistant.company_name,
        assistant.description,
        assistant.role,
        assistant.personality_style,
        assistant.language,
        valid_intents,
        assistant.fallback_message,
        assistant.steps,
        tools=None
    )
    vector_store_id = create_vector_store(file_urls)
    if not vector_store_id:
        return None
    new_assistant = send_assistant_create_request(instruction, assistant.name, vector_store_id)
    if not assistant:
        return None
    print(f"[+] New assistant: {assistant}, assistant_id: {new_assistant.id}, vector_store_id: {vector_store_id}")
    return new_assistant.id, vector_store_id


def send_assistant_create_request(instructions, name, vector_store_id):
    tools = [{"type": "file_search"}]
    tool_resources = {"file_search": {"vector_store_ids": [vector_store_id]}}
    default_model = "gpt-4o"

    try:
        my_assistant = client.beta.assistants.create(
            instructions=instructions,  #change here from instructions.content to instructions
            name=name,
            tools=tools,
            tool_resources=tool_resources,
            model=default_model
        )

        # Check the response type before returning
        if my_assistant is None:
            raise Exception("Assistant creation returned None unexpectedly.")
        print(f"[+] Assistant created: {my_assistant}")
        return my_assistant
    except Exception as e:
        print(f"Error creating assistant: {e}")
        return None


def delete_assistant_by_id(assistant_id: str) -> dict:
    deleted_response = client.beta.assistants.delete(assistant_id=assistant_id)
    print(f"Delete assistant response: {deleted_response}")
    return deleted_response


def update_assistant_id_vector_id(assistant, request):
    assistant_id, vector_id = create_payload_and_assistant(assistant, request)
    if not assistant_id or not vector_id:
        return None
    assistant.assistant_id = assistant_id
    assistant.vector_id = vector_id
    assistant.save()
    print(f"[+] Assistant ID: {assistant.assistant_id}, vector_id: {assistant.vector_id} updated successfully")
    return 200