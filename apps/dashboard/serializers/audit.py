"""Audit-log serializers for the dashboard."""
from rest_framework import serializers

from apps.dashboard.models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = [
            'id', 'user', 'user_name', 'action', 'target_type',
            'target_id', 'target_repr', 'details', 'ip_address',
            'created_time',
        ]

    def get_user_name(self, obj):
        if obj.user:
            return f"{obj.user.first_name or ''} {obj.user.last_name or ''}".strip() or obj.user.username
        return None
