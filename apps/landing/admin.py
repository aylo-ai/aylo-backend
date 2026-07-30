from django.contrib import admin
from apps.landing.models import LandingLead, LeadNotificationGroup


@admin.register(LandingLead)
class LandingLeadAdmin(admin.ModelAdmin):
    list_display = ["full_name", "phone_number", "telegram_username", "source_page", "contacted", "created_time"]
    list_filter = ["contacted", "source_page", "created_time"]
    search_fields = ["full_name", "phone_number", "telegram_username"]
    list_editable = ["contacted"]
    ordering = ["-created_time"]


@admin.register(LeadNotificationGroup)
class LeadNotificationGroupAdmin(admin.ModelAdmin):
    list_display = ["group_title", "group_id", "is_active", "created_time"]
    list_filter = ["is_active"]
