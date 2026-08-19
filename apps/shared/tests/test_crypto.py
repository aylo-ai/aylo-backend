import logging
from unittest import mock

from cryptography.fernet import Fernet
from django.core.exceptions import FieldError, ImproperlyConfigured
from django.db import connection
from django.test import TestCase, override_settings

from apps.assistant.models import Assistant, Conversation, Message
from apps.integration.models import Integration
from apps.shared.addons import crypto
from apps.shared.addons.enums import IntegrationTypes, SenderTypes
from apps.shared.fields import EncryptedCharField, EncryptedTextField

BOT_TOKEN = "8012345678:AAH-super-secret-telegram-bot-token"


def raw_column(table, column, pk):
    with connection.cursor() as cursor:
        cursor.execute(
            f'SELECT {connection.ops.quote_name(column)} '
            f'FROM {connection.ops.quote_name(table)} WHERE id = %s',
            [str(pk)],
        )
        return cursor.fetchone()[0]


def write_raw_column(table, column, pk, value):
    with connection.cursor() as cursor:
        cursor.execute(
            f'UPDATE {connection.ops.quote_name(table)} '
            f'SET {connection.ops.quote_name(column)} = %s WHERE id = %s',
            [value, str(pk)],
        )


class EncryptDecryptTests(TestCase):
    def test_round_trip(self):
        self.assertEqual(crypto.decrypt(crypto.encrypt(BOT_TOKEN)), BOT_TOKEN)

    def test_ciphertext_is_not_the_plaintext(self):
        token = crypto.encrypt(BOT_TOKEN)
        self.assertNotEqual(token, BOT_TOKEN)
        self.assertNotIn(BOT_TOKEN, token)
        self.assertTrue(token.startswith(crypto.VERSION_PREFIX))

    def test_same_plaintext_encrypts_differently_every_time(self):
        self.assertNotEqual(crypto.encrypt(BOT_TOKEN), crypto.encrypt(BOT_TOKEN))

    def test_empty_and_null_pass_through(self):
        self.assertIsNone(crypto.encrypt(None))
        self.assertEqual(crypto.encrypt(""), "")
        self.assertIsNone(crypto.decrypt(None))
        self.assertEqual(crypto.decrypt(""), "")

    def test_unicode_survives_the_round_trip(self):
        value = "Ассалому алайкум — narx 1 200 000 so'm 🙂"
        self.assertEqual(crypto.decrypt(crypto.encrypt(value)), value)

    def test_legacy_plaintext_is_returned_unchanged(self):
        self.assertEqual(crypto.decrypt(BOT_TOKEN), BOT_TOKEN)
        self.assertFalse(crypto.is_encrypted(BOT_TOKEN))

    def test_tampered_ciphertext_fails_closed(self):
        token = crypto.encrypt(BOT_TOKEN)
        body = token[len(crypto.VERSION_PREFIX):]
        tampered = crypto.VERSION_PREFIX + body[:20] + ("A" if body[20] != "A" else "B") + body[21:]

        with self.assertRaises(crypto.DecryptionError):
            crypto.decrypt(tampered)

    def test_truncated_ciphertext_fails_closed(self):
        token = crypto.encrypt(BOT_TOKEN)
        for cut in (1, 6, 12, 20):
            with self.subTest(cut=cut):
                with self.assertRaises(crypto.DecryptionError):
                    crypto.decrypt(token[:-cut])

    def test_decryption_failure_never_logs_the_token(self):
        logging.disable(logging.NOTSET)
        self.addCleanup(logging.disable, logging.CRITICAL)

        token = crypto.encrypt(BOT_TOKEN)
        with self.assertLogs("apps.shared.addons.crypto", level="ERROR") as logs:
            with self.assertRaises(crypto.DecryptionError):
                crypto.decrypt(token[:-6])
        self.assertNotIn(token[:40], "".join(logs.output))


