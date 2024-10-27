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
