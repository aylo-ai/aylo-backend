from django.utils.timezone import localtime

from apps.assistant.models import Assistant, Conversation, Message, Settings, AssistantFileUpload
from rest_framework import serializers

from shared.addons.ai_requests import send_assistant_data, get_thread_id, \
    get_assistant_response, update_vector_store_files
from shared.addons.payloads import create_file_urls
from shared.addons.validations import raise_validation_error
from shared.addons.enums import ConversationStatuses
from shared.ai_service.assistant import update_assistant_id_vector_id


class AssistantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Assistant
        fields = [
            "id",
            "name",
            "description",
            "user",
            "company_name",
            "role",
            "language",
            "personality_style",
            "greeting_message",
            "fallback_message",
            "wait_message",
            "created_time",
            "updated_time",
            "is_active",
        ]
        read_only_fields = ["created_time", "updated_time"]


class ConversationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversation
        fields = [
            "id",
            "assistant",
            "status",
            "thread_id",
            "platform",
            "start_time",
            "end_time",
            "created_time",
            "updated_time",
        ]
        read_only_fields = ["created_time", "updated_time"]
        extra_kwargs = {
            "assistant": {"required": False},
        }

    def validate(self, attrs):
        assistant = self.context.get("assistant_id")
        try:
            assistant = Assistant.objects.get(id=assistant)
        except Assistant.DoesNotExist:
            raise_validation_error("Assistant does not exist.")
        attrs["assistant"] = assistant
        return attrs

    def create(self, validated_data):
        assistant = validated_data.get("assistant")
        thread_id = get_thread_id(str(assistant.assistant_id), str(assistant.vector_id))
        conversation = Conversation.objects.create(
            assistant=assistant,
            thread_id=thread_id
        )
        return thread_id, conversation

    def to_representation(self, instance):
        response = super().to_representation(instance)
        print(f"to_representation: instance: {instance}")
        # Fetching the messages ordered by `created_time`
        last_message = instance.messages.order_by('-created_time').first()
        last_message_time = last_message.created_time if last_message else None
        # Convert the time to the local time zone
        if last_message_time:
            last_message_time = localtime(last_message_time)
        response["last_message"] = last_message.message_content if last_message else None
        response["last_message_time"] = last_message_time if last_message_time else None
        return response


class ConversationRetrieveSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversation
        fields = [
            "id",
            "assistant",
            "status",
            "thread_id",
            "platform",
            "start_time",
            "end_time",
            "created_time",
            "updated_time",
        ]
        read_only_fields = ["created_time", "updated_time"]
        extra_kwargs = {
            "assistant": {"required": False},
        }

    def to_representation(self, instance):
        response = super().to_representation(instance)
        last_message = instance.messages.last()
        response["last_message"] = last_message.message_content if last_message else None
        return response


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = [
            "id",
            "conversation",
            "sender",
            "message_content",
            "message_type",
            "created_time",
            "updated_time",
        ]
        read_only_fields = ["created_time", "updated_time"]
        extra_kwargs = {
            "conversation": {"required": False},
        }

    def validate(self, attrs):
        conversation = self.context.get("conversation_id")
        print(f"validate: conversation_id: {conversation}")
        try:
            conversation = Conversation.objects.get(id=conversation)
        except Conversation.DoesNotExist:
            raise_validation_error("Conversation does not exist.")
        attrs["conversation"] = conversation
        print(f"validate: conversation: {conversation}")
        return attrs

    def create(self, validated_data):
        message_content = validated_data.get("message_content")
        print(f"create: message_content: {message_content}")
        message = Message.objects.create(**validated_data)
        print(f"message is created: {message}")

        # check assistant status
        if message.conversation.status == ConversationStatuses.ESCALATED.value:
            return message

        # send message to chat assistant
        response = get_assistant_response(
            message=message_content,
            assistant_id=message.conversation.assistant.assistant_id,
            thread_id=message.conversation.thread_id
        )
        print(f"response from ai: {response}")
        assistant_response = Message.objects.create(
            conversation=message.conversation,
            sender="assistant",
            message_content=response,
            message_type="text",
        )
        return assistant_response


class SettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Settings
        fields = [
            "id",
            "assistant",
            "timezone",
            "language",
            "notification_preferences",
            "escalation_rules",
            "created_time",
            "updated_time",
        ]
        read_only_fields = ["created_time", "updated_time"]


class AssistantFileUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssistantFileUpload
        fields = [
            "id",
            "assistant",
            "filename",
            "file",
            "created_time",
            "updated_time",
        ]
        read_only_fields = ["created_time", "updated_time"]
        extra_kwargs = {
            "assistant": {"required": False},
        }

    def validate(self, attrs):
        files = self.context.get("files")
        if not files:
            raise_validation_error(message="No files were uploaded.")

        for file in files:
            if file.size > 30 * 1024 * 1024:  # 30MB limit
                raise_validation_error(message=f"File {file.name} exceeds the 30MB size limit.")
        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        files = self.context.get('files')
        assistant = self.context.get("assistant")
        for file in files:
            filename = file.name
            AssistantFileUpload.objects.create(
                assistant=assistant,
                file=file,
                filename=filename
            )
        # send_assistant_data(assistant, request)
        update_assistant_id_vector_id(assistant, request)

        return assistant

    def to_representation(self, instance):
        assistant = getattr(instance, "assistant", None)
        response = super().to_representation(instance)
        if assistant:
            is_new = True if assistant.assistant_id is None else False
            print("is_new: ", is_new)
            response["is_new"] = is_new
        return response


class UpdateFileUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssistantFileUpload
        fields = [
            "id",
            "assistant",
            "filename",
            "file",
            "created_time",
            "updated_time",
        ]
        read_only_fields = ["created_time", "updated_time"]
        extra_kwargs = {
            "assistant": {"required": False},
        }

    def validate(self, attrs):
        files = self.context.get("files")
        if not files:
            raise_validation_error(message="No files were uploaded.")

        for file in files:
            if file.size > 30 * 1024 * 1024:  # 30MB limit
                raise_validation_error(message=f"File {file.name} exceeds the 30MB size limit.")
        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        files = self.context.get('files')
        assistant = self.context.get("assistant")
        for file in files:
            filename = file.name
            AssistantFileUpload.objects.create(
                assistant=assistant,
                file=file,
                filename=filename
            )
        file_urls = create_file_urls(assistant, request)
        update_vector_store_files(assistant.vector_id, file_urls)

        return assistant