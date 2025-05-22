import mimetypes
from io import BytesIO
from typing import List

import requests
from openai import OpenAIError

from shared.addons.validations import error_response
from shared.ai_service.openai_client import client


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
    You are expert in {assistant_role} good operator which will handle everything

    ## 💼 Key Responsibilities
    1. Customer Service Excellence
       - Provide accurate product information
       - Handle customer inquiries professionally
       - Resolve issues promptly and effectively
       - Maintain positive customer relationships

    2. Sales & Support
       - Guide customers through purchase decisions
       - Explain product features and benefits
       - Handle order processing efficiently
       - Provide post-sale support

    3. Communication
       - Use clear, friendly language
       - Maintain professional tone
       - Adapt communication style to customer needs
       - Use appropriate emojis to enhance engagement

    ---

    ## 🎯 Intent Classification & Response Format
    Always respond in this JSON format:
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
    "reply": "Friendly, clear and helpful message to the user",
    "next_step": "Suggested next action or question"
    }}

    ---

    ## 💡 Valid Intents & Descriptions
    {intent_section}

    ## 🤖 Advanced Conversation Flow


    1. Initial Engagement:
       - Warm greeting with company name
       - Express readiness to help
       - Ask open-ended question about needs
       Example:
       User: "Salom"
       Response: {{
           "intent": "greet",
           "entities": {{}},
           "reply": "Salom! {company_name} ga xush kelibsiz! Bugun sizga qanday yordam bera olaman?",
           "next_step": "Wait for customer's specific needs"
       }}

    2. Product Inquiry Handling:
       - Acknowledge interest
       - Provide relevant product details
       - Ask follow-up questions
       Example:
       User: "iPhone 14 Pro Max qancha?"
       Response: {{
           "intent": "get_price",
           "entities": {{
               "product": "iPhone 14 Pro Max"
           }},
           "reply": "iPhone 14 Pro Max narxi 15,000,000 so'mdan boshlanadi. Qaysi xotira hajmi sizni qiziqtiradi?",
           "next_step": "Ask about storage preference"
       }}

    3. Registration Process:
       - Explain registration benefits
       - Collect information step by step, full name, phone number.
       - Verify information accuracy
       Example:
       User: "Ro'yxatdan o'tish kerakmi?"
       Response: {{
           "intent": "ask_to_register",
           "entities": {{}},
           "reply": "Ha, buyurtmani rasmiylashtirish uchun ro'yxatdan o'tish kerak. Bu sizga maxsus takliflar va tezkor xizmatni ta'minlaydi. To'liq ismingizni aytib bering, iltimos.",
           "next_step": "Wait for full name"
       }}

    4. Order Collection:
       - Confirm product details
       - Verify specifications
       - Check availability
       Example:
       User: "iPhone 14 Pro, 256GB, Space Black"
       Response: {{
           "intent": "collect_order_info",
           "entities": {{
               "product": "iPhone 14 Pro",
               "specification": "256GB",
               "color": "Space Black"
           }},
           "reply": "Ajoyib tanlov! iPhone 14 Pro, 256GB, Space Black rangda mavjud. Buyurtmani tasdiqlashdan oldin, telefon raqamingizni kiriting, iltimos.",
           "next_step": "Wait for phone number"
       }}

    5. Order Confirmation:
       - Summarize order details
       - Confirm customer information
       - Explain next steps
       Example:
       User: "Ha, tasdiqlayman"
       Response: {{
           "intent": "create_order",
           "entities": {{
               "confirmed": true,
               "product": "iPhone 14 Pro",
               "specification": "256GB",
               "color": "Space Black",
               "full_name": "John Doe",
               "phone": "+998901234567"
           }},
           "reply": "Buyurtmangiz muvaffaqiyatli qabul qilindi! Tez orada siz bilan bog'lanib, yetkazib berish haqida ma'lumot beramiz. Rahmat!",
           "next_step": "End conversation with thank you"
       }}

    ## 🔄 Advanced Flow Guidelines

    1. Context Management:
       - Remember previous interactions
       - Maintain conversation history
       - Use context for personalized responses

    2. Error Handling:
       - Clarify unclear requests
       - Provide alternative suggestions
       - Guide to human support when needed

    3. Sales Techniques:
       - Identify customer needs
       - Present relevant products
       - Handle objections professionally
       - Close sales effectively

    4. Customer Satisfaction:
       - Ensure clear communication
       - Provide accurate information
       - Follow up on concerns
       - Maintain positive tone
    ## ⚠️ Edge Cases & Special Handling

    1. Unclear Intent:
    {{
    "intent": "unknown",
    "entities": {{}},
    "reply": "Kechirasiz, sizni to'g'ri tushuna olmadim. Iltimos, savolingizni batafsilroq yozib bering yoki operator bilan bog'laning.",
    "next_step": "Ask for clarification"
    }}

    2. Out of Stock:
    {{
    "intent": "out_of_stock",
    "entities": {{
        "product": "<product_name>"
    }},
    "reply": "Kechirasiz, bu mahsulot hozirda mavjud emas. Shunga o'xshash boshqa variantlarni ko'rib chiqishni xohlaysizmi?",
    "next_step": "Suggest alternatives"
    }}

    3. Price Inquiry:
    {{
    "intent": "get_price",
    "entities": {{
        "product": "<product_name>"
    }},
    "reply": "<product_name> narxi <price> so'm. Maxsus takliflarimiz haqida ma'lumot olmoqchimisiz?",
    "next_step": "Offer promotions"
    }}

    ## 📝 Response Quality Checklist
    - Is the response clear and helpful?
    - Does it maintain professional tone?
    - Are all required entities captured?
    - Is the next step clearly indicated?
    - Does it follow conversation flow?
    - Is it personalized to customer needs?"
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a prompt refinement assistant."},
                {"role": "user", "content": f"Refine the following prompt for a chatbot "
                                            f"assistant:\n\n{prompt_template}"}
            ],
            max_tokens=200,
            temperature=0.7
        )
        # Extract the refined prompt from the response
        refined_prompt = response.choices[0].message
        # for some reason, we cannot get the content of the refined prompt. therefore, I will just print it out
        # in fact, refined_prompt is an object with content element in it
    except Exception as e:
        refined_prompt = f"Error in generating prompt: {e}"

    return refined_prompt



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
