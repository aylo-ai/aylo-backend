from django.apps import AppConfig


class AssistantConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.assistant"

    def ready(self):
        # Registering the agent tools here — rather than having the shared AI
        # layer import app models — is what keeps `apps.shared` dependency-free.
        from apps.assistant import ai_tools

        ai_tools.register_tools()
