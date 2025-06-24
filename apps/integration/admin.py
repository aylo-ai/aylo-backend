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

class InstagramCommentResponseInline(admin.TabularInline):
    model = InstagramCommentResponse.instagram_media.through
    extra = 0
    verbose_name = "Comment Response"
    verbose_name_plural = "Comment Responses"
    can_delete = False
    show_change_link = True

@admin.register(InstagramCommentResponse)
class InstagramCommentResponseAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "get_instagram_media",
        "get_trigger_words",
        "comment_message_template",
        "private_message_template",
        "is_respond_to_all_comments",
        "created_time",
    ]
    list_filter = ["integration", "is_respond_to_all_comments", "created_time"]
    search_fields = [
        "comment_message_template",
        "private_message_template",
        "trigger_words__trigger_word",
        "instagram_media__media_id",
    ]
    filter_horizontal = ("instagram_media", "trigger_words")
    readonly_fields = ("is_respond_to_all_comments",)
    fieldsets = (
        (None, {
            "fields": (
                "integration",
                "instagram_media",
                "comment_message_template",
                "private_message_template",
                "trigger_words",
                "is_respond_to_all_comments",
            )
        }),
    )

    def get_instagram_media(self, obj):
        return ", ".join([m.media_id for m in obj.instagram_media.all()])
    get_instagram_media.short_description = "Instagram Media"

    def get_trigger_words(self, obj):
        return ", ".join([w.trigger_word for w in obj.trigger_words.all()])
    get_trigger_words.short_description = "Trigger Words"

@admin.register(CommentTriggerWord)
class CommentTriggerWordAdmin(admin.ModelAdmin):
    list_display = ["trigger_word", "created_time"]
    search_fields = ["trigger_word"]
    list_filter = ["created_time"]
    fieldsets = (
        (None, {"fields": ("trigger_word",)}),
    )

@admin.register(InstagramMedia)
class InstagramMediaAdmin(admin.ModelAdmin):
    list_display = ["media_id", "created_time"]
    search_fields = ["media_id"]
    list_filter = ["created_time"]
    inlines = [InstagramCommentResponseInline]


@admin.register(TelegramGroupIntegration)
class TelegramGroupIntegrationAdmin(admin.ModelAdmin):
    list_display = ["group_id", "group_title", "lead_count", "created_time"]
    search_fields = ["group_title"]
    fieldsets = (
        (None, {"fields": ("group_id", "group_title", "lead_count")}),
        ("Integration", {"fields": ("integration",)}),
    )
    