from openai import AzureOpenAI

from config import settings

# Initialize the OpenAI client
client = AzureOpenAI(api_key=settings.OPENAI_API_KEY,
                     azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                     api_version="2025-04-14")