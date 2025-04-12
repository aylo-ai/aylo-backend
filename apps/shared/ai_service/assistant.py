import re

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