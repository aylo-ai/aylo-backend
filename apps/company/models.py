from django.db import models

from apps.payment.models import PricingPackage
from shared.models import BaseModel
from apps.user.models import User


class Company(BaseModel):
    name = models.CharField(max_length=100, unique=True)
    industry = models.CharField(max_length=100, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    pricing_package = models.ForeignKey(PricingPackage, on_delete=models.SET_NULL, null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    users = models.ManyToManyField(User, related_name="companies")
    phone_number = models.CharField(max_length=15, null=True, blank=True)

    class Meta:
        db_table = 'company'
        indexes = [
            models.Index(fields=['name']),
        ]

    def __str__(self):
        return self.name


class Settings(BaseModel):
    company = models.OneToOneField(Company, on_delete=models.CASCADE, related_name="settings")
    timezone = models.CharField(max_length=50, default="UTC")
    language = models.CharField(max_length=50, default="en")
    notification_preferences = models.JSONField(default=dict)  # E.g., {"email": True, "sms": False}
    escalation_rules = models.JSONField(default=dict)          # Custom escalation rules

    class Meta:
        db_table = 'settings'
        indexes = [
            models.Index(fields=['company']),
            models.Index(fields=['created_time']),
        ]

    def __str__(self):
        return f"Settings for {self.company.name}"