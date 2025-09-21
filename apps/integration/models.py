from django.db import models

from shared.addons.enums import IntegrationTypes, ActionType, ButtonType, ConditionType, FlowType
from shared.models import BaseModel


class Integration(BaseModel):
    assistant = models.ForeignKey(
        'assistant.Assistant', 
        on_delete=models.CASCADE, 
        related_name='integrations',
        null=True, blank=True
    )
    user = models.ForeignKey(
        'user.User',
        on_delete=models.CASCADE,
        related_name='integrations',
        null=True, blank=True
    )
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    api_token = models.CharField(max_length=255, null=True, blank=True)
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
    media_url = models.CharField(max_length=1500, null=True, blank=True)
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

def comment_response_image_path(instance, filename):
    return f"integrtion/{instance.integration.id}/image/{filename}"

class InstagramCommentResponse(BaseModel):
    integration = models.ForeignKey(Integration, on_delete=models.CASCADE, related_name='instagram_comment_responses', blank=True, null=True)
    instagram_media = models.ManyToManyField(InstagramMedia, related_name='instagram_comment_responses')
    comment_message_template = models.TextField(blank=True)
    private_message_template = models.TextField(blank=True)
    trigger_words = models.ManyToManyField("CommentTriggerWord", related_name='instagram_comment_responses')
    is_respond_to_all_comments = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.private_message_template} - {self.comment_message_template}"
    
    def delete(self, *args, **kwargs):
        self.instagram_media.all().delete()
        super().delete(*args, **kwargs)

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

class CommentResponseButton(BaseModel):
    text = models.CharField(max_length=255)
    url = models.CharField(max_length=255, null=True, blank=True)
    type = models.CharField(max_length=50, choices=ButtonType.choices, null=True, blank=True)

    def __str__(self):
        return f"{self.text} button"

    class Meta:
        db_table = 'comment_response_btn'


class Flow(BaseModel):
    title = models.CharField(max_length=255)
    flow_type = models.CharField(max_length=50, choices=FlowType.choices, default=FlowType.COMMENT_RESPONSE.value)
    is_active = models.BooleanField(default=True)
    comment_response = models.ForeignKey(InstagramCommentResponse, on_delete=models.CASCADE, related_name='flows', null=True, blank=True)

    class Meta:
        db_table = 'flow'

    def __str__(self):
        return self.title


class Step(BaseModel):
    message_content = models.CharField(max_length=255, null=True, blank=True)
    action = models.CharField(max_length=255, choices=ActionType.choices)
    condition_type = models.CharField(max_length=255, choices=ConditionType.choices, null=True, blank=True)
    extra_button = models.ManyToManyField(CommentResponseButton, related_name='steps')
    message_image = models.ImageField(upload_to=comment_response_image_path, null=True, blank=True)
    flow = models.ForeignKey(Flow, on_delete=models.CASCADE, related_name='steps')
    start_point = models.BooleanField(default=False)

    class Meta:
        db_table = 'step'

    def __str__(self):
        return self.message_content or f"Step {self.id}"

class Transition(BaseModel):
    from_to = models.ForeignKey(Step, on_delete=models.CASCADE, related_name='transitions_from')
    to_step = models.ForeignKey(Step, on_delete=models.CASCADE, related_name='transitions_to', null=True, blank=True)
    button_text = models.ForeignKey(CommentResponseButton, on_delete=models.CASCADE, related_name='transitions', null=True, blank=True)

    class Meta:
        db_table = 'transition'

    def __str__(self):
        return f"{self.from_to.message_content} --> {self.to_step.message_content if self.to_step else 'END'}"

class InstagramUserState(BaseModel):
    account_id = models.CharField(max_length=255)   # ig user / account id
    user_id = models.CharField(max_length=255)      # commenter / recipient id
    current_step = models.ForeignKey(Step, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        db_table = "instagram_user_state"
        unique_together = ("account_id", "user_id")

    def __str__(self):
        return f"{self.account_id}::{self.user_id} -> {self.current_step.message_content if self.current_step else 'END'}"