import os

from django.db import models, transaction
from django.utils import timezone
from django.utils.timezone import now

from shared.addons.enums import AssistantLanguages, PersonalityStyles, SenderTypes, MessageStatuses, \
    ConversationStatuses, MessageTypes, ConversationPlatforms
from shared.models import BaseModel
from apps.integration.models import Integration

def assistant_file_path(instance, filename):
    return f"assistant/{instance.assistant.id}/files/{filename}"

def assistant_audio_path(instance, filename):
    return f"assistant/{instance.conversation.assistant.id}/conversation/{instance.conversation.id}/audio/{filename}"

class Assistant(BaseModel):
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    user = models.ForeignKey(
        'user.User',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='assistants'
    )
    company_name = models.CharField(max_length=50)
    role = models.CharField(max_length=50, default="sales, support, and operations")

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
    created_by = models.ForeignKey(
        'user.User',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='created_assistants'
    )

    greeting_message = models.TextField(null=True, blank=True)
    fallback_message = models.TextField(null=True, blank=True)
    wait_message = models.TextField(null=True, blank=True)
    assistant_id = models.CharField(max_length=255, null=True, blank=True)
    vector_id = models.CharField(max_length=255, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    # Type hint for the reverse relationship using string reference
    integrations: 'models.QuerySet[Integration]'

    def __str__(self):
        return f"{self.assistant_id} - {self.name}"

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
    user_id = models.CharField(max_length=255, null=True, blank=True)
    token = models.CharField(max_length=255, null=True, blank=True)
    thread_id = models.CharField(max_length=255, null=True, blank=True)
    start_time = models.DateTimeField(default=timezone.now)
    end_time = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

    class Meta:
        db_table = 'conversation'

    def __str__(self):
        return f"Conversation with {self.assistant.name} - {self.platform} - {self.created_time}"


class Message(BaseModel):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    sender = models.CharField(max_length=10, choices=SenderTypes.choices())
    message_content = models.TextField()
    audio_file = models.FileField(upload_to=assistant_audio_path, null=True, blank=True, max_length=255)
    message_type = models.CharField(max_length=10, choices=MessageTypes.choices(), default=MessageTypes.TEXT.value)
    status = models.CharField(
        max_length=15,
        choices=MessageStatuses.choices(),
        default=MessageStatuses.DELIVERED.value
    )

    class Meta:
        db_table = 'messages'
        indexes = [
            models.Index(fields=['created_time']),
        ]

    def __str__(self):
        return f"Message from {self.sender} in conversation {self.conversation.id}"

    def save(self, *args, **kwargs):
        """
        Save method to update the conversation's updated_time and
        increment the user's used_request_count if applicable.
        """
        # Ensure atomicity of the operations
        with transaction.atomic():
            # Update the conversation's updated_time if it exists
            if self.conversation:
                self.conversation.updated_time = now()
                self.conversation.save(update_fields=["updated_time"])

            # If the sender is the assistant, update the user's used_request_count
            assistant_user = getattr(self.conversation.assistant, "user", None) if self.conversation else None
            if assistant_user and self.sender == SenderTypes.ASSISTANT.value:
                subscription = assistant_user.subscription
                subscription.used_request_count += 1
                subscription.save(update_fields=["used_request_count"])
            # Call the parent save method
            super().save(*args, **kwargs)


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
    website_url = models.URLField(max_length=255, null=True, blank=True)
    file = models.FileField(upload_to=assistant_file_path)
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
        # Delete the file from storage (S3)
        if self.file:
            self.file.delete(save=False)  # This will delete from S3
        super(AssistantFileUpload, self).delete(*args, **kwargs)

class Lead(BaseModel):
    full_name = models.CharField(max_length=255, null=True, blank=True)
    phone_number = models.CharField(max_length=255, null=True, blank=True)
    email = models.EmailField(max_length=255, null=True, blank=True)
    product = models.CharField(max_length=255, null=True, blank=True)
    source = models.CharField(max_length=255, 
                              choices=ConversationPlatforms.choices(),
                              default=ConversationPlatforms.TELEGRAM.value)
    metadata = models.JSONField(blank=True, null=True) 
    contacted = models.BooleanField(default=False)
    
    class Meta:
        db_table = 'lead'

    def __str__(self):
        return f"{self.full_name} - {self.product}"
        
