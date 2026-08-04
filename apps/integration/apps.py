from django.apps import AppConfig


class IntegrationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.integration"

    def ready(self):
        # Step rows are cascaded away by Flow and InstagramCommentResponse
        # deletes, which never ran a Python-level delete() — their images stayed
        # in the bucket forever.
        from apps.integration.models import Step
        from apps.shared.file_cleanup import register_file_cleanup

        register_file_cleanup(Step, "message_image")
