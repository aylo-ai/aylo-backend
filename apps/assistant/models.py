import uuid

from django.db import models
from django.utils import timezone

from shared.addons.enums import AssistantLanguages, PersonalityStyles, SenderTypes, MessageStatuses, \
    ConversationStatuses, MessageTypes
from shared.models import BaseModel


class Assistant(BaseModel):
    name = models.CharField(max_length=255)
    company = models.ForeignKey(
        'company.Company',
        on_delete=models.CASCADE,
        related_name='assistants'
    )
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
    session_id = models.CharField(max_length=255, unique=True, db_index=True, editable=False)
    start_time = models.DateTimeField(default=timezone.now)
    end_time = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.session_id:
            self.session_id = str(uuid.uuid4())  # Generate a new UUID if it doesn’t exist
        super().save(*args, **kwargs)

    class Meta:
        db_table = 'conversation'
        indexes = [
            models.Index(fields=['session_id']),
        ]

    def __str__(self):
        return f"Conversation {self.session_id} with Assistant {self.assistant_id}"


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

