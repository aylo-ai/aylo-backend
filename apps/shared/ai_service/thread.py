import time
from shared.ai_service.openai_client import client


# Updated function to create and run a thread for the initial interaction
def create_and_run_thread(assistant_id, vector_store_id):
    # Start the thread and get the initial run
    try:
        run = client.beta.threads.create_and_run(
            assistant_id=assistant_id,
            tool_resources={"file_search": {"vector_store_ids": [vector_store_id]}},
            tools=[{"type": "file_search"}],
        )
    except Exception as e:
        print(f"Error while creating a run \n {e}")
    # Extract thread_id from the run object
    thread_id = run.thread_id
    return thread_id, run


def wait_on_run(run, thread):
    while run.status in ["queued", "in_progress"]:
        run = client.beta.threads.runs.retrieve(
            thread_id=thread, # this is probelm here thread_id.id dont have so i change to thread it self
            run_id=run.id,
        )
        time.sleep(0.5)
    return run
