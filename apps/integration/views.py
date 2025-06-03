import requests
import base64
import hashlib
import hmac
import json

from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework import generics, permissions
from django.utils.translation import gettext as _

from config.settings import INSTAGRAM_CLIENT_ID, INSTAGRAM_CLIENT_SECRET, INSTAGRAM_REDIRECT_URI
from shared.addons.enums import IntegrationTypes
from shared.addons.instagram import get_long_lived_access_token, get_user_profile
from shared.addons.telegram import handle_bot_added_to_group, handle_bot_removed_from_group
from shared.addons.validations import success_response, error_response
from shared.permissions import IsCustomer
from .models import Integration, TelegramGroupIntegration
from .serializers import IntegrationCreateSerializer, IntegrationSerializer, SendUserMessageSerializer, \
    TelegramGroupSerializer
from .tasks import process_message_task, process_instagram_message, process_voice_task, process_instagram_comment

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

    def post(self, request, *args, **kwargs):  # noqa
        print("Instagram webhook data received")
        data = request.data
        print(f"Instagram webhook data: {data}")
        if not data:
            return error_response(message="No data received", code=400)
        
        entry = data.get("entry")[0]
        print(f"Entry: {entry}")
        account_id = entry.get("id")
        print(f"Account ID: {account_id}")

        # Handle comments
        if "changes" in entry:
            for change in entry["changes"]:
                if change.get("field") == "comments":
                    comment_data = change.get("value", {})
                    if comment_data:
                        print(f"Comment data: {comment_data}, Account ID: {account_id}")
                        # process_instagram_comment.delay(account_id, comment_data)
                        return success_response(message="Comment webhook data received successfully", code=200)

        # Handle messages
        messaging = entry.get("messaging")
        if messaging:
            is_echo = messaging[0].get("message", {}).get("is_echo")
            audio_file = messaging[0].get("message", {}).get("attachments", [{}])[0].get("payload", {}).get("url", None)
            print(f"Is echo: {is_echo}, Audio file: {audio_file}")
            if is_echo:
                print(f"Echo message received")
                return success_response(message="Echo message received", code=200)
            print(f"Messaging: {messaging}")
            if not Integration.objects.filter(instagram_account_id=account_id).exists():
                print(f"Integration not found for account ID: {account_id}")
                return error_response(message="Integration not found", code=404)
            # Start celery task to process the incoming message
            process_instagram_message.delay(account_id, messaging, audio_file)
            return success_response(message="Message webhook data received successfully", code=200)

        return success_response(message="Webhook data received successfully", code=200)


class InstagramCallbackView(APIView):
    CLIENT_ID = INSTAGRAM_CLIENT_ID
    CLIENT_SECRET = INSTAGRAM_CLIENT_SECRET
    REDIRECT_URI = INSTAGRAM_REDIRECT_URI

    def get(self, request, *args, **kwargs):
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
                integration_type=IntegrationTypes.INSTAGRAM.value,
                defaults={
                    "name": "Instagram integration",
                    "api_token": access_token,
                    "instagram_user_id": user_profile.get("instagram_user_id"),
                    "instagram_account_id": user_profile.get("instagram_account_id"),
                    "instagram_username": user_profile.get("instagram_username"),
                }
            )
            print(f"Integration is successfully created: {integration}")
        else:
            return error_response(message="Failed to get user profile", code=400)
        
        # enable webhook for the integration
        url = f"https://graph.instagram.com/v22.0/me/subscribed_apps?access_token={access_token}&subscribed_fields=messages,comments"
        response = requests.post(url)
        print(f"Response: {response.text}")
        if response.status_code == 200:
            return success_response(message="Integration created successfully", code=200,)
        else:
            return error_response(message="Failed to enable webhook", code=400)



