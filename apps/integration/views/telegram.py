import functools
import logging
import time

from django.db import transaction
from django.utils.translation import gettext_lazy as _
from rest_framework import generics, permissions
from rest_framework.views import APIView

from apps.integration.gateways.telegram import (
    check_bot_in_group,
    handle_bot_added_to_group,
    handle_bot_removed_from_group,
)
from apps.integration.models import Integration, TelegramGroupIntegration
from apps.integration.serializers import TelegramGroupSerializer
from apps.integration.tasks import (
    WAIT_SECONDS,
    process_collected_messages,
    process_photo_task,
    process_voice_task,
)
from apps.integration.views.mixins import IntegrationOwnedQuerysetMixin
from apps.shared.addons.redis import redis_client
from apps.shared.addons.validations import error_response, success_response

logger = logging.getLogger(__name__)


class TelegramWebhookView(APIView):
    def post(self, request, bot_token):  # noqa
        integration = Integration.objects.filter(api_token=bot_token).only("id").first()
        if integration is None:
            return error_response(message=_("Invalid bot token"), code=403)

        update_id = request.data.get('update_id')
        if update_id:
            dedup_key = f"tg_dedup:{update_id}"
            if redis_client.get(dedup_key):
                logger.info("Duplicate Telegram update detected: %s", update_id)
                return success_response(message=_("Duplicate update ignored"), code=200)
            redis_client.setex(dedup_key, 300, "1")

        data = request.data.get('message')
        if not data:
            return error_response(message=_("No message data received"))
        logger.info("Telegram webhook received for integration %s", integration.id)
        chat_id = data.get("chat", {}).get("id", None)
        chat_title = data.get('chat', {}).get('title', 'Private Chat')
        chat_type = data.get("chat", {}).get("type", None)
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
                    handle_bot_removed_from_group(chat_id)
            else:
                if "sticker" in data:
                    return success_response(message=_("Sticker message muvaffaqiyatli olindi"), code=200)

                if "document" in data:
                    return success_response(message=_("Document message muvaffaqiyatli olindi"), code=200)

                if "photo" in data:
                    photos = data["photo"]
                    if photos:
                        largest_photo = photos[-1]
                        photo_file_id = largest_photo.get("file_id")
                        if photo_file_id:
                            transaction.on_commit(functools.partial(
                                process_photo_task.delay, chat_id, photo_file_id, bot_token, chat_username, username))
                            return success_response(message=_("Photo message muvaffaqiyatli olindi"), code=200)

                if "voice" in data:
                    voice_file_id = data["voice"]["file_id"]
                    transaction.on_commit(functools.partial(
                        process_voice_task.delay, chat_id, voice_file_id, bot_token))
                    return success_response(message=_("Voice message muvaffaqiyatli olindi"), code=200)
                if user_message:
                    redis_client.rpush(f"messages:{chat_id}", user_message)
                redis_client.set(f"last_seen:{chat_id}", time.time())

                redis_client.setex(f"collecting:{chat_id}", WAIT_SECONDS + 1, "1")
                transaction.on_commit(functools.partial(
                    process_collected_messages.apply_async,
                    (chat_id, bot_token, None, chat_username, username, None),
                    countdown=WAIT_SECONDS))
        return success_response(message=_("Xabar muvaffaqiyatli olindi"), code=200)


class TelegramGroupListView(IntegrationOwnedQuerysetMixin, generics.ListAPIView):
    owner_path = "integration"
    queryset = TelegramGroupIntegration.objects.all()
    serializer_class = TelegramGroupSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset().filter(integration_id=self.kwargs.get('pk'))
        is_approved = self.request.query_params.get('is_approved')
        if is_approved is not None:
            qs = qs.filter(is_approved=is_approved.lower() == 'true')
        return qs


class TelegramGroupUpdateDestroyView(IntegrationOwnedQuerysetMixin,
                                     generics.RetrieveUpdateDestroyAPIView):
    owner_path = "integration"
    queryset = TelegramGroupIntegration.objects.all()
    serializer_class = TelegramGroupSerializer
    permission_classes = [permissions.IsAuthenticated]

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        is_approving = request.data.get('is_approved')
        if is_approving is True or is_approving == 'true' or is_approving == True:
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
