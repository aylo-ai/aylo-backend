"""End-to-end tests for the channel tasks: Telegram, Instagram and voice/photo.

OpenAI, Telegram and Instagram are all mocked, so these run offline. They test the
wiring — that the right things get stored, sent and skipped — rather than the model.
"""
from unittest import mock

from django.test import TestCase

from apps.assistant.models import Assistant, Conversation, Message
from apps.integration.models import Integration
from apps.integration import tasks
from shared.addons.enums import ConversationStatuses, IntegrationTypes, SenderTypes

BOT_TOKEN = "test-bot-token"
ACCOUNT_ID = "ig-account-1"


class ChannelTestCase(TestCase):
    def setUp(self):
        self.assistant = Assistant.objects.create(
            name="Repli Bot",
            company_name="Repli",
            system_prompt="You sell phones.",
            fallback_message="Sorry, please try again shortly.",
            greeting_message="Welcome!",
            vector_id="vs_test",
        )
        Integration.objects.create(
            assistant=self.assistant,
            name="tg",
            integration_type=IntegrationTypes.TELEGRAM.value,
            api_token=BOT_TOKEN,
        )
        Integration.objects.create(
            assistant=self.assistant,
            name="ig",
            integration_type=IntegrationTypes.INSTAGRAM.value,
            api_token="ig-token",
            instagram_account_id=ACCOUNT_ID,
        )

        self.respond = mock.patch.object(
            tasks, "respond", return_value="Hello from the agent!"
        ).start()
        self.addCleanup(mock.patch.stopall)

        self.send_telegram = mock.patch.object(tasks, "send_telegram_message").start()
        mock.patch.object(tasks, "send_telegram_action").start()
        # handle_start_command sends through its own import, so patch that too —
        # otherwise a real request escapes to Telegram during the tests. Note the
        # `apps.` prefix: this codebase can import the same module under both
        # `shared.x` and `apps.shared.x`, which produces two distinct module
        # objects. Patch the one the task actually holds.
        self.send_greeting = mock.patch(
            "apps.shared.ai_service.conversation.send_telegram_message"
        ).start()
        self.instagram = mock.patch.object(tasks, "instagram_service").start()
        mock.patch("shared.addons.redis.publish_message_to_ws").start()
        mock.patch("shared.addons.redis.publish_message_to_ws_assistant").start()


class TelegramTests(ChannelTestCase):
    def test_message_is_stored_answered_and_sent(self):
        tasks.process_message_task(chat_id="123", user_message="Salom", bot_token=BOT_TOKEN)

        conversation = Conversation.objects.get(user_id="123")
        self.assertEqual(conversation.messages.count(), 1)
        self.assertEqual(conversation.messages.get().sender, SenderTypes.USER.value)
        self.respond.assert_called_once()
        self.send_telegram.assert_called_once_with("123", "Hello from the agent!", BOT_TOKEN)

    def test_escalated_conversation_stores_but_does_not_answer(self):
        conversation = Conversation.objects.create(
            assistant=self.assistant, user_id="123", token=BOT_TOKEN,
            status=ConversationStatuses.ESCALATED.value, platform="telegram",
        )

        tasks.process_message_task(chat_id="123", user_message="Hello?", bot_token=BOT_TOKEN)

        self.respond.assert_not_called()
        self.send_telegram.assert_not_called()
        self.assertEqual(conversation.messages.count(), 1)

    def test_inactive_assistant_does_not_answer(self):
        self.assistant.is_active = False
        self.assistant.save()

        tasks.process_message_task(chat_id="123", user_message="Salom", bot_token=BOT_TOKEN)

        self.respond.assert_not_called()

    def test_start_command_sends_the_greeting_and_does_not_call_the_agent(self):
        tasks.process_message_task(chat_id="123", user_message="/start", bot_token=BOT_TOKEN)

        self.respond.assert_not_called()
        self.send_greeting.assert_called_once()
        self.assertEqual(self.send_greeting.call_args.args[1], "Welcome!")

    def test_start_command_resets_an_existing_conversation(self):
        """`/start` must wipe the agent chain and reopen a closed chat, so the
        next message begins fresh instead of continuing the old context."""
        conversation = Conversation.objects.create(
            assistant=self.assistant, user_id="123", token=BOT_TOKEN,
            status=ConversationStatuses.CLOSED.value, platform="telegram",
            previous_response_id="resp_old", instructions_version=self.assistant.updated_time,
        )

        tasks.process_message_task(chat_id="123", user_message="/start", bot_token=BOT_TOKEN)

        conversation.refresh_from_db()
        self.assertIsNone(conversation.previous_response_id)
        self.assertIsNone(conversation.instructions_version)
        self.assertEqual(conversation.status, ConversationStatuses.OPEN.value)

    def test_unknown_bot_token_is_ignored(self):
        tasks.process_message_task(chat_id="123", user_message="Hi", bot_token="nope")

        self.respond.assert_not_called()
        self.assertFalse(Conversation.objects.exists())

    def test_empty_reply_is_not_sent(self):
        self.respond.return_value = ""

        tasks.process_message_task(chat_id="123", user_message="Salom", bot_token=BOT_TOKEN)

        self.send_telegram.assert_not_called()

    def test_conversation_is_reused_across_messages(self):
        tasks.process_message_task(chat_id="123", user_message="Salom", bot_token=BOT_TOKEN)
        tasks.process_message_task(chat_id="123", user_message="Narxi?", bot_token=BOT_TOKEN)

        self.assertEqual(Conversation.objects.filter(user_id="123").count(), 1)
        self.assertEqual(Message.objects.filter(sender=SenderTypes.USER.value).count(), 2)


