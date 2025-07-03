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
                        "text": str(message)
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

valid_intents = {
    "greeting": "The user is greeting or being polite",
    "get_price": "The user is asking for the price of a product or service",
    "create_order": "The user wants to place an order",
    "cancel_order": "The user wants to cancel an order",
    "get_description": "The user is asking for information about a product",
    "collect_order_info": "The user is providing or being asked for order details",
    "order_confirmation": "The user is confirming an order",
    "get_contact_info": "The user is asking for a phone number or address",
    "get_payment_methods": "The user is asking about payment methods",
    "recommend_product": "The user is asking for a product recommendation",
    "register_user": "The user wants to register",
    "track_order": "The user wants to know the status of an order",
    "contact_support": "The user wants to contact a support agent",
    "faq_question": "The user is asking a general question (services, working hours, etc.)",
    "unknown": "The intent is unclear or does not match any of the above"
}