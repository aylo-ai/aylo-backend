import requests
from openai import OpenAI

from django.utils.translation import gettext as _
from shared.addons.payloads import create_assistant_payload
from shared.addons.validations import raise_validation_error
from config.settings import OPENAI_API_KEY
from shared.addons.utils import delete_assistant_by_id
from shared.ai_service.helper import create_prompt, create_vector_store, update_vector_store_files_ai
from shared.addons.utils import create_assistant, get_assistant_response_ai
from shared.addons.payloads import valid_intents


BASE_URL = "http://localhost:8080"
# BASE_URL = "https://ai.repli.uz"


def create_assistant_and_vector_id(data: dict):
    payload = {
        "name": data.get("name"),
        "company_name": data.get("company_name"),
        "company_description": data.get("company_description"),
        "assistant_role": data.get("assistant_role"),
        "conversation_style": data.get("conversation_style"),
        "assistant_language": data.get("assistant_language"),
        "file_links": data.get("file_links"),
    }
    print(f"Payload: {payload}")
    try:
        instruction = create_prompt(
            payload.get("company_name"),
            payload.get("company_description"),
            payload.get("assistant_role"),
            payload.get("conversation_style"),
            payload.get("assistant_language"),
            valid_intents,
        )

        file_links = data.get("file_links")
        vector_store_id = create_vector_store(file_links)
        new_assistant = create_assistant(instruction, data.get("name"), vector_store_id)
        print(f"New assistant: {new_assistant}")
        return {
            "assistant_id": new_assistant.id,
            "vector_id": vector_store_id,
        }
    except Exception as e:
        raise_validation_error(message=str(e))


def send_assistant_data(assistant, request=None):
    payload = create_assistant_payload(assistant, request)
    print(f"Assistant data: {payload}")
    data = create_assistant_and_vector_id(payload)
    print(f"assistant data received: {data}")
    if isinstance(data, str):
        raise_validation_error(message=data)
    if data is None:
        raise_validation_error(message="Failed to create assistant: No data returned")
    assistant.assistant_id = data.get("assistant_id") # type: ignore
    assistant.vector_id = data.get("vector_id") # type: ignore
    assistant.save()
    print(f"Assistant ID: {assistant.assistant_id}, vector_id: {assistant.vector_id} created successfully")


def get_assistant_response(message, assistant_id, thread_id):
    print(f"message: {message}, assistant_id: {assistant_id}, thread_id: {thread_id}")
    try:
        # Get the assistant's response
        response = get_assistant_response_ai(
            message=message,
            assistant_id=assistant_id,
            thread_id=thread_id
        )
        return response
    except Exception as e:
        print(f"Error getting assistant response: {e}")
        raise_validation_error(message=str(e))


def delete_assitant(assistant_id):
    if not assistant_id:
        raise_validation_error("assistant_id is required.")

    try:
        deleted_response = delete_assistant_by_id(assistant_id)
        return {
            "message": "Assistant deleted successfully.",
            "data": deleted_response
        }, 200
    except Exception as e:
        raise_validation_error(f"Failed to delete assistant: {e}")

def update_vector_store_files(vector_store_id, new_file_urls):
    updated_assistant = update_vector_store_files_ai(vector_store_id, new_file_urls)
    if updated_assistant is not None:
        print("Vector store updated successfully", updated_assistant)
        return updated_assistant
    else:
        input_field = updated_assistant.get("detail")[0].get("loc")[1]
        message = updated_assistant.get("detail")[0].get("msg")
        error_message = f"{input_field}: {message}"
        print(f"Error updating vector store: {error_message}")
        raise_validation_error(message=error_message)