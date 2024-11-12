from django.contrib import admin
from .models import Integration


@admin.register(Integration)
class Integration(admin.ModelAdmin):
    list_display = ["get_asssitant_name", "name", "integration_type", "is_active", "created_time"]
    search_fields = ["name"]
    fieldsets = (
        (None, {"fields": ("name", "description", "is_active", "api_token", "integration_type")}),
        ("Assistant", {"fields": ("assistant",)}),
    )

    def get_asssitant_name(self, obj): # noqa
        return obj.assistant.name
