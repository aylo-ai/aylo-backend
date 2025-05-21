import requests
import base64
import hashlib
import hmac
import json

from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework import generics, permissions
from django.utils.translation import gettext as _

from apps.assistant.models import  Assistant
from config.settings import INSTAGRAM_CLIENT_ID, INSTAGRAM_CLIENT_SECRET, INSTAGRAM_REDIRECT_URI
from shared.addons.ai_requests import get_assistant_response
from shared.addons.enums import ConversationStatuses, IntegrationTypes
from shared.addons.instagram import get_long_lived_access_token, get_user_profile
from shared.addons.telegram import send_telegram_message, delete_telegram_message, handle_bot_added_to_group, \
    handle_bot_removed_from_group
from shared.mixins import SubscriptionValidationMixin
from shared.addons.utils import create_message, get_or_create_conversation, handle_start_command, create_lead
from shared.addons.validations import success_response, error_response
from shared.permissions import IsAdmin, IsCustomer
from .models import Integration, TelegramGroupIntegration
from .serializers import IntegrationCreateSerializer, IntegrationSerializer, SendUserMessageSerializer, \
    TelegramGroupSerializer
from .tasks import process_message_task, process_instagram_message, process_voice_task


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
            "assistant_id": self.kwargs.get('pk'),
            "request": request
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
        # create lead
        if response_message and response_message.get("intent") == "create_order":
            response_data = create_lead(
                full_name=response_message['entities']['full_name'],
                phone_number=response_message['entities']['phone_number'],
                email=response_message['entities']['email'],
                product=response_message['entities']['product'],
                source=conversation.platform,
                metadata=response_message['entities']
            )
            print("✅ Lead created from Telegram message" + response_data)  
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


class InstagramWebhookView(APIView, SubscriptionValidationMixin):
    VERIFY_TOKEN = "wqbm2DoK5zfsF28Qb82Z"  # Replace with your actual verify token

    def get(self, request, *args, **kwargs):
        user = request.user
        self.validate_subscription(user)
        # Extract query parameters
        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge")

        # Validate the token
        if mode == "subscribe" and token == self.VERIFY_TOKEN:
            return HttpResponse(challenge, content_type="text/plain", status=200)

        # Return 403 if the validation fails
        return error_response(message="Invalid token", code=403)

    def post(self, request, *args, **kwargs):  # noqa
        user = request.user
        self.validate_subscription(user)
        print("Instagram webhook data received")
        data = request.data
        print(f"Instagram webhook data: {data}")
        if not data:
            return error_response(message="No data received", code=400)
        entry = data.get("entry")[0]
        print(f"Entry: {entry}")
        account_id = entry.get("id")
        print(f"Account ID: {account_id}")
        messaging = entry.get("messaging")
        print(f"Messaging: {messaging}")
        if not Integration.objects.filter(instagram_account_id=account_id).exists():
            print(f"Integration not found for account ID: {account_id}")
            return error_response(message="Integration not found", code=404)
        # Start celery task to process the incoming message
        process_instagram_message.delay(account_id, messaging)
        return success_response(message="Webhook data receieved successfully", code=200)


class InstagramCallbackView(APIView, SubscriptionValidationMixin):
    CLIENT_ID = INSTAGRAM_CLIENT_ID
    CLIENT_SECRET = INSTAGRAM_CLIENT_SECRET
    REDIRECT_URI = INSTAGRAM_REDIRECT_URI

    def get(self, request, *args, **kwargs):
        user = request.user
        self.validate_subscription(user)
        # Get the authorization code from the query parameters
        code = request.query_params.get("code")
        assistant_id = request.query_params.get("assistant_id")
        if not assistant_id:
            return error_response(message="Assistant ID not found", code=400)
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
        print(f"Data: {data}")

        response = requests.post(token_url, data=data)
        print(f"Response: {response.text}")
        if response.status_code == 200:
            token_data = response.json()
            short_lived_access_token = token_data.get("access_token")
            user_id = token_data.get("user_id")
            print(f"Short lived Access Token: {short_lived_access_token}, User ID: {user_id}")
            # Fetch Instagram Business Accounts
            access_token = get_long_lived_access_token(short_lived_access_token)
            print(f"Long lived Access Token: {access_token}")
        else:
            return error_response(message="Failed to get access token", code=400)
        # get instagram user profile
        user_profile = get_user_profile(access_token)
        if user_profile:
            print(f"User Profile: {user_profile}")
            integration, _ = Integration.objects.update_or_create(
                assistant_id=assistant_id,
                defaults={
                    "name": "Instagram integration",
                    "integration_type": IntegrationTypes.INSTAGRAM.value,
                    "api_token": access_token,
                    "instagram_user_id": user_profile.get("instagram_user_id"),
                    "instagram_account_id": user_profile.get("instagram_account_id"),
                    "instagram_username": user_profile.get("instagram_username"),
                }
            )
            print(f"Integration is successfully created: {integration}")
        else:
            return error_response(message="Failed to get user profile", code=400)
        return success_response(message="Integration created successfully", code=200,)


