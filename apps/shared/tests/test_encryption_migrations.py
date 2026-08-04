"""End-to-end regression tests for the encryption **data migrations**.

`apps/shared/tests/test_crypto.py` proves the cipher and the model fields work.
That is not the same thing as proving that the migrations correctly convert a
table which *already contains plaintext rows* — the one-shot, irreversible step
that runs against production data.

These tests therefore drive the real migration callables
(``0052_encrypt_conversation_and_message_data.encrypt_rows`` and friends), and
one of them drives the real :class:`~django.db.migrations.executor.MigrationExecutor`
over the ``assistant`` migration graph, against rows seeded as raw plaintext.

What is asserted
----------------
======================  ====================================================
Forward                 every seeded row becomes ``v1:…`` in the raw column
                        and decrypts back to the byte-exact original
Reverse                 ``reverse_code`` restores the byte-exact plaintext
Idempotency             a second forward run does not touch a single byte
Batching                a table larger than ``batch_size`` is walked in
                        chunks; no statement selects the whole table
Awkward values          NULL, empty string, Cyrillic / Uzbek text, emoji,
                        embedded quotes and newlines, a 300 KB body, and
                        plaintext that itself starts with ``v1:``
Degradation             a row encrypted under a key we no longer hold is
                        skipped with a warning instead of aborting the run
======================  ====================================================

The ``v1:`` case is the reason this file exists: ``message_content`` is
free-form user input, and a prefix-only "is this already encrypted?" test made
the migration skip those rows and then made every read of them raise.
"""
import uuid
from importlib import import_module

from cryptography.fernet import Fernet
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext

from apps.assistant.models import Assistant, Conversation, Message
from apps.integration.models import Integration
from apps.payment.models import Card
from apps.shared.addons import crypto
from apps.shared.addons.enums import (
    ConversationPlatforms,
    ConversationStatuses,
    IntegrationTypes,
    MessageStatuses,
    MessageTypes,
    SenderTypes,
    UserRoles,
)

ASSISTANT_MIGRATION = import_module(
    "apps.assistant.migrations.0052_encrypt_conversation_and_message_data"
)
INTEGRATION_MIGRATION = import_module(
    "apps.integration.migrations.0045_encrypt_integration_secret_data"
)
PAYMENT_MIGRATION = import_module(
    "apps.payment.migrations.0022_encrypt_card_token_data"
)

#: State the `assistant` graph is rewound to — the commit before encryption.
ASSISTANT_BEFORE = "0050_conversation_conv_assistant_user_token_idx"
ASSISTANT_AFTER = "0052_encrypt_conversation_and_message_data"

#: The values that break naive implementations, keyed by a readable label.
AWKWARD_TEXT = {
    "empty": "",
    "plain": "Salom, narxlar qanday?",
    "cyrillic": "Здравствуйте! Меня зовут Ўзбек. Нархлар қандай?",
    "latin_uz": "O'tkirbek G'aniyev — narx 1 200 000 so'm",
    "emoji": "Rahmat! 🇺🇿😀👍",
    "looks_encrypted": "v1:gAAAAA-but-not-really-a-token",
    "bare_prefix": "v1:",
    "quotes_newlines": "He said: 'hi'\nShe said: \"bye\"\\n literal\ttab",
    "json_like": '{"a": 1, "b": [null, true]}',
    "long": "Assalomu alaykum, qanday yordam bera olaman? " * 5000,
}


