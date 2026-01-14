from django.contrib import admin
from apps.assistant.models import Assistant, Message, Conversation, AssistantFileUpload, Lead, Integration



class IntegrationInline(admin.TabularInline):
    model = Integration
    extra = 0
    readonly_fields = ("name", "created_time", "is_active", "integration_type")
    fields = ("name", "integration_type", "is_active", "created_time")
    can_delete = False
    show_change_link = True

@admin.register(Assistant)
class AssistantAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'user', 'language', 'personality_style', 'is_active')
    list_filter = ('language', 'personality_style', 'is_active')
    search_fields = ('name', )
    ordering = ('name', 'created_time')
    readonly_fields = ('created_time', 'updated_time')
    fieldsets = (
        (None, {
            'fields': ('name', 'description', 'user', 'company_name', 'role', 'language', 'created_by','steps',
                       'personality_style', 'greeting_message', 'fallback_message', 'wait_message','web_search_tool',
                       'assistant_id','ai_enabled', 'system_prompt', 'is_active', "vector_id", "created_time", "updated_time")
        }),
    )
    inlines = [IntegrationInline]

@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ('id', 'full_name', 'phone_number', 'platform', 'product', 'created_time')
    list_filter = ('product', 'created_time', 'platform')
    search_fields = ('full_name', 'phone_number', 'platform')
    ordering = ('created_time', )
    readonly_fields = ('created_time', 'updated_time')
    fieldsets = (
        (None, {
            'fields': ('full_name', 'phone_number', 'email', 'product', 'metadata','assistant','status','contacted', 'platform')
        }),
    )
        

class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    readonly_fields = ('sender', 'message_content', 'message_type', 'status', 'audio_file', 'created_time', 'input_tokens', 'output_tokens')
    can_delete = False
    show_change_link = True

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.order_by("created_time")  # eng boshidan boshlab ketadi


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('id', 'assistant', 'status', 'platform', 'start_time', 'end_time')
    list_filter = ('assistant', 'status', 'platform')
    search_fields = ('assistant__name', 'thread_id')
    ordering = ('assistant', 'start_time', 'platform', "created_time")
    list_per_page = 20
    list_max_show_all = 100
    save_as = True
    save_on_top = True
    actions_on_top = True
    actions_on_bottom = True
    date_hierarchy = 'start_time'
    readonly_fields = ('start_time', 'end_time')
    inlines = [MessageInline]  # 👉 Shu yerga qo‘shiladi

    fieldsets = (
        (None, {
            'fields': ('assistant', 'status', 'thread_id', 'user_id', 
            'username', 'token','client_full_name','client_phone_email', 'platform',)
        }),
        ('System', {
            'fields': ('start_time', 'end_time'),
            'classes': ('collapse',)
        }),
    )



@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'conversation', 'sender', 'message_type', 'status', 'created_time', 'input_tokens', 'output_tokens',"is_read")
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
            'fields': ('conversation', 'sender', 'message_content', 'message_type', 'status', 'audio_file', 'input_tokens', 'output_tokens','is_read')
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
            'fields': ('assistant', 'file', 'file_id')
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