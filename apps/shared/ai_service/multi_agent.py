from google import genai
from google.genai import types
import requests
import logging
import mimetypes
from io import BytesIO



class GeminiService:
    client: genai.Client

    def __init__(self, gemini_key: str):
        self.client = genai.Client(api_key=gemini_key)
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


    def create_vectore_store(self, file_url, clear_text=None):
        vectore_store = self.client.file_search_stores.create()

        if file_url:
            mime_type, _ = mimetypes.guess_type(file_url)

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
                file_content.name = file_url.split("/")[-1]
                file = self.client.file_search_stores.upload_to_file_search_store(
                    file_search_store_name = vectore_store.name,
                    file = file_content
                )
                logging.info(f"Uploaded file ID: {file.id} for URL: {file_url}")
                return file.id

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
                file_search_store_name = vectore_store.name
            )
            logging.info(f"Uploaded file ID: {file.id} for clear text")
            return file.id





    