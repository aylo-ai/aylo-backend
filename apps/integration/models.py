from django.db import models

from apps.assistant.models import Assistant
from shared.addons.enums import IntegrationTypes
from shared.models import BaseModel


class Integration(BaseModel):
    assistant = models.ForeignKey(Assistant, on_delete=models.CASCADE, related_name='integrations')
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    api_token = models.CharField(max_length=255)
    integration_type = models.CharField(max_length=50, choices=IntegrationTypes.choices())

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