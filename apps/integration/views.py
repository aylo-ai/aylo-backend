from django.utils import timezone
from rest_framework.views import APIView
from django.utils.translation import gettext as _
from apps.assistant.models import Conversation, Message, Assistant
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
    def post(self, request, bot_token):  # noqa
        data = request.data
        message_data = data.get('message')
        print(f"Message data: {message_data}")
        if not message_data:
            return error_response(message=_("No message data received"))

        chat_id = message_data['chat']['id']
        user_message = message_data.get('text')

        # Retrieve the assistant based on bot_token
        assistant = Assistant.objects.filter(integrations__api_token=bot_token).first()
        print(f"Assistant: {assistant}")
        if not assistant:
            return error_response(message=_("Invalid bot token"))

        # Check if the message is a start command
        if user_message == '/start':
            greeting_message = assistant.greeting_message
            send_telegram_message(chat_id, greeting_message, bot_token)
            # Create a new conversation
            thread_id = get_thread_id(str(assistant.assistant_id))
            print(f"Thread ID: {thread_id}")
            conversation, created = Conversation.objects.get_or_create(
                assistant=assistant,
                thread_id=thread_id,
                telegram_user_id=chat_id,
                status='open',
                defaults={'start_time': timezone.now()}
            )
            if not created:
                conversation.start_time = timezone.now()
                conversation.status = 'open'
                conversation.thread_id = thread_id
                conversation.save()

            return success_response(message=_("Greeting sent and conversation started"), code=200)

        # For other messages, handle as a regular message
        conversation = Conversation.objects.filter(
            assistant=assistant,
            telegram_user_id=chat_id,
            status='open'
        ).order_by('-created_time').first()
        print(f"existing conversation: {conversation}")
        if not conversation:
            conversation = Conversation.objects.create(
                thread_id=get_thread_id(str(assistant.assistant_id)),
                assistant=assistant,
                telegram_user_id=chat_id,
                start_time=timezone.now(),
                status='open'
            )
            print(f"New conversation created: {conversation}")

        # Save the user's message to the Message model
        try:
            print(f"User message: {user_message}, conversation: {conversation}")
            Message.objects.create(
                conversation=conversation,
                sender='user',
                message_content=user_message,
                message_type='text'
            )
        except Exception as e:
            print(f"Error saving message: {e}")
            return error_response(message=_("Failed to save user message"), code=400)

        # Generate and send assistant's response
        response_message = get_assistant_response(user_message, assistant.assistant_id, conversation.thread_id)
        print(f"Assistant response: {response_message}")
        Message.objects.create(
            conversation=conversation,
            sender='assistant',
            message_content=response_message,
            message_type='text'
        )
        send_telegram_message(chat_id, response_message, bot_token)
        print(f"Message processed: {response_message}")
        return success_response(message=_("Message processed successfully"), code=200)