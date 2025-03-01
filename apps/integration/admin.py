from django.contrib import admin
from .models import Integration, TelegramGroupIntegration


@admin.register(Integration)
class Integration(admin.ModelAdmin):
    list_display = ["get_asssitant_name", "name", "integration_type", "is_active", "created_time"]
    search_fields = ["name"]
    fieldsets = (
        (None, {"fields": ("assistant", "name", "description", "is_active", "api_token",
                           "refresh_token", "integration_type")}),
        ("Instagram", {"fields": ("instagram_user_id", "page_id", "username", "profile_picture")}),
    )

    def get_asssitant_name(self, obj): # noqa
        return obj.assistant.name


@admin.register(TelegramGroupIntegration)
class TelegramGroupIntegrationAdmin(admin.ModelAdmin):
    list_display = ["group_id", "group_title", "lead_count", "created_time"]
    search_fields = ["group_title"]
    fieldsets = (
        (None, {"fields": ("group_id", "group_title", "lead_count")}),
        ("Integration", {"fields": ("integration",)}),
    )