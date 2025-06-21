from django.contrib import admin
from .models import Integration, TelegramGroupIntegration, InstagramMedia, InstagramCommentResponse, CommentTriggerWord


@admin.register(Integration)
class Integration(admin.ModelAdmin):
    list_display = ["get_asssitant_name", "name", "integration_type", "is_active", "created_time"]
    search_fields = ["name"]
    fieldsets = (
        (None, {"fields": ("assistant", "name", "description", "is_active", "api_token",
                           "refresh_token", "integration_type")}),
        ("Instagram", {"fields": ("instagram_user_id", "instagram_account_id", "instagram_username")}),
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

@admin.register(InstagramCommentResponse)
class InstagramCommentResponseAdmin(admin.ModelAdmin):
    list_display = ["instagram_media", "comment_message_template", "private_message_template", "created_time"]
    search_fields = ["instagram_media__media_id"]
    fieldsets = (
        (None, {"fields": ("instagram_media", "comment_message_template", "private_message_template")}),
    )

@admin.register(CommentTriggerWord)
class CommentTriggerWordAdmin(admin.ModelAdmin):
    list_display = ["trigger_word", "created_time"]
    search_fields = ["trigger_word"]
    fieldsets = (
        (None, {"fields": ("trigger_word",)}),
    )

class InstagramCommentResponseInline(admin.TabularInline):
    model = InstagramCommentResponse
    extra = 0
    readonly_fields = ("comment_message_template", "private_message_template")
    can_delete = False
    show_change_link = True

@admin.register(InstagramMedia)
class InstagramMediaAdmin(admin.ModelAdmin):
    list_display = ["media_id", "media_type", "is_respond_to_all_comments", "created_time"]
    search_fields = ["media_id"]
    fieldsets = (
        (None, {"fields": ("media_id", "media_type", "is_respond_to_all_comments")}),
    )
    inlines = [InstagramCommentResponseInline]