class TelegramPhotoTests(ChannelTestCase):
    def setUp(self):
        super().setUp()
        self.analyze = mock.patch.object(
            tasks.media, "analyze_image", return_value="A black iPhone 15 Pro."
        ).start()
        get = mock.patch.object(tasks.requests, "get").start()
        get.return_value.json.return_value = {"result": {"file_path": "photos/a.jpg"}}

    def test_photo_is_described_and_answered(self):
        tasks.process_photo_task(chat_id="123", photo_file_id="f1", bot_token=BOT_TOKEN)

        self.respond.assert_called_once()
        self.assertEqual(self.respond.call_args.args[2], "A black iPhone 15 Pro.")
        conversation = Conversation.objects.get(user_id="123")
        self.assertIn("[Image]", conversation.messages.first().message_content)

    def test_unreadable_photo_apologises_without_calling_the_agent(self):
        self.analyze.return_value = tasks.media.IMAGE_FAILED

        tasks.process_photo_task(chat_id="123", photo_file_id="f1", bot_token=BOT_TOKEN)

        self.respond.assert_not_called()
        self.send_telegram.assert_called_once()


class TelegramVoiceTests(ChannelTestCase):
    def setUp(self):
        super().setUp()
        get = mock.patch.object(tasks.requests, "get").start()
        get.return_value.json.return_value = {"result": {"file_path": "voice/a.ogg"}}
        get.return_value.content = b"ogg-bytes"
        mock.patch.object(
            tasks.conversation_service, "convert_ogg_to_mp3", return_value=b"mp3"
        ).start()
        self.transcribe = mock.patch.object(tasks.media, "transcribe_audio").start()
        self.queued = mock.patch.object(tasks.process_message_task, "delay").start()

    def test_voice_is_transcribed_and_handed_to_the_message_task(self):
        self.transcribe.return_value = ("Narxi qancha?", 0, 0)

        tasks.process_voice_task(chat_id="123", voice_file_id="v1", bot_token=BOT_TOKEN)

        self.queued.assert_called_once()
        self.assertEqual(self.queued.call_args.kwargs["user_message"], "Narxi qancha?")

    def test_failed_transcription_asks_the_customer_to_retry(self):
        self.transcribe.return_value = (tasks.media.TRANSCRIBE_FAILED, 0, 0)

        tasks.process_voice_task(chat_id="123", voice_file_id="v1", bot_token=BOT_TOKEN)

        self.queued.assert_not_called()
        self.send_telegram.assert_called_once()


class InstagramTests(ChannelTestCase):
    def messaging(self):
        return [{"sender": {"id": "ig-user-1"}}]

    def test_message_is_answered_and_sent(self):
        with mock.patch.object(tasks, "get_user_info", return_value={"username": "customer"}):
            tasks.process_instagram_message(
                account_id=ACCOUNT_ID, combined_message="Salom", user_message=self.messaging()
            )

        self.respond.assert_called_once()
        self.instagram.send_message.assert_called_once()
        self.assertEqual(Conversation.objects.get(user_id="ig-user-1").platform, "instagram")

    def test_ai_disabled_stores_the_message_but_does_not_answer(self):
        self.assistant.ai_enabled = False
        self.assistant.save()

        with mock.patch.object(tasks, "get_user_info", return_value={"username": "customer"}):
            tasks.process_instagram_message(
                account_id=ACCOUNT_ID, combined_message="Salom", user_message=self.messaging()
            )

        self.respond.assert_not_called()
        self.assertEqual(Message.objects.count(), 1)

    def test_shared_post_context_reaches_the_agent(self):
        self.instagram.extract_media_id_from_url.return_value = "m1"
        self.instagram.get_media_details.return_value = {
            "caption": "iPhone 15 Pro sale", "media_type": "IMAGE",
        }

        with mock.patch.object(tasks, "get_user_info", return_value={"username": "customer"}):
            tasks.process_shared_post_message(
                account_id=ACCOUNT_ID, shared_url="https://instagram.com/p/x",
                user_text="How much?", messaging=self.messaging(),
            )

        self.respond.assert_called_once()
        self.assertIn("iPhone 15 Pro sale", self.respond.call_args.args[2])

    def test_comment_triggers_a_private_reply(self):
        integration = Integration.objects.get(integration_type=IntegrationTypes.INSTAGRAM.value)

        tasks.process_instagram_comment_message(
            account_id=ACCOUNT_ID, message="Is this available?",
            comment_id="c1", integration_id=str(integration.id),
        )

        self.respond.assert_called_once()
        self.instagram.send_private_reply.assert_called_once()
