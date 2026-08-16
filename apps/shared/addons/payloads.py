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
