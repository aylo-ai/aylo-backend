from threading import Thread

import requests
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.views import APIView
from django.utils.translation import gettext as _
from apps.assistant.models import Conversation, Message, Assistant
from shared.addons.ai_requests import get_thread_id, get_assistant_response
from shared.addons.enums import ConversationStatuses
from shared.addons.telegram import send_telegram_message, delete_telegram_message, handle_bot_added_to_group, \
    handle_bot_removed_from_group, check_register_info
from shared.addons.utils import create_message, get_or_create_conversation, handle_start_command
from shared.addons.validations import success_response, error_response
from shared.permissions import IsAdmin, IsCustomer
from .models import Integration, TelegramGroupIntegration
from rest_framework import generics, permissions
from .serializers import IntegrationCreateSerializer, IntegrationSerializer, SendUserMessageSerializer


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


class TelegramWebhookViewDraft(APIView):
    def post(self, request, bot_token):  # noqa
        data = request.data.get('message')
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
        # Handle regular messages
        conversation = get_or_create_conversation(chat_id, assistant, token=bot_token)
        print(f"conversation: {conversation}")
        # Check if the conversation is escalated
        if conversation.status == ConversationStatuses.ESCALATED.value or not assistant.is_active:
            create_message(conversation, 'user', user_message)

            return success_response(message=_("Message forwarded to admin"), code=200)

        response = send_telegram_message(chat_id, wait_message, bot_token)
        wait_message_id = response.json().get("result").get("message_id")
        print(f"Wait message sent: {wait_message_id}")

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


class SendUserMessageView(generics.CreateAPIView):
    serializer_class = SendUserMessageSerializer
    permission_classes = [IsCustomer]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        response = serializer.save()
        return success_response(message=response.get("message"), code=200)


class InstagramWebhookView(APIView):
    VERIFY_TOKEN = "wqbm2DoK5zfsF28Qb82Z"  # Replace with your actual verify token

    def get(self, request, *args, **kwargs):
        # Extract query parameters
        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge")

        # Validate the token
        if mode == "subscribe" and token == self.VERIFY_TOKEN:
            return HttpResponse(challenge, content_type="text/plain", status=200)

        # Return 403 if the validation fails
        return error_response(message="Invalid token", code=403)

    def post(self, request, *args, **kwargs):
        # Handle incoming webhook data
        data = request.data
        print(f"Instagram webhook data: {data}")
        # Process the incoming data as needed
        return success_response(message="Webhook data processed successfully", code=200)


class InstagramCallbackView(APIView):
    CLIENT_ID = "601663735749252"
    CLIENT_SECRET = "5012f3e33700b8b659a9c97c1fc1f7bd"
    REDIRECT_URI = "https://api.repli.uz/api/v1/integration/instagram/callback/"

    def get(self, request, *args, **kwargs):
        # Get the authorization code from the query parameters
        code = request.query_params.get("code")
        if not code:
            return error_response(message="Authorization code not found", code=400)

        # Exchange the authorization code for an access token
        token_url = "https://api.instagram.com/oauth/access_token"
        data = {
            "client_id": self.CLIENT_ID,
            "client_secret": self.CLIENT_SECRET,
            "grant_type": "authorization_code",
            "redirect_uri": self.REDIRECT_URI,
            "code": code,
        }

        response = requests.post(token_url, data=data)
        if response.status_code == 200:
            access_token = response.json().get("access_token")
            print(f"Instagram access token: {access_token}")
            return success_response(data={"access_token": access_token}, code=200)
        else:
            return error_response(message="Failed to get access token", code=400)


class TelegramWebhookView(APIView):
    def post(self, request, bot_token):  # noqa
        data = request.data.get('message')
        if not data:
            return error_response(message=_("No message data received"))
        print(f"received data: {data}")
        chat_id = data.get("chat", {}).get("id", None)
        chat_title = data.get('title', 'Private Chat')
        user_message = data.get('text')
        print(f"Chat ID: {chat_id}, Message: {user_message}")

        if data.get('new_chat_member', {}).get('is_bot'):
            handle_bot_added_to_group(chat_id, chat_title, bot_token)
        elif data.get('left_chat_member', {}).get('is_bot'):
            handle_bot_removed_from_group(chat_id, chat_title)
        else:
            # Start processing in a separate thread to return HTTP 200 immediately
            thread = Thread(target=self.process_message, args=(chat_id, user_message, bot_token))
            thread.start()
            print("Thread started")
        return success_response(message=_("Message received"), code=200)

    def process_message(self, chat_id, user_message, bot_token):  # noqa
        assistant = Assistant.objects.filter(integrations__api_token=bot_token).first()
        print(f"Assistant: {assistant}")
        if not assistant:
            return  # No assistant found, skip processing

        # Handle `/start` command
        if user_message == '/start':
            print("user_message: /start")
            handle_start_command(chat_id, assistant, bot_token)
            return

        # Handle regular messages
        conversation = get_or_create_conversation(chat_id, assistant, token=bot_token)
        print(f"conversation: {conversation}")
        if conversation.status == ConversationStatuses.ESCALATED.value or not assistant.is_active:
            create_message(conversation, 'user', user_message)
            return
        if assistant.wait_message:
            response = send_telegram_message(chat_id, assistant.wait_message, bot_token)
            wait_message_id = response.json().get("result").get("message_id")
        else:
            wait_message_id = None
        create_message(conversation, 'user', user_message)

        # Generate and send assistant's response
        response_message = get_assistant_response(user_message, assistant.assistant_id, conversation.thread_id)
        print(f"Response message: {response_message}")
        user_register_message = check_register_info(response_message)
        if wait_message_id:
            delete_telegram_message(chat_id, wait_message_id, bot_token)
        if user_register_message:
            telegram_group = TelegramGroupIntegration.objects.filter(
                integration=assistant.integrations.first()
            ).first()
            if telegram_group:
                print(f"group_id: {telegram_group.group_id}")
                send_telegram_message(telegram_group.group_id, user_register_message, bot_token)
            send_telegram_message(chat_id, user_register_message, bot_token)
            create_message(conversation, 'assistant', response_message)
        else:
            create_message(conversation, 'assistant', response_message)