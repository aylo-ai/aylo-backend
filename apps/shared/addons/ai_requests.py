import requests
from django.utils.translation import gettext as _
from shared.addons.payloads import create_assistant_payload
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
        assistant_id = response.json().get("assistant_id")
        vector_id = response.json().get("vector_id")
        data = {
            "assistant_id": assistant_id,
            "vector_id": vector_id
        }
        return data, 200
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
    data = create_assistant_payload(assistant, request)
    print(f"Assistant data: {data}")
    data, code = create_assistant_id(data)
    print(f"assistant data received: {data}, Code: {code}")
    if code == 400:
        raise_validation_error(message=data)
    assistant.assistant_id = data.get("assistant_id")
    assistant.vector_id = data.get("vector_id")
    assistant.save()
    print(f"Assistant ID: {assistant.assistant_id}, vector_id: {assistant.vector_id} created successfully")


def get_thread_id(assistant_id, vector_id):
    url = f"{BASE_URL}/api/v1/thread/initialize"
    data = {
        "assistant_id": assistant_id,
        "vector_id": vector_id
    }
    response = requests.post(url, json=data)
    if response.status_code == 200:
        thread_id = response.json().get("thread_id")
        return thread_id
    else:
        raise_validation_error(message=_(f"Failed to initialize thread for assistant_id: {assistant_id}"))


def get_assistant_response(message, assistant_id, thread_id):
    payload = {
        "message": message,
        "assistant_id": assistant_id,
        "thread_id": thread_id
    }
    print(f"Payload: {payload}")
    response = requests.post(f"{BASE_URL}/api/v1/assistant/response", json=payload)
    print(f"response text: {response.text}")
    print(f"response status: {response.status_code}, response: {response.json()}")
    if response.status_code == 200:
        return response.json().get("response")
    else:
        input_field = response.json().get("detail")[0].get("loc")[1]
        message = response.json().get("detail")[0].get("msg")
        error_message = f"{input_field}: {message}"
        raise_validation_error(message=error_message)


def delete_assitant(assistant_id):
    payload = {
        "assistant_id": assistant_id
    }
    response = requests.post(f"{BASE_URL}/api/v1/assistant/delete-assistant/", json=payload)
    if response.status_code == 200:
        print("response status: ", response.status_code)
        print("Assistant deleted successfully", response.json())
    else:
        print("Error deleting assistant", response.text)


def update_vector_store_files(vector_store_id, new_file_urls):
    payload = {
        "vector_store_id": vector_store_id,
        "new_file_urls": new_file_urls
    }
    response = requests.post(f"{BASE_URL}/api/v1/assistant/update-vector-id/", json=payload)
    if response.status_code == 200:
        print("Vector store updated successfully", response.json())
        return response.json()
    else:
        input_field = response.json().get("detail")[0].get("loc")[1]
        message = response.json().get("detail")[0].get("msg")
        error_message = f"{input_field}: {message}"
        print(f"Error updating vector store: {error_message}")
        raise_validation_error(message=error_message)


def get_assistant_response(message, assistant_id, thread_id):
    if thread_id is None:
        return "Thread not initialized. Please create an assistant first."

    # Check if an active run exists for the given thread_id
    active_run = client.beta.threads.runs.list(thread_id=thread_id)
    if active_run.data:
        print(f"active run found")
        # Wait for the active run to complete
        wait_on_run(active_run.data[0], thread_id)

    # Send the user's message to the assistant
    user_message = client.beta.threads.messages.create(
        thread_id=thread_id,
        role="user",
        content=f"User: {message}",
    )
    print(f"User message: {user_message}")

    # Start a new assistant run
    run = client.beta.threads.runs.create(
        thread_id=thread_id,
        assistant_id=assistant_id,
    )
    thread_obj = client.beta.threads.retrieve(thread_id)
    wait_on_run(run, thread_obj)
    # Retrieve the assistant's response
    messages = client.beta.threads.messages.list(
        thread_id=thread_id, order="asc", after=user_message.id
    )
    print(f"Assistant response: {messages.data}")

    # Get the response text or a fallback message if empty
    assistant_response = messages.data[0].content[0].text.value if messages.data else "No response received."
    print(f"Assistant response: {assistant_response}")
    clean_response = check_response(assistant_response)

    return clean_response