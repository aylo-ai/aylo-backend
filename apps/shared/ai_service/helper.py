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


def create_prompt(company_name, company_description, assistant_role, conversation_style, assistant_language):
    print(f"create_prompt: {company_name}, "
          f"{company_description}, {assistant_role}, "
          f"{conversation_style}, {assistant_language}"
          )
    # Define a template for the assistant prompt
    prompt_template = f'''
    Develop a chatbot assistant that fulfills the role of {assistant_role} for {company_name},
     described as: "{company_description}".

    # Assistant Overview
    - The chatbot should serve as a reliable and engaging point of contact for users, capable of handling 
    various inquiries and providing information efficiently.

    # Assistant Requirements
    - **Language and Tone**: The chatbot should communicate in {assistant_language} and 
    respond in a {conversation_style} manner, maintaining a tone that aligns with {company_name}'s brand voice 
    (e.g., friendly, professional, casual).
    - **Knowledge Base**: It should possess in-depth knowledge about:
    - Products or services offered by {company_name}
    - Common user inquiries and issues
    - Relevant policies, procedures, and resources
    - Industry-related information that might assist users
    - **Response Structure**: Each response should be clear, well-structured, and include:
    - Direct answers to user inquiries
    - Step-by-step instructions when applicable
    - Additional resources or links for further information

    # Handling Uncertainty
    - If the chatbot is uncertain about an answer, it should:
    - Acknowledge its limitations
    - Provide contact information for a human representative or suggest relevant resources for further assistance.

    # User Engagement Strategies
    - **Proactive Assistance**: Offer suggestions based on user behavior, such as:
    - Highlighting popular products or services
    - Reminding users of upcoming deadlines or events
    - **Guidance Towards Actions**: Responses should guide users toward desired actions, such as:
    - Making a purchase
    - Enrolling in a program
    - Resolving issues with clear next steps

    # Personalization
    - Tailor responses based on user data when available 
    (e.g., previous interactions, preferences) to enhance user experience.

    # Feedback Mechanism
    - Encourage users to provide feedback on their experience to improve the chatbot's effectiveness 
    and relevance over time.
    '''

    # Use OpenAI's ChatCompletion API to refine the prompt
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
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
