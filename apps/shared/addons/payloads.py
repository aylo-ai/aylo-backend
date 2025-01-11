from datetime import timedelta
from django.utils.timezone import now


def get_playmobile_payload(recipient: str, message_id: str, originator: str, message: str):
    return {
        "messages": [
            {
                "recipient": f"{recipient}",
                "message-id": f"{message_id}",
                "sms": {
                    "originator": f"{originator}",
                    "content": {
                        "text": message
                    }
                }
            }
        ]
    }


def create_assistant_payload(assistant, request=None):
    file_urls = [
        request.build_absolute_uri(file.file.url) if request else file.file.url
        for file in assistant.files.all()
    ]
    return {
        "name": assistant.name,
        "company_name": assistant.company_name,
        "company_description": assistant.description,
        "assistant_role": assistant.role,
        "conversation_style": assistant.personality_style,
        "assistant_language": assistant.language,
        "file_links": file_urls
    }


def create_file_urls(assistant, request=None):
    file_urls = [
        request.build_absolute_uri(file.file.url) if request else file.file.url
        for file in assistant.files.all()
    ]
    return file_urls