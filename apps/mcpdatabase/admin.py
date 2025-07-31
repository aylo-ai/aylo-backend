from django.contrib import admin

from .models import DatabaseConnection

@admin.register(DatabaseConnection)
class DatabaseConnectionAdmin(admin.ModelAdmin):
    list_display = ('id', 'database_name', 'database_type', "assistant", "created_time", 'updated_time')
    search_fields = ('database_name', 'database_type',)
    list_filter = ('database_type',)
    list_per_page = 10
    fieldsets = (
        (None, {'fields': ( 'database_type', 'assistant', "password_encrypted", "database_username", "host", "port", "database_name")}),
    )
