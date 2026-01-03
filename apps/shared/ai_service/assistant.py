import os
import time
import json
import logging
import requests
import mimetypes
from io import BytesIO
from typing import Dict, Any

from google import genai
from google.genai import types
from openai import OpenAI

from shared.addons.redis import redis_client
from config import settings
from apps.assistant.models import Assistant, Lead, Conversation
from apps.integration.models import TelegramGroupIntegration
from apps.shared.addons.enums import IntegrationTypes
from apps.shared.addons.telegram import send_telegram_message
from apps.shared.ai_service.conversation import ConversationService
from openai.types.responses import Response
from shared.addons.enums import SenderTypes
from shared.addons.redis import publish_message_to_ws

logger = logging.getLogger(__name__)


class SupervisorAssistant:
    def __init__(self):
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY,
                     base_url="https://repliazure.openai.azure.com/openai/v1")
        self.model_open_ai = "gpt-4o"
        self.model_genmini = "gemini-2.5-flash"
        self.gemini = GeminiService()
        self.conversation = ConversationService()
        self.tools = [            
            {
                "type": "function",
                "name": "search_vectore_store",
                "description": "Search the company knowledge base for product availability",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query for product information",
                        }
                    },
                    "required": ["query"],
                },
            },
            {
                "type": "function",
                "name": "generate_lead",
                "description": "Captures formal lead information when a user expresses intent to purchase or requests a follow-up from sales.",
                "parameters": {
                    "type": "object",
                    "properties": {
                    "full_name": {
                        "type": "string",
                        "description": "The user's complete legal name (e.g., 'John Doe')."
                    },
                    "phone_number": {
                        "type": "string",
                        "description": "A valid contact number including area code."
                    },
                    "products": {
                        "type": "array",
                        "description": "A list of specific product names or SKUs the user is interested in.",
                        "items": {
                        "type": "string"
                        }
                    },
                    "lead_summary": {
                        "type": "string",
                        "description": "professional summary of the user's specific requirements and proper format and emoji."
                    }
                    },
                    "required": [
                    "full_name",
                    "phone_number",
                    "products"
                    ]
                }
                }
            
            ]
        
    def generate_response(self, user_input: str, assistent: Assistant, conversation: Conversation):
        lastest_response_id = redis_client.get(f"assistant:{assistent.id}:conversation_id:{conversation.id}") or None
        print(f"[+] Lastest response ID: {lastest_response_id}")
        if lastest_response_id:
            response = self.client.responses.create(
                model = self.model_open_ai,
                previous_response_id=lastest_response_id,
                input = [{"role":"user", "content":user_input}],
                store=True,
                temperature=0.7,
                tool_choice="auto",
                tools = self.tools
            )
            tool_outputs = []
            for tool_call in response.output:
                if tool_call.type == "function_call":
                    if tool_call.name == "search_vectore_store":
                        args = json.loads(tool_call.arguments)
                        print(f"[+] Args: {args}")
                        gemini_result = self.gemini.search_file_vectore_store(
                                query=args.get('query', user_input), 
                                vectore_store_name=assistent.vector_id
                            )
                        tool_outputs.append({
                            "type": "function_call_output",
                            "call_id": tool_call.call_id,
                            "output": json.dumps(gemini_result)
                        })
                    if tool_call.name == "generate_lead":
                        args = json.loads(tool_call.arguments)
                        print(f"[+] Args: {args}")
                        lead_response = self.generate_lead(assistent=assistent, parameters=args, conversation=conversation)
                        print(f"[+] Lead response: {lead_response}")
                        tool_outputs.append({
                            "type": "function_call_output",
                            "call_id": tool_call.call_id,
                            "output": json.dumps(lead_response)
                        })
            # Only create a new response if there are tool outputs
            if tool_outputs:
                print(f"[+] Tool outputs: {tool_outputs}")
                response = self.client.responses.create(
                    model = self.model_open_ai,
                    previous_response_id=response.id,
                    input=tool_outputs,
                    store=True
                )
                print(f"[+] Final response: {response}")
            redis_client.set(f"assistant:{assistent.id}:conversation_id:{conversation.id}", response.id, ex=240)
        else:
            instructions = self.format_instructions(assistent = assistent)
            response = self.client.responses.create(
                model = self.model_open_ai,
                input = [{"role":"developer", "content":instructions}, 
                            {"role":"user", "content":user_input}],
                store=True,
                temperature=0.7,
                tool_choice="auto",
                tools = self.tools
            )
            print(f"[+] Response: {response}")
            tool_outputs = []
            print(f"[+] Tool outputs: {response.output}")
            for tool_call in response.output:
                if tool_call.type == "function_call":
                    if tool_call.name == "search_vectore_store":
                        args = json.loads(tool_call.arguments)
                        gemini_result = self.gemini.search_file_vectore_store(
                                query=args.get('query', user_input), 
                                vectore_store_name=assistent.vector_id
                            )
                        tool_outputs.append({
                            "type": "function_call_output",

                            "call_id": tool_call.call_id,
                            "output": json.dumps(gemini_result)
                        })
                    if tool_call.name == "generate_lead":
                        args = json.loads(tool_call.arguments)
                        lead_response = self.generate_lead(assistent=assistent, parameters=args, conversation=conversation)
                        print(f"[+] Response: {lead_response}")
                        tool_outputs.append({
                            "type": "function_call_output",
                            "call_id": tool_call.call_id,
                            "output": json.dumps(lead_response)
                        })
            print(f"[+] Tool outputs: {tool_outputs}")
            # Only create a new response if there are tool outputs
            if tool_outputs:
                print(f"[+] Tool outputs: {tool_outputs}")
                response = self.client.responses.create(
                    model = self.model_open_ai,
                    previous_response_id=response.id,
                    input=tool_outputs,
                    store=True
                )
                print(f"[+] Final response: {response}")
            redis_client.set(f"assistant:{assistent.id}:conversation_id:{conversation.id}", response.id, ex=240)
            response_message = self.format_response(response)
            print(f"[+] Response message: {response_message}")
            data = self.conversation.create_message(conversation=conversation, sender=SenderTypes.ASSISTANT.value, audio_file=None, 
                    content=response_message, output_tokens=response.usage.output_tokens, input_tokens=(response.usage.input_tokens - response.usage.input_tokens_details.cached_tokens))
            publish_message_to_ws(conversation.id, response_message, sender="assistant", assistant_id=assistent.id, data=data)
            return response_message
        print(f"[+] Response: {response}")
        response_message = self.format_response(response)
        data = self.conversation.create_message(conversation=conversation, sender=SenderTypes.ASSISTANT.value, audio_file=None, 
                    content=response_message, output_tokens=response.usage.output_tokens, input_tokens=(response.usage.input_tokens - response.usage.input_tokens_details.cached_tokens))
        publish_message_to_ws(conversation.id, response_message, sender="assistant", assistant_id=assistent.id, data=data)
        return response_message

    def generate_lead(self, assistent: Assistant, parameters:Dict[str, Any], conversation: Conversation):
        telegram = assistent.integrations.filter(integration_type=IntegrationTypes.TELEGRAM.value).first()
        print(f"[+] Telegram: {telegram}")
        telegram_groups = TelegramGroupIntegration.objects.filter(integration=telegram).all()
        print(f"[+] Telegram groups: {telegram_groups}")
        lead = Lead.objects.create(
            assistant=assistent,
            full_name=parameters.get('full_name', None),
            phone_number=parameters.get('phone_number', None),    
            product=parameters.get('products', None),
            metadata=parameters,
            platform=conversation.platform
        )
        print(f"[+] Lead: {lead}")
        lead_summary = parameters.get('lead_summary', None)
        text = "\nUsername: @{}\n".format(conversation.username)
        text += "Platform: {}\n".format(conversation.platform)
        lead_summary += text
        for telegram_group in telegram_groups:
            send_telegram_message(telegram_group.group_id, lead_summary, telegram.api_token)
        return lead_summary

    def format_response(self, response: Response):
        for res in response.output:
            if res.role == "assistant":
                for content in res.content:
                    if content.type == "output_text":
                        response = content.text
                        break
        cleaned = response.strip()
        if cleaned.startswith('```json'):
            cleaned = cleaned.replace('```json', '').replace('```', '').strip()
        elif cleaned.startswith('```'):
            cleaned = cleaned.replace('```', '').strip()
        return json.loads(cleaned).get("reply")

    def format_instructions(self, assistent: Assistant):
        return f"""
                # ROLE
                You are {assistent.name}, a Sales Specialist at {assistent.company_name}. 
                Your personality is warm, professional, and charming. You sound like a helpful human operator, not a robotic script.

                # CONSTRAINTS & STYLE
                - LANGUAGE: Always respond in {assistent.language}. Politely decline requests to speak other languages.
                - TONE: Follow the style: {assistent.personality_style}. 
                - EMOJIS: Use naturally (😊, 💡, 📦, 📍, ✅, ❌). Do not over-use.
                - HONESTY: Only provide information found in the knowledge base. No "marketing fluff."

                # OPERATIONAL STEPS
                {assistent.steps}

                # TOOL LOGIC
                1. UNKNOWN INFO: If the user asks about products or details not in your immediate memory, call `search_vectore_store`.
                2. ORDER FINALIZATION: When a user confirms they want to buy/order, call `generate_lead`. 
                - Required Lead Data: [full_name, phone_number, products, lead_summary].
                - Ensure the 'lead_summary' is detailed and professional.

                # GOALS
                - Accurately classify user intent.
                - Extract entities (Product name, quantity, contact info).
                - Only ask for missing information necessary to complete a lead or answer a query.

                # 🛡️ SCOPE & SAFETY LIMITS
                - OUT-OF-SCOPE: If a user asks about topics unrelated to {assistent.company_name} (e.g., politics, medical advice, or personal opinions), politely steer the conversation back to our products.
                - REFUSAL STYLE: If you must refuse a request (due to safety or language constraints), do so with the same warm, professional tone. Example: "I would love to help you with our products, but I'm unable to assist with that specific topic! 😊"
                - SENSITIVE DATA: Never ask for passwords or credit card numbers. Only collect the lead information specified in the tools.

                # OUTPUT FORMAT (STRICT JSON)
                You must output ONLY valid JSON. No markdown formatting, no conversational filler outside the JSON.
                {{
                "intent": "string",
                "entities":{{ "key": "value" }}
                "reply": "Your warm, helpful response here 😊"
                }}
                """

