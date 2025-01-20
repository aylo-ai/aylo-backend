from django.contrib import admin
from apps.assistant.models import Assistant, Message, Conversation, AssistantFileUpload


@admin.register(Assistant)
class AssistantAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'user', 'language', 'personality_style', 'is_active')
    list_filter = ('language', 'personality_style', 'is_active')
    search_fields = ('name', )
    ordering = ('name', )
    fieldsets = (
        (None, {
            'fields': ('name', 'description', 'user', 'company_name', 'role', 'language',
                       'personality_style', 'greeting_message', 'fallback_message', 'wait_message',
                       'assistant_id', 'is_active', "vector_id")
        }),
    )


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('id', 'assistant', 'status', 'thread_id', 'platform', 'start_time', 'end_time')
    list_filter = ('assistant', 'status')
    search_fields = ('assistant__name', 'thread_id')
    ordering = ('assistant', 'start_time')
    list_per_page = 20
    list_max_show_all = 100
    save_as = True
    save_on_top = True
    actions_on_top = True
    actions_on_bottom = True
    date_hierarchy = 'start_time'
    readonly_fields = ('start_time', 'end_time')
    fieldsets = (
        (None, {
            'fields': ('assistant', 'status', 'thread_id', 'telegram_user_id', 'token')
        }),
        ('System', {
            'fields': ('start_time', 'end_time'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'conversation', 'sender', 'message_type', 'status', 'created_time')
    list_filter = ('conversation', 'sender')
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