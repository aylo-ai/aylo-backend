from django.db import models
from apps.shared.models import BaseModel


class AuditLog(BaseModel):
    """Tracks admin actions for accountability and compliance."""
    user = models.ForeignKey(
        'user.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs'
    )
    action = models.CharField(max_length=50)  # create, update, delete, block, refund, etc.
    target_type = models.CharField(max_length=50)  # user, assistant, transaction, etc.
    target_id = models.UUIDField(null=True, blank=True)
    target_repr = models.CharField(max_length=255, blank=True, default='')
    details = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = 'audit_log'
        ordering = ['-created_time']
        indexes = [
            models.Index(fields=['action']),
            models.Index(fields=['target_type']),
            models.Index(fields=['user']),
            models.Index(fields=['-created_time']),
        ]

    def __str__(self):
        return f"{self.user} {self.action} {self.target_type} {self.target_id}"

    @classmethod
    def log(cls, user, action, target_type, target_id=None, target_repr='', details=None, ip_address=None):
        return cls.objects.create(
            user=user,
            action=action,
            target_type=target_type,
            target_id=target_id,
            target_repr=target_repr,
            details=details or {},
            ip_address=ip_address,
        )
