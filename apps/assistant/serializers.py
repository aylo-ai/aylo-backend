import time
import os

from rest_framework import serializers
from django.utils.translation import gettext as _
from django.utils.timezone import localtime
from django.core.files import File


from apps.assistant.models import Assistant, Conversation, Message, Settings, AssistantFileUpload
from shared.addons.ai_requests import get_assistant_response, update_vector_store_files
from shared.addons.utils import get_thread_id, speech_to_text
from shared.addons.payloads import create_file_urls
from shared.addons.validations import raise_validation_error
from shared.addons.enums import ConversationPlatforms, ConversationStatuses
from shared.addons.enums import MessageTypes
from shared.addons.parsing import WebsiteScreenshot
from shared.mixins import SubscriptionValidationMixin


class AssistantSerializer(serializers.ModelSerializer,
                          SubscriptionValidationMixin):
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
    
    def validate(self, attrs):
        user = self.context.get("request").user
        # Use the mixin's validation method
        self.validate_subscription(user)
        return attrs


class ConversationSerializer(serializers.ModelSerializer,
                             SubscriptionValidationMixin):
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
        user = self.context.get("request").user
        # Use the mixin's validation method
        self.validate_subscription(user)
        assistant = self.context.get("assistant_id")
        try:
            assistant = Assistant.objects.get(id=assistant)
        except Assistant.DoesNotExist:
            raise_validation_error("Assistant does not exist.")
        if assistant is None:
            raise_validation_error("Assistant is not found.")
        if not assistant.assistant_id or not assistant.vector_id:
            raise_validation_error("Firstly, upload file for assistant.")
        attrs["assistant"] = assistant
        return attrs

    def create(self, validated_data):
        assistant = validated_data.get("assistant")
        thread_id = get_thread_id(str(assistant.assistant_id), str(assistant.vector_id))
        conversation = Conversation.objects.create(
            platform=ConversationPlatforms.WEBSITE.value,
            assistant=assistant,
            thread_id=thread_id
        )
        return conversation

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


class ConversationRetrieveSerializer(serializers.ModelSerializer, SubscriptionValidationMixin):
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
        user = self.context.get("request").user
        # Use the mixin's validation method
        self.validate_subscription(user)
        return attrs

    def to_representation(self, instance):
        response = super().to_representation(instance)
        last_message = instance.messages.last()
        response["last_message"] = last_message.message_content if last_message else None
        return response


class MessageSerializer(serializers.ModelSerializer, SubscriptionValidationMixin):
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
            "message_content": {"required": False},
        }

    def validate(self, attrs):
        user = self.context.get("request").user
        # Use the mixin's validation method
        self.validate_subscription(user)

        if user.subscription.used_request_count >= user.subscription.pricing_package.request_count:
            raise_validation_error(message=_("Sizning so'rovlar soningiz tugagan. Iltimos, obunangizni yangilang."))

        message_content = attrs.get("message_content")
        audio_file = attrs.get("audio_file")
        if not message_content and not audio_file:
            raise_validation_error(message=_("Message content or audio file is required."))
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
        user = self.context.get("request").user
        audio_file = validated_data.get("audio_file")
        conversation = validated_data.get("conversation")
        assistant = conversation.assistant
        sender = validated_data.get("sender")
        print(f"time before transcribe: {time.time()}")
        # 1. Transcribe if audio exists
        if audio_file:
            print("[MessageSerializer] Audio file received.")
            audio_bytes = audio_file.read()
            transcribed_text = speech_to_text(audio_bytes, language=assistant.language or "uz")
            print(f"time after transcribe: {time.time()}")
            validated_data["message_content"] = transcribed_text
            validated_data["message_type"] = MessageTypes.AUDIO.value
        else:
            transcribed_text = validated_data.get("message_content")
        
        message = Message.objects.create(**validated_data)
        if conversation.status == ConversationStatuses.ESCALATED.value or not assistant.is_active:
            return message
        print(f"time before get_assistant_response: {time.time()}")
        response = get_assistant_response(
            message=transcribed_text,
            assistant_id=assistant.assistant_id,
            thread_id=conversation.thread_id
        )
        print(f"time after get_assistant_response: {time.time()}")
        response_message = Message.objects.create(
            conversation=conversation,
            sender=sender,
            message_content=response,
            message_type=MessageTypes.TEXT.value
        )
        # Increment used request count
        user.subscription.used_request_count += 1
        user.subscription.save()
        return response_message
        


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


