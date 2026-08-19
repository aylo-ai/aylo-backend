import io
import logging
from contextlib import redirect_stdout
from unittest import mock

from django.contrib import admin as django_admin
from django.test import TestCase

from apps.assistant.models import Assistant
from apps.integration.admin import IntegrationAdmin
from apps.integration.gateways.telegram import handle_bot_added_to_group
from apps.integration.models import Integration, TelegramGroupIntegration
from apps.integration.serializers import IntegrationSerializer
from apps.integration.tasks.telegram import process_message_task
from apps.shared.addons import crypto
from apps.shared.addons.enums import IntegrationTypes
from apps.shared.tests.test_crypto import raw_column

BOT_TOKEN = "8012345678:AAH-super-secret-telegram-bot-token"


class IntegrationTokenAtRestTests(TestCase):
    def setUp(self):
        self.assistant = Assistant.objects.create(name="Sales", company_name="Acme")
        self.integration = Integration.objects.create(
            assistant=self.assistant,
            name="Telegram",
            integration_type=IntegrationTypes.TELEGRAM.value,
            api_token=BOT_TOKEN,
            refresh_token="billz-refresh",
            metadata={"refresh_token": "amocrm-refresh", "subdomain": "acme"},
        )

    def test_no_credential_column_holds_plaintext(self):
        for column, secret in (
            ("api_token", BOT_TOKEN),
            ("refresh_token", "billz-refresh"),
            ("metadata", "amocrm-refresh"),
        ):
            with self.subTest(column=column):
                self.assertNotIn(secret, str(raw_column("integration", column, self.integration.id)))

    def test_the_application_still_reads_the_credentials(self):
        reloaded = Integration.objects.get(pk=self.integration.pk)
        self.assertEqual(reloaded.api_token, BOT_TOKEN)
        self.assertEqual(reloaded.refresh_token, "billz-refresh")
        self.assertEqual(reloaded.metadata["refresh_token"], "amocrm-refresh")

    def test_webhook_dispatch_still_resolves_the_bot(self):
        self.assertEqual(Integration.assistant_for_bot_token(BOT_TOKEN), self.assistant)

    def test_group_registration_still_resolves_the_bot(self):
        handle_bot_added_to_group("-100123", "Leads", BOT_TOKEN)
        self.assertTrue(
            TelegramGroupIntegration.objects.filter(
                integration=self.integration, group_id="-100123",
            ).exists()
        )


