from django.utils import timezone
from rest_framework.views import APIView
from django.utils.translation import gettext as _
from apps.assistant.models import Conversation, Message, Assistant
from shared.addons.ai_requests import get_thread_id, get_assistant_response
from shared.addons.telegram import send_telegram_message, delete_telegram_message
from shared.addons.utils import create_message, get_or_create_conversation, handle_start_command
from shared.addons.validations import success_response, error_response
from .models import Integration
from rest_framework import generics, permissions
from .serializers import IntegrationCreateSerializer, IntegrationSerializer


class IntegrationListCreateView(generics.ListCreateAPIView):
    queryset = Integration.objects.all()
    serializer_class = IntegrationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return IntegrationCreateSerializer
        return IntegrationSerializer

    def get_queryset(self):
        assistant_id = self.kwargs.get('pk')
        return self.queryset.filter(assistant_id=assistant_id)

    def create(self, request, *args, **kwargs):
        base_url = f"{request.scheme}://{request.get_host()}"
        context_data = {
            "base_url": base_url,
            "assistant_id": self.kwargs.get('pk')
        }
        assistant_id = self.kwargs.get('pk')
        serializer = self.get_serializer(data=request.data, context=context_data)
        serializer.is_valid(raise_exception=True)
        serializer.save(assistant_id=assistant_id)
        return success_response(message="Integration created successfully", data=serializer.data, code=201)


class IntegrationRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Integration.objects.all()
    serializer_class = IntegrationCreateSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        # check if the integration belongs to the assistant
        obj = super().get_object()
        if obj.assistant.user != self.request.user:
            return error_response(message="Integration not found")
        return obj

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data, code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(message="Integration updated successfully", data=serializer.data, code=200)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return success_response(message="Integration deleted successfully", code=204)


class TelegramWebhookView(APIView):
    def post(self, request, bot_token):  # noqa
        data = request.data.get('message')
        print(f"Data: {data}")
        if not data:
            return error_response(message=_("No message data received"))

        chat_id = data['chat']['id']
        user_message = data.get('text')
        print(f"Chat ID: {chat_id}, Message: {user_message}")
        # Retrieve the assistant based on bot_token
        assistant = Assistant.objects.filter(integrations__api_token=bot_token).first()
        print(f"Assistant: {assistant}")
        if not assistant:
            return error_response(message=_("Invalid bot token"))
        wait_message = f"Iltimos, kutib turing. {assistant.name} sizga xabar yozmoqda.\n" \
                       f"Please wait, {assistant.name} is typing your message.\n" \
                        f"Пожалуйста, подождите, {assistant.name} печатает ваше сообщение."

        # Handle `/start` command
        if user_message == '/start':
            print("user_message: /start")
            return handle_start_command(chat_id, assistant, bot_token)
        response = send_telegram_message(chat_id, wait_message, bot_token)
        wait_message_id = response["result"]["message_id"]
        print(f"Wait message sent: {wait_message_id}")
        # Handle regular messages
        conversation = get_or_create_conversation(chat_id, assistant)
        print(f"conversation: {conversation}")
        create_message(conversation, 'user', user_message)
        print(f"Message created: {user_message}")
        # Generate and send assistant's response
        response_message = get_assistant_response(user_message, assistant.assistant_id, conversation.thread_id)
        print(f"Response message: {response_message}")
        create_message(conversation, 'assistant', response_message)
        delete_telegram_message(chat_id, wait_message_id, bot_token)

        send_telegram_message(chat_id, response_message, bot_token)
        print(f"Assistant message sent: {response_message}")
        return success_response(message=_("Message processed successfully"), code=200)