class CiphertextOrPlaintextBoundaryTests(TestCase):
    def setUp(self):
        self.token = crypto.encrypt(BOT_TOKEN)

    def test_intact_ciphertext_round_trips(self):
        self.assertTrue(crypto.is_encrypted(self.token))
        self.assertEqual(crypto.decrypt(self.token), BOT_TOKEN)

    def test_tampered_in_place_fails_loud(self):
        body = self.token[len(crypto.VERSION_PREFIX):]
        tampered = crypto.VERSION_PREFIX + body[:20] + ("A" if body[20] != "A" else "B") + body[21:]

        self.assertTrue(crypto.is_encrypted(tampered))
        with self.assertRaises(crypto.DecryptionError):
            crypto.decrypt(tampered)

    def test_truncated_ciphertext_fails_loud_not_open(self):
        truncated = self.token[:-6]

        self.assertTrue(crypto.is_encrypted(truncated))
        with self.assertRaises(crypto.DecryptionError):
            crypto.decrypt(truncated)

    def test_prefixed_human_text_is_plaintext(self):
        for value in ("v1:", "v1:notbase64!!", "v1:hello world", "v1:Ivan",
                      "v1:gAAAAA-but-not-really"):
            with self.subTest(value=value):
                self.assertFalse(crypto.is_encrypted(value))
                self.assertEqual(crypto.decrypt(value), value)
                self.assertEqual(crypto.decrypt(crypto.encrypt(value)), value)

    def test_a_token_under_a_retired_key_fails_loud(self):
        foreign = crypto.VERSION_PREFIX + Fernet(Fernet.generate_key()).encrypt(b"x").decode()

        self.assertTrue(crypto.is_encrypted(foreign))
        with self.assertRaises(crypto.DecryptionError):
            crypto.decrypt(foreign)

    def test_severe_damage_is_indistinguishable_from_plaintext(self):
        wrecked = self.token[: len(self.token) // 2]

        self.assertFalse(crypto.is_encrypted(wrecked))
        self.assertEqual(crypto.decrypt(wrecked), wrecked)

    def test_missing_keys_raise_improperly_configured(self):
        with override_settings(FIELD_ENCRYPTION_KEYS=[]):
            with self.assertRaises(ImproperlyConfigured):
                crypto.encrypt("x")

    def test_dev_key_derived_from_secret_key_is_a_valid_fernet_key(self):
        key = crypto.derive_key_from_secret("some-secret")
        self.assertEqual(key, crypto.derive_key_from_secret("some-secret"))
        Fernet(key)


class KeyRotationTests(TestCase):
    def setUp(self):
        self.old_key = Fernet.generate_key().decode()
        self.new_key = Fernet.generate_key().decode()

    def test_value_encrypted_with_the_old_key_still_decrypts_after_rotation(self):
        with override_settings(FIELD_ENCRYPTION_KEYS=[self.old_key]):
            token = crypto.encrypt(BOT_TOKEN)

        with override_settings(FIELD_ENCRYPTION_KEYS=[self.new_key, self.old_key]):
            self.assertEqual(crypto.decrypt(token), BOT_TOKEN)

    def test_new_writes_use_the_first_key(self):
        with override_settings(FIELD_ENCRYPTION_KEYS=[self.new_key, self.old_key]):
            token = crypto.encrypt(BOT_TOKEN)

        with override_settings(FIELD_ENCRYPTION_KEYS=[self.new_key]):
            self.assertEqual(crypto.decrypt(token), BOT_TOKEN)

    def test_retiring_a_key_that_is_still_in_use_fails_closed(self):
        with override_settings(FIELD_ENCRYPTION_KEYS=[self.old_key]):
            token = crypto.encrypt(BOT_TOKEN)

        with override_settings(FIELD_ENCRYPTION_KEYS=[self.new_key]):
            with self.assertRaises(crypto.DecryptionError):
                crypto.decrypt(token)


class MaskSecretTests(TestCase):
    def test_reveals_only_the_kept_suffix(self):
        self.assertEqual(crypto.mask_secret(BOT_TOKEN), f"***{BOT_TOKEN[-4:]}")
        self.assertNotIn(BOT_TOKEN[:-4], crypto.mask_secret(BOT_TOKEN))

    def test_short_secret_reveals_nothing(self):
        self.assertEqual(crypto.mask_secret("abcd"), "***")
        self.assertEqual(crypto.mask_secret("ab"), "***")

    def test_empty_values_are_safe(self):
        self.assertEqual(crypto.mask_secret(None), "***")
        self.assertEqual(crypto.mask_secret(""), "***")

    def test_mask_does_not_leak_the_length(self):
        short = crypto.mask_secret("aaaaaaaaXYZW")
        long = crypto.mask_secret("a" * 400 + "XYZW")
        self.assertEqual(short, long)

    def test_keep_is_configurable(self):
        self.assertEqual(crypto.mask_secret("0123456789", keep=2), "***89")


class HashSecretTests(TestCase):
    def test_is_deterministic(self):
        self.assertEqual(crypto.hash_secret(BOT_TOKEN), crypto.hash_secret(BOT_TOKEN))

    def test_differs_per_value_and_hides_the_plaintext(self):
        digest = crypto.hash_secret(BOT_TOKEN)
        self.assertNotEqual(digest, crypto.hash_secret(BOT_TOKEN + "x"))
        self.assertNotIn(BOT_TOKEN, digest)
        self.assertEqual(len(digest), crypto.HASH_HEX_LENGTH)

    def test_is_keyed(self):
        with override_settings(FIELD_ENCRYPTION_HASH_KEY="key-one"):
            first = crypto.hash_secret(BOT_TOKEN)
        with override_settings(FIELD_ENCRYPTION_HASH_KEY="key-two"):
            self.assertNotEqual(crypto.hash_secret(BOT_TOKEN), first)

    def test_empty_values_hash_to_none(self):
        self.assertIsNone(crypto.hash_secret(None))
        self.assertIsNone(crypto.hash_secret(""))


class EncryptedFieldTests(TestCase):
    def setUp(self):
        self.integration = Integration.objects.create(
            name="Sales bot",
            integration_type=IntegrationTypes.TELEGRAM.value,
            api_token=BOT_TOKEN,
            refresh_token="refresh-abc",
        )

    def test_the_database_never_sees_the_plaintext(self):
        stored = raw_column("integration", "api_token", self.integration.id)
        self.assertTrue(stored.startswith(crypto.VERSION_PREFIX))
        self.assertNotIn(BOT_TOKEN, stored)
        self.assertNotIn("refresh-abc", raw_column("integration", "refresh_token", self.integration.id))

    def test_reads_come_back_decrypted(self):
        reloaded = Integration.objects.get(pk=self.integration.pk)
        self.assertEqual(reloaded.api_token, BOT_TOKEN)
        self.assertEqual(reloaded.refresh_token, "refresh-abc")

    def test_values_list_is_decrypted_too(self):
        self.assertEqual(
            list(Integration.objects.filter(pk=self.integration.pk).values_list("api_token", flat=True)),
            [BOT_TOKEN],
        )

    def test_legacy_plaintext_row_reads_back_unchanged(self):
        write_raw_column("integration", "api_token", self.integration.id, "legacy-plain-token")

        reloaded = Integration.objects.get(pk=self.integration.pk)
        self.assertEqual(reloaded.api_token, "legacy-plain-token")

    def test_resaving_a_legacy_row_encrypts_it(self):
        write_raw_column("integration", "api_token", self.integration.id, "legacy-plain-token")

        reloaded = Integration.objects.get(pk=self.integration.pk)
        reloaded.save()

        self.assertTrue(
            raw_column("integration", "api_token", self.integration.id).startswith(crypto.VERSION_PREFIX)
        )

    def test_null_stays_null(self):
        integration = Integration.objects.create(
            name="No token", integration_type=IntegrationTypes.INSTAGRAM.value,
        )
        self.assertIsNone(raw_column("integration", "api_token", integration.id))
        self.assertIsNone(Integration.objects.get(pk=integration.pk).api_token)

    def test_undecryptable_row_raises_instead_of_returning_ciphertext(self):
        foreign = crypto.VERSION_PREFIX + Fernet(Fernet.generate_key()).encrypt(b"x").decode()
        write_raw_column("integration", "api_token", self.integration.id, foreign)

        with self.assertRaises(crypto.DecryptionError):
            Integration.objects.get(pk=self.integration.pk)

    def test_plaintext_token_starting_with_the_prefix_still_reads(self):
        write_raw_column("integration", "api_token", self.integration.id, "v1:legacy-token")

        reloaded = Integration.objects.get(pk=self.integration.pk)
        self.assertEqual(reloaded.api_token, "v1:legacy-token")

    def test_json_field_is_encrypted_but_still_a_dict(self):
        self.integration.metadata = {"refresh_token": "amocrm-refresh", "subdomain": "acme"}
        self.integration.save()

        stored = raw_column("integration", "metadata", self.integration.id)
        self.assertNotIn("amocrm-refresh", str(stored))

        reloaded = Integration.objects.get(pk=self.integration.pk)
        self.assertEqual(reloaded.metadata["refresh_token"], "amocrm-refresh")
        self.assertEqual(reloaded.metadata["subdomain"], "acme")

    def test_legacy_plaintext_json_still_reads(self):
        write_raw_column("integration", "metadata", self.integration.id, '{"subdomain": "acme"}')
        self.assertEqual(Integration.objects.get(pk=self.integration.pk).metadata, {"subdomain": "acme"})

    def test_char_field_column_is_text_so_ciphertext_fits(self):
        field = Conversation._meta.get_field("client_full_name")
        self.assertIsInstance(field, EncryptedCharField)
        self.assertEqual(field.db_type(connection), "text")

    def test_char_field_stores_a_full_length_value(self):
        assistant = Assistant.objects.create(name="A", company_name="C")
        conversation = Conversation.objects.create(assistant=assistant, client_full_name="x" * 255)
        self.assertEqual(Conversation.objects.get(pk=conversation.pk).client_full_name, "x" * 255)


class EncryptedLookupTests(TestCase):
    def setUp(self):
        self.integration = Integration.objects.create(
            name="Sales bot",
            integration_type=IntegrationTypes.TELEGRAM.value,
            api_token=BOT_TOKEN,
        )

    def test_hash_column_is_maintained_on_save(self):
        self.assertEqual(
            raw_column("integration", "api_token_hash", self.integration.id),
            crypto.hash_secret(BOT_TOKEN),
        )

    def test_filter_by_plaintext_token_is_rewritten_onto_the_hash(self):
        self.assertEqual(
            Integration.objects.filter(api_token=BOT_TOKEN).first(), self.integration,
        )
        self.assertEqual(
            Integration.objects.get(api_token=BOT_TOKEN, integration_type=IntegrationTypes.TELEGRAM.value),
            self.integration,
        )

    def test_filter_by_a_different_token_matches_nothing(self):
        self.assertFalse(Integration.objects.filter(api_token="someone-elses-token").exists())

    def test_exclude_and_q_objects_are_rewritten_too(self):
        from django.db.models import Q

        self.assertFalse(Integration.objects.exclude(api_token=BOT_TOKEN).exists())
        self.assertTrue(Integration.objects.filter(Q(api_token=BOT_TOKEN)).exists())

    def test_assistant_for_bot_token(self):
        assistant = Assistant.objects.create(name="A", company_name="C")
        self.integration.assistant = assistant
        self.integration.save()

        self.assertEqual(Integration.assistant_for_bot_token(BOT_TOKEN), assistant)
        self.assertIsNone(Integration.assistant_for_bot_token("nope"))

    def test_encrypted_column_without_a_hash_refuses_to_be_queried(self):
        with self.assertRaises(FieldError):
            list(Message.objects.filter(message_content="hello"))

    def test_substring_search_on_an_encrypted_column_raises(self):
        with self.assertRaises(FieldError):
            list(Conversation.objects.filter(client_full_name__icontains="ali"))

    def test_json_key_transform_on_an_encrypted_column_raises(self):
        with self.assertRaises(FieldError):
            list(Integration.objects.filter(metadata__subdomain="acme"))

    def test_isnull_still_works(self):
        Integration.objects.create(name="No token", integration_type=IntegrationTypes.INSTAGRAM.value)
        self.assertEqual(Integration.objects.filter(api_token__isnull=True).count(), 1)


class DataMigrationHelperTests(TestCase):
    def setUp(self):
        self.assistant = Assistant.objects.create(name="A", company_name="C")
        self.conversation = Conversation.objects.create(assistant=self.assistant)

    def _plaintext_messages(self, count):
        messages = []
        for index in range(count):
            message = Message.objects.create(
                conversation=self.conversation,
                sender=SenderTypes.USER.value,
                message_content=f"order {index}",
            )
            write_raw_column("messages", "message_content", message.id, f"order {index}")
            messages.append(message)
        return messages

    def test_encrypts_every_row_across_several_batches(self):
        messages = self._plaintext_messages(7)

        crypto.encrypt_table_columns(connection, "messages", ["message_content"], batch_size=2)

        for index, message in enumerate(messages):
            self.assertTrue(
                raw_column("messages", "message_content", message.id).startswith(crypto.VERSION_PREFIX)
            )
            self.assertEqual(
                Message.objects.get(pk=message.pk).message_content, f"order {index}",
            )

    def test_is_idempotent(self):
        messages = self._plaintext_messages(3)
        crypto.encrypt_table_columns(connection, "messages", ["message_content"], batch_size=2)
        before = raw_column("messages", "message_content", messages[0].id)

        crypto.encrypt_table_columns(connection, "messages", ["message_content"], batch_size=2)

        self.assertEqual(raw_column("messages", "message_content", messages[0].id), before)

    def test_reverse_restores_plaintext(self):
        messages = self._plaintext_messages(3)
        crypto.encrypt_table_columns(connection, "messages", ["message_content"], batch_size=2)

        crypto.decrypt_table_columns(connection, "messages", ["message_content"], batch_size=2)

        self.assertEqual(raw_column("messages", "message_content", messages[0].id), "order 0")

    def test_json_column_round_trip(self):
        integration = Integration.objects.create(
            name="amoCRM", integration_type=IntegrationTypes.AMOCRM.value,
        )
        write_raw_column("integration", "metadata", integration.id, '{"refresh_token": "r-1"}')

        crypto.encrypt_table_columns(connection, "integration", json_columns=["metadata"])
        self.assertNotIn("r-1", str(raw_column("integration", "metadata", integration.id)))
        self.assertEqual(Integration.objects.get(pk=integration.pk).metadata, {"refresh_token": "r-1"})

        crypto.decrypt_table_columns(connection, "integration", json_columns=["metadata"])
        self.assertIn("r-1", str(raw_column("integration", "metadata", integration.id)))

    def test_hash_backfill_works_on_plaintext_and_ciphertext(self):
        integration = Integration.objects.create(
            name="Bot", integration_type=IntegrationTypes.TELEGRAM.value, api_token=BOT_TOKEN,
        )
        write_raw_column("integration", "api_token", integration.id, BOT_TOKEN)
        write_raw_column("integration", "api_token_hash", integration.id, None)

        crypto.backfill_hash_column(connection, "integration", "api_token", "api_token_hash")
        self.assertEqual(
            raw_column("integration", "api_token_hash", integration.id),
            crypto.hash_secret(BOT_TOKEN),
        )

        crypto.encrypt_table_columns(connection, "integration", ["api_token"])
        crypto.backfill_hash_column(connection, "integration", "api_token", "api_token_hash")
        self.assertEqual(
            raw_column("integration", "api_token_hash", integration.id),
            crypto.hash_secret(BOT_TOKEN),
        )

    def test_batches_do_not_load_the_whole_table(self):
        self._plaintext_messages(5)

        with mock.patch.object(
            connection, "cursor", wraps=connection.cursor
        ) as cursor:
            crypto.encrypt_table_columns(connection, "messages", ["message_content"], batch_size=2)

        self.assertGreaterEqual(cursor.call_count, 6)


class EncryptedFieldDefinitionTests(TestCase):
    def test_expected_columns_use_encrypted_fields(self):
        from apps.payment.models import Card

        expected = [
            (Integration, "api_token", EncryptedTextField),
            (Integration, "refresh_token", EncryptedTextField),
            (Card, "card_token", EncryptedTextField),
            (Message, "message_content", EncryptedTextField),
            (Conversation, "client_full_name", EncryptedCharField),
            (Conversation, "client_phone_email", EncryptedCharField),
        ]
        for model, name, field_class in expected:
            with self.subTest(field=f"{model.__name__}.{name}"):
                self.assertIsInstance(model._meta.get_field(name), field_class)
