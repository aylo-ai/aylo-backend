import json
import logging
from datetime import datetime
from io import BytesIO

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.timezone import localtime
from django.utils.translation import gettext_lazy as _
from openpyxl import Workbook
from rest_framework import serializers

from apps.assistant.models import (
    Assistant,
    AssistantFileUpload,
    Conversation,
    FollowUpConfig,
    FollowUpLog,
    FollowUpStage,
    Lead,
    Message,
    PromptTemplate,
)
from apps.assistant.tasks import index_assistant_file
from apps.shared.addons.enums import (
    ConversationPlatforms,
    ConversationStatuses,
    FileIndexStatuses,
    MessageTypes,
    SenderTypes,
)
from apps.shared.addons.redis import publish_message_to_ws_assistant
from apps.shared.addons.validations import raise_validation_error
from apps.shared.ai_service import knowledge_base, media
from apps.shared.ai_service.agent import agent
from apps.shared.file_validation import validate_audio, validate_document
from apps.shared.mixins import SubscriptionValidationMixin

logger = logging.getLogger(__name__)


class PromptTemplateListSerializer(serializers.ModelSerializer):
    class Meta:
        model = PromptTemplate
        fields = ['id', 'name', 'description']


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
            "prompt_template",
        ]
        read_only_fields = ["created_time", "updated_time", "user"]

    def get_integrations(self, obj):  # noqa
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
        if company_name and len(company_name) > 100:
            raise_validation_error(message=_("Company nomi 100 ta belgidan kam bo'lishi kerak"))
        if role and len(role) > 100:
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
            "user_id",
            "username",
            "client_full_name",
            "client_phone_email",
            "start_time",
            "end_time",
            "created_time",
            "updated_time",
        ]
        read_only_fields = ["assistant", "created_time", "updated_time"]

    def validate(self, attrs):
        assistant = self.context.get("assistant_id")
        try:
            assistant = Assistant.objects.get(id=assistant)
            self.validate_subscription(assistant.user.subscription)
        except Assistant.DoesNotExist:
            raise_validation_error(message=_("Assistant topilmadi"))
        if assistant is None:
            raise_validation_error(message=_("Assistant topilmadi"))
        if assistant.ai_enabled:
            if not knowledge_base.has_knowledge_base(assistant):
                raise_validation_error(message=_("Assistant uchun fayl yuklash kerak"))

        attrs["assistant"] = assistant
        return attrs

    def create(self, validated_data):
        validated_data.setdefault("platform", ConversationPlatforms.WEBSITE.value)
        conversation = Conversation.objects.create(**validated_data)
        publish_message_to_ws_assistant(conversation)
        return conversation

    def to_representation(self, instance):
        response = super().to_representation(instance)
        last_message = instance.messages.order_by('-created_time').first()
        last_message_time = last_message.created_time if last_message else None
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
            "user_id",
            "username",
            "client_full_name",
            "client_phone_email",
            "start_time",
            "end_time",
            "created_time",
            "updated_time",
        ]
        read_only_fields = ["created_time", "updated_time", "assistant"]


    def to_representation(self, instance):
        response = super().to_representation(instance)
        last_message = instance.messages.last()
        response["last_message"] = last_message.message_content if last_message else None
        return response


class MessageSerializer(serializers.ModelSerializer, SubscriptionValidationMixin):
    answered_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            "id",
            "conversation",
            "sender",
            "message_content",
            "message_type",
            "audio_file",
            "is_read",
            "created_time",
            "updated_time",
            "answered_by",
            "answered_by_name",
        ]
        read_only_fields = [
            "conversation", "created_time", "updated_time",
            "answered_by", "answered_by_name",
        ]
        extra_kwargs = {
            "message_content": {"required": False},
        }

    def get_answered_by_name(self, obj):
        if obj.answered_by:
            return f"{obj.answered_by.first_name} {obj.answered_by.last_name}".strip()
        return None

    def validate(self, attrs):
        validate_audio(attrs.get("audio_file"))

        if self.instance is not None:
            attrs.pop("conversation", None)
            return attrs

        message_content = attrs.get("message_content")
        audio_file = attrs.get("audio_file")
        if not message_content and not audio_file:
            raise_validation_error(message=_("Xabar matni yoki audio fayl kerak"))

        conversation = self.context.get("conversation_id")
        if conversation is None:
            raise_validation_error(message=_("Conversation topilmadi"))
        try:
            conversation = Conversation.objects.get(id=getattr(conversation, "id", conversation))
        except (Conversation.DoesNotExist, ValidationError, ValueError):
            raise_validation_error(message=_("Conversation topilmadi"))
        self.validate_subscription(conversation.assistant.user.subscription)

        attrs["conversation"] = conversation
        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        if not request:
            raise_validation_error(message=_("Request obyekti kerak"))
        audio_file = validated_data.get("audio_file")
        conversation = validated_data.get("conversation")
        assistant = conversation.assistant
        sender = validated_data.get("sender")
        if audio_file:
            audio_bytes = audio_file.read()
            transcribed_text, _in_tokens, _out_tokens = media.transcribe_audio(
                audio_bytes, filename=audio_file.name
            )
            validated_data["message_content"] = transcribed_text
            validated_data["message_type"] = MessageTypes.AUDIO.value
        else:
            transcribed_text = validated_data.get("message_content")

        validated_data['sender'] = sender
        message = Message.objects.create(**validated_data)
        if conversation.status == ConversationStatuses.ESCALATED.value or not assistant.is_active:
            return message

        result = agent.run(assistant, conversation, transcribed_text)
        return Message.objects.create(
            conversation=conversation,
            sender=SenderTypes.ASSISTANT.value,
            message_content=result.text,
            message_type=MessageTypes.TEXT.value,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )


