from django.contrib import admin

from apps.dashboard.models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['user', 'action', 'target_type', 'target_id', 'created_time']
    list_filter = ['action', 'target_type', 'created_time']
    search_fields = ['target_repr', 'user__username']
    readonly_fields = ['user', 'action', 'target_type', 'target_id', 'target_repr', 'details', 'ip_address', 'created_time']
