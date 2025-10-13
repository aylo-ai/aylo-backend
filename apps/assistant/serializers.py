import time
import os
import json

from rest_framework import serializers
from django.utils.translation import gettext_lazy as _
from django.utils.timezone import localtime
from django.core.files import File
from openpyxl import Workbook
from datetime import datetime

from shared.addons.google_integrations import process_google_doc
from apps.assistant.models import Assistant, Conversation, Message, Settings, AssistantFileUpload, Lead
from apps.integration.models import TelegramGroupIntegration
from shared.addons.ai_requests import update_vector_store_files
from shared.ai_service.openai_client import client
from shared.ai_service.helper import upload_knowledge_base_file
from shared.addons.utils import get_assistant_response_ai, get_thread_id, speech_to_text, send_telegram_message
from shared.addons.payloads import create_file_urls
from shared.addons.validations import raise_validation_error
from shared.addons.enums import ConversationPlatforms, ConversationStatuses
from shared.addons.enums import MessageTypes
from shared.mixins import SubscriptionValidationMixin
from shared.addons.redis import publish_message_to_ws_assistant
from shared.addons.utils import update_assistant

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
            "steps",
            "personality_style",
            "greeting_message",
            "fallback_message",
            "wait_message",
            "created_time",
            "updated_time",
            "is_active",
            "ai_enabled",
            "integrations",
        ]
        read_only_fields = ["created_time", "updated_time"]

    def get_integrations(self, obj):  # noqa
        #  count of instagram and telegram integrations
        telegram_count = obj.integrations.filter(integration_type="telegram").exists()
        instagram_count = obj.integrations.filter(integration_type="instagram").exists()
        widget_count = obj.integrations.filter(integration_type="website").exists()
        return {
            "is_telegram_integration": telegram_count,
            "is_instagram_integration": instagram_count,
            "is_widget_integration": widget_count,
        }
    
    def validate(self, attrs):
        user = self.context.get("request").user
        self.validate_subscription(user.subscription)
        company_name = attrs.get("company_name")
        role = attrs.get("role")
        if len(company_name) > 100:
            raise_validation_error(message=_("Company nomi 100 ta belgidan kam bo'lishi kerak"))
        if len(role) > 100:
            raise_validation_error(message=_("Role 100 ta belgidan kam bo'lishi kerak"))
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
        assistant = self.context.get("assistant_id")
        print(f"validate: assistant: {assistant}")
        try:
            assistant = Assistant.objects.get(id=assistant)
            self.validate_subscription(assistant.user.subscription)
        except Assistant.DoesNotExist:
            raise_validation_error(message=_("Assistant topilmadi"))
        if assistant is None:
            raise_validation_error(message=_("Assistant topilmadi"))
        if assistant.ai_enabled:
            if not assistant.assistant_id or not assistant.vector_id:
                raise_validation_error(message=_("Assistant uchun fayl yuklash kerak"))

        attrs["assistant"] = assistant
        return attrs

    def create(self, validated_data):
        assistant = validated_data.get("assistant")
        thread_id = None
        if assistant.ai_enabled:
            thread_id = get_thread_id(str(assistant.assistant_id), str(assistant.vector_id))
        conversation = Conversation.objects.create(
            platform=ConversationPlatforms.WEBSITE.value,
            assistant=assistant,
            thread_id=thread_id
        )
        publish_message_to_ws_assistant(conversation)
        return conversation

    def to_representation(self, instance):
        response = super().to_representation(instance)
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
        message_content = attrs.get("message_content")
        audio_file = attrs.get("audio_file")

        if not message_content and not audio_file:
            raise_validation_error(message=_("Xabar matni yoki audio fayl kerak"))
        conversation = self.context.get("conversation_id")
        try:
            conversation = Conversation.objects.get(id=conversation)
        except Conversation.DoesNotExist:
            raise_validation_error(message=_("Conversation topilmadi"))
        # Use the mixin's validation method
        self.validate_subscription(conversation.assistant.user.subscription)

        message_content = attrs.get("message_content")
        audio_file = attrs.get("audio_file")
        if not message_content and not audio_file:
            raise_validation_error(message=_("Xabar matni yoki audio fayl kerak"))
        attrs["conversation"] = conversation
        print(f"validate: conversation: {conversation}")
        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        if not request:
            raise_validation_error(message=_("Request obyekti kerak"))
        audio_file = validated_data.get("audio_file")
        conversation = validated_data.get("conversation")
        assistant = conversation.assistant
        sender = validated_data.get("sender")
        # 1. Transcribe if audio exists
        if audio_file:
            audio_bytes = audio_file.read()
            transcribed_text, input_tokens, output_tokens = speech_to_text(audio_bytes, language=assistant.language or "uz")
            validated_data["message_content"] = transcribed_text
            validated_data["message_type"] = MessageTypes.AUDIO.value
        else:
            transcribed_text = validated_data.get("message_content")

        validated_data['sender'] = sender
        message = Message.objects.create(**validated_data)
        if conversation.status == ConversationStatuses.ESCALATED.value or not assistant.is_active:
            return message
        response, run_status, response_data = get_assistant_response_ai(
            message=transcribed_text,
            assistant_id=assistant.assistant_id,
            thread_id=conversation.thread_id,
            conversation=conversation
        )
        if response_data and response_data.full_name and response_data.phone_number:
            # Build response_text conditionally
            response_lines = [
                "🎉 *New Lead Created!*\n",
                f"👤 *Full Name:* {response_data.full_name}  " if getattr(response_data, 'full_name', None) else None,
                f"📞 *Phone Number:* {response_data.phone_number}  " if getattr(response_data, 'phone_number', None) not in [None, ""] else None,
                f"📧 *Email:* {response_data.email}  " if getattr(response_data, 'email', None) not in [None, ""] else None,
                f"📦 *Interested Product:* {response_data.product}\n" if getattr(response_data, 'product', None) else None,
                "\n✅ Please follow up accordingly."
            ]
            response_text = "\n".join([line for line in response_lines if line])
            telegram_integration = assistant.integrations.filter(integration_type="telegram").first()
            telegram_groups = TelegramGroupIntegration.objects.filter(
                integration=telegram_integration
            ).all()
            for telegram_group in telegram_groups:
                send_telegram_message(telegram_group.group_id, response_text, telegram_integration.api_token)
                telegram_group.lead_count += 1
                telegram_group.save()
        response_message = Message.objects.create(
            conversation=conversation,
            sender=sender,
            message_content=response,
            message_type=MessageTypes.TEXT.value,
            input_tokens = run_status.usage.prompt_tokens or 0,
            output_tokens = run_status.usage.completion_tokens or 0
        )
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
            "file_type",
            "created_time",
            "updated_time",
        ]
        read_only_fields = ["created_time", "updated_time"]
        extra_kwargs = {
            "assistant": {"required": False},
        }

    def validate(self, attrs):
        files = self.context.get("files")
        assistant = self.context.get("assistant")
        print(f"validate: assistant: {assistant}")
        # Use the mixin's validation method
        self.validate_subscription(assistant.user.subscription)
        if not assistant.ai_enabled:
            raise_validation_error(message=_("Assistant AI sizda yoqilmagan"))

        # Validate files if no website URL
        if not files:
            raise_validation_error(message=_("Fayl yuklanmadi"))

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
        
        if not assistant:
            raise_validation_error(message=_("Assistant kerak"))

        uploaded_files = []

        # Handle file uploads
        if files:
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
                # Upload to OpenAI and attach to vector store
                try:
                    file_url = request.build_absolute_uri(upload.file.url) if request else upload.file.url
                    openai_file_id = upload_knowledge_base_file(file_url)
                    if openai_file_id:
                        upload.file_id = openai_file_id
                        upload.save(update_fields=["file_id"])
                        if getattr(assistant, 'vector_id', None):
                            batch = client.vector_stores.file_batches.create(
                                vector_store_id=assistant.vector_id,
                                file_ids=[openai_file_id]
                            )
                            # Poll until completed/failed
                            while True:
                                status = client.vector_stores.file_batches.retrieve(
                                    vector_store_id=assistant.vector_id,
                                    batch_id=batch.id
                                )
                                if status.status in ["completed", "failed"]:
                                    break
                                time.sleep(0.5)
                except Exception as e:
                    print(f"[-] OpenAI upload/attach failed: {e}")
                uploaded_files.append(upload)

        # Avoid full replacement to preserve existing vector store content

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
        request = self.context.get("request")
        assistant = self.context.get("assistant")
        files = self.context.get('files')
        if not assistant.ai_enabled:
            raise_validation_error(message=_("Assistant AI sizda yoqilmagan"))
        if not request:
            raise_validation_error(message=_("Request obyekt kerak"))
        user = request.user
        # Use the mixin's validation method
        self.validate_subscription(user.subscription)
        if not files:
            raise_validation_error(message=_("Fayl yuklanmadi"))

        if not isinstance(files, (list, tuple)):
            files = [files]

        for file in files:
            if not file:
                continue
            if not hasattr(file, 'size') or not hasattr(file, 'name'):
                raise_validation_error(message=f"Invalid file object: {file}")
            if file.size > 30 * 1024 * 1024:  # 30MB limit
                raise_validation_error(message=f"Fayl {file.name} 30MB dan katta")
        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        if not request:
            raise_validation_error(message=_("Request obyekt kerak"))
        user = request.user
        files = self.context.get('files')
        assistant = self.context.get("assistant")
        
        if not files or not assistant:
            raise_validation_error(message=_("Fayl va assistant kerak"))

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
            # Upload to OpenAI and attach to vector store
            try:
                file_url = request.build_absolute_uri(upload.file.url)
                openai_file_id = upload_knowledge_base_file(file_url)
                if openai_file_id:
                    upload.file_id = openai_file_id
                    upload.save(update_fields=["file_id"])
                    if getattr(assistant, 'vector_id', None):
                        batch = client.vector_stores.file_batches.create(
                            vector_store_id=assistant.vector_id,
                            file_ids=[openai_file_id]
                        )
                        while True:
                            status = client.vector_stores.file_batches.retrieve(
                                vector_store_id=assistant.vector_id,
                                batch_id=batch.id
                            )
                            if status.status in ["completed", "failed"]:
                                break
                            time.sleep(0.5)
            except Exception as e:
                print(f"[-] OpenAI upload/attach failed: {e}")
            uploaded_files.append(upload)

        return uploaded_files[0] if len(uploaded_files) == 1 else uploaded_files


