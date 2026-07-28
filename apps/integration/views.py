import logging
import requests
import base64
import hashlib
import hmac
import time
import json
import secrets

logger = logging.getLogger(__name__)

from django.db.models import Q
from django.conf import settings
from urllib.parse import urlencode
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework import generics, permissions
from django.utils.translation import gettext_lazy as _

from config.settings import INSTAGRAM_CLIENT_ID, INSTAGRAM_CLIENT_SECRET, INSTAGRAM_REDIRECT_URI
from shared.addons.enums import IntegrationTypes
from shared.addons.telegram import handle_bot_added_to_group, handle_bot_removed_from_group
from shared.addons.validations import success_response, error_response
from shared.permissions import IsCustomer
from apps.shared.addons.instagram import instagram_service
from apps.assistant.models import Assistant
from .models import Integration, TelegramGroupIntegration, InstagramMedia, CommentTriggerWord, InstagramCommentResponse, Flow, Transition, Step, CommentResponseButton, Broadcast
from .serializers import (IntegrationCreateSerializer,
                        IntegrationSerializer,
                        SendUserMessageSerializer,
                        SendIntegrationMessageSerializer,
                        TelegramGroupSerializer,
                        InstagramMediaSerializer,
                        CommentTriggerWordSerializer,
                        InstagramCommentResponseSerializer,
                        InstagramCommentResponseFlowSerializer,
                        TransitionSerializer,
                        StepSerializer,
                        CommentResponseButtonSerializer,
                        BroadcastSerializer)
from .tasks import (process_instagram_message,
                    process_voice_task,
                    process_photo_task,
                    process_instagram_comment,
                    WAIT_SECONDS,
                    process_collected_messages,
                    handle_postback_event_task,
                    send_message_integration_task)
try:
    from .tasks import process_shared_post_message
except ImportError:
    process_shared_post_message = None

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
        # Filtering by the URL's assistant alone let any authenticated user
        # list another tenant's integrations — including their Telegram bot
        # `api_token`, i.e. full takeover of the victim's bot.
        assistant_id = self.kwargs.get('pk')
        return self.queryset.filter(
            Q(assistant__user=self.request.user) | Q(user=self.request.user),
            assistant_id=assistant_id,
        ).distinct()

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

    def get_queryset(self):
        # Scope at the queryset so retrieve/update/destroy all 404 on another
        # tenant's integration. The previous `get_object` *returned* an
        # `error_response(...)` — a DRF `Response` — which the handlers then
        # used as if it were a model instance, so every cross-tenant request
        # blew up with a 500 (`'Response' object has no attribute 'delete'`)
        # rather than being refused.
        return self.queryset.filter(
            Q(assistant__user=self.request.user) | Q(user=self.request.user),
        ).distinct()

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
        # Drop the Meta subscription first, otherwise Instagram keeps delivering
        # webhooks for an account that no longer resolves to an integration.
        if instance.integration_type == IntegrationTypes.INSTAGRAM.value:
            instagram_service.unsubscribe_webhooks(instance.api_token)
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


class SendIntegrationMessageView(generics.CreateAPIView):
    serializer_class = SendIntegrationMessageSerializer
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request, *args, **kwargs):
        integration_id = self.kwargs.get('pk')
        message = request.data.get("message")
        if not message:
            return error_response(message=_("Xabar mavjud emas"), code=400)
        if not integration_id:
            return error_response(message=_("Integration ID mavjud emas"), code=400)
        try:
            integration = Integration.objects.get(id=integration_id)
            if integration.assistant.user != request.user:
                return error_response(message=_("Sizda bu integration mavjud emas"), code=400)
        except Integration.DoesNotExist:
            return error_response(message=_("Integration topilmadi"), code=404)
        send_message_integration_task.delay(integration_id, message)
        return success_response(message=_("Xabar muvaffaqiyatli yuborildi"), code=200)