def queue_file_uploads(assistant, files):
    if not isinstance(files, (list, tuple)):
        files = [files] if files else []

    uploads = []
    for file in files:
        if not file:
            continue
        upload = AssistantFileUpload.objects.create(
            assistant=assistant,
            file=file,
            filename=file.name,
            index_status=FileIndexStatuses.PENDING.value,
        )
        index_assistant_file.delay(upload.id)
        uploads.append(upload)

    if not uploads:
        raise_validation_error(message=_("Fayl yuklanmadi"))

    return uploads


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
            "index_status",
            "created_time",
            "updated_time",
        ]
        read_only_fields = [
            "assistant", "index_status", "created_time", "updated_time",
        ]

    def validate(self, attrs):
        files = self.context.get("files")
        assistant = self.context.get("assistant")
        self.validate_subscription(assistant.user.subscription)
        if not assistant.ai_enabled:
            raise_validation_error(message=_("Assistant AI sizda yoqilmagan"))

        if not files and self.instance is None:
            raise_validation_error(message=_("Fayl yuklanmadi"))

        if not isinstance(files, (list, tuple)):
            files = [files]

        for file in files:
            if not file:
                continue
            if not hasattr(file, "size") or not hasattr(file, "name"):
                raise_validation_error(message=_("Yaroqsiz fayl obyekti"))
            validate_document(file)
        return attrs

    def create(self, validated_data):
        files = self.context.get('files')
        assistant = self.context.get("assistant")

        if not assistant:
            raise_validation_error(message=_("Assistant kerak"))

        self.uploaded_files = queue_file_uploads(assistant, files)
        return self.uploaded_files[0]

    def to_representation(self, instance):
        assistant = getattr(instance, "assistant", None)
        response = super().to_representation(instance)
        if assistant:
            is_new = assistant.vector_id is None
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
        read_only_fields = ["assistant", "created_time", "updated_time"]

    def validate(self, attrs):
        request = self.context.get("request")
        assistant = self.context.get("assistant")
        files = self.context.get('files')
        if not assistant.ai_enabled:
            raise_validation_error(message=_("Assistant AI sizda yoqilmagan"))
        if not request:
            raise_validation_error(message=_("Request obyekt kerak"))
        user = request.user
        self.validate_subscription(user.subscription)
        if not files:
            raise_validation_error(message=_("Fayl yuklanmadi"))

        if not isinstance(files, (list, tuple)):
            files = [files]

        for file in files:
            if not file:
                continue
            if not hasattr(file, 'size') or not hasattr(file, 'name'):
                raise_validation_error(message=_("Yaroqsiz fayl obyekti"))
            validate_document(file)
        return attrs

    def create(self, validated_data):
        if not self.context.get("request"):
            raise_validation_error(message=_("Request obyekt kerak"))
        files = self.context.get('files')
        assistant = self.context.get("assistant")

        if not files or not assistant:
            raise_validation_error(message=_("Fayl va assistant kerak"))

        self.uploaded_files = queue_file_uploads(assistant, files)
        return self.uploaded_files[0]


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
            "platform",
            "username",
            "metadata",
            "contacted",
            "created_time",
            "updated_time",
        ]
        read_only_fields = ["assistant", "created_time", "updated_time"]


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

        buffer = BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        filename = f"leads_export_{assistant_id}_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
        return filename, buffer


class FollowUpStageSerializer(serializers.ModelSerializer):
    class Meta:
        model = FollowUpStage
        fields = [
            "id", "config", "stage_number", "delay_hours",
            "message_template", "is_active", "created_time",
        ]
        read_only_fields = ["created_time", "config"]


class FollowUpConfigSerializer(serializers.ModelSerializer):
    stages = FollowUpStageSerializer(many=True, read_only=True)

    class Meta:
        model = FollowUpConfig
        fields = [
            "id", "assistant", "is_enabled", "target_statuses",
            "stages", "created_time", "updated_time",
        ]
        read_only_fields = ["created_time", "updated_time", "assistant"]


class FollowUpLogSerializer(serializers.ModelSerializer):
    stage_number = serializers.IntegerField(source="stage.stage_number", read_only=True)
    conversation_username = serializers.CharField(source="conversation.username", read_only=True)
    conversation_platform = serializers.CharField(source="conversation.platform", read_only=True)

    class Meta:
        model = FollowUpLog
        fields = [
            "id", "conversation", "stage", "stage_number",
            "conversation_username", "conversation_platform",
            "status", "scheduled_at", "sent_at", "cancelled_at",
            "created_time",
        ]
        read_only_fields = fields
