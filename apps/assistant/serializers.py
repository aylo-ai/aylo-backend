import json
import logging
from io import BytesIO
from openpyxl import Workbook
from datetime import datetime

from rest_framework import serializers
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.utils.timezone import localtime


from apps.assistant.services.google import process_google_doc
from apps.assistant.models import (
    Assistant, Conversation, Message, Settings, AssistantFileUpload, Lead, PromptTemplate,
    FollowUpConfig, FollowUpStage, FollowUpLog,
)
from apps.shared.ai_service import knowledge_base, media
from apps.shared.ai_service.agent import agent
from apps.shared.addons.validations import raise_validation_error
from apps.shared.addons.enums import (
    ConversationPlatforms, ConversationStatuses, MessageTypes, SenderTypes,
)
from apps.shared.mixins import SubscriptionValidationMixin
from apps.shared.addons.redis import publish_message_to_ws_assistant

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
        # `user` is the tenancy column. While it was writable, `PATCH
        # /assistant/<own id>/ {"user": "<someone else's id>"}` silently moved
        # the assistant into that account: it then counted against the victim's
        # assistant quota and every integration hung off it billed the victim's
        # subscription. Owners are set by the server — `AssistantListCreateView`
        # and the dashboard's create path both pass `user=` to `save()`, which
        # a read-only field does not block.
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
        read_only_fields = ["created_time", "updated_time"]
        extra_kwargs = {
            "assistant": {"required": False},
        }

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
            if not assistant.vector_id:
                raise_validation_error(message=_("Assistant uchun fayl yuklash kerak"))

        attrs["assistant"] = assistant
        return attrs

    def create(self, validated_data):
        # The agent tracks its own state per conversation, so there is nothing
        # to set up here beyond the row itself. Everything the caller sent is
        # persisted — this used to hard-code `platform=website` and pass only
        # the assistant, silently discarding the validated `user_id`,
        # `username`, `client_full_name`, `client_phone_email` and `status`.
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
        # This serializer only ever serves retrieve/update. A writable
        # `assistant` let `PATCH /conversation/<own id>/` re-parent the
        # conversation onto another tenant's assistant, pushing attacker-written
        # messages into that tenant's inbox. Conversations are created — with
        # their assistant — by `ConversationSerializer`.
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
            # Exposed so an inbox can render unread badges/counts. The column
            # already existed and `messages/bulk-read/` already maintained it —
            # it was simply never serialized, leaving clients unable to tell a
            # read message from an unread one.
            "is_read",
            "created_time",
            "updated_time",
            "answered_by",
            "answered_by_name",
        ]
        read_only_fields = ["created_time", "updated_time", "answered_by", "answered_by_name"]
        extra_kwargs = {
            "conversation": {"required": False},
            "message_content": {"required": False},
        }

    def get_answered_by_name(self, obj):
        if obj.answered_by:
            return f"{obj.answered_by.first_name} {obj.answered_by.last_name}".strip()
        return None

    def validate(self, attrs):
        # On an update the message already has its conversation and the content
        # may not be re-sent, so both checks below only apply to a create.
        if self.instance is not None:
            # A message never changes conversation. `conversation` stayed
            # writable on this path, so `PATCH /message/<own id>/
            # {"conversation": "<victim's>"}` moved an attacker-authored message
            # into another tenant's thread — the view's ownership check had
            # already passed on the *original* conversation.
            attrs.pop("conversation", None)
            return attrs

        message_content = attrs.get("message_content")
        audio_file = attrs.get("audio_file")
        if not message_content and not audio_file:
            raise_validation_error(message=_("Xabar matni yoki audio fayl kerak"))

        # The conversation comes from the URL (`MessageListCreateView` puts it in
        # the context); falling back to the body keeps the serializer usable
        # from any caller rather than 400-ing whenever the context is absent.
        conversation = self.context.get("conversation_id") or attrs.get("conversation")
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
            # Not `_`: that name is gettext, and binding it here makes it a
            # local for the whole method — the `_("Request obyekti kerak")`
            # above then raises UnboundLocalError (a 500) instead of the
            # validation error it is meant to raise.
            transcribed_text, _input_tokens, _output_tokens = media.transcribe_audio(
                audio_bytes, filename=audio_file.name,
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
        self.validate_subscription(assistant.user.subscription)
        if not assistant.ai_enabled:
            raise_validation_error(message=_("Assistant AI sizda yoqilmagan"))

        # A file is mandatory when uploading, but not when editing an existing
        # row: the detail view reuses this serializer, and requiring a file
        # there made it impossible to rename a document without re-uploading it.
        if not files and self.instance is None:
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
                try:
                    file_url = request.build_absolute_uri(upload.file.url) if request else upload.file.url
                    store_id = knowledge_base.ensure_store(assistant)
                    file_id = knowledge_base.add_file(store_id, file_url)
                    if file_id:
                        upload.file_id = file_id
                        upload.save(update_fields=["file_id"])
                except Exception as exc:
                    logger.exception("Failed to index %s for assistant %s: %s", filename, assistant.id, exc)
                uploaded_files.append(upload)


        return uploaded_files[0] if len(uploaded_files) == 1 else uploaded_files

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
            if file.size > 30 * 1024 * 1024:
                raise_validation_error(message=f"Fayl {file.name} 30MB dan katta")
        return attrs

    def create(self, validated_data):
        # `validated_data` is unused — the files come off the request via the
        # context, because DRF cannot bind a multi-file upload to a single
        # model field. The parameter is still required: DRF always calls
        # `create(validated_data)`, and the old zero-argument signature raised
        # TypeError the moment this path was reached.
        request = self.context.get("request")
        if not request:
            raise_validation_error(message=_("Request obyekt kerak"))
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
            try:
                file_url = request.build_absolute_uri(upload.file.url)
                store_id = knowledge_base.ensure_store(assistant)
                file_id = knowledge_base.add_file(store_id, file_url)
                if file_id:
                    upload.file_id = file_id
                    upload.save(update_fields=["file_id"])
            except Exception as exc:
                logger.exception("Failed to index %s for assistant %s: %s", filename, assistant.id, exc)
            uploaded_files.append(upload)

        # Keep the full set available to the view, but return a single instance:
        # returning a list from `create()` breaks `serializer.data`, which
        # expects one object on a non-`many` serializer.
        self.uploaded_files = uploaded_files
        return uploaded_files[0]


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
        file_url = response.get("file_url")
        if assistant and file_url:
            store_id = knowledge_base.ensure_store(assistant)
            knowledge_base.add_file(store_id, file_url)

        validated_data["file_type"] = response.get("file_type")
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
            "platform",
            "username",
            "metadata",
            "contacted",
            "created_time",
            "updated_time",
        ]
        # `assistant` is set from the URL, never from the body — a writable
        # field here let a caller attach a lead to somebody else's assistant,
        # bypassing the ownership check the view had already performed.
        read_only_fields = ["assistant", "created_time", "updated_time"]

    
class LeadExportSerializer(serializers.Serializer):
    def export_leads(self, assistant_id):
        """Build the leads workbook in memory.

        Returns (filename, BytesIO). This used to write
        `leads_export_<date>.xlsx` into the process working directory — one
        path shared by *every* assistant and every tenant on a given day, so
        two concurrent exports raced and one caller could be handed the other's
        leads. Nothing ever deleted the files either.
        """
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