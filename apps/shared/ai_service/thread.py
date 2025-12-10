import time
from shared.ai_service.openai_client import client


def create_and_run_thread(assistant_id, vector_store_id):
    try:
        run = client.beta.threads.create_and_run(
            assistant_id=assistant_id,
            tool_resources={"file_search": {"vector_store_ids": [vector_store_id]}},
            tools=[{"type": "file_search"}],
        )
    except Exception as e:
        print(f"Error while creating a run \n {e}")
    thread_id = run.thread_id
    return thread_id, run


def wait_on_run(run, thread_id):
    while run.status in ["queued", "in_progress"]:
        run = client.beta.threads.runs.retrieve(
            thread_id=thread_id,
            run_id=run.id,
        )
        time.sleep(0.5)
    return run
