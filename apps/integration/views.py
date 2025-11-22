import requests
import base64
import hashlib
import hmac
import time
import json

import secrets
from django.db.models import Q
from django.conf import settings
from urllib.parse import urlencode
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework import generics, permissions
from django.utils.translation import gettext_lazy as _


from config.settings import INSTAGRAM_CLIENT_ID, INSTAGRAM_CLIENT_SECRET, INSTAGRAM_REDIRECT_URI
from shared.addons.enums import IntegrationTypes
from shared.addons.instagram import get_long_lived_access_token, get_user_profile
from shared.addons.telegram import handle_bot_added_to_group, handle_bot_removed_from_group
from shared.addons.validations import success_response, error_response
from shared.permissions import IsCustomer
from .models import Integration, TelegramGroupIntegration, InstagramMedia, CommentTriggerWord, InstagramCommentResponse, Flow, Transition, Step, CommentResponseButton, InstagramUserState
from .serializers import (IntegrationCreateSerializer, 
                        IntegrationSerializer, 
                        SendUserMessageSerializer, 
                        TelegramGroupSerializer, 
                        InstagramMediaSerializer, 
                        CommentTriggerWordSerializer, 
                        InstagramCommentResponseSerializer, 
                        InstagramCommentResponseFlowSerializer, 
                        TransitionSerializer, 
                        StepSerializer, 
                        CommentResponseButtonSerializer)
from .tasks import (process_instagram_message, 
                    process_voice_task, 
                    process_instagram_comment, 
                    WAIT_SECONDS, 
                    process_collected_messages, 
                    handle_postback_event_task)

from shared.addons.redis import redis_client



class IntegrationListView(generics.ListAPIView):
    queryset = Integration.objects.all()
    serializer_class = IntegrationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        return Integration.objects.filter(
            Q(user=user) | Q(assistant__user=user)
        ).distinct()
    
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return success_response(data=serializer.data, message="Integrations retrieved successfully", code=200)


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
        assistant_id = self.kwargs.get('pk', None)
        context_data = {
            "base_url": base_url,
            "assistant_id": assistant_id,
            "request": request
        }
        serializer = self.get_serializer(data=request.data, context=context_data)
        serializer.is_valid(raise_exception=True)
        serializer.save(assistant_id=assistant_id)
        return success_response(message=_("Integration muvaffaqiyatli yaratildi"), data=serializer.data, code=201)


class IntegrationRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Integration.objects.all()
    serializer_class = IntegrationCreateSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        # check if the integration belongs to the assistant
        obj = super().get_object()
        if obj.assistant:
            if obj.assistant.user != self.request.user:
                return error_response(message=_("Integration topilmadi"))
        else:
            if obj.user != self.request.user:
                return error_response(message=_("Integration topilmadi"))
        return obj

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(data=serializer.data, message=_("Integration muvaffaqiyatli olindi"), code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        base_url = f"{request.scheme}://{request.get_host()}"
        context_data = {
            "base_url": base_url,
            "request": request,
            "assistant_id": instance.assistant_id
        }
        serializer = self.get_serializer(instance, data=request.data, context=context_data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(message=_("Integration muvaffaqiyatli o'zgartirildi"), data=serializer.data, code=200)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return success_response(message=_("Integration muvaffaqiyatli o'chirildi"), code=204)


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
        return error_response(message=_("Token yaroqsiz"), code=403)

    def post(self, request, *args, **kwargs):  # noqa
        print("Instagram webhook data received")
        data = request.data
        print(f"Instagram webhook data: {data}")
        if not data:
            return error_response(message=_("Ma'lumot topilmadi"), code=400)
        
        entry = data.get("entry")[0]
        print(f"Entry: {entry}")
        account_id = entry.get("id") # IG Professional Account ID (instagram_user_id)
        print(f"Account ID: {account_id}")

        # Handle comments
        if "changes" in entry:
            for change in entry["changes"]:
                if change.get("field") == "comments":
                    comment_data = change.get("value", {})
                    if comment_data:
                        print(f"Comment data: {comment_data}, Account ID: {account_id}")
                        # Get access token from integration
                        integration = Integration.objects.filter(instagram_account_id=account_id).first()
                        if integration and integration.api_token:
                            process_instagram_comment.delay(account_id, comment_data)
                            return success_response(message=_("Comment webhook ma'lumotlar muvaffaqiyatli olindi"), code=200)

        # Handle messages
        messaging = entry.get("messaging")
        if messaging:
            # Handle postback events (button clicks)
            if "postback" in messaging[0]:
                integration = Integration.objects.filter(instagram_account_id=account_id).first()
                if integration and integration.api_token:
                    handle_postback_event_task.delay(messaging[0], integration.api_token)
                return success_response(message=_("Postback muvaffaqiyatli olindi"), code=200)
            
            audio_file = None
            is_echo = messaging[0].get("message", {}).get("is_echo")
            reaction = messaging[0].get("reaction", {}).get("action", None)
            if reaction:
                print(f"Reaction received: {reaction}")
                return success_response(message=_("Reaction muvaffaqiyatli olindi"), code=200)
            if messaging[0].get("message", {}).get("attachments",[{}])[0].get('type') == 'audio':
                audio_file = messaging[0].get("message", {}).get("attachments", [{}])[0].get("payload", {}).get("url", None)
            elif messaging[0].get("message", {}).get("attachments",[{}])[0].get('type') in ['ig_reel', 'unsupported_type']:
                return success_response(message=_("Reel yoki qo'shimcha turdagi xabar muvaffaqiyatli olindi"), code=200)
            print(f"Is echo: {is_echo}, Audio file: {audio_file}")
            if is_echo:
                print("Echo message received")
                return success_response(message=_("Echo xabar muvaffaqiyatli olindi"), code=200)
            print(f"Messaging: {messaging}")
            sender_id = messaging[0].get("sender", {}).get("id", None)
            print(f"Sender ID: {sender_id}")
            if not Integration.objects.filter(instagram_account_id=sender_id).exists():
                if not Integration.objects.filter(instagram_account_id=account_id).exists():
                    print(f"Integration not found for account ID: {account_id}")
                    return error_response(message="Integration not found", code=404)
                # Start celery task to process the incoming message
                if audio_file:
                    process_instagram_message.delay(account_id, None, messaging,audio_file)
                else:
                    message = messaging[0].get("message", {}).get("text",None)
                    if message is not None:  # Only push if message is not None
                        # Buffer per end-user (sender_id) to avoid mixing conversations across users
                        redis_client.rpush(f"messages:{sender_id}", message)
                        redis_client.set(f"last_seen:{sender_id}", time.time())

                        # Schedule collector task only if not already scheduled for this sender
                        redis_client.setex(f"collecting:{sender_id}", WAIT_SECONDS + 1, "1")  # Prevent overlap
                        # Pass sender_id as chat_id, and include account_id for routing
                        process_collected_messages.apply_async((sender_id, None, messaging, None, None, account_id), countdown=WAIT_SECONDS)
                return success_response(message=_("Xabar webhook ma'lumotlar muvaffaqiyatli olindi"), code=200)
            else:
                print("Integration same found with the integration:", account_id)
                return success_response(message=_("Integratsiya boshqa foydalanuvchida ham topildi"), code=400)

        return success_response(message=_("Webhook ma'lumotlar muvaffaqiyatli olindi"), code=200)


class InstagramCallbackView(APIView):
    CLIENT_ID = INSTAGRAM_CLIENT_ID
    CLIENT_SECRET = INSTAGRAM_CLIENT_SECRET
    REDIRECT_URI = INSTAGRAM_REDIRECT_URI

    def get(self, request, *args, **kwargs):
        # Get the authorization code from the query parameters
        user = request.user if request.user.is_authenticated else None
        code = request.query_params.get("code")
        assistant_id = request.query_params.get("assistant_id", None)
        is_automation_only = request.query_params.get("is_automation_only", "false")
        if not assistant_id and is_automation_only == "false":
            return error_response(message=("Assistant ID topilmadi"), code=400)
        if not code:
            return error_response(message=("Authorization code topilmadi"), code=400)

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
        if response.status_code == 400:
            return error_response(message=response.json().get("error_message"), code=400)
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
            return error_response(message=("Access token topilmadi"), code=400)
        # get instagram user profile
        user_profile = get_user_profile(access_token)
        if user_profile:
            print(f"User Profile: {user_profile}")
            if Integration.objects.filter(instagram_account_id=user_profile.get("instagram_account_id")).exists():
                print("Sizda instagram integratsiyasi mavjud")
                return error_response(message=("Instagram integratsiyasi sizda mavjud"), code=400)
            integration, created = Integration.objects.get_or_create(
                instagram_user_id=user_profile.get("instagram_user_id"),
                user=user,
                integration_type=IntegrationTypes.INSTAGRAM.value,
                defaults={
                    "assistant_id": assistant_id,
                    "name": user_profile.get("instagram_username"),
                    "api_token": access_token,
                    "refresh_token": short_lived_access_token,
                    "instagram_account_id": user_profile.get("instagram_account_id"),
                    "instagram_username": user_profile.get("instagram_username"),
                }
            )
            if not created:
                return error_response(message=("Instagram integratsiyasi sizda mavjud"), code=200)
            print(f"Integration is successfully created: {integration}")
            # enqueue background build of Instagram knowledge base
            try:
                if assistant_id:
                    # transaction.on_commit(lambda: build_instagram_kb.delay(str(integration.id)))
                    print(f"Enqueued build_instagram_kb for integration: {integration.id}")
            except Exception as e:
                print(f"Failed to enqueue build_instagram_kb: {e}")
        else:
            return error_response(message=("Foydalanuvchi profili topilmadi"), code=400)
        
        # enable webhook for the integration
        url = f"https://graph.instagram.com/v22.0/me/subscribed_apps?access_token={access_token}&subscribed_fields=messages,comments"
        response = requests.post(url)
        print(f"Response: {response.text}")
        if response.status_code == 200:
            return success_response(message=("Integration muvaffaqiyatli yaratildi"), code=200)
        else:
            return error_response(message=("Webhook topilmadi"), code=400)

class InstagramDeauthorizeView(APIView):
    def post(self, request, *args, **kwargs): # noqa
        # Facebook sends a signed request
        signed_request = request.data.get("signed_request")
        print(f"Deauthorize Signed request: {signed_request}")
        if not signed_request:
            return error_response(message="Signed request not found", code=400)
        def parse_signed_request(signed_request: str, app_secret: str):
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
                    # Delete all related InstagramCommentResponse and their InstagramMedia
                    comment_responses = InstagramCommentResponse.objects.filter(integration=integration)
                    for response in comment_responses:
                        old_media = list(response.instagram_media.all())
                        print(f"Old media: {old_media}")
                        for media in old_media:
                            media.delete()
                        response.delete()
                    # Delete the integration itself
                    integration.delete()
                    print(f"User {user_id} deauthorized the app and their integration and related data were removed.")
                else:
                    print(f"User {user_id} deauthorized the app but no integration was found.")
                return success_response(message=_("Foydalanuvchi appni deauthorized qildi"), code=200)
            except Exception as e:
                print(f"Error during deauthorization: {str(e)}")
                return error_response(message=_("Deauthorization xatolik"), code=500)
        else:
            return error_response(message=_("Foydalanuvchi ID topilmadi"), code=400)


class InstagramDataDeletionView(APIView):
    def post(self, request, *args, **kwargs):
        signed_request = request.data.get("signed_request")

        if not signed_request:
            return error_response(message=_("Signed request topilmadi"), code=400)
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
        #handling username
        first_name = data.get("chat", {}).get("first_name", None)
        last_name = data.get("chat", {}).get("last_name", None)
        username = data.get("chat", {}).get("username", None)
        chat_username = None
        if first_name and last_name:
            chat_username = f"{first_name} {last_name}"
        elif first_name:
            chat_username = first_name
        else:
            chat_username = f"@{username}_{chat_id}"
        user_message = data.get('text', None)
        chat_group_id = data.get('chat', {}).get('id', None)
        if user_message or chat_group_id:
            print(f"Chat ID: {chat_id}, Message: {user_message}")
            if chat_type in ['group', 'supergroup']:
                # if "reply_to_message" in data and data["reply_to_message"]["from"]["is_bot"]:
                print("Ignoring group messages and replies to the bot.")
                
                if data.get('new_chat_member', {}).get('is_bot'):
                    handle_bot_added_to_group(chat_id, chat_title, bot_token)
                elif data.get('left_chat_member', {}).get('is_bot'):
                    handle_bot_removed_from_group(chat_id, chat_title)
            else:
                if "sticker" in data:
                    print("[-] Cannot handle sticker messages")
                    return success_response(message=_("Sticker message muvaffaqiyatli olindi"), code=200)
                
                if "document" in data:
                    print("[-] Cannot handle document messages")
                    return success_response(message=_("Document message muvaffaqiyatli olindi"), code=200)

                    # Voice message handling
                if "voice" in data:
                    voice_file_id = data["voice"]["file_id"]
                    process_voice_task.delay(chat_id, voice_file_id, bot_token)
                    return success_response(message=_("Voice message muvaffaqiyatli olindi"), code=200)
                # --- Redis Message Queuing ---
                if user_message:  # Only push if user_message is not None
                    redis_client.rpush(f"messages:{chat_id}", user_message)
                redis_client.set(f"last_seen:{chat_id}", time.time())

                # Schedule collector task only if not already scheduled
                print(f"chat_username: {chat_username}")
                print(f"contact username: {username}")
                redis_client.setex(f"collecting:{chat_id}", WAIT_SECONDS + 1, "1")  # Prevent overlap
                process_collected_messages.apply_async((chat_id, bot_token, None, chat_username, username, None), countdown=WAIT_SECONDS)
                # Start the Celery task
                print("celery task started")
        return success_response(message=_("Xabar muvaffaqiyatli olindi"), code=200)


class TelegramGroupListView(generics.ListAPIView):
    queryset = TelegramGroupIntegration.objects.all()
    serializer_class = TelegramGroupSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        integration_id = self.kwargs.get('pk')
        return self.queryset.filter(integration_id=integration_id)
    
class InstagramPostListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        integration_id = self.kwargs.get('pk')
        integration = Integration.objects.filter(id=integration_id, integration_type=IntegrationTypes.INSTAGRAM.value).first()
        if not integration:
            return error_response(message=_("Integration topilmadi"), code=400)
        access_token = integration.api_token
        url = "https://graph.instagram.com/v23.0/me/media"
        params = {
            "access_token": access_token,
            "fields": "id,media_type,media_url,username,timestamp,caption,comments_count,like_count,permalink,thumbnail_url,children{media_type,media_url}"
        }
        response = requests.get(url, params=params)
        if response.status_code == 200:
            data = response.json()["data"]
            return success_response(message=_("Instagram post muvaffaqiyatli olindi"), code=200, data=data)
        else:
            return error_response(message=_("Instagram post topilmadi"), code=400)
        

class CommentTriggerWordListCreateView(generics.CreateAPIView):
    queryset = CommentTriggerWord.objects.all()
    serializer_class = CommentTriggerWordSerializer
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(message=_("Trigger word muvaffaqiyatli yaratildi"), data=serializer.data, code=201)


class CommentTriggerWordRetrieveView(generics.RetrieveUpdateDestroyAPIView):
    queryset = CommentTriggerWord.objects.all()
    serializer_class = CommentTriggerWordSerializer
    permission_classes = [permissions.IsAuthenticated]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(message=_("Trigger word muvaffaqiyatli olindi"), data=serializer.data, code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return success_response(message=_("Trigger word muvaffaqiyatli o'zgartirildi"), data=serializer.data, code=200)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return success_response(message=_("Trigger word muvaffaqiyatli o'chirildi"), code=204)


class InstagramCommentResponseListCreateView(generics.ListCreateAPIView):
    queryset = InstagramCommentResponse.objects.all()
    serializer_class = InstagramCommentResponseSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        integration_id = self.kwargs.get('integration_id')
        integration_id = Integration.objects.filter(id = integration_id, integration_type=IntegrationTypes.INSTAGRAM.value).first()
        return self.queryset.filter(integration_id=integration_id)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return success_response(message=_("Comment responses muvaffaqiyatli olindi"), data=serializer.data, code=200)

    def create(self, request, *args, **kwargs):
        integration_id = self.kwargs.get('integration_id')
        try:
            integration = Integration.objects.get(id=integration_id, integration_type=IntegrationTypes.INSTAGRAM.value)
        except Integration.DoesNotExist:
            return error_response(message=_("Integration topilmadi"), code=404)
        
        serializer = self.get_serializer(data=request.data, context={"integration": integration})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(message=_("Comment response muvaffaqiyatli yaratildi"), data=serializer.data, code=201)


class InstagramCommentResponseRetrieveView(generics.RetrieveUpdateDestroyAPIView):
    queryset = InstagramCommentResponse.objects.all()
    serializer_class = InstagramCommentResponseSerializer
    permission_classes = [permissions.IsAuthenticated]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(message=_("Comment response muvaffaqiyatli olindi"), data=serializer.data, code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return success_response(message=_("Comment response muvaffaqiyatli o'zgartirildi"), data=serializer.data, code=200)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return success_response(message=_("Comment response muvaffaqiyatli o'chirildi"), code=204)

class InstagramMediaRetrieveView(generics.RetrieveUpdateDestroyAPIView):
    queryset = InstagramMedia.objects.all()
    serializer_class = InstagramMediaSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        # Add custom things here
        context["integration"] = Integration.objects.filter(
            user=self.request.user,
            integration_type=IntegrationTypes.INSTAGRAM.value
        ).first()
        return context

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(message=_("Instagram media muvaffaqiyatli olindi"), data=serializer.data, code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return success_response(message=_("Instagram media muvaffaqiyatli o'zgartirildi"), data=serializer.data, code=200)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return success_response(message=_("Instagram media muvaffaqiyatli o'chirildi"), code=204)
    

class InstagramCommentResponseFlowListCreateView(generics.ListCreateAPIView):
    queryset = Flow.objects.all()
    serializer_class = InstagramCommentResponseFlowSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        id = self.kwargs.get('pk')
        return self.queryset.filter(comment_response_id=id)
    
    def get_serializer_context(self):
        """Pass pk to serializer context for linking"""
        context = super().get_serializer_context()
        context["comment_response_id"] = self.kwargs.get("pk")
        return context
    

class InstagramFlowTransitionListCreateView(generics.ListCreateAPIView):
    queryset = Transition.objects.all()
    serializer_class = TransitionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        flow_id = self.kwargs.get("pk")
        # Return only transitions whose from_to step belongs to this flow
        if not Flow.objects.filter(id=flow_id).exists():
            return self.queryset.none()
        return self.queryset.all()

    def create(self, request, *args, **kwargs):
        flow_id = self.kwargs.get("pk")
        # Support both single object and list payloads (do not hard-fail on single)
        is_many = isinstance(request.data, list)
        serializer = self.get_serializer(data=request.data, many=is_many)
        serializer.is_valid(raise_exception=True)

        # Validate that transitions belong to the provided flow
        def _validate_transition(datum):
            from_step = datum.get("from_to")
            to_step = datum.get("to_step")
            from_step_id = getattr(from_step, "id", from_step)
            to_step_id = getattr(to_step, "id", to_step)
            
            # Steps must belong to the same flow
            if from_step:
                if not Step.objects.filter(id=from_step_id, flow_id=flow_id).exists():
                    raise ValueError("from_to step does not belong to this flow")
            if to_step:
                if not Step.objects.filter(id=to_step_id, flow_id=flow_id).exists():
                    raise ValueError("to_step does not belong to this flow")
        try:
            if is_many:
                for item in serializer.validated_data:
                    _validate_transition(item)
            else:
                _validate_transition(serializer.validated_data)
        except ValueError as e:
            return error_response(message=str(e), code=400)

        self.perform_create(serializer)
        return success_response(data=serializer.data)


class TransitionRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Transition.objects.all()
    serializer_class = TransitionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        # Optional: ensure steps remain in the same flow
        from_to = serializer.validated_data.get("from_to") or instance.from_to
        to_step = serializer.validated_data.get("to_step") or instance.to_step
        if to_step and from_to.flow_id != to_step.flow_id:
            return error_response(message=_("Steps must belong to the same flow"), code=400)
        self.perform_update(serializer)
        return success_response(message=_("Transition muvaffaqiyatli o'zgartirildi"), data=serializer.data, code=200)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return success_response(message=_("Transition muvaffaqiyatli o'chirildi"), code=204)


class FlowRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Flow.objects.all()
    serializer_class = InstagramCommentResponseFlowSerializer
    permission_classes = [permissions.IsAuthenticated]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(message=_("Flow muvaffaqiyatli olindi"), data=serializer.data, code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return success_response(message=_("Flow muvaffaqiyatli o'zgartirildi"), data=serializer.data, code=200)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return success_response(message=_("Flow muvaffaqiyatli o'chirildi"), code=204)


class StepRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Step.objects.all()
    serializer_class = StepSerializer
    permission_classes = [permissions.IsAuthenticated]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(message=_("Step muvaffaqiyatli olindi"), data=serializer.data, code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        extra_buttons = request.data.pop("extra_buttons", None)
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        # Replace buttons if provided
        if extra_buttons is not None:
            instance.extra_button.clear()
            for btn in extra_buttons:
                btn_obj = CommentResponseButton.objects.create(**btn)
                instance.extra_button.add(btn_obj)
        return success_response(message=_("Step muvaffaqiyatli o'zgartirildi"), data=self.get_serializer(instance).data, code=200)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return success_response(message=_("Step muvaffaqiyatli o'chirildi"), code=204)


class CommentResponseButtonListCreateView(generics.ListCreateAPIView):
    queryset = CommentResponseButton.objects.all()
    serializer_class = CommentResponseButtonSerializer
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return success_response(message=_("Tugmalar muvaffaqiyatli olindi"), data=serializer.data, code=200)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return success_response(message=_("Tugma muvaffaqiyatli yaratildi"), data=serializer.data, code=201)


class CommentResponseButtonRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = CommentResponseButton.objects.all()
    serializer_class = CommentResponseButtonSerializer
    permission_classes = [permissions.IsAuthenticated]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return success_response(message=_("Tugma muvaffaqiyatli olindi"), data=serializer.data, code=200)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return success_response(message=_("Tugma muvaffaqiyatli o'zgartirildi"), data=serializer.data, code=200)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return success_response(message=_("Tugma muvaffaqiyatli o'chirildi"), code=204)


class AmoCRMOAuthInstallView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        try:
            # Get parameters from request
            subdomain = 'repli'
            user_id = request.user.id
            
            if not subdomain:
                return error_response(
                    message="Subdomain is required", 
                    code=400
                )
            
            # Use credentials from settings
            client_id = getattr(settings, 'AMOCRM_CLIENT_ID', None)
            client_secret = getattr(settings, 'AMOCRM_SECRET_KEY', None)
            
            if not client_id or not client_secret:
                return error_response(
                    message="amoCRM credentials not configured", 
                    code=500
                )
            
            # Generate state parameter for security
            state = secrets.token_urlsafe(32)
            
            # Store state and user info in session/redis for verification
            redis_client.setex(
                f"amocrm_oauth_state:{state}", 
                300,  # 5 minutes expiry
                json.dumps({
                    'user_id': str(user_id),  # Convert UUID to string
                    'subdomain': subdomain,
                    'client_id': client_id,
                    'client_secret': client_secret
                })
            )
            
            # Build OAuth authorization URL
            redirect_uri = f"{settings.BASE_URL}/api/v1/integration/amocrm/"
            auth_params = {
                'response_type': 'code',
                'client_id': client_id,
                'redirect_uri': redirect_uri,
                'state': state
            }
            
            auth_url = f"https://www.amocrm.ru/oauth?{urlencode(auth_params)}"
            
            return success_response(
                data={
                    'auth_url': auth_url,
                    'state': state,
                    'subdomain': subdomain
                },
                message="amoCRM OAuth URL generated successfully",
                code=200
            )
            
        except Exception as e:
            return error_response(
                message=f"Error generating amoCRM OAuth URL: {str(e)}",
                code=500
            )


class AmoCRMOAuthHandlerView(APIView):
    permission_classes = [permissions.AllowAny]  # amoCRM will call this directly
    
    def get(self, request):
        try:
            # Get OAuth parameters
            code = request.GET.get('code')
            state = request.GET.get('state')
            referer = request.GET.get('referer')  # amoCRM subdomain
            error = request.GET.get('error')
            
            if error:
                return error_response(
                    message=f"OAuth error: {error}",
                    code=400
                )
            
            if not code or not state or not referer:
                return error_response(
                    message="Missing required OAuth parameters",
                    code=400
                )
            
            # Verify state parameter
            stored_state = redis_client.get(f"amocrm_oauth_state:{state}")
            if not stored_state:
                return error_response(
                    message="Invalid or expired state parameter",
                    code=400
                )
            
            state_data = json.loads(stored_state)
            user_id = state_data.get('user_id')
            client_id = state_data.get('client_id')
            client_secret = state_data.get('client_secret')
            
            # Exchange authorization code for access token
            token_url = f"https://{referer}/oauth2/access_token"
            token_data = {
                'grant_type': 'authorization_code',
                'client_id': client_id,
                'client_secret': client_secret,
                'redirect_uri': f"{settings.BASE_URL}/api/v1/integration/amocrm/",
                'code': code
            }
            
            token_response = requests.post(token_url, data=token_data)
            
            if token_response.status_code != 200:
                return error_response(
                    message=f"Failed to exchange code for token: {token_response.text}",
                    code=400
                )
            
            print(f"[DEBUG] Token response status: {token_response.status_code}")
            print(f"[DEBUG] Token response: {token_response.text}")
            
            if token_response.status_code != 200:
                return error_response(
                    message=f"Failed to exchange code for token: {token_response.text}",
                    code=400
                )
            
            token_info = token_response.json()
            access_token = token_info.get('access_token')
            print(f"[DEBUG] Access token: {access_token}")
            refresh_token = token_info.get('refresh_token')
            expires_in = token_info.get('expires_in')
            print(f"[DEBUG] Refresh token: {refresh_token}")
            print(f"[DEBUG] Expires in: {expires_in}")
            
            if not access_token:
                return error_response(
                    message="No access token received from amoCRM",
                    code=400
                )
            # Get user info from amoCRM
            user_info_url = f"https://{referer}/api/v4/account"
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
            user_response = requests.get(user_info_url, headers=headers)
            print(f"[DEBUG] User response: {user_response.text}")
            if user_response.status_code != 200:
                return error_response(
                    message="Failed to get user information from amoCRM",
                    code=400
                )
            
            user_info = user_response.json()
            account_id = user_info.get('id')
            print(f"[DEBUG] Account ID: {account_id}")
            # Create or update integration
            from apps.assistant.models import Assistant
            assistant = Assistant.objects.filter(user_id=user_id).first()
            
            if not assistant:
                return error_response(
                    message="No assistant found for user",
                    code=404
                )
            
            integration, created = Integration.objects.get_or_create(
                assistant=assistant,
                integration_type=IntegrationTypes.AMOCRM.value,
                defaults={
                    'name': f"amoCRM - {referer}",
                    'api_token': access_token,
                    'metadata': {
                        'subdomain': referer,
                        'client_id': client_id,
                        'refresh_token': refresh_token,
                        'expires_in': expires_in,
                        'account_id': account_id,
                        'user_info': user_info
                    }
                }
            )
            
            if not created:
                # Update existing integration
                integration.api_token = access_token
                integration.metadata.update({
                    'subdomain': referer,
                    'client_id': client_id,
                    'refresh_token': refresh_token,
                    'expires_in': expires_in,
                    'account_id': account_id,
                    'user_info': user_info
                })
                integration.save()
            
            # Clean up state
            redis_client.delete(f"amocrm_oauth_state:{state}")
            
            return success_response(
                data={
                    'integration_id': str(integration.id),
                    'subdomain': referer,
                    'account_id': account_id,
                    'user_info': user_info
                },
                message="amoCRM integration successful",
                code=200
            )
            
        except Exception as e:
            return error_response(
                message=f"Error processing amoCRM OAuth callback: {str(e)}",
                code=500
            )


class AmoCRMTokenRefreshView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        try:
            integration_id = request.data.get('integration_id')
            if not integration_id:
                return error_response(
                    message="Integration ID is required",
                    code=400
                )
            
            integration = Integration.objects.filter(
                id=integration_id,
                integration_type=IntegrationTypes.AMOCRM.value
            ).first()
            
            if not integration:
                return error_response(
                    message="amoCRM integration not found",
                    code=404
                )
            
            metadata = integration.metadata or {}
            refresh_token = metadata.get('refresh_token')
            subdomain = metadata.get('subdomain')
            client_id = metadata.get('client_id')
            client_secret = getattr(settings, 'AMOCRM_SECRET_KEY', None)
            
            if not refresh_token or not subdomain or not client_secret:
                return error_response(
                    message="Missing refresh token or credentials",
                    code=400
                )
            
            # Refresh the token
            token_url = f"https://{subdomain}/oauth2/access_token"
            token_data = {
                'grant_type': 'refresh_token',
                'client_id': client_id,
                'client_secret': client_secret,
                'refresh_token': refresh_token
            }
            
            token_response = requests.post(token_url, data=token_data)
            
            if token_response.status_code != 200:
                return error_response(
                    message=f"Failed to refresh token: {token_response.text}",
                    code=400
                )
            
            token_info = token_response.json()
            new_access_token = token_info.get('access_token')
            new_refresh_token = token_info.get('refresh_token')
            new_expires_in = token_info.get('expires_in')
            
            # Update integration with new tokens
            integration.api_token = new_access_token
            integration.metadata.update({
                'refresh_token': new_refresh_token,
                'expires_in': new_expires_in,
                'last_refresh': time.time()
            })
            integration.save()
            
            return success_response(
                data={
                    'access_token': new_access_token,
                    'expires_in': new_expires_in
                },
                message="Token refreshed successfully",
                code=200
            )
            
        except Exception as e:
            return error_response(
                message=f"Error refreshing token: {str(e)}",
                code=500
            )


class AmoCRMSetPipelineView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        try:
            integration_id = request.data.get('integration_id')
            pipeline_id = request.data.get('pipeline_id')
            if not integration_id or not pipeline_id:
                return error_response(
                    message="Integration ID and Pipeline ID are required",
                    code=400
                )
            
            integration = Integration.objects.filter(
                id=integration_id,
                integration_type=IntegrationTypes.AMOCRM.value
            ).first()
            
            if not integration:
                return error_response(
                    message="amoCRM integration not found",
                    code=404
                )
            
            # Get pipeline info from amoCRM
            print(f"[DEBUG] Integration metadata: {integration.metadata}")
            subdomain = integration.metadata.get('subdomain') if integration.metadata else 'repli.amocrm.ru'
            print(f"[DEBUG] Subdomain: {subdomain}")
            access_token = integration.api_token
            
            # Get pipeline details
            pipeline_url = f"https://{subdomain}/api/v4/leads/pipelines/{pipeline_id}"
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
            
            pipeline_response = requests.get(pipeline_url, headers=headers)
            
            if pipeline_response.status_code != 200:
                return error_response(
                    message=f"Failed to get pipeline info: {pipeline_response.text}",
                    code=400
                )
            
            pipeline_info = pipeline_response.json()
            pipeline_name = pipeline_info.get('name', f'Pipeline {pipeline_id}')
            
            # Update integration metadata
            integration.metadata.update({
                'pipeline_id': pipeline_id,
                'pipeline_name': pipeline_name,
                'pipeline_info': pipeline_info
            })
            integration.save()
            
            return success_response(
                data={
                    'pipeline_id': pipeline_id,
                    'pipeline_name': pipeline_name,
                    'integration_id': str(integration.id)
                },
                message="Pipeline set successfully",
                code=200
            )
            
        except Exception as e:
            return error_response(
                message=f"Error setting pipeline: {str(e)}",
                code=500
            )
        
class BillzSecretTokenHandlerView(generics.CreateAPIView):
    serializer_class = IntegrationSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = Integration.objects.all()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['assistant_id'] = self.kwargs.get('pk')
        return context