class MessageBulkReadSerializer(serializers.Serializer):
    message_ids = serializers.ListField(
        child=serializers.UUIDField(),
        help_text="List of message UUIDs to mark as read"
    )

    def validate(self, attrs):
        message_ids = attrs.get('message_ids')
        if not message_ids:
            raise_validation_error(message=_("Xabar ID lari kiritilmagan"))
        return attrs

class AssistantFileGoogleDocSerializer(serializers.Serializer):
    sheet_doc_url = serializers.CharField(required=True)
    assistant_id = serializers.UUIDField(required=True)
    file_type = serializers.CharField(read_only=True)

    def validate(self, attrs):
        sheet_doc_url = attrs.get('sheet_doc_url')
        assistant_id = attrs.get('assistant_id')
        if not sheet_doc_url:
            raise_validation_error(message=_("Sheet URL kiritilmagan"))
        if not assistant_id:
            raise_validation_error(message=_("Assistant ID kiritilmagan"))
        try:
            assistant = Assistant.objects.get(id=assistant_id)
        except Assistant.DoesNotExist:
            raise_validation_error(message=_("Assistant topilmadi"))

        attrs['sheet_doc_url'] = sheet_doc_url
        attrs['assistant'] = assistant
        return attrs

    def create(self, validated_data):
        sheet_doc_url = validated_data.get('sheet_doc_url')
        assistant = validated_data.get('assistant')
        response = process_google_doc(sheet_doc_url, assistant)
        if assistant and assistant.vector_id:
            file_url = response.get("file_url")
            print(f"file_url: {file_url}")
            update_vector_store_files(assistant.vector_id, [file_url])
        
        print(f"response: {response}")
        validated_data["file_type"] = response.get("file_type")
        print(f"validated_data: {validated_data}")
        return validated_data


class LeadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lead
        fields = [
            "id",
            "assistant",
            "full_name",
            "phone_number",
            "email",
            "product",
            "status",
            "metadata",
            "contacted",
            "created_time",
            "updated_time",
        ]   
        read_only_fields = ["created_time", "updated_time"]

    
class LeadExportSerializer(serializers.Serializer):
    def export_leads(self, assistant_id):
        leads = Lead.objects.filter(assistant_id=assistant_id).select_related('assistant').only(
            'full_name', 'phone_number', 'email', 'product', 'status', 'contacted', 'created_time', 'assistant__name', 'metadata'
        ).iterator(chunk_size=1000)

        wb = Workbook()
        ws = wb.active
        ws.append(["Ism familiya", "Email", "Telefon raqam", "Maxsulot", "Status", "Yaratilgan vaqt", "Assistant nomi", "Qoshimcha ma'lumotlar"])

        for lead in leads:
            ws.append([
                lead.full_name,
                lead.email,
                lead.phone_number,
                lead.product,
                lead.status,
                lead.created_time.strftime("%Y-%m-%d %H:%M:%S") if lead.created_time else "",
                lead.assistant.name,
                json.dumps(lead.metadata) if lead.metadata else ""
            ])

        file_path = f"leads_export_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
        wb.save(file_path)
        return file_path