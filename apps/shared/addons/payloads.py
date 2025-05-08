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

valid_intents = {
    "greeting": "Foydalanuvchi salomlashmoqda yoki muloyimlik bildirayapti",
    "get_price": "Foydalanuvchi mahsulot yoki xizmat narxini so‘raydi",
    "create_order": "Foydalanuvchi buyurtma bermoqchi",
    "cancel_order": "Foydalanuvchi buyurtmani bekor qilmoqchi",
    "get_description": "Foydalanuvchi mahsulot haqida ma'lumot so'raydi",
    "order_confirmation": "Foydalanuvchi buyurtmani tasdiqlashmoqda",
    "get_contact_info": "Foydalanuvchi telefon raqami yoki manzil so‘raydi",
    "get_payment_methods": "Foydalanuvchi to'lov usullarini so'raydi",
    "recommend_product": "Foydalanuvchi mahsulot taklifini so'raydi",
    "register_user": "Foydalanuvchi ro‘yxatdan o‘tmoqchi",
    "track_order": "Foydalanuvchi buyurtma holatini bilmoqchi",
    "contact_support": "Foydalanuvchi yordamchi xodim bilan bog‘lanmoqchi",
    "faq_question": "Foydalanuvchi umumiy savol bermoqda (xizmatlar, ish vaqti)",
    "unknown": "Niyat aniq emas yoki hech biri bilan mos kelmaydi"
}