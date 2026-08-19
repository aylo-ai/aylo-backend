from django.contrib import admin as django_admin
from django.test import TestCase

from apps.assistant.admin import ConversationAdmin
from apps.assistant.models import Assistant, Conversation, Message
from apps.shared.addons.enums import SenderTypes
from apps.shared.tests.test_crypto import raw_column

SECRET_MESSAGE = "Manzil: Chilonzor 12-uy, karta 8600 1234 5678 9012"
BOT_TOKEN = "8012345678:AAH-super-secret-telegram-bot-token"


class ConversationEncryptionTests(TestCase):
    def setUp(self):
        self.assistant = Assistant.objects.create(name="Sales", company_name="Acme")
        self.conversation = Conversation.objects.create(
            assistant=self.assistant,
            token=BOT_TOKEN,
            client_full_name="Ali Valiyev",
            client_phone_email="+998901234567",
        )
        self.message = Message.objects.create(
            conversation=self.conversation,
            sender=SenderTypes.USER.value,
            message_content=SECRET_MESSAGE,
        )

    def test_message_body_is_not_readable_in_the_database(self):
        stored = raw_column("messages", "message_content", self.message.id)
        self.assertNotIn("Chilonzor", stored)
        self.assertNotIn("8600", stored)

    def test_client_pii_is_not_readable_in_the_database(self):
        self.assertNotIn("Ali Valiyev", raw_column("conversation", "client_full_name", self.conversation.id))
        self.assertNotIn("998901234567", raw_column("conversation", "client_phone_email", self.conversation.id))

    def test_the_application_still_reads_them(self):
        conversation = Conversation.objects.get(pk=self.conversation.pk)
        self.assertEqual(conversation.client_full_name, "Ali Valiyev")
        self.assertEqual(conversation.client_phone_email, "+998901234567")
        self.assertEqual(conversation.messages.first().message_content, SECRET_MESSAGE)

    def test_bulk_read_of_a_thread_decrypts_every_row(self):
        for index in range(5):
            Message.objects.create(
                conversation=self.conversation,
                sender=SenderTypes.ASSISTANT.value,
                message_content=f"reply {index}",
            )
        contents = list(
            Message.objects.filter(conversation=self.conversation)
            .order_by("created_time")
            .values_list("message_content", flat=True)
        )
        self.assertEqual(contents[0], SECRET_MESSAGE)
        self.assertEqual(contents[1:], [f"reply {index}" for index in range(5)])

    def test_editing_a_message_re_encrypts_it(self):
        self.message.message_content = "edited"
        self.message.save()

        self.assertNotIn("edited", raw_column("messages", "message_content", self.message.id))
        self.assertEqual(Message.objects.get(pk=self.message.pk).message_content, "edited")


class ConversationAdminTokenTests(TestCase):
    def setUp(self):
        self.assistant = Assistant.objects.create(name="Sales", company_name="Acme")
        self.conversation = Conversation.objects.create(assistant=self.assistant, token=BOT_TOKEN)

    def test_admin_does_not_render_the_bot_token(self):
        model_admin = ConversationAdmin(Conversation, django_admin.site)
        rendered = [
            field
            for _, options in model_admin.fieldsets
            for field in options["fields"]
        ]
        self.assertNotIn("token", rendered)

    def test_admin_masks_the_bot_token(self):
        model_admin = ConversationAdmin(Conversation, django_admin.site)
        masked = model_admin.bot_token_masked(self.conversation)
        self.assertEqual(masked, f"***{BOT_TOKEN[-4:]}")
        self.assertNotIn(BOT_TOKEN, masked)
