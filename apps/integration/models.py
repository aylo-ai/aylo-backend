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