class InstagramDeauthorizeView(APIView, SubscriptionValidationMixin):
    def post(self, request, *args, **kwargs): # noqa
        user = request.user
        self.validate_subscription(user)
        # Facebook sends a signed request
        signed_request = request.data.get("signed_request")
        if not signed_request:
            return error_response(message="Signed request not found", code=400)

        def parse_signed_request(signed_request, secret):  # noqa
            encoded_sig, payload = signed_request.split('.', 1)
            decoded_payload = base64.urlsafe_b64decode(payload + "==").decode()
            data = json.loads(decoded_payload)

            # Verify signature
            expected_sig = hmac.new(
                secret.encode(),
                msg=payload.encode(),
                digestmod=hashlib.sha256
            ).digest()

            if not hmac.compare_digest(base64.urlsafe_b64encode(expected_sig).strip(), encoded_sig.encode()):
                return None

            return data

        CLIENT_SECRET = "5012f3e33700b8b659a9c97c1fc1f7bd"
        data = parse_signed_request(signed_request, CLIENT_SECRET)

        if not data:
            return error_response(message="Invalid signed request", code=400)

        user_id = data.get("user_id")

        if user_id:
            # Here you should remove the user from your database
            print(f"User {user_id} deauthorized the app.")
            return success_response(message="User deauthorized the app", code=200)
        else:
            return error_response(message="User ID not found in signed request", code=400)


class InstagramDataDeletionView(APIView, SubscriptionValidationMixin):
    def post(self, request, *args, **kwargs):
        user = request.user
        self.validate_subscription(user)
        signed_request = request.data.get("signed_request")
        if not signed_request:
            return error_response(message="Signed request not found", code=400)

        CLIENT_SECRET = "5012f3e33700b8b659a9c97c1fc1f7bd"

        def parse_signed_request(signed_request, secret):
            import base64, hashlib, hmac

            encoded_sig, payload = signed_request.split('.', 1)
            decoded_payload = base64.urlsafe_b64decode(payload + "==").decode()
            data = json.loads(decoded_payload)

            expected_sig = hmac.new(
                secret.encode(),
                msg=payload.encode(),
                digestmod=hashlib.sha256
            ).digest()

            if not hmac.compare_digest(base64.urlsafe_b64encode(expected_sig).strip(), encoded_sig.encode()):
                return None

            return data

        data = parse_signed_request(signed_request, CLIENT_SECRET)
        if not data:
            return error_response(message="Invalid signed request", code=400)

        user_id = data.get("user_id")
        if user_id:
            # Process data deletion for the user
            print(f"Deleting data for user: {user_id}")
            return success_response(data={
                "url": "https://api.repli.uz/integration/instagram/data-deletion-status/",
                "confirmation_code": user_id
            }, code=200)
        else:
            return error_response(message="User ID not found in signed request", code=400)


class TelegramWebhookView(APIView):
    def post(self, request, bot_token):  # noqa
        data = request.data.get('message')
        if not data:
            return error_response(message=_("No message data received"))
        print(f"received data: {data}")
        chat_id = data.get("chat", {}).get("id", None)
        chat_title = data.get('chat', {}).get('title', 'Private Chat')
        chat_type = data.get("chat", {}).get("type", None)

            # Voice message handling
        if "voice" in data:
            voice_file_id = data["voice"]["file_id"]
            process_voice_task.delay(chat_id, voice_file_id, bot_token)
            return success_response(message=_("Voice message received"), code=200)

        user_message = data.get('text')
        print(f"Chat ID: {chat_id}, Message: {user_message}")
        if chat_type in ['group', 'supergroup']:
            if "reply_to_message" in data and data["reply_to_message"]["from"]["is_bot"]:
                print("Ignoring group replies to the bot.")
                return success_response(message=_("Message received"), code=200)
        if data.get('new_chat_member', {}).get('is_bot'):
            handle_bot_added_to_group(chat_id, chat_title, bot_token)
        elif data.get('left_chat_member', {}).get('is_bot'):
            handle_bot_removed_from_group(chat_id, chat_title)
        else:
            # Start the Celery task
            process_message_task.delay(chat_id, user_message, bot_token)
            print("celery task started")
        return success_response(message=_("Message received"), code=200)


class TelegramGroupListView(generics.ListAPIView):
    queryset = TelegramGroupIntegration.objects.all()
    serializer_class = TelegramGroupSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        integration_id = self.kwargs.get('pk')
        return self.queryset.filter(integration_id=integration_id)