class _MigrationFixtureMixin:
    """Seeds the encrypted tables with raw plaintext, bypassing the fields."""

    def raw(self, table, column, pk):
        quote = connection.ops.quote_name
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {quote(column)} FROM {quote(table)} WHERE id = %s", [str(pk)]
            )
            return cursor.fetchone()[0]

    def raw_json(self, table, column, pk):
        quote = connection.ops.quote_name
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {quote(column)}::text FROM {quote(table)} WHERE id = %s", [str(pk)]
            )
            return cursor.fetchone()[0]

    def execute(self, sql, params=None):
        with connection.cursor() as cursor:
            cursor.execute(sql, params or [])

    def seed_assistant(self):
        """An `assistant` row, created with raw SQL so it survives a rewind."""
        assistant_id = uuid.uuid4()
        self.execute(
            "INSERT INTO assistant (id, created_time, updated_time, name, company_name,"
            " role, personality_style, is_active, ai_enabled, web_search_tool)"
            " VALUES (%s, now(), now(), 'Enc', 'Enc Co', 'sales', 'formal', true, true, false)",
            [str(assistant_id)],
        )
        return assistant_id

    def seed_conversation(self, assistant_id, full_name=None, contact=None):
        conversation_id = uuid.uuid4()
        self.execute(
            "INSERT INTO conversation (id, created_time, updated_time, status, start_time,"
            " assistant_id, platform, client_full_name, client_phone_email)"
            " VALUES (%s, now(), now(), %s, now(), %s, %s, %s, %s)",
            [
                str(conversation_id),
                ConversationStatuses.OPEN.value,
                str(assistant_id),
                ConversationPlatforms.TELEGRAM.value,
                full_name,
                contact,
            ],
        )
        return conversation_id

    def seed_message(self, conversation_id, content):
        message_id = uuid.uuid4()
        self.execute(
            "INSERT INTO messages (id, created_time, updated_time, sender, message_content,"
            " message_type, status, conversation_id, input_tokens, output_tokens, is_read)"
            " VALUES (%s, now(), now(), %s, %s, %s, %s, %s, 0, 0, false)",
            [
                str(message_id),
                SenderTypes.USER.value,
                content,
                MessageTypes.TEXT.value,
                MessageStatuses.DELIVERED.value,
                str(conversation_id),
            ],
        )
        return message_id


class MigrationExecutorRoundTripTests(_MigrationFixtureMixin, TransactionTestCase):
    """Drive the real migration graph over rows that already hold plaintext.

    The `assistant` graph is rewound to the state before encryption, seeded
    with plaintext through raw SQL, then migrated forward and backward with
    :class:`MigrationExecutor` — the same code path a deploy runs.

    Rewinding also unapplies `integration.0044/0045`, which drops
    `integration.api_token_hash`. Nothing in this class may touch the
    `Integration` model while the graph is rewound; the cleanup puts the whole
    graph back before anything else runs.
    """

    available_apps = None

    def setUp(self):
        self.addCleanup(self.migrate_to_latest)

    @staticmethod
    def _executor():
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        return executor

    def migrate(self, targets):
        executor = self._executor()
        executor.migrate(targets)

    def migrate_to_latest(self):
        executor = self._executor()
        targets = executor.loader.graph.leaf_nodes()
        executor.migrate(targets)

    def test_forward_reverse_and_idempotency_over_pre_existing_plaintext(self):
        self.migrate([("assistant", ASSISTANT_BEFORE)])

        assistant_id = self.seed_assistant()
        conversation_id = self.seed_conversation(
            assistant_id,
            full_name="Аҳмадов Жасурбек Ўткирович",
            contact="v1:+998900000000",
        )
        # NULL and empty must survive untouched.
        null_conversation = self.seed_conversation(assistant_id)
        empty_conversation = self.seed_conversation(assistant_id, full_name="", contact="")
        messages = {
            label: self.seed_message(conversation_id, value)
            for label, value in AWKWARD_TEXT.items()
        }

        # --- forward -----------------------------------------------------
        self.migrate([("assistant", ASSISTANT_AFTER)])

        self.assertTrue(
            crypto.is_encrypted(self.raw("conversation", "client_full_name", conversation_id))
        )
        self.assertTrue(
            crypto.is_encrypted(self.raw("conversation", "client_phone_email", conversation_id))
        )
        self.assertIsNone(self.raw("conversation", "client_full_name", null_conversation))
        self.assertEqual(self.raw("conversation", "client_full_name", empty_conversation), "")

        for label, value in AWKWARD_TEXT.items():
            with self.subTest(label=label):
                stored = self.raw("messages", "message_content", messages[label])
                if value == "":
                    self.assertEqual(stored, "")
                else:
                    self.assertTrue(crypto.is_encrypted(stored), f"{label} was left in plaintext")
                    body = stored[len(crypto.VERSION_PREFIX):]
                    self.assertNotIn(value, body)
                self.assertEqual(
                    Message.objects.get(pk=messages[label]).message_content, value
                )

        reloaded = Conversation.objects.get(pk=conversation_id)
        self.assertEqual(reloaded.client_full_name, "Аҳмадов Жасурбек Ўткирович")
        self.assertEqual(reloaded.client_phone_email, "v1:+998900000000")

        # --- idempotency: a re-run must not touch a byte -------------------
        snapshot = {
            label: self.raw("messages", "message_content", pk) for label, pk in messages.items()
        }
        ASSISTANT_MIGRATION.encrypt_rows(None, connection.schema_editor())
        for label, pk in messages.items():
            with self.subTest(label=label):
                self.assertEqual(self.raw("messages", "message_content", pk), snapshot[label])

        # --- reverse: byte-for-byte plaintext ------------------------------
        self.migrate([("assistant", ASSISTANT_BEFORE)])

        self.assertEqual(
            self.raw("conversation", "client_full_name", conversation_id),
            "Аҳмадов Жасурбек Ўткирович",
        )
        self.assertEqual(
            self.raw("conversation", "client_phone_email", conversation_id),
            "v1:+998900000000",
        )
        for label, value in AWKWARD_TEXT.items():
            with self.subTest(label=label):
                self.assertEqual(self.raw("messages", "message_content", messages[label]), value)

    def test_char_columns_become_text_so_ciphertext_cannot_be_truncated(self):
        """A 255-char name encrypts to ~460 chars; varchar(255) would truncate."""
        self.migrate([("assistant", ASSISTANT_BEFORE)])
        assistant_id = self.seed_assistant()
        long_name = "Ж" * 255
        conversation_id = self.seed_conversation(assistant_id, full_name=long_name)

        self.migrate([("assistant", ASSISTANT_AFTER)])

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT data_type, character_maximum_length FROM information_schema.columns"
                " WHERE table_name = 'conversation' AND column_name = 'client_full_name'"
            )
            data_type, max_length = cursor.fetchone()
        self.assertEqual(data_type, "text")
        self.assertIsNone(max_length)
        self.assertEqual(Conversation.objects.get(pk=conversation_id).client_full_name, long_name)