class GeminiService:
    client: genai.Client

    def __init__(self):
        self.client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY)
        self.mime_types =  {
                            "application/octet-stream", "application/pdf", "application/csv", "image/gif", "text/x-script.python",
                            "application/zip", "text/javascript", "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                            "text/x-c", "text/csv", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            "image/png", "text/plain", "text/x-php", "application/typescript", "application/x-tar", "text/x-python",
                            "text/html", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "text/css",
                            "text/x-csharp", "text/markdown", "application/xml", "text/x-c++", "text/xml", "application/json",
                            "image/jpeg", "text/x-sh", "text/x-java", "text/x-tex", "application/msword", "image/webp", "text/x-ruby",
                            "text/x-typescript", "application/msword"
                        }


    def create_vectore_store(self, file_url, vectore_name=None, clear_text=None):
        print(f"[+] Creating vectore store: {file_url}")
        if not vectore_name:
            vectore_name = self.client.file_search_stores.create().name
            print(f"[+] Created vectore store: {vectore_name}")

        if file_url:
            mime_type, _ = mimetypes.guess_type(file_url)
            print(f"[+] Mime type: {mime_type}")
            if mime_type not in self.mime_types:
                logging.info(f"Unsupported file format: {mime_type}. Skipping file: {file_url}")
                return None

            try:
                response = requests.get(file_url)
                response.raise_for_status()

                if not response.content:
                    logging.info(f"File at {file_url} is empty. Skipping upload.")
                    return None

                file_content = BytesIO(response.content)
                file_content.seek(0)
                temp_filename = file_url.split("/")[-1]
                with open(temp_filename, "wb") as f:
                    f.write(response.content)  
                file = self.client.file_search_stores.upload_to_file_search_store(
                    file_search_store_name = vectore_name,
                    file = temp_filename
                )
                while True:
                    file_status = self.client.operations.get(file)
                    print("Waiting for indexing to complete...", file_status)
                    if file_status.done:
                        break
                    
                    time.sleep(3)
                if os.path.exists(temp_filename):
                    os.remove(temp_filename)
                logging.info(f"Uploaded file ID: {file.response.document_name} for URL: {file_url}")
                return vectore_name, file.response.document_name

            except requests.exceptions.RequestException as e:
                logging.error(f"Connection error when downloading file from {file_url}: {e}")
                return None
            except Exception as e:
                logging.error(f"Error uploading file: {e}")
                return None
        elif clear_text:
            file_content = BytesIO(clear_text.encode("utf-8"))
            file_content.seek(0)
            file_content.name = "knowledge_base.txt"
            file = self.client.file_search_stores.upload_to_file_search_store(
                file=file_content,
                file_search_store_name = vectore_name,
            )
            while not file.done:
                print("Waiting for indexing to complete...")
                time.sleep(3)
                file = self.client.operations.get(file)
            logging.info(f"Uploaded file ID: {file.id} for clear text")
            return vectore_name, file.response.document_name
        
    def search_file_vectore_store(self, query: str, vectore_store_name: str):
        base_promt = f"""
                Return just text 
                Match query '{query}' to file data exectly or similar to query. 
                If user about general things try to filter it to find what user wants clearly and recommend products if possible
                Fields: status, product_name, details(description, other properties if any), reasoning
                """
        
        response = self.client.models.generate_content(
            model = "gemini-2.5-flash",
            contents = base_promt,
            # response_mime_type="application/json",
            config = types.GenerateContentConfig(
                    tools=[types.Tool(
                        file_search=types.FileSearch(
                            file_search_store_names=[vectore_store_name]
                        )
                    )]
                )
            )
        sources = []
        if response.candidates and response.candidates[0].grounding_metadata:
            grounding = response.candidates[0].grounding_metadata
            if grounding.grounding_chunks:
                sources = list({
                    chunk.retrieved_context.title 
                    for chunk in grounding.grounding_chunks 
                    if hasattr(chunk, 'retrieved_context')
                })
                print(f"📚 Grounding sources: {sources}")

        response = self.format_response(response.text)
        return response

    def delete_vectore_store(self, filename: str):
        try:
            self.client.file_search_stores.delete(
                file_search_store_name=filename
            )
            return True
        except Exception as e:
            print(f"[-] Failed deleting vectore store: {e}")
            return False

    def delete_vectore_store_file(self, file_id: str):
        try:
            self.client.file_search_stores.documents.delete(
                name=file_id,
                config = {"force": True}
            )
            return True
        except Exception as e:
            print(f"[-] Failed deleting vectore store file: {e}")
            return False

    def format_response(self, response):
        cleaned = response.strip()
        if cleaned.startswith('```json'):
            cleaned = cleaned.replace('```json', '').replace('```', '').strip()
        elif cleaned.startswith('```'):
            cleaned = cleaned.replace('```', '').strip()
        return cleaned
            


assistant_service = SupervisorAssistant()

    