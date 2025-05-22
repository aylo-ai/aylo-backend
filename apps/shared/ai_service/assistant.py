import re

import requests

from config import settings
from shared.addons.validations import error_response, success_response
from shared.ai_service.helper import create_prompt, create_vector_store
from shared.ai_service.openai_client import client
from shared.ai_service.thread import wait_on_run


def check_response(response):
    """
    Removes asterisks and patterns enclosed within 【】 from the response.
    """
    # Remove asterisks
    if "*" in response:
        response = response.replace("*", "")

    # Remove 【...】 patterns
    pattern = r'【[^【】]*?】'
    response = re.sub(pattern, '', response)

    return response


def get_assistant_response_final(message, assistant_id, thread_id):
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

    wait_on_run(run, thread_id)
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


def create_payload_and_assistant(assistant, request=None):
    file_urls = [
        request.build_absolute_uri(file.file.url) if request else file.file.url
        for file in assistant.files.all()
    ]

    instruction = create_prompt(
        assistant.company_name,
        assistant.description,
        assistant.role,
        assistant.personality_style,
        assistant.language,
    )
    vector_store_id = create_vector_store(file_urls)
    if not vector_store_id:
        return None
    new_assistant = send_assistant_create_request(instruction, assistant.name, vector_store_id)
    if not assistant:
        return None
    print(f"New assistant: {assistant}, assistant_id: {new_assistant.id}, vector_store_id: {vector_store_id}")
    return new_assistant.id, vector_store_id


def send_assistant_create_request(instructions, name, vector_store_id):
    tools = [{"type": "file_search"}]
    tool_resources = {"file_search": {"vector_store_ids": [vector_store_id]}}
    default_model = "gpt-4o"

    try:
        my_assistant = client.beta.assistants.create(
            instructions=instructions.content,  #change here from instructions.content to instructions
            name=name,
            tools=tools,
            tool_resources=tool_resources,
            model=default_model
        )

        # Check the response type before returning
        if my_assistant is None:
            raise Exception("Assistant creation returned None unexpectedly.")
        print(f"Assistant created: {my_assistant}")
        return my_assistant
    except Exception as e:
        print(f"Error creating assistant: {e}")
        return None


def delete_assistant_by_id(assistant_id: str) -> dict:
    BASE_URL = "https://api.openai.com/v1/assistants"
    headers = {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "Content-Type": "application/json",
        "OpenAI-Beta": "assistants=v2",
    }
    url = f"{BASE_URL}/{assistant_id}"

    # Make the DELETE request
    response = requests.delete(url, headers=headers)
    print(f"Delete assistant response: {response.text}")
    if response.status_code == 200:
        return response.json()
    elif response.status_code == 404:
        return error_response(message="Assistant not found", code=404)
    else:
        return error_response(message="Failed to delete assistant", code=response.status_code)


def update_assistant_id_vector_id(assistant, request):
    assistant_id, vector_id = create_payload_and_assistant(assistant, request)
    if not assistant_id or not vector_id:
        return None
    assistant.assistant_id = assistant_id
    assistant.vector_id = vector_id
    assistant.save()
    print(f"Assistant ID: {assistant.assistant_id}, vector_id: {assistant.vector_id} updated successfully")
    return 200