class DataMigrationCallableTests(_MigrationFixtureMixin, TransactionTestCase):
    """The `RunPython` callables themselves, run against seeded plaintext.

    Cheaper than rewinding the graph, so this is where the per-table detail
    (jsonb, the hash backfill, the Payme card token, batching, degradation)
    lives.
    """

    def schema_editor(self):
        return connection.schema_editor()

    # -- integration -------------------------------------------------------

    def _seed_integration(self, **columns):
        integration_id = uuid.uuid4()
        self.execute(
            "INSERT INTO integration (id, created_time, updated_time, name, is_active,"
            " api_token, refresh_token, metadata, integration_type, is_comment_response)"
            " VALUES (%s, now(), now(), 'bot', true, %s, %s, %s::jsonb, %s, false)",
            [
                str(integration_id),
                columns.get("api_token"),
                columns.get("refresh_token"),
                columns.get("metadata"),
                IntegrationTypes.TELEGRAM.value,
            ],
        )
        return integration_id

    def test_integration_secrets_and_hash_backfill(self):
        token = "8012345678:AAH-legacy-plaintext-token"
        rows = {
            "normal": self._seed_integration(
                api_token=token, refresh_token="refresh-1", metadata='{"subdomain": "acme"}'
            ),
            "null": self._seed_integration(),
            "empty": self._seed_integration(api_token="", refresh_token=""),
            "looks_encrypted": self._seed_integration(
                api_token="v1:not-a-token", metadata='"v1:also-not-a-token"'
            ),
            "json_null": self._seed_integration(metadata="null"),
            "unicode": self._seed_integration(api_token="токен-Ўзбекистон-🇺🇿"),
        }

        INTEGRATION_MIGRATION.encrypt_rows(None, self.schema_editor())

        self.assertTrue(crypto.is_encrypted(self.raw("integration", "api_token", rows["normal"])))
        self.assertIsNone(self.raw("integration", "api_token", rows["null"]))
        self.assertEqual(self.raw("integration", "api_token", rows["empty"]), "")

        # Every row must still read back exactly, including the two that only
        # look like ciphertext.
        self.assertEqual(Integration.objects.get(pk=rows["normal"]).api_token, token)
        self.assertEqual(Integration.objects.get(pk=rows["normal"]).metadata, {"subdomain": "acme"})
        self.assertEqual(
            Integration.objects.get(pk=rows["looks_encrypted"]).api_token, "v1:not-a-token"
        )
        self.assertEqual(
            Integration.objects.get(pk=rows["looks_encrypted"]).metadata, "v1:also-not-a-token"
        )
        self.assertIsNone(Integration.objects.get(pk=rows["json_null"]).metadata)
        self.assertEqual(
            Integration.objects.get(pk=rows["unicode"]).api_token, "токен-Ўзбекистон-🇺🇿"
        )

        # The hash backfill is what keeps inbound Telegram webhooks resolving.
        self.assertEqual(
            self.raw("integration", "api_token_hash", rows["normal"]), crypto.hash_secret(token)
        )
        self.assertEqual(Integration.objects.filter(api_token=token).count(), 1)

        INTEGRATION_MIGRATION.decrypt_rows(None, self.schema_editor())

        self.assertEqual(self.raw("integration", "api_token", rows["normal"]), token)
        self.assertEqual(self.raw("integration", "refresh_token", rows["normal"]), "refresh-1")
        self.assertEqual(
            self.raw("integration", "api_token", rows["looks_encrypted"]), "v1:not-a-token"
        )
        self.assertEqual(self.raw_json("integration", "metadata", rows["json_null"]), "null")

    def test_a_row_encrypted_under_a_lost_key_is_skipped_not_fatal(self):
        """One unreadable row must not abort the rewrite of a million others."""
        foreign = crypto.VERSION_PREFIX + Fernet(Fernet.generate_key()).encrypt(b"x").decode()
        poisoned = self._seed_integration(api_token=foreign)
        healthy = self._seed_integration(api_token="plain-token")

        INTEGRATION_MIGRATION.encrypt_rows(None, self.schema_editor())

        self.assertEqual(self.raw("integration", "api_token", poisoned), foreign)
        self.assertIsNone(self.raw("integration", "api_token_hash", poisoned))
        self.assertTrue(crypto.is_encrypted(self.raw("integration", "api_token", healthy)))
        self.assertEqual(
            self.raw("integration", "api_token_hash", healthy), crypto.hash_secret("plain-token")
        )

    # -- payment -----------------------------------------------------------

    def test_card_tokens_round_trip(self):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create(
            username="cardholder",
            phone_number="+998900000009",
            user_role=UserRoles.CUSTOMER.value,
        )
        tokens = {
            "normal": "5e9f8a7b6c5d4e3f2a1b0c9d",
            "looks_encrypted": "v1:not-a-token",
            "unicode": "карта-токен-Ўзбек",
            "quotes": "tok'en\"with\nnewline",
        }
        rows = {}
        for label, value in tokens.items():
            card_id = uuid.uuid4()
            self.execute(
                'INSERT INTO "Card" (id, created_time, updated_time, card_token, card_number,'
                " expiry_date, is_verified, is_default, user_id)"
                " VALUES (%s, now(), now(), %s, '8600123412341234', '12/30', true, false, %s)",
                [str(card_id), value, str(user.id)],
            )
            rows[label] = card_id

        PAYMENT_MIGRATION.encrypt_rows(None, self.schema_editor())

        for label, value in tokens.items():
            with self.subTest(label=label):
                self.assertTrue(crypto.is_encrypted(self.raw("Card", "card_token", rows[label])))
                self.assertEqual(Card.objects.get(pk=rows[label]).card_token, value)

        PAYMENT_MIGRATION.decrypt_rows(None, self.schema_editor())

        for label, value in tokens.items():
            with self.subTest(label=label):
                self.assertEqual(self.raw("Card", "card_token", rows[label]), value)

    # -- batching ----------------------------------------------------------

    def test_the_table_is_walked_in_chunks_never_loaded_whole(self):
        """`messages` holds every conversation turn — one big SELECT is not an option."""
        assistant_id = self.seed_assistant()
        conversation_id = self.seed_conversation(assistant_id)
        for index in range(7):
            self.seed_message(conversation_id, f"order {index}")

        with CaptureQueriesContext(connection) as captured:
            crypto.encrypt_table_columns(
                connection, "messages", ["message_content"], batch_size=2
            )

        selects = [q["sql"] for q in captured.captured_queries if q["sql"].startswith("SELECT")]
        # 7 rows / 2 per batch = 4 pages, plus the empty page that ends the walk.
        self.assertEqual(len(selects), 5)
        for sql in selects:
            self.assertIn("LIMIT", sql)
            self.assertIn('"id" >', sql)

        for index in range(7):
            self.assertEqual(
                Message.objects.filter(conversation_id=conversation_id)
                .order_by("created_time")[index]
                .message_content,
                f"order {index}",
            )

    def test_a_conversation_with_no_pii_is_left_alone(self):
        assistant_id = self.seed_assistant()
        conversation_id = self.seed_conversation(assistant_id)

        with CaptureQueriesContext(connection) as captured:
            ASSISTANT_MIGRATION.encrypt_rows(None, self.schema_editor())

        self.assertFalse(
            [q for q in captured.captured_queries if q["sql"].startswith("UPDATE")],
            "a table of NULLs must not be rewritten",
        )
        self.assertIsNone(Conversation.objects.get(pk=conversation_id).client_full_name)

    def test_assistant_migration_handles_a_300kb_message_body(self):
        assistant_id = self.seed_assistant()
        conversation_id = self.seed_conversation(assistant_id)
        body = AWKWARD_TEXT["long"]
        message_id = self.seed_message(conversation_id, body)

        ASSISTANT_MIGRATION.encrypt_rows(None, self.schema_editor())

        self.assertTrue(crypto.is_encrypted(self.raw("messages", "message_content", message_id)))
        self.assertEqual(Message.objects.get(pk=message_id).message_content, body)

        ASSISTANT_MIGRATION.decrypt_rows(None, self.schema_editor())

        self.assertEqual(self.raw("messages", "message_content", message_id), body)

    def test_migrations_declare_themselves_non_atomic_and_reversible(self):
        """`atomic = False` is what makes a long run resumable and lock-friendly."""
        for module in (ASSISTANT_MIGRATION, INTEGRATION_MIGRATION, PAYMENT_MIGRATION):
            with self.subTest(module=module.__name__):
                self.assertFalse(module.Migration.atomic)
                operation = module.Migration.operations[0]
                self.assertIsNotNone(operation.reverse_code)


class OrmWriteAfterMigrationTests(_MigrationFixtureMixin, TransactionTestCase):
    """The application must keep serving while the table is half converted."""

    def test_mixed_plaintext_and_ciphertext_rows_all_read(self):
        assistant = Assistant.objects.create(name="A", company_name="C")
        conversation = Conversation.objects.create(assistant=assistant)
        encrypted = Message.objects.create(
            conversation=conversation,
            sender=SenderTypes.USER.value,
            message_content="written after the deploy",
        )
        legacy = self.seed_message(conversation.id, "written before the deploy")

        self.assertEqual(
            Message.objects.get(pk=legacy).message_content, "written before the deploy"
        )
        self.assertEqual(
            Message.objects.get(pk=encrypted.pk).message_content, "written after the deploy"
        )

        crypto.encrypt_table_columns(connection, "messages", ["message_content"])

        self.assertEqual(
            Message.objects.get(pk=legacy).message_content, "written before the deploy"
        )
        self.assertEqual(
            Message.objects.get(pk=encrypted.pk).message_content, "written after the deploy"
        )
