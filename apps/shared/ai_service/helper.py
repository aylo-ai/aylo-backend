import mimetypes
from io import BytesIO
from typing import List

import requests
from openai import OpenAIError

from shared.addons.validations import error_response
from shared.ai_service.openai_client import client
from django.utils.translation import gettext_lazy as _

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


def create_prompt(company_name, company_description, assistant_role, conversation_style, assistant_language, valid_intents, fallback_message):
    """
    Generate a structured prompt for an AI assistant, including intent classification, reply format, and flow guidelines.
    """
    print(f"create_prompt: {company_name}, {company_description}, {assistant_role}, {conversation_style}, {assistant_language}")

    # Format valid intents for display
    intent_section = "\n".join([
        f'- "{intent}": {desc}' for intent, desc in valid_intents.items()
    ])

    prompt_template = f"""
        You are an AI assistant for "{company_name}" ({company_description}).
        Your expertise: {assistant_role}. You act as a helpful, charming operator.

        # ⚠️ Critical Constraint
        You MUST ONLY respond based on the uploaded knowledge files.
        Never assume, invent, or hallucinate information. If the answer cannot be found in the documents, do **not guess**. Instead, say you don't know.

        # 💬 Role & Tone
        - Must respond in {assistant_language} with a {conversation_style} tone.
        - Be friendly, clear, and helpful — like a well-trained human operator.
        - Use relevant emojis (😊 📞 ✅ ❌ 📦 📍 💬) where appropriate, but do not sacrifice clarity.
        - Never add marketing fluff or false information.

        # 🎯 Goals
        - Understand user intent from their message and classify it using the valid intents list below.
        - Extract any relevant entities such as product names, quantities, user info, etc.
        - Ask clarifying questions only if necessary.
        - If a user expresses intent to buy, collect name and phone number first.
        - Responses MUST always follow the strict JSON format shown below.

        # 🧾 Reply Format (Strict JSON Only)
        Respond strictly in this JSON format — nothing else:

        {{
        "intent": "<one of the valid intents below>",
        "entities": {{
            "<entity_name>": "<value>"
        }},
        "reply": "Clear, helpful response based strictly on the documents 😊"
        }}

        # 💡 Intent List
        Use one of the following intents when responding:

        {intent_section}

        # ⛔ Unknown or Out-of-Scope Responses

        If the answer is not available in the uploaded documents, respond with this format:

        - If a product is mentioned, use:

        {{
        "intent": "unknown",
        "entities": {{
            "product": "<name mentioned by user>"
        }},
        "reply": "❌ Sorry, we couldn't find information about the \"<product>\" product you asked about. 
                    Please ask another question or contact our operator. 📞" use {assistant_language} this language
        }}

        - If there is no specific product mentioned or it's just unclear:

        {{
        "intent": "unknown",
        "entities": {{}},
        "reply": "😕 Sorry, I couldn't understand your question properly. 
                    Please clarify your question or contact our operator. 📞" use {assistant_language} this language
        }}

        # 📂 File-Aware Behavior
        - Before answering, mentally "search" the uploaded files to locate any relevant info.
        - If a product, service, price, or location is NOT mentioned in the uploaded files, you must respond with `intent: "unknown"`.
        - Do not rely on examples or prior patterns — ONLY rely on the uploaded documents.

        # 🔄 Smart Flow for Order Collection
        If the user wants to make a purchase:
        1. Use `"intent": "ask_to_register"` — ask for name and phone number
        2. Then, use `"intent": "collect_order_info"` — ask what they want
        3. Then, use `"intent": "order_confirmation"` — confirm details
        4. Finally, use `"intent": "create_order"` — trigger lead creation

        # ❗ Prohibited Behaviors
        - DO NOT mention products, services, or pricing that are not explicitly stated in the documents.
        - DO NOT fabricate availability of items.
        - DO NOT respond with plain text or markdown — respond only with the JSON structure above.
        - DO NOT create an order with product/service that is not explicitly stated in the documents.
        """

    return prompt_template

def upload_knowledge_base_file(file_url):
    # Determine MIME type and check if it's supported
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
                raise ValueError(_("Failed to upload file from URL: {}").format(file_url))
        except Exception as e:
            return error_response(
                message=_("Error uploading file from URL: {}, Error: {}").format(file_url, str(e)),
                code=400
            )

    if not new_file_ids:
        print(_("No valid file IDs obtained from provided URLs."))
        return error_response(
            message=_("No valid file IDs found"),
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
