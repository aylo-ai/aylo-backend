import mimetypes
from io import BytesIO
from typing import List

import requests
from openai import OpenAIError

from shared.addons.validations import error_response
from shared.ai_service.openai_client import client
from shared.addons.payloads import valid_intents


SUPPORTED_MIME_TYPES = {
    "application/octet-stream", "application/pdf", "application/csv", "image/gif", "text/x-script.python",
    "application/zip", "text/javascript", "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/x-c", "text/csv", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "image/png", "text/plain", "text/x-php", "application/typescript", "application/x-tar", "text/x-python",
    "text/html", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "text/css",
    "text/x-csharp", "text/markdown", "application/xml", "text/x-c++", "text/xml", "application/json",
    "image/jpeg", "text/x-sh", "text/x-java", "text/x-tex", "application/msword", "image/webp", "text/x-ruby",
    "text/x-typescript"
}


def extract_text_from_txt_files(txt_file_path):
    text = ""
    with open(txt_file_path, 'r', encoding='utf-8') as file:
        text += file.read()
    return text[:2000]  # Limit text to the first 2000 characters


def create_prompt(company_name, company_description, assistant_role, conversation_style, assistant_language, valid_intents):
    print(f"create_prompt: {company_name}, {company_description}, {assistant_role}, {conversation_style}, {assistant_language}")

    # 1. Format valid intents
    intent_section = "\n".join([
        f'- "{intent}": {desc}' for intent, desc in valid_intents.items()
    ])

    # 2. Prompt template with double braces for JSON safety inside f-string
    prompt_template = f"""
    You are an AI assistant for "{company_name}", described as: "{company_description}".
    You act as a smart **salesperson, operator, and support agent**.
    You are an expert in {assistant_role} and act as a good operator who handles everything.

    ## Role & Responsibilities
    Your role is: **{assistant_role}**.
    You are a helpful agent guiding customers through buying, asking questions, and 
    getting support. You're charming, smart, and always reply in {assistant_language} 
    using a {conversation_style} tone.

    ## Goals
    - Understand customer needs and classify their request into intents.
    - Ask questions to clarify, gather info, and help them.
    - Collect relevant data (products, quantities, user info).
    - Always reply in {assistant_language}, using a {conversation_style} tone.
    - Respond naturally, persuasively, and clearly — like a helpful human with charm.
    - Encourage conversation with friendly chat-like responses.
    - Include emojis 😊 📞 ✅ ❌ 📦 📍 💬 where appropriate.
    - If user wants to buy something, you need to register them first.
    - Format all replies in strict JSON (see below).

    ---

    ## 🎯 Intent Classification
    Set the `intent` based on user requests and use json format for response.

    ## 🧾 Reply Format (Strict!)
    Always reply ONLY in this JSON format:

    {{
    "intent": "<one of the valid intents below>",
    "entities": {{
        "<product_name>": "<value>"
    }},
    "reply": "Friendly, clear and helpful message to the user 😊"
    }}

    ---

    ## 💡 Valid Intents & Descriptions

    {intent_section}

    ---

    ## 🤖 Response Examples

    User: "Iphone 14 bormi?"

    Response:
    {{
    "intent": "get_availability",
    "entities": {{
        "product": "iPhone 14"
    }},
    "reply": "📱 Ha, iPhone 14 mavjud! Sizga qaysi rang yoki xotira hajmi kerak? 😊"
    }}

    User: "Buyurtma bermoqchiman"

    Response:
    {{
    "intent": "ask_to_register",
    "entities": {{}},
    "reply": "😊 Ajoyib! Buyurtmani boshlashdan oldin, sizni ro'yxatdan o'tkazishim mumkinmi?"
    }}

    User: "Narxi qancha?"

    Response:
    {{
    "intent": "get_price",
    "entities": {{}},
    "reply": "📦 Qaysi mahsulotni nazarda tutayapsiz? Nomi yoki modeli bilan ayting, iltimos. 😊"
    }}

    ---

    ## 🔄 Smart Flow Guidelines

    - If user wants to buy or get something, start with:
    - `ask_to_register`: ask full name and phone number.
    - Then `get_contact_info`: after collecting info, add reason field (what they want).

    - **Order Creation Flow**:
    1. collect_user_info → ask full name and phone number
    2. collect_order_info → ask what the user wants
    3. order_confirmation → confirm order
    4. create_order → create the lead ✅

    - **Missing Intent?** Use:
    {{
    "intent": "unknown",
    "entities": {{}},
    "reply": "😕 Kechirasiz, sizni to‘g‘ri tushuna olmadim. Iltimos, yana bir bor yozib ko‘ring yoki operator bilan bog‘laning 📞."
    }}
    """

    return prompt_template



def upload_knowledge_base_file(file_url):
    # Determine MIME type and check if it’s supported
    mime_type, _ = mimetypes.guess_type(file_url)

    if mime_type not in SUPPORTED_MIME_TYPES:
        print(f"Unsupported file format: {mime_type}. Skipping file: {file_url}")
        return None

    try:
        # Download the file content and check that it's non-empty
        response = requests.get(file_url)
        response.raise_for_status()

        if not response.content:
            print(f"File at {file_url} is empty. Skipping upload.")
            return None

        # Prepare file for upload
        file_content = BytesIO(response.content)
        file_content.seek(0)
        file_content.name = file_url.split("/")[-1]
        file = client.files.create(
            file=file_content,
            purpose="assistants"
        )
        print(f"Uploaded file ID: {file.id} for URL: {file_url}")
        return file.id

    except requests.exceptions.RequestException as e:
        print(f"Connection error when downloading file from {file_url}: {e}")
        return None
    except Exception as e:
        print(f"Error uploading file: {e}")
        return None


# Function to create a vector store for the knowledge base from multiple files
def create_vector_store(file_urls):
    file_ids = []

    # Upload each file and collect valid file IDs
    for file_url in file_urls:
        file_id = upload_knowledge_base_file(file_url)
        if file_id:
            file_ids.append(file_id)

    # Ensure there are valid files for vector store creation
    if not file_ids:
        print("No valid files available for vector store creation.")
        return None

    try:
        # Create a vector store from collected file IDs
        vector_store = client.vector_stores.create(
            file_ids=file_ids,
        )
        print(f"Vector store created with ID: {vector_store.id}")
        return vector_store.id

    except Exception as e:
        print(f"Error creating vector store: {e}")
        return None


def update_vector_store_files_ai(vector_store_id: str, new_file_urls: List[str]) -> dict:

    # Upload new files and collect their file IDs
    new_file_ids = []
    for file_url in new_file_urls:
        try:
            file_id = upload_knowledge_base_file(file_url)
            if file_id:
                new_file_ids.append(file_id)
            else:
                raise ValueError(f"Failed to upload file from URL: {file_url}")
        except Exception as e:
            return error_response(message=f"Error uploading file from URL: {file_url}, Error: {str(e)}", code=400)

    if not new_file_ids:
        print("No valid file IDs obtained from provided URLs.")
        return error_response(
            message="No valid file IDs obtained from provided URLs.",
            code=400
        )

    try:
        # Replace the current files in the vector store with the new file IDs
        batch_response = client.beta.vector_stores.file_batches.create(
            vector_store_id=vector_store_id,
            file_ids=new_file_ids
        )
        return {
            "message": "Files replaced successfully.",
            "batch_id": batch_response.id
        }
    except OpenAIError as e:
        return error_response(
            message=f"OpenAI API error: {str(e)}",
            code=400
        )
    except Exception as e:
        return error_response(
            message=f"Error updating vector store files: {str(e)}",
            code=400
        )
