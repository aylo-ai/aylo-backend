from django.apps import AppConfig


class AssistantConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.assistant"

    def ready(self):
        from apps.assistant import ai_tools

        ai_tools.register_tools()

        from apps.assistant.models import AssistantFileUpload, Message
        from apps.shared.file_cleanup import register_file_cleanup

        register_file_cleanup(Message, "audio_file")
        register_file_cleanup(AssistantFileUpload, "file")
