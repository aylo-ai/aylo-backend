from openai import AzureOpenAI

from config import settings

client = AzureOpenAI(api_key=settings.OPENAI_API_KEY,
                     azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                     api_version="2024-05-01-preview")