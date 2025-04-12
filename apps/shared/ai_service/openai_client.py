from openai import OpenAI

from config import settings

# Initialize the OpenAI client
client = OpenAI(api_key=settings.OPENAI_API_KEY)