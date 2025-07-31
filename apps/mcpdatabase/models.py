from django.db import models

from shared.models import BaseModel
from apps.assistant.models import Assistant
from shared.addons.enums import DatabaseTypes

class DatabaseConnection(BaseModel):
    database_type = models.CharField(max_length=255, choices=DatabaseTypes.choices(), null=True, blank=True)
    host = models.CharField(max_length=255, null=True, blank=True)
    database_username = models.CharField(max_length=255, null=True, blank=True)
    password_encrypted = models.CharField(max_length=255, null=True, blank=True)
    port = models.IntegerField(null=True, blank=True)
    database_name = models.CharField(max_length=255, null=True, blank=True)
    assistant = models.ForeignKey(Assistant, on_delete=models.CASCADE, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    
    def __str__(self):
        return f"{self.database_type} - {self.database_name}"
    
    class Meta:
        verbose_name = "Database Connection"
        verbose_name_plural = "Database Connections"

