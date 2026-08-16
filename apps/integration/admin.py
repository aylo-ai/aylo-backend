from django.contrib import admin

from apps.shared.addons.crypto import mask_secret

from .models import (
    CommentResponseButton,
    CommentTriggerWord,
    Flow,
    InstagramCommentResponse,
    InstagramMedia,
    InstagramUserState,
    Integration,
    Step,
    TelegramGroupIntegration,
    Transition,
)


@admin.register(Integration)
class IntegrationAdmin(admin.ModelAdmin):
    """The credentials are deliberately absent from the change form.

    `api_token`, `refresh_token` and the amoCRM payload in `metadata` are live
    bearer credentials. They used to be plain editable inputs, so any staff
    member with integration access — and anyone who got hold of a session —
    could read every customer's bot token straight off the page. They are shown
    masked and read-only now; tokens are set by the OAuth callbacks and the
    integration API, never by hand.
    """

    list_display = ["get_asssitant_name", "name", "integration_type", "is_active", "created_time"]
    search_fields = ["name",]
    readonly_fields = ("api_token_masked", "refresh_token_masked", "metadata_keys")
    fieldsets = (
        (None, {"fields": ("assistant", "user", "name", "description", "is_active",
                           "is_comment_response", "integration_type")}),
        ("Credentials (read-only)", {
            "fields": ("api_token_masked", "refresh_token_masked", "metadata_keys"),
        }),
        ("Instagram", {"fields": ("instagram_user_id", "instagram_account_id", "instagram_username")}),
    )

    def get_asssitant_name(self, obj): # noqa
        if obj.assistant:
            return obj.assistant.name
        return obj.user.first_name if obj.user else None

    @admin.display(description="API token")
    def api_token_masked(self, obj):
        return mask_secret(obj.api_token)

    @admin.display(description="Refresh token")
    def refresh_token_masked(self, obj):
        return mask_secret(obj.refresh_token)

    @admin.display(description="Metadata keys")
    def metadata_keys(self, obj):
        """Key names only — the values hold the amoCRM refresh token."""
        return ", ".join(sorted(obj.metadata)) if isinstance(obj.metadata, dict) else "—"

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
    list_display = ["media_id", "media_type", "created_time"]
    search_fields = ["media_id"]
    list_filter = ["created_time"]
    inlines = [InstagramCommentResponseInline]
    fieldsets = (
        (None, {"fields": ("media_id", "media_type", "media_url", "username", "timestamp", "caption", "comments_count", "like_count", "children")}),
    )


@admin.register(TelegramGroupIntegration)
class TelegramGroupIntegrationAdmin(admin.ModelAdmin):
    list_display = ["group_title", "group_id", "is_approved", "lead_count", "integration", "created_time"]
    list_filter = ["is_approved"]
    list_editable = ["is_approved"]
    search_fields = ["group_title", "group_id"]
    fieldsets = (
        (None, {"fields": ("group_id", "group_title", "lead_count", "is_approved")}),
        ("Integration", {"fields": ("integration",)}),
    )

@admin.register(CommentResponseButton)
class CommentResponseButtonAdmin(admin.ModelAdmin):
    list_display = ('text','url')
    fieldsets = (
        (None, {'fields':('text', 'url','type')}),
    )

admin.site.register(Step)
admin.site.register(Flow)
admin.site.register(InstagramUserState)
admin.site.register(Transition)
