from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils import timezone
from django.utils.timezone import now
from shared.models import BaseModel
from apps.integration.models import Integration
from shared.addons.enums import (
    AssistantLanguages,
    PersonalityStyles,
    SenderTypes,
    MessageStatuses,
    ConversationStatuses,
    MessageTypes,
    ConversationPlatforms,
    FileTypes,
    LeadStatuses,
    FollowUpLogStatus,
)

def assistant_file_path(instance, filename):
    return f"assistant/{instance.assistant.id}/files/{filename}"


def assistant_audio_path(instance, filename):
    return f"assistant/{instance.conversation.assistant.id}/conversation/{instance.conversation.id}/audio/{filename}"


class PromptTemplate(BaseModel):
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    content = models.TextField()
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "prompt_template"
        ordering = ['-created_time']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.is_default:
            PromptTemplate.objects.filter(is_default=True).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)


class Assistant(BaseModel):
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    company_name = models.CharField(max_length=100)
    role = models.CharField(max_length=100, default="sales, support, and operations")
    system_prompt = models.TextField(null=True, blank=True)
    user = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="assistants",
    )
    language = ArrayField(
       models.CharField(max_length=50, choices=AssistantLanguages.choices()),
        default=list,
        blank=True,
        null=True
    )
    personality_style = models.CharField(
        max_length=255,
        choices=PersonalityStyles.choices(),
        default=PersonalityStyles.PROFESSIONAL.value,
    )
    created_by = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="created_assistants",
    )
    steps = models.JSONField(default=dict, null=True, blank=True)
    greeting_message = models.TextField(null=True, blank=True)
    fallback_message = models.TextField(null=True, blank=True)
    wait_message = models.TextField(null=True, blank=True)
    assistant_id = models.CharField(max_length=255, null=True, blank=True)
    vector_id = models.CharField(max_length=255, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    ai_enabled = models.BooleanField(default=True)
    web_search_tool = models.BooleanField(default=False)
    prompt_template = models.ForeignKey(
        PromptTemplate, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='assistants'
    )

    integrations: "models.QuerySet[Integration]"

    def __str__(self):
        return f"{self.assistant_id} - {self.name}"

    class Meta:
        db_table = "assistant"


class Conversation(BaseModel):
    assistant = models.ForeignKey(
        Assistant, on_delete=models.CASCADE, related_name="conversations"
    )
    status = models.CharField(
        max_length=15,
        choices=ConversationStatuses.choices(),
        default=ConversationStatuses.OPEN.value,
    )
    platform = models.CharField(
        max_length=50,
        choices=ConversationPlatforms.choices(),
        default=ConversationPlatforms.TELEGRAM.value,
    )
    user_id = models.CharField(max_length=255, null=True, blank=True)
    username = models.CharField(max_length=255, null=True, blank=True)
    token = models.CharField(max_length=255, null=True, blank=True)
    thread_id = models.CharField(max_length=255, null=True, blank=True)
    # Agent state. previous_response_id continues the OpenAI response chain;
    # instructions_version records the assistant's updated_time when the chain
    # started, so editing the prompt restarts it on the next message.
    previous_response_id = models.CharField(max_length=255, null=True, blank=True)
    instructions_version = models.DateTimeField(null=True, blank=True)
    start_time = models.DateTimeField(default=timezone.now)
    end_time = models.DateTimeField(null=True, blank=True)
    client_full_name = models.CharField(max_length=255, null=True, blank=True)
    client_phone_email = models.CharField(max_length=255, null=True, blank=True)
    
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

    class Meta:
        db_table = "conversation"

    def __str__(self):
        return f"Conversation with {self.assistant.name} - {self.platform} - {self.created_time}"


class Message(BaseModel):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    sender = models.CharField(max_length=10, choices=SenderTypes.choices())
    message_content = models.TextField()
    audio_file = models.FileField(
        upload_to=assistant_audio_path, null=True, blank=True, max_length=255
    )
    message_type = models.CharField(
        max_length=10, choices=MessageTypes.choices(), default=MessageTypes.TEXT.value
    )
    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    status = models.CharField(
        max_length=15,
        choices=MessageStatuses.choices(),
        default=MessageStatuses.DELIVERED.value,
    )
    is_read = models.BooleanField(default=False)
    answered_by = models.ForeignKey(
        "user.User", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="answered_messages"
    )

    class Meta:
        db_table = "messages"
        indexes = [
            models.Index(fields=["created_time"]),
        ]

    def __str__(self):
        return f"Message from {self.sender} in conversation {self.conversation.id}"

    def save(self, *args, **kwargs):
        from shared.addons.utils import notify_user_about_low_tokens
        from apps.payment.models import Subscription

        if self.conversation:
            # Bump conversation activity with a single UPDATE, no full save.
            Conversation.objects.filter(pk=self.conversation.pk).update(updated_time=now())

        assistant_user = (
            getattr(self.conversation.assistant, "user", None)
            if self.conversation
            else None
        )
        # Charge the owner's quota only when a NEW assistant reply is inserted:
        # edits/re-saves must not charge again, and an owner without a
        # subscription must not crash the reply.
        subscription = getattr(assistant_user, "subscription", None)
        if (
            self._state.adding
            and subscription is not None
            and self.sender == SenderTypes.ASSISTANT.value
        ):
            # Race-free decrement that can never go negative.
            charged = Subscription.objects.filter(
                pk=subscription.pk, remained_request_count__gt=0
            ).update(remained_request_count=models.F("remained_request_count") - 1)
            if charged:
                subscription.refresh_from_db(fields=["remained_request_count"])
                # Warn the owner only when a request was actually consumed.
                if subscription.remained_request_count in [0, 10, 20]:
                    notify_user_about_low_tokens(
                        assistant_user, subscription.remained_request_count
                    )
        super().save(*args, **kwargs)


class Settings(BaseModel):
    assistant = models.OneToOneField(
        Assistant, on_delete=models.CASCADE, related_name="settings"
    )
    timezone = models.CharField(max_length=50, default="UTC")
    language = models.CharField(max_length=50, default="en")
    notification_preferences = models.JSONField(default=dict)
    escalation_rules = models.JSONField(default=dict)

    class Meta:
        db_table = "settings"

    def __str__(self):
        return f"Settings for {self.assistant.name}"


class AssistantFileUpload(BaseModel):
    assistant = models.ForeignKey(
        "Assistant", 
        on_delete=models.CASCADE, 
        related_name="files"
    )
    website_url = models.URLField(max_length=255, null=True, blank=True)
    file = models.FileField(upload_to=assistant_file_path)
    filename = models.CharField(max_length=255, null=True, blank=True)
    google_sheet_doc_id = models.CharField(max_length=255, null=True, blank=True)
    file_type = models.CharField(
        max_length=255, null=True, blank=True, choices=FileTypes.choices()
    )
    file_id = models.CharField(max_length=355, null=True, blank=True)

    def __str__(self):
        return self.filename

    class Meta:
        db_table = "assistant_file_upload"
        ordering = ["created_time"]

    def save(self, *args, **kwargs):
        if not self.filename:
            self.filename = self.file.name
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.file:
            self.file.delete(save=False)
        super(AssistantFileUpload, self).delete(*args, **kwargs)

class Lead(BaseModel):
    assistant = models.ForeignKey(
        Assistant, on_delete=models.CASCADE, related_name="leads", null=True, blank=True
    )
    full_name = models.CharField(max_length=255, null=True, blank=True)
    phone_number = models.CharField(max_length=255, null=True, blank=True)
    email = models.EmailField(max_length=255, null=True, blank=True)
    product = models.CharField(max_length=255, null=True, blank=True)
    metadata = models.JSONField(blank=True, null=True)
    status = models.CharField(
        max_length=255, choices=LeadStatuses.choices(), default=LeadStatuses.NEW.value
    )
    platform = models.CharField(
        max_length=255,
        choices=ConversationPlatforms.choices(),
        default=ConversationPlatforms.TELEGRAM.value,
    )
    username = models.CharField(max_length=255, null=True, blank=True)
    contacted = models.BooleanField(default=False)

    class Meta:
        db_table = "lead"

    def __str__(self):
        return f"{self.full_name} - {self.product}"


class FollowUpConfig(BaseModel):
    assistant = models.OneToOneField(
        Assistant, on_delete=models.CASCADE, related_name="follow_up_config"
    )
    is_enabled = models.BooleanField(default=False)
    target_statuses = ArrayField(
        models.CharField(max_length=15),
        default=list,
        blank=True,
    )

    class Meta:
        db_table = "follow_up_config"

    def __str__(self):
        return f"FollowUpConfig for {self.assistant.name} (enabled={self.is_enabled})"


class FollowUpStage(BaseModel):
    config = models.ForeignKey(
        FollowUpConfig, on_delete=models.CASCADE, related_name="stages"
    )
    stage_number = models.PositiveIntegerField()
    delay_hours = models.PositiveIntegerField()
    message_template = models.TextField()
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "follow_up_stage"
        ordering = ["stage_number"]
        unique_together = [("config", "stage_number")]

    def __str__(self):
        return f"Stage {self.stage_number} ({self.delay_hours}h) - {self.config.assistant.name}"


class FollowUpLog(BaseModel):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="follow_up_logs"
    )
    stage = models.ForeignKey(
        FollowUpStage, on_delete=models.CASCADE, related_name="logs"
    )
    status = models.CharField(
        max_length=15,
        choices=FollowUpLogStatus.choices(),
        default=FollowUpLogStatus.PENDING.value,
    )
    scheduled_at = models.DateTimeField()
    sent_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "follow_up_log"
        indexes = [
            models.Index(fields=["status", "scheduled_at"]),
        ]
        unique_together = [("conversation", "stage")]

    def __str__(self):
        return f"FollowUp [{self.status}] conv={self.conversation_id} stage={self.stage.stage_number}"
