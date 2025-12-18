import time
import logging

from django.utils.translation import gettext_lazy as _

from shared.ai_service.openai_client import client
from shared.addons.validations import raise_validation_error


logger = logging.getLogger(__name__)


class ThreadService:
    """
    Central service for creating threads/runs and waiting on them.
    """

    def __init__(self):
        self.client = client

    def create_and_run_thread(self, assistant_id, vector_store_id):
        """
        Create a new thread and run for the given assistant/vector store.
        Returns (thread_id, run) or (None, None) on error.
        """
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

    def wait_on_run(self, run, thread_id):
        """
        Poll a run until it is completed/failed and return the final run object.
        """
        while run.status in ["queued", "in_progress"]:
            run = self.client.beta.threads.runs.retrieve(
                thread_id=thread_id,
                run_id=run.id,
            )
            time.sleep(0.5)
        return run

    def get_thread_id(self, assistant_id, vector_id):
        """
        Public helper to get/create a thread id for an assistant/vector pair.
        """
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