class InstagramWebhookView(APIView):

    def _verify_signature(self, request):
        """Verify Instagram X-Hub-Signature-256 header."""
        app_secret = settings.INSTAGRAM_APP_SECRET
        if not app_secret:
            # Fail closed: without a configured secret we cannot authenticate
            # the sender, so reject rather than accept forged events.
            logger.error("INSTAGRAM_APP_SECRET is not configured; rejecting webhook")
            return False

        signature_header = request.META.get('HTTP_X_HUB_SIGNATURE_256', '')
        if not signature_header:
            return False

        expected_signature = 'sha256=' + hmac.new(
            app_secret.encode('utf-8'),
            request.body,
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(signature_header, expected_signature)

    def get(self, request, *args, **kwargs):
        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge")

        if mode == "subscribe" and settings.INSTAGRAM_VERIFY_TOKEN and token == settings.INSTAGRAM_VERIFY_TOKEN:
            return HttpResponse(challenge, content_type="text/plain", status=200)

        return error_response(message=_("Token yaroqsiz"), code=403)

    def post(self, request, *args, **kwargs):  # noqa
        if not self._verify_signature(request):
            return error_response(message=_("Invalid signature"), code=403)

        data = request.data
        if not data:
            return error_response(message=_("Ma'lumot topilmadi"), code=400)

        entries = data.get("entry") or []
        if not entries:
            logger.warning("Instagram webhook carried no entry")
            return success_response(message=_("Ma'lumot topilmadi"), code=200)
        if len(entries) > 1:
            # Meta batches deliveries; only the first is handled below.
            logger.warning("Instagram webhook carried %s entries — only the first is processed", len(entries))

        entry = entries[0]
        account_id = entry.get("id") # IG Professional Account ID (instagram_user_id)

        # Shape only — never the message body, which is customer content.
        logger.info(
            "Instagram webhook received for account %s: keys=%s changes=%s",
            account_id, sorted(entry.keys()),
            [c.get("field") for c in entry.get("changes", [])],
        )

        # Handle comments
        if "changes" in entry:
            for change in entry["changes"]:
                if change.get("field") == "comments":
                    comment_data = change.get("value", {})
                    if not comment_data:
                        logger.warning("Instagram comment change for %s had an empty value", account_id)
                        continue
                    # Get access token from integration
                    integration = Integration.instagram_by_id(account_id).first()
                    if not integration:
                        logger.warning("Instagram comment for unknown account %s", account_id)
                        continue
                    if not integration.api_token:
                        logger.warning("Instagram integration %s has no api_token; comment dropped", integration.id)
                        continue
                    process_instagram_comment.delay(account_id, comment_data)
                    return success_response(message=_("Comment webhook ma'lumotlar muvaffaqiyatli olindi"), code=200)

        # Instagram delivers DMs in one of two shapes. The classic one is
        # entry[].messaging[]; the Instagram-Login product instead sends a
        # changes[] entry with field "messages" whose `value` mirrors a
        # messaging item (sender / recipient / message). In that shape entry.id
        # is "0", so the account has to be read off the recipient.
        messaging = entry.get("messaging")
        if not messaging:
            messaging = [
                change.get("value")
                for change in entry.get("changes", [])
                if change.get("field") == "messages" and change.get("value")
            ]
        if messaging and account_id in (None, "", "0", 0):
            account_id = (messaging[0].get("recipient") or {}).get("id")
            logger.info("Instagram account resolved from the message recipient: %s", account_id)

        if messaging:
            # Handle postback events (button clicks)
            if "postback" in messaging[0]:
                integration = Integration.instagram_by_id(account_id).first()
                if integration and integration.api_token:
                    handle_postback_event_task.delay(messaging[0], integration.api_token)
                return success_response(message=_("Postback muvaffaqiyatli olindi"), code=200)
            
            # Deduplicate: check message ID to prevent processing the same webhook twice
            msg_mid = messaging[0].get("message", {}).get("mid")
            if msg_mid:
                dedup_key = f"ig_dedup:{msg_mid}"
                if redis_client.get(dedup_key):
                    logger.info(f"Duplicate Instagram message detected: {msg_mid}")
                    return success_response(message=_("Duplicate message ignored"), code=200)
                redis_client.setex(dedup_key, 300, "1")  # 5 min TTL

            audio_file = None
            is_echo = messaging[0].get("message", {}).get("is_echo")
            reaction = messaging[0].get("reaction", {}).get("action", None)
            if reaction:
                return success_response(message=_("Reaction muvaffaqiyatli olindi"), code=200)
            attachment_type = messaging[0].get("message", {}).get("attachments",[{}])[0].get('type')
            if attachment_type == 'audio':
                audio_file = messaging[0].get("message", {}).get("attachments", [{}])[0].get("payload", {}).get("url", None)
            elif attachment_type == 'share':
                # User shared a post/reel in DM — extract post URL and process with context
                shared_url = messaging[0].get("message", {}).get("attachments", [{}])[0].get("payload", {}).get("url", None)
                user_text = messaging[0].get("message", {}).get("text", None)
                sender_id = messaging[0].get("sender", {}).get("id", None)
                if sender_id and not Integration.instagram_by_id(sender_id).exists():
                    if Integration.instagram_by_id(account_id).exists() and process_shared_post_message:
                        process_shared_post_message.delay(account_id, shared_url, user_text, messaging)
                return success_response(message=_("Shared post xabar muvaffaqiyatli olindi"), code=200)
            elif attachment_type in ['ig_reel', 'unsupported_type']:
                return success_response(message=_("Reel yoki qo'shimcha turdagi xabar muvaffaqiyatli olindi"), code=200)
            if is_echo:
                return success_response(message=_("Echo xabar muvaffaqiyatli olindi"), code=200)
            sender_id = messaging[0].get("sender", {}).get("id", None)
            if not Integration.instagram_by_id(sender_id).exists():
                if not Integration.instagram_by_id(account_id).exists():
                    # Ack unknown accounts: repeated non-2xx replies make Meta
                    # throttle and eventually disable the webhook subscription.
                    logger.warning("Integration not found for Instagram account %s", account_id)
                    return success_response(message=_("Integratsiya topilmadi"), code=200)
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
                logger.info("Instagram sender %s is itself an integrated account; skipping", account_id)
                return success_response(message=_("Integratsiya boshqa foydalanuvchida ham topildi"), code=400)

        # Nothing above claimed this delivery. Ack it — Meta disables a
        # subscription that keeps failing — but say so, because this used to be
        # indistinguishable from a handled event in the logs.
        logger.warning(
            "Instagram webhook for %s was not handled: keys=%s changes=%s",
            account_id, sorted(entry.keys()),
            [c.get("field") for c in entry.get("changes", [])],
        )
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

        response = requests.post(token_url, data=data)
        if response.status_code == 400:
            return error_response(message=response.json().get("error_message"), code=400)
        if response.status_code == 200:
            token_data = response.json()
            short_lived_access_token = token_data.get("access_token")
            # Fetch Instagram Business Accounts
            access_token = instagram_service.get_long_lived_access_token(short_lived_access_token)
        else:
            return error_response(message=("Access token topilmadi"), code=400)
        # get instagram user profile
        user_profile = instagram_service.get_user_profile(access_token)
        if not user_profile:
            return error_response(message=("Foydalanuvchi profili topilmadi"), code=400)

        instagram_account_id = user_profile.get("instagram_account_id")
        instagram_user_id = user_profile.get("instagram_user_id")
        if not instagram_account_id:
            logger.warning("Instagram profile returned no user_id; refusing to create an unroutable integration")
            return error_response(message=("Foydalanuvchi profili topilmadi"), code=400)

        # A row for this identity may already exist. Matched explicitly rather
        # than with update_or_create, which raises MultipleObjectsReturned when
        # instagram_user_id and user are both NULL on more than one row — the
        # callback runs unauthenticated, so user is regularly NULL.
        existing = None
        if instagram_user_id:
            existing = Integration.objects.filter(
                instagram_user_id=instagram_user_id,
                user=user,
                integration_type=IntegrationTypes.INSTAGRAM.value,
            ).first()

        if existing and existing.instagram_account_id:
            logger.info("Instagram integration already exists for account %s", instagram_account_id)
            return error_response(message=("Instagram integratsiyasi sizda mavjud"), code=400)

        # Any *other* row holding either identifier is a genuine duplicate.
        duplicates = Integration.instagram_by_id(instagram_account_id)
        if instagram_user_id:
            duplicates = duplicates | Integration.instagram_by_id(instagram_user_id)
        if existing:
            duplicates = duplicates.exclude(pk=existing.pk)
        if duplicates.exists():
            logger.info("Instagram integration already exists for account %s", instagram_account_id)
            return error_response(message=("Instagram integratsiyasi sizda mavjud"), code=400)

        fields = {
            "assistant_id": assistant_id,
            "name": user_profile.get("instagram_username"),
            "api_token": access_token,
            "refresh_token": short_lived_access_token,
            "instagram_account_id": instagram_account_id,
            "instagram_username": user_profile.get("instagram_username"),
        }
        # Repair rather than get_or_create: a row left behind by an earlier failed
        # attempt keeps its blank identity columns (get_or_create skips its defaults
        # on a match), staying invisible to every webhook lookup.
        if existing:
            for field, value in fields.items():
                setattr(existing, field, value)
            existing.save()
            integration = existing
            logger.info("Instagram integration %s relinked", integration.id)
        else:
            integration = Integration.objects.create(
                instagram_user_id=instagram_user_id,
                user=user,
                integration_type=IntegrationTypes.INSTAGRAM.value,
                **fields,
            )
            logger.info("Instagram integration %s created", integration.id)

        # enable webhook for the integration
        url = f"https://graph.instagram.com/v22.0/me/subscribed_apps?access_token={access_token}&subscribed_fields=messages,comments"
        response = requests.post(url)
        if response.status_code != 200:
            logger.warning("Instagram webhook subscription failed with status %s", response.status_code)
        if response.status_code == 200:
            return success_response(message=("Integration muvaffaqiyatli yaratildi"), code=200)
        else:
            return error_response(message=("Webhook topilmadi"), code=400)

class InstagramDeauthorizeView(APIView):
    def post(self, request, *args, **kwargs): # noqa
        # Facebook sends a signed request
        signed_request = request.data.get("signed_request")
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
                    logger.warning("Instagram deauthorize: invalid signed request signature")
                    return None

                return data

            except Exception:
                logger.exception("Error parsing Instagram signed request")
                return None


        data = parse_signed_request(signed_request, INSTAGRAM_CLIENT_SECRET)
        if not data:
            return error_response(message="Invalid signed request", code=400)

        user_id = data.get("user_id")
        if user_id:
            # Find and remove the user's Instagram integration
            try:
                # The signed request carries the app-scoped ID, which OAuth
                # stores in instagram_user_id — match either column.
                integration = Integration.instagram_by_id(user_id).first()
                if integration:
                    # Delete all related InstagramCommentResponse and their InstagramMedia
                    comment_responses = InstagramCommentResponse.objects.filter(integration=integration)
                    for response in comment_responses:
                        old_media = list(response.instagram_media.all())
                        for media in old_media:
                            media.delete()
                        response.delete()
                    # Delete the integration itself
                    integration.delete()
                    logger.info("Instagram user %s deauthorized the app; integration removed", user_id)
                else:
                    logger.info("Instagram user %s deauthorized the app but no integration was found", user_id)
                return success_response(message=_("Foydalanuvchi appni deauthorized qildi"), code=200)
            except Exception:
                logger.exception("Error during Instagram deauthorization")
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
                    logger.warning("Instagram data deletion: invalid signed request signature")
                    return None

                return data

            except Exception:
                logger.exception("Error parsing Instagram signed request")
                return None

        data = parse_signed_request(signed_request, INSTAGRAM_CLIENT_SECRET)
        if not data:
            return error_response(message="Invalid signed request", code=400)

        user_id = data.get("user_id")
        if user_id:
            # Process data deletion for the user
            logger.info("Instagram data deletion requested for user %s", user_id)
            return success_response(data={
                "url": "https://api.repli.uz/integration/instagram/data-deletion-status/",
                "confirmation_code": user_id
            }, code=200)
        else:
            return error_response(message="User ID not found in signed request", code=400)


class TelegramWebhookView(APIView):
    def post(self, request, bot_token):  # noqa
        # Verify the bot token exists as an integration
        if not Integration.objects.filter(api_token=bot_token).exists():
            return error_response(message=_("Invalid bot token"), code=403)

        # Deduplicate: use Telegram update_id
        update_id = request.data.get('update_id')
        if update_id:
            dedup_key = f"tg_dedup:{update_id}"
            if redis_client.get(dedup_key):
                logger.info(f"Duplicate Telegram update detected: {update_id}")
                return success_response(message=_("Duplicate update ignored"), code=200)
            redis_client.setex(dedup_key, 300, "1")  # 5 min TTL

        data = request.data.get('message')
        if not data:
            return error_response(message=_("No message data received"))
        logger.info(f"Telegram webhook received for bot_token ending ...{bot_token[-6:]}")
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
            if chat_type in ['group', 'supergroup']:
                if data.get('new_chat_member', {}).get('is_bot'):
                    handle_bot_added_to_group(chat_id, chat_title, bot_token)
                elif data.get('left_chat_member', {}).get('is_bot'):
                    handle_bot_removed_from_group(chat_id, chat_title)
            else:
                if "sticker" in data:
                    return success_response(message=_("Sticker message muvaffaqiyatli olindi"), code=200)

                if "document" in data:
                    return success_response(message=_("Document message muvaffaqiyatli olindi"), code=200)

                # Photo message handling
                if "photo" in data:
                    photos = data["photo"]
                    if photos:
                        # Get the largest photo (last in the array)
                        largest_photo = photos[-1]
                        photo_file_id = largest_photo.get("file_id")
                        if photo_file_id:
                            process_photo_task.delay(chat_id, photo_file_id, bot_token, chat_username, username)
                            return success_response(message=_("Photo message muvaffaqiyatli olindi"), code=200)

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
                redis_client.setex(f"collecting:{chat_id}", WAIT_SECONDS + 1, "1")  # Prevent overlap
                process_collected_messages.apply_async((chat_id, bot_token, None, chat_username, username, None), countdown=WAIT_SECONDS)
        return success_response(message=_("Xabar muvaffaqiyatli olindi"), code=200)


class TelegramGroupListView(generics.ListAPIView):
    queryset = TelegramGroupIntegration.objects.all()
    serializer_class = TelegramGroupSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        integration_id = self.kwargs.get('pk')
        qs = self.queryset.filter(integration_id=integration_id)
        is_approved = self.request.query_params.get('is_approved')
        if is_approved is not None:
            qs = qs.filter(is_approved=is_approved.lower() == 'true')
        return qs


class TelegramGroupUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = TelegramGroupIntegration.objects.all()
    serializer_class = TelegramGroupSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        obj = super().get_object()
        integration = obj.integration
        if integration.assistant and integration.assistant.user != self.request.user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied(_("Bu guruhni boshqarish huquqi yo'q"))
        return obj

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        is_approving = request.data.get('is_approved')
        if is_approving is True or is_approving == 'true' or is_approving == True:
            from shared.addons.telegram import check_bot_in_group
            token = instance.integration.api_token
            if not check_bot_in_group(instance.group_id, token):
                return error_response(
                    message=_("Bot bu guruhda mavjud emas. Avval botni guruhga qo'shing."),
                    code=400
                )
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            data=serializer.data,
            message=_("Telegram guruh muvaffaqiyatli yangilandi"),
            code=200
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return success_response(
            message=_("Telegram guruh muvaffaqiyatli o'chirildi"),
            code=204
        )


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
            "fields": "id,media_type,media_url,username,timestamp,caption,comments_count,like_count,permalink,thumbnail_url,children{media_type,media_url}",
            "limit": 50
        }
        all_posts = []
        max_pages = 5
        for _page in range(max_pages):
            response = requests.get(url, params=params)
            if response.status_code != 200:
                break
            json_data = response.json()
            all_posts.extend(json_data.get("data", []))
            next_url = json_data.get("paging", {}).get("next")
            if not next_url:
                break
            url = next_url
            params = {}
        if all_posts:
            return success_response(message=_("Instagram post muvaffaqiyatli olindi"), code=200, data=all_posts)
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

    def get_queryset(self):
        # Without this the view was `objects.all()` + IsAuthenticated:
        # any logged-in user could read, edit and DELETE another
        # tenant's automation objects.
        user = self.request.user
        return self.queryset.filter(
            Q(instagram_comment_responses__integration__assistant__user=user) | Q(instagram_comment_responses__integration__user=user),
        ).distinct()

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

    def get_queryset(self):
        # Without this the view was `objects.all()` + IsAuthenticated:
        # any logged-in user could read, edit and DELETE another
        # tenant's automation objects.
        user = self.request.user
        return self.queryset.filter(
            Q(integration__assistant__user=user) | Q(integration__user=user),
        ).distinct()

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

    def get_queryset(self):
        # Without this the view was `objects.all()` + IsAuthenticated:
        # any logged-in user could read, edit and DELETE another
        # tenant's automation objects.
        user = self.request.user
        return self.queryset.filter(
            Q(instagram_comment_responses__integration__assistant__user=user) | Q(instagram_comment_responses__integration__user=user),
        ).distinct()

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

    def get_queryset(self):
        # Without this the view was `objects.all()` + IsAuthenticated:
        # any logged-in user could read, edit and DELETE another
        # tenant's automation objects.
        user = self.request.user
        return self.queryset.filter(
            Q(from_to__flow__comment_response__integration__assistant__user=user) | Q(from_to__flow__comment_response__integration__user=user),
        ).distinct()

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

    def get_queryset(self):
        # Without this the view was `objects.all()` + IsAuthenticated:
        # any logged-in user could read, edit and DELETE another
        # tenant's automation objects.
        user = self.request.user
        return self.queryset.filter(
            Q(comment_response__integration__assistant__user=user) | Q(comment_response__integration__user=user),
        ).distinct()

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

    def get_queryset(self):
        # Without this the view was `objects.all()` + IsAuthenticated:
        # any logged-in user could read, edit and DELETE another
        # tenant's automation objects.
        user = self.request.user
        return self.queryset.filter(
            Q(flow__comment_response__integration__assistant__user=user) | Q(flow__comment_response__integration__user=user),
        ).distinct()

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

    def get_queryset(self):
        # Without this the view was `objects.all()` + IsAuthenticated:
        # any logged-in user could read, edit and DELETE another
        # tenant's automation objects.
        user = self.request.user
        return self.queryset.filter(
            Q(steps__flow__comment_response__integration__assistant__user=user) | Q(steps__flow__comment_response__integration__user=user),
        ).distinct()

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


