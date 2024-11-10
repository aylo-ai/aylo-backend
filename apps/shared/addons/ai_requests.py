import requests

from shared.addons.payloads import get_assistant_data
from shared.addons.validations import raise_validation_error

# BASE_URL = "http://localhost:8000"
BASE_URL = "https://ai.repli.uz"


def create_assistant_id(data: dict):
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
    response = requests.post(f"{BASE_URL}/api/v1/assistant/", json=payload)
    print(f"Response: {response.json()}, Status code: {response.status_code}")
    if response.status_code == 200:
        return response.json().get("assistant_id"), 200
    else:
        input_field = response.json().get("detail")[0].get("loc")[1]
        message = response.json().get("detail")[0].get("msg")
        error_message = f"{input_field}: {message}"
        return error_message, 400


def save_uploaded_file(assistant, file_data, filename):
    # Create an instance of the AssistantFileUpload model
    # AssistantFileUpload.objects.create(
    #     assistant=assistant,
    #     file=file_data,
    #     filename=filename
    # )
    print(f"File uploaded successfully for assistant_id: {assistant.id}")


def send_assistant_data(assistant, request=None):
    data = get_assistant_data(assistant, request)
    assistant_id, code = create_assistant_id(data)
    if code == 400:
        raise_validation_error(message=assistant_id)
    assistant.assistant_id = assistant_id
    assistant.save()
    print(f"Assistant ID: {assistant.assistant_id} created successfully")


def get_thread_id(assistant_id):
    url = f"{BASE_URL}/api/v1/thread/initialize"
    data = {
        "assistant_id": assistant_id
    }
    response = requests.post(url, json=data)
    if response.status_code == 200:
        thread_id = response.json().get("thread_id")
        return thread_id
    else:
        input_field = response.json().get("detail")[0].get("loc")[1]
        message = response.json().get("detail")[0].get("msg")
        error_message = f"{input_field}: {message}"
        raise_validation_error(message=error_message)


def get_assistant_response(message, assistant_id, thread_id):
    payload = {
        "message": message,
        "assistant_id": assistant_id,
        "thread_id": thread_id
    }
    response = requests.post(f"{BASE_URL}/api/v1/assistant/response", json=payload)
    if response.status_code == 200:
        return response.json().get("response")
    else:
        input_field = response.json().get("detail")[0].get("loc")[1]
        message = response.json().get("detail")[0].get("msg")
        error_message = f"{input_field}: {message}"
        raise_validation_error(message=error_message)