import time
import logging

from django.utils.translation import gettext_lazy as _

from shared.ai_service.openai_client import client
from shared.addons.validations import raise_validation_error


logger = logging.getLogger(__name__)


class ThreadService:
    def __init__(self):
        self.client = client

    def create_and_run_thread(self, assistant_id, vector_store_id):
        try:
            run = self.client.beta.threads.create_and_run(
                assistant_id=assistant_id,
                tool_resources={"file_search": {"vector_store_ids": [vector_store_id]}},
                tools=[{"type": "file_search"}],
            )
            thread_id = run.thread_id
            return thread_id, run
        except Exception as e:
            logger.error(f"Error while creating a run: {e}")
            return None, None
        
    def check_thread_exists(self, thread_id):
        try:
            thread = client.beta.threads.runs.list(thread_id=thread_id)
            if thread.data:
                return True
            else:
                return False
        except Exception as e:
            print(f"Error checking thread exists: {e}")
            return False

    def wait_on_run(self, run, thread_id):
        while run.status in ["queued", "in_progress"]:
            run = self.client.beta.threads.runs.retrieve(
                thread_id=thread_id,
                run_id=run.id,
            )
            time.sleep(0.5)
        return run

    def get_thread_id(self, assistant_id, vector_id):
        if assistant_id is None or vector_id is None:
            raise_validation_error(
                message=_(
                    f"Assistant or vector id is not found: {assistant_id}"
                )
            )
        thread_id, _ = self.create_and_run_thread(assistant_id, vector_id)
        if thread_id is not None:
            return thread_id
        raise_validation_error(
            message=_(
                f"Failed to initialize thread for error: {assistant_id}"
            )
        )

thread_service = ThreadService()
