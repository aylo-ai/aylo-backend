import os
import uuid

from django.db import models
from django.utils import timezone

from apps.payment.models import PricingPackage
from shared.addons.enums import AssistantLanguages, PersonalityStyles, SenderTypes, MessageStatuses, \
    ConversationStatuses, MessageTypes, ConversationPlatforms
from shared.models import BaseModel


class Assistant(BaseModel):
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    user = models.ForeignKey(
        'user.User',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='assistants'
    )
    pricing_package = models.ForeignKey(
        PricingPackage,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='assistants'
    )
    company_name = models.CharField(max_length=50)
    role = models.CharField(max_length=50)

    language = models.CharField(
        max_length=10,
        choices=AssistantLanguages.choices(),
        default=AssistantLanguages.ENGLISH.value
    )
    personality_style = models.CharField(
        max_length=255,
        choices=PersonalityStyles.choices(),
        default=PersonalityStyles.PROFESSIONAL.value
    )

    greeting_message = models.TextField(null=True, blank=True)
    fallback_message = models.TextField(null=True, blank=True)
    assistant_id = models.CharField(max_length=255, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'assistant'


class Conversation(BaseModel):
    assistant = models.ForeignKey(
        Assistant,
        on_delete=models.CASCADE,
        related_name='conversations'
    )
    status = models.CharField(
        max_length=15,
        choices=ConversationStatuses.choices(),
        default=ConversationStatuses.OPEN.value
    )
    platform = models.CharField(
        max_length=50,
        choices=ConversationPlatforms.choices(),
        default=ConversationPlatforms.TELEGRAM.value
    )
    telegram_user_id = models.CharField(max_length=255, null=True, blank=True)
    token = models.CharField(max_length=255, null=True, blank=True)
    thread_id = models.CharField(max_length=255, null=True, blank=True)
    start_time = models.DateTimeField(default=timezone.now)
    end_time = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

    class Meta:
        db_table = 'conversation'

    def __str__(self):
        return f"Conversation with {self.assistant.name}"


class Message(BaseModel):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    sender = models.CharField(max_length=10, choices=SenderTypes.choices)
    message_content = models.TextField()
    message_type = models.CharField(max_length=10, choices=MessageTypes.choices(), default=MessageTypes.TEXT.value)
    status = models.CharField(
        max_length=15,
        choices=MessageStatuses.choices,
        default=MessageStatuses.DELIVERED.value
    )

    class Meta:
        db_table = 'messages'
        ordering = ['created_time']

    def __str__(self):
        return f"Message from {self.sender} in conversation {self.conversation_id}"


class Settings(BaseModel):
    assistant = models.OneToOneField(Assistant, on_delete=models.CASCADE, related_name="settings")
    timezone = models.CharField(max_length=50, default="UTC")
    language = models.CharField(max_length=50, default="en")
    notification_preferences = models.JSONField(default=dict)  # E.g., {"email": True, "sms": False}
    escalation_rules = models.JSONField(default=dict)

    class Meta:
        db_table = 'settings'

    def __str__(self):
        return f"Settings for {self.assistant.name}"


class AssistantFileUpload(BaseModel):
    assistant = models.ForeignKey("Assistant", on_delete=models.CASCADE, related_name="files")
    file = models.FileField(upload_to="assistant/files/")
    filename = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return self.filename

    class Meta:
        db_table = 'assistant_file_upload'
        ordering = ['created_time']

    def save(self, *args, **kwargs):
        if not self.filename:
            self.filename = self.file.name
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.file:
            if os.path.isfile(self.file.path):
                os.remove(self.file.path)
        super(AssistantFileUpload, self).delete(*args, **kwargs)
