from django.utils import timezone
from rest_framework.views import APIView
from django.utils.translation import gettext as _
from apps.assistant.models import Conversation, Message
from shared.addons.ai_requests import get_thread_id, get_assistant_response
from shared.addons.telegram import send_telegram_message
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
    def post(self, request, token, *args, **kwargs): # noqa
        payload = request.data
        chat_id = payload.get("message", {}).get("chat", {}).get("id")
        message_text = payload.get("message", {}).get("text")
        print(f"payload: {payload}, Chat ID: {chat_id}, Message: {message_text}")
        try:
            # Validate and fetch integration
            integration = Integration.objects.get(api_token=token, is_active=True)
            assistant = integration.assistant
            print(f"assistant: {assistant}, integration: {integration}")
            # Fetch or create conversation
            conversation, created = Conversation.objects.get_or_create(
                assistant=assistant,
                status="open",
                telegram_user_id=chat_id,
                defaults={
                    "start_time": timezone.now(),
                    "thread_id": get_thread_id(assistant.assistant_id)
                }
            )
            print(f"conversation: {conversation}, created: {created}")
            # Send greeting if a new conversation is created
            if created:
                send_telegram_message(chat_id, assistant.greeting_message, token)

            # Save incoming user message
            Message.objects.create(
                conversation=conversation,
                sender="user",
                message_content=message_text,
                message_type="text"
            )

            # Get assistant response and save it
            assistant_response = get_assistant_response(
                message=message_text,
                assistant_id=assistant.assistant_id,
                thread_id=conversation.thread_id
            )
            Message.objects.create(
                conversation=conversation,
                sender="assistant",
                message_content=assistant_response,
                message_type="text"
            )

            # Send assistant response to Telegram
            send_telegram_message(chat_id, assistant_response, token)

            return success_response(message=_("Xabar muvaffaqiyatli yuborildi"))

        except Integration.DoesNotExist:
            return error_response(message=_("Xatolik: Integratsiya topilmadi"))
