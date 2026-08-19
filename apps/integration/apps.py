from django.apps import AppConfig


class IntegrationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.integration"

    def ready(self):
        from apps.integration.models import Step
        from apps.shared.file_cleanup import register_file_cleanup

        register_file_cleanup(Step, "message_image")
