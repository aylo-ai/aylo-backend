from django.utils.timezone import localtime

from apps.assistant.models import Assistant, Conversation, Message, Settings, AssistantFileUpload
from rest_framework import serializers

from shared.addons.ai_requests import send_assistant_data, \
    get_assistant_response, update_vector_store_files
from shared.addons.utils import get_thread_id, speech_to_text
from shared.addons.payloads import create_file_urls
from shared.addons.validations import raise_validation_error
from shared.addons.enums import ConversationStatuses
from shared.ai_service.assistant import update_assistant_id_vector_id
from shared.addons.enums import MessageTypes


class AssistantSerializer(serializers.ModelSerializer):
    integrations = serializers.SerializerMethodField()

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
            "integrations",
        ]
        read_only_fields = ["created_time", "updated_time"]

    def get_integrations(self, obj):  # noqa
        #  count of instagram and telegram integrations
        telegram_count = obj.integrations.filter(integration_type="telegram").exists()
        instagram_count = obj.integrations.filter(integration_type="instagram").exists()
        return {
            "is_telegram_integration": telegram_count,
            "is_instagram_integration": instagram_count,
        }


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
            "audio_file",
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
        audio_file = validated_data.get("audio_file")
        conversation = validated_data.get("conversation")
        assistant = conversation.assistant
        sender = validated_data.get("sender")

        # 1. Transcribe if audio exists
        if audio_file:
            print("[MessageSerializer] Audio file received.")
            audio_bytes = audio_file.read()
            transcribed_text = speech_to_text(audio_bytes, language=assistant.language or "uz")
            validated_data["message_content"] = transcribed_text
            validated_data["message_type"] = MessageTypes.Audio.value
        else:
            transcribed_text = validated_data.get("message_content")
        
        message = Message.objects.create(**validated_data)
        if conversation.status == ConversationStatuses.ESCALATED.value or not assistant.is_active:
            return message

        response = get_assistant_response(
            message=transcribed_text,
            assistant_id=assistant.assistant_id,
            thread_id=conversation.thread_id
        )
        Message.objects.create(
            conversation=conversation,
            sender=sender,
            message_content=response,
            message_type=MessageTypes.Text.value
        )
        return message
        


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
        response = update_assistant_id_vector_id(assistant, request)
        if not response:
            raise_validation_error(message="Failed to update assistant ID and vector ID.")
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

        uploaded_files = []
        for file in files:
            filename = file.name
            upload = AssistantFileUpload.objects.create(
                assistant=assistant,
                file=file,
                filename=filename
            )
            uploaded_files.append(upload)

        # Ensure file URLs are created and vector store is updated
        if assistant.vector_id:
            file_urls = create_file_urls(assistant, request)
            update_vector_store_files(assistant.vector_id, file_urls)

        return uploaded_files[0] if len(uploaded_files) == 1 else uploaded_files # initailly return assistant but later assistant has no field of file and i changeed to list of upload files