class InstagramDeauthorizeView(APIView):
    def post(self, request, *args, **kwargs): # noqa
        # Facebook sends a signed request
        signed_request = request.data.get("signed_request")
        print(f"Deauthorize Signed request: {signed_request}")
        if not signed_request:
            return error_response(message="Signed request not found", code=400)
        def parse_signed_request(signed_request: str, app_secret: str):
            """
            Parses and validates a signed_request from Instagram/Facebook.

            Args:
                signed_request (str): The signed request string from Meta.
                app_secret (str): Your Instagram app's secret key.

            Returns:
                dict or None: Decoded data if valid, otherwise None.
            """
            try:
                def base64_url_decode(input_str):
                    input_str += '=' * ((4 - len(input_str) % 4) % 4)  # Proper padding
                    return base64.urlsafe_b64decode(input_str.encode())

                encoded_sig, payload = signed_request.split('.', 1)

                # Decode the payload and signature
                decoded_sig = base64_url_decode(encoded_sig)
                decoded_payload = base64_url_decode(payload)
                data = json.loads(decoded_payload)

                # Generate expected signature
                expected_sig = hmac.new(
                    app_secret.encode(),
                    msg=payload.encode(),
                    digestmod=hashlib.sha256
                ).digest()

                # Validate signature
                if not hmac.compare_digest(decoded_sig, expected_sig):
                    print("Invalid signature!")
                    return None

                return data

            except Exception as e:
                print("Error parsing signed request:", str(e))
                return None
                

        data = parse_signed_request(signed_request, INSTAGRAM_CLIENT_SECRET)
        print(f"Deauthorize Data: {data}")
        if not data:
            return error_response(message="Invalid signed request", code=400)

        user_id = data.get("user_id")
        print(f"Deauthorize User ID: {user_id}")
        if user_id:
            # Find and remove the user's Instagram integration
            try:
                integration = Integration.objects.filter(
                    integration_type=IntegrationTypes.INSTAGRAM.value,
                    instagram_account_id=user_id
                ).first()
                print(f"Deauthorize Integration: {integration}")
                if integration:
                    # Delete the integration
                    integration.delete()
                    print(f"User {user_id} deauthorized the app and their integration was removed.")
                else:
                    print(f"User {user_id} deauthorized the app but no integration was found.")
                
                return success_response(message="User deauthorized the app", code=200)
            except Exception as e:
                print(f"Error during deauthorization: {str(e)}")
                return error_response(message="Error processing deauthorization", code=500)
        else:
            return error_response(message="User ID not found in signed request", code=400)


class InstagramDataDeletionView(APIView):
    def post(self, request, *args, **kwargs):
        signed_request = request.data.get("signed_request")

        if not signed_request:
            return error_response(message="Signed request not found", code=400)
        def parse_signed_request(signed_request: str, app_secret: str):
            """
            Parses and validates a signed_request from Instagram/Facebook.

            Args:
                signed_request (str): The signed request string from Meta.
                app_secret (str): Your Instagram app's secret key.

            Returns:
                dict or None: Decoded data if valid, otherwise None.
            """
            try:
                def base64_url_decode(input_str):
                    input_str += '=' * ((4 - len(input_str) % 4) % 4)  # Proper padding
                    return base64.urlsafe_b64decode(input_str.encode())

                encoded_sig, payload = signed_request.split('.', 1)

                # Decode the payload and signature
                decoded_sig = base64_url_decode(encoded_sig)
                decoded_payload = base64_url_decode(payload)
                data = json.loads(decoded_payload)

                # Generate expected signature
                expected_sig = hmac.new(
                    app_secret.encode(),
                    msg=payload.encode(),
                    digestmod=hashlib.sha256
                ).digest()

                # Validate signature
                if not hmac.compare_digest(decoded_sig, expected_sig):
                    print("Invalid signature!")
                    return None

                return data

            except Exception as e:
                print("Error parsing signed request:", str(e))
                return None

        data = parse_signed_request(signed_request, INSTAGRAM_CLIENT_SECRET)
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
            # if "reply_to_message" in data and data["reply_to_message"]["from"]["is_bot"]:
            print("Ignoring group messages and replies to the bot.")
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