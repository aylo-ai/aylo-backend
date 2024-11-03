from django.contrib import admin
from apps.assistant.models import Assistant, Message, Conversation, AssistantFileUpload


@admin.register(Assistant)
class AssistantAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'language', 'personality_style')
    list_filter = ('user', 'language', 'personality_style')
    search_fields = ('name', 'user__first_name', 'user__last_name', 'user__email')
    ordering = ('user', 'name')
    list_per_page = 20
    list_max_show_all = 100
    save_as = True
    save_on_top = True
    actions_on_top = True
    actions_on_bottom = True
    date_hierarchy = 'created_time'
    readonly_fields = ('created_time', 'updated_time')
    fieldsets = (
        (None, {
            'fields': ('name', 'user', 'language', 'personality_style')
        }),
        ('Messages', {
            'fields': ('greeting_message', 'fallback_message')
        }),
        ('System', {
            'fields': ('created_time', 'updated_time'),
            'classes': ('collapse',)
        }),
    )
    add_fieldsets = (
        (None, {
            'fields': ('name', 'user', 'language', 'personality_style')
        }),
        ('Messages', {
            'fields': ('greeting_message', 'fallback_message')
        }),
    )


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('assistant', 'status', 'session_id', 'start_time', 'end_time')
    list_filter = ('assistant', 'status')
    search_fields = ('assistant__name', 'session_id')
    ordering = ('assistant', 'start_time')
    list_per_page = 20
    list_max_show_all = 100
    save_as = True
    save_on_top = True
    actions_on_top = True
    actions_on_bottom = True
    date_hierarchy = 'start_time'
    readonly_fields = ('session_id', 'start_time', 'end_time')
    fieldsets = (
        (None, {
            'fields': ('assistant', 'status')
        }),
        ('System', {
            'fields': ('session_id', 'start_time', 'end_time'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('conversation', 'sender', 'message_type', 'status', 'created_time')
    list_filter = ('conversation', 'sender')
    search_fields = ('conversation__session_id',)
    ordering = ('conversation', 'created_time')
    list_per_page = 20
    list_max_show_all = 100
    save_as = True
    save_on_top = True
    actions_on_top = True
    actions_on_bottom = True
    date_hierarchy = 'created_time'
    readonly_fields = ('created_time', 'updated_time')
    fieldsets = (
        (None, {
            'fields': ('conversation', 'sender', 'message_content', 'message_type', 'status')
        }),
        ('System', {
            'fields': ('created_time', 'updated_time'),
            'classes': ('collapse',)
        }),
    )
    add_fieldsets = (
        (None, {
            'fields': ('conversation', 'sender', 'message_content', 'message_type', 'status')
        }),
    )


@admin.register(AssistantFileUpload)
class AssistantFileUploadAdmin(admin.ModelAdmin):
    list_display = ('assistant', 'file', 'created_time')
    list_filter = ('assistant', 'created_time')
    search_fields = ('assistant__name', 'file')
    ordering = ('assistant', 'created_time')
    list_per_page = 20
    list_max_show_all = 100
    save_as = True
    save_on_top = True
    actions_on_top = True
    actions_on_bottom = True
    date_hierarchy = 'created_time'
    readonly_fields = ('created_time', 'updated_time')
    fieldsets = (
        (None, {
            'fields': ('assistant', 'file')
        }),
        ('System', {
            'fields': ('created_time', 'updated_time'),
            'classes': ('collapse',)
        }),
    )
    add_fieldsets = (
        (None, {
            'fields': ('assistant', 'file')
        }),
    )