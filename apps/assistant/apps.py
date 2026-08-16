from django.apps import AppConfig


class AssistantConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.assistant"

    def ready(self):
        # Registering the agent tools here — rather than having the shared AI
        # layer import app models — is what keeps `apps.shared` dependency-free.
        from apps.assistant import ai_tools

        ai_tools.register_tools()

        # Stored objects follow their rows into the void — including on cascade
        # and bulk deletes, which a Model.delete() override never sees.
        from apps.assistant.models import AssistantFileUpload, Message
        from apps.shared.file_cleanup import register_file_cleanup

        register_file_cleanup(Message, "audio_file")
        register_file_cleanup(AssistantFileUpload, "file")
