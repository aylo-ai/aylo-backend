from django.contrib import admin
from apps.user.models import User, PrivacyPolicy, UserAgreement


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("username", "first_name", "last_name", "email", "phone_number", "user_role")
    search_fields = ("username", "first_name", "last_name", "email", "phone_number")
    list_filter = ("user_role",)
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "email", "phone_number", "user_role")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser",)}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("username", "password1", "password2"),
        }),
    )
    ordering = ("username",)
    filter_horizontal = ("groups", "user_permissions")
    readonly_fields = ("last_login", "date_joined")
    list_per_page = 10
    actions = ["make_verified"]

    def make_verified(self, request, queryset):
        queryset.update(is_verified=True)
    make_verified.short_description = "Mark selected users as verified"


@admin.register(PrivacyPolicy)
class PrivacyPolicyAdmin(admin.ModelAdmin):
    list_display = ("title", "language", "is_active")
    search_fields = ("title", "language")
    list_filter = ("is_active",)
    fieldsets = (
        (None, {"fields": ("title", "content")}),
        ("Settings", {"fields": ("is_active", "language")}),
    )


@admin.register(UserAgreement)
class UserAgreementAdmin(admin.ModelAdmin):
    list_display = ("title", "language", "is_active")
    search_fields = ("title", "language")
    list_filter = ("is_active",)
    fieldsets = (
        (None, {"fields": ("title", "content")}),
        ("Settings", {"fields": ("is_active", "language")}),
    )