class IntegrationTokenLeakTests(TestCase):
    def setUp(self):
        self.integration = Integration.objects.create(
            name="Telegram",
            integration_type=IntegrationTypes.TELEGRAM.value,
            api_token=BOT_TOKEN,
            refresh_token="billz-refresh",
        )

    def test_serializer_output_carries_no_token(self):
        data = IntegrationSerializer(self.integration).data
        self.assertNotIn("api_token", data)
        self.assertNotIn(BOT_TOKEN, str(data))

    def test_admin_does_not_expose_the_credentials(self):
        model_admin = IntegrationAdmin(Integration, django_admin.site)
        rendered = [
            field
            for _, options in model_admin.fieldsets
            for field in options["fields"]
        ]
        for name in ("api_token", "refresh_token", "metadata"):
            self.assertNotIn(name, rendered)

    def test_admin_masks_what_it_does_show(self):
        model_admin = IntegrationAdmin(Integration, django_admin.site)
        self.assertEqual(model_admin.api_token_masked(self.integration), f"***{BOT_TOKEN[-4:]}")
        self.assertNotIn(BOT_TOKEN, model_admin.api_token_masked(self.integration))
        self.assertNotIn("billz-refresh", model_admin.refresh_token_masked(self.integration))
        self.integration.metadata = {"refresh_token": "amocrm-refresh"}
        self.assertEqual(model_admin.metadata_keys(self.integration), "refresh_token")

    def test_unknown_bot_token_is_masked_in_the_task_log(self):
        logging.disable(logging.NOTSET)
        self.addCleanup(logging.disable, logging.CRITICAL)

        with self.assertLogs("apps.integration.tasks.telegram", level="WARNING") as logs:
            process_message_task("chat-1", "hi", "9999:UNKNOWN-BOT-TOKEN")

        output = "".join(logs.output)
        self.assertNotIn("9999:UNKNOWN-BOT-TOKEN", output)
        self.assertIn(crypto.mask_secret("9999:UNKNOWN-BOT-TOKEN"), output)

    def test_group_registration_failure_does_not_print_the_token(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            handle_bot_added_to_group("-100999", "Strangers", "9999:UNKNOWN-BOT-TOKEN")

        self.assertNotIn("9999:UNKNOWN-BOT-TOKEN", buffer.getvalue())


class IntegrationTokenLookupRegressionTests(TestCase):
    def test_creating_a_second_integration_with_the_same_token_is_findable(self):
        first = Integration.objects.create(
            name="A", integration_type=IntegrationTypes.TELEGRAM.value, api_token=BOT_TOKEN,
        )
        second = Integration.objects.create(
            name="B", integration_type=IntegrationTypes.TELEGRAM.value, api_token=BOT_TOKEN,
        )
        found = set(Integration.objects.filter(api_token=BOT_TOKEN).values_list("id", flat=True))
        self.assertEqual(found, {first.id, second.id})

    def test_changing_the_token_moves_the_digest(self):
        integration = Integration.objects.create(
            name="A", integration_type=IntegrationTypes.TELEGRAM.value, api_token=BOT_TOKEN,
        )
        integration.api_token = "1111:NEW-TOKEN"
        integration.save()

        self.assertFalse(Integration.objects.filter(api_token=BOT_TOKEN).exists())
        self.assertTrue(Integration.objects.filter(api_token="1111:NEW-TOKEN").exists())

    def test_update_fields_save_still_refreshes_the_digest(self):
        integration = Integration.objects.create(
            name="A", integration_type=IntegrationTypes.TELEGRAM.value, api_token=BOT_TOKEN,
        )
        integration.api_token = "1111:NEW-TOKEN"
        integration.save(update_fields=["api_token"])

        self.assertTrue(Integration.objects.filter(api_token="1111:NEW-TOKEN").exists())

    def test_billz_product_sync_can_still_write_metadata_only(self):
        integration = Integration.objects.create(
            name="Billz", integration_type=IntegrationTypes.BILLZ.value, api_token=BOT_TOKEN,
            metadata={"billz_products_file_id": "f-1"},
        )
        integration.metadata = {"billz_products_file_id": "f-2"}
        integration.save(update_fields=["metadata"])

        reloaded = Integration.objects.get(pk=integration.pk)
        self.assertEqual(reloaded.metadata, {"billz_products_file_id": "f-2"})
        self.assertEqual(reloaded.api_token, BOT_TOKEN)


class TelegramWebhookRegistrationTests(TestCase):
    def test_a_duplicate_bot_token_does_not_raise_multiple_objects_returned(self):
        for name in ("A", "B"):
            Integration.objects.create(
                name=name, integration_type=IntegrationTypes.TELEGRAM.value, api_token=BOT_TOKEN,
            )
        from apps.user.models import User

        owner = User.objects.create(username="enc-owner", auth_type="email")
        assistant = Assistant.objects.create(
            name="S", company_name="C", vector_id="vs_1", user=owner,
        )

        from apps.integration.serializers import IntegrationCreateSerializer

        request = mock.Mock()
        request.user = owner
        serializer = IntegrationCreateSerializer(
            context={"request": request, "base_url": "https://x", "assistant_id": assistant.id},
        )
        with mock.patch.object(serializer, "validate_subscription"), \
                mock.patch("apps.integration.serializers.telegram_get_me", return_value=(True, 200)), \
                mock.patch("apps.integration.serializers.set_telegram_webhook", return_value=200), \
                mock.patch("apps.integration.serializers.get_webhook_info", return_value=200):
            attrs = serializer.validate({
                "integration_type": IntegrationTypes.TELEGRAM.value,
                "api_token": BOT_TOKEN,
            })

        self.assertEqual(attrs["api_token"], BOT_TOKEN)
