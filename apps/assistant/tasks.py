from celery import shared_task

from shared.addons.ai_requests import create_assistant_id
from shared.addons.validations import raise_validation_error
from .models import AssistantFileUpload, Assistant


@shared_task
def save_uploaded_file(assistant, file_data, filename):
    # Create an instance of the AssistantFileUpload model
    AssistantFileUpload.objects.create(
        assistant=assistant,
        file=file_data,
        filename=filename
    )
    print(f"File uploaded successfully for assistant_id: {assistant.id}")


@shared_task
def finalize_assistant_files(assistant_id):
    # Retrieve the assistant and compile file links
    assistant = Assistant.objects.get(id=assistant_id)
    data = {
        "name": assistant.name,
        "company_name": assistant.company_name,
        "company_description": assistant.description,
        "assistant_role": assistant.role,
        "conversation_style": assistant.personality_style,
        "assistant_language": assistant.language,
        "file_links": [file.file.url for file in assistant.files.all()]
    }
    assistant_id, code = create_assistant_id(data)
    if code == 400:
        raise_validation_error(message=assistant_id)
    assistant.assistant_id = assistant_id
    assistant.save()
    print(f"Assistant ID: {assistant.assistant_id} created successfully")