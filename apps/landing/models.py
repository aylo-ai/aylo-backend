from django.db import models
from apps.shared.models import BaseModel


class LandingLead(BaseModel):
    full_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=50)
    telegram_username = models.CharField(max_length=255, blank=True, default="")
    source_page = models.CharField(max_length=255, blank=True, default="")
    contacted = models.BooleanField(default=False)

    class Meta:
        db_table = "landing_leads"
        ordering = ["-created_time"]

    def __str__(self):
        return f"{self.full_name} — {self.phone_number}"


class LeadNotificationGroup(BaseModel):
    """Telegram groups verified with password to receive lead notifications."""
    group_id = models.CharField(max_length=100, unique=True)
    group_title = models.CharField(max_length=255, blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "lead_notification_groups"

    def __str__(self):
        return f"{self.group_title} ({self.group_id})"
