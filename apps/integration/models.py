from django.db import models

from shared.addons.enums import IntegrationTypes
from shared.models import BaseModel


class Integration(BaseModel):
    assistant = models.ForeignKey('assistant.Assistant', on_delete=models.CASCADE, related_name='integrations')
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    api_token = models.CharField(max_length=255)
    refresh_token = models.CharField(max_length=500, null=True, blank=True)  # Optional for Instagram
    integration_type = models.CharField(max_length=50, choices=IntegrationTypes.choices())

    # Instagram-specific fields
    instagram_user_id = models.CharField(max_length=50, null=True, blank=True)  # IG user ID
    instagram_account_id = models.CharField(max_length=50, null=True, blank=True)  # IG account ID
    instagram_username = models.CharField(max_length=100, null=True, blank=True)  # IG username

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'integration'
        ordering = ['-created_time']


class TelegramGroupIntegration(BaseModel):
    integration = models.ForeignKey(Integration, on_delete=models.CASCADE, related_name='telegram_group')
    group_id = models.CharField(max_length=255)
    group_title = models.CharField(max_length=255)
    lead_count = models.IntegerField(default=0)

    def __str__(self):
        return f"Telegram Group {self.group_title} for {self.integration.name}"

    class Meta:
        db_table = 'telegram_group_integration'


class InstagramMedia(BaseModel):
    media_id = models.CharField(max_length=255, null=True, blank=True, unique=True)
    media_type = models.CharField(max_length=600, null=True, blank=True)
    media_url = models.CharField(max_length=600, null=True, blank=True)
    username = models.CharField(max_length=255, null=True, blank=True)
    timestamp = models.DateTimeField(null=True, blank=True)
    caption = models.TextField(null=True, blank=True)
    comments_count = models.IntegerField(default=0)
    like_count = models.IntegerField(default=0)
    children = models.JSONField(null=True, blank=True)

    def __str__(self):
        return f"Instagram Media {self.media_id}"

    class Meta:
        db_table = 'instagram_media'
        ordering = ['-created_time']


class InstagramCommentResponse(BaseModel):
    integration = models.ForeignKey(Integration, on_delete=models.CASCADE, related_name='instagram_comment_responses', blank=True, null=True)
    instagram_media = models.ManyToManyField(InstagramMedia, related_name='instagram_comment_responses')
    comment_message_template = models.TextField(blank=True)
    private_message_template = models.TextField(blank=True)
    trigger_words = models.ManyToManyField("CommentTriggerWord", related_name='instagram_comment_responses')
    is_respond_to_all_comments = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.private_message_template} - {self.comment_message_template}"

    class Meta:
        db_table = 'instagram_comment_response'
        ordering = ['-created_time']

class CommentTriggerWord(BaseModel):
    trigger_word = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"Comment Trigger Word {self.trigger_word}"
    
    class Meta:
        db_table = 'comment_trigger_word'
        ordering = ['-created_time']    

