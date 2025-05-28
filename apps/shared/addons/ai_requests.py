import requests
from openai import OpenAI

from django.utils.translation import gettext as _
from shared.addons.payloads import create_assistant_payload
from shared.addons.validations import raise_validation_error
from config.settings import OPENAI_API_KEY
from shared.addons.utils import delete_assistant_by_id
from shared.ai_service.helper import create_prompt, create_vector_store, update_vector_store_files_ai
from shared.addons.utils import create_assistant
from shared.addons.payloads import valid_intents


BASE_URL = "http://localhost:8080"
# BASE_URL = "https://ai.repli.uz"


def create_assistant_and_vector_id(assistant, request=None):
    file_urls = [
    request.build_absolute_uri(file.file.url) if request else file.file.url
    for file in assistant.files.all()
        ]

    try:
        instruction = create_prompt(
            assistant.company_name,
            assistant.description,
            assistant.role,
            assistant.personality_style,
            assistant.language,
            valid_intents,
            assistant.fallback_message
        )

        vector_store_id = create_vector_store(file_urls=file_urls)
        new_assistant = create_assistant(instruction, assistant.name, vector_store_id)
        print(f"New assistant: {new_assistant}")
        # save assistant_id and vector_id to assistant
        assistant.assistant_id = new_assistant.id
        assistant.vector_id = vector_store_id
        assistant.save()
        return True, "Successfully created assistant and vector id"
    except Exception as e:
        return False, str(e)



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