class AssistantFileUploadSerializer(serializers.ModelSerializer, SubscriptionValidationMixin):
    class Meta:
        model = AssistantFileUpload
        fields = [
            "id",
            "assistant",
            "filename",
            "website_url",
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
        website_url = attrs.get("website_url")
        user = self.context.get("request").user
        # Use the mixin's validation method
        self.validate_subscription(user)
        # Validate website URL if provided
        if website_url:
            if not website_url.startswith(('http://', 'https://')):
                raise_validation_error(message="Invalid website URL. Must start with http:// or https://")
            return attrs

        # Validate files if no website URL
        if not files:
            raise_validation_error(message="Either files or website_url must be provided.")

        if not isinstance(files, (list, tuple)):
            files = [files]

        for file in files:
            if not file:
                continue
            if not hasattr(file, 'size') or not hasattr(file, 'name'):
                raise_validation_error(message=f"Invalid file object: {file}")
            if file.size > 30 * 1024 * 1024:  # 30MB limit
                raise_validation_error(message=f"File {file.name} exceeds the 30MB size limit.")
        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        files = self.context.get('files')
        assistant = self.context.get("assistant")
        website_url = validated_data.get("website_url")
        
        if not assistant:
            raise_validation_error(message="Assistant is required.")

        uploaded_files = []

        # Handle website URL parsing
        if website_url:
            try:
                screenshot = WebsiteScreenshot()
                screenshot_path, pdf_path = screenshot.process_url(website_url)
                filename = f"website_screenshot_{os.path.basename(website_url)}.pdf"
                
                with open(pdf_path, 'rb') as pdf_file:
                    django_file = File(pdf_file)
                    upload = AssistantFileUpload.objects.create(
                        assistant=assistant,
                        file=django_file,
                        filename=filename,
                        website_url=website_url
                    )
                    uploaded_files.append(upload)
                
                # Clean up temporary files
                os.remove(screenshot_path)
                os.remove(pdf_path)
                
            except Exception as e:
                raise_validation_error(message=f"Error processing website URL: {str(e)}")

        # Handle file uploads
        elif files:
            if not isinstance(files, (list, tuple)):
                files = [files]

            for file in files:
                if not file:
                    continue
                filename = file.name
                upload = AssistantFileUpload.objects.create(
                    assistant=assistant,
                    file=file,
                    filename=filename
                )
                uploaded_files.append(upload)

        # Ensure file URLs are created and vector store is updated
        if assistant and assistant.vector_id:
            file_urls = create_file_urls(assistant, request)
            print(f"file_urls: {file_urls}")
            update_vector_store_files(assistant.vector_id, file_urls)

        return uploaded_files[0] if len(uploaded_files) == 1 else uploaded_files

    def to_representation(self, instance):
        assistant = getattr(instance, "assistant", None)
        response = super().to_representation(instance)
        if assistant:
            is_new = True if assistant.assistant_id is None else False
            print("is_new: ", is_new)
            response["is_new"] = is_new
        return response


class UpdateFileUploadSerializer(serializers.ModelSerializer, SubscriptionValidationMixin):
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
        user = self.context.get("request").user
        # Use the mixin's validation method
        self.validate_subscription(user)
        if not files:
            raise_validation_error(message="No files were uploaded.")

        if not isinstance(files, (list, tuple)):
            files = [files]

        for file in files:
            if not file:
                continue
            if not hasattr(file, 'size') or not hasattr(file, 'name'):
                raise_validation_error(message=f"Invalid file object: {file}")
            if file.size > 30 * 1024 * 1024:  # 30MB limit
                raise_validation_error(message=f"File {file.name} exceeds the 30MB size limit.")
        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        files = self.context.get('files')
        assistant = self.context.get("assistant")
        
        if not files or not assistant:
            raise_validation_error(message="Files and assistant are required.")

        if not isinstance(files, (list, tuple)):
            files = [files]

        uploaded_files = []
        for file in files:
            if not file:
                continue
            filename = file.name
            upload = AssistantFileUpload.objects.create(
                assistant=assistant,
                file=file,
                filename=filename
            )
            uploaded_files.append(upload)

        # Ensure file URLs are created and vector store is updated
        if assistant and getattr(assistant, 'vector_id', None):
            file_urls = create_file_urls(assistant, request)
            update_vector_store_files(assistant.vector_id, file_urls)

        return uploaded_files[0] if len(uploaded_files) == 1 else uploaded_files