class BroadcastListCreateView(generics.ListCreateAPIView):
    serializer_class = BroadcastSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Broadcast.objects.none()
        return Broadcast.objects.filter(user=self.request.user)

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return success_response(message=_("Broadcast ro'yxati"), data=serializer.data, code=200)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        integration = serializer.validated_data['integration']
        owner = integration.user or (integration.assistant.user if integration.assistant else None)
        if owner != request.user:
            return error_response(message=_("Bu integratsiya sizga tegishli emas"), code=403)

        # Count recipients
        recipients_count = self._get_recipients_count(integration)
        if recipients_count == 0:
            return error_response(message=_("Xabar yuborish uchun qabul qiluvchilar topilmadi"), code=400)

        broadcast = serializer.save(user=request.user, total_recipients=recipients_count)

        from .tasks import send_broadcast_task
        send_broadcast_task.delay(str(broadcast.id))

        return success_response(
            message=_("Broadcast muvaffaqiyatli yaratildi"),
            data=BroadcastSerializer(broadcast).data,
            code=201
        )

    def _get_recipients_count(self, integration):
        from .tasks import get_broadcast_recipients
        return get_broadcast_recipients(integration).count()


class BroadcastRecipientsCountView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, integration_id, *args, **kwargs):
        try:
            integration = Integration.objects.get(
                Q(user=request.user) | Q(assistant__user=request.user),
                id=integration_id
            )
        except Integration.DoesNotExist:
            return error_response(message=_("Integratsiya topilmadi"), code=404)

        from .tasks import get_broadcast_recipients
        recipients = get_broadcast_recipients(integration)

        return success_response(
            message=_("Qabul qiluvchilar soni"),
            data={"count": recipients.count()},
            code=200
        )


class BroadcastRecipientsListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, integration_id, *args, **kwargs):
        try:
            integration = Integration.objects.get(
                Q(user=request.user) | Q(assistant__user=request.user),
                id=integration_id
            )
        except Integration.DoesNotExist:
            return error_response(message=_("Integratsiya topilmadi"), code=404)

        from .tasks import get_broadcast_recipients
        recipients = get_broadcast_recipients(integration).values(
            'id', 'user_id', 'username', 'client_full_name', 'platform', 'updated_time'
        )

        return success_response(
            message=_("Qabul qiluvchilar ro'yxati"),
            data=list(recipients),
            code=200
        )


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
            
        except Exception:
            logger.exception("Error generating amoCRM OAuth URL")
            return error_response(
                message="Error generating amoCRM OAuth URL",
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
                logger.warning("amoCRM token exchange failed with status %s", token_response.status_code)
                return error_response(
                    message="Failed to exchange code for token",
                    code=400
                )

            token_info = token_response.json()
            access_token = token_info.get('access_token')
            refresh_token = token_info.get('refresh_token')
            expires_in = token_info.get('expires_in')


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
            if user_response.status_code != 200:
                return error_response(
                    message="Failed to get user information from amoCRM",
                    code=400
                )
            
            user_info = user_response.json()
            account_id = user_info.get('id')
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
            
        except Exception:
            logger.exception("Error processing amoCRM OAuth callback")
            return error_response(
                message="Error processing amoCRM OAuth callback",
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
                    message="Failed to refresh token",
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
            
        except Exception:
            logger.exception("Error refreshing amoCRM token")
            return error_response(
                message="Error refreshing token",
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
            subdomain = integration.metadata.get('subdomain') if integration.metadata else 'repli.amocrm.ru'
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
                    message="Failed to get pipeline info",
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
            
        except Exception:
            logger.exception("Error setting amoCRM pipeline")
            return error_response(
                message="Error setting pipeline",
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
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        api_token = request.data.get('api_token')
        assistant_id = self.kwargs.get('pk')
        if not Assistant.objects.filter(id=assistant_id).exists():
            return error_response(message=_("Assistant topilmadi"), code=404)
        if not api_token:
            return error_response(message=_("Billz API token kerak"), code=400)
        response = requests.post("https://api-admin.billz.ai/v1/auth/login", json={"secret_token": api_token})
        if response.status_code != 200:
            return error_response(message=_("Billz API token yaroqli emas"), code=400)

        access_token = response.json().get('data').get('access_token')
        if not access_token:
            return error_response(message=_("Billz access token topilmadi"), code=400)
        request.data['refresh_token'] = api_token
        request.data['api_token'] = access_token
        serializer.is_valid(raise_exception=True)
        integration = serializer.save()
        
        # Trigger async task to fetch and save Billz products
        from apps.integration.tasks import fetch_and_save_billz_products
        fetch_and_save_billz_products.delay(str(integration.id))
        
        return success_response(message=_("Billz secret token muvaffaqiyatli yaratildi"), data=serializer.data, code=201)