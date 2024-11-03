from django.contrib import admin
from .models import Integration


@admin.register(Integration)
class Integration(admin.ModelAdmin):
    list_display = ["id", "name", "integration_type", "is_active", "created_time"]
    search_fields = ["name"]
    fieldsets = (
        (None, {"fields": ("name", "description")}),
    )
