"""End-to-end tests for the channel tasks: Telegram, Instagram and voice/photo.

OpenAI, Telegram and Instagram are all mocked, so these run offline. They test the
wiring — that the right things get stored, sent and skipped — rather than the model.
"""
from unittest import mock

from django.test import TestCase

from apps.assistant.models import Assistant, Conversation, Message
from apps.integration.models import Integration
from apps.integration import tasks
from apps.integration.tasks import (
    instagram_comments as comment_tasks,
    instagram_messaging as instagram_tasks,
    telegram as telegram_tasks,
)
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

        # The tasks package is split by domain, so shared collaborators must be
        # patched in every submodule that holds its own reference to them.
        self.respond = mock.MagicMock(return_value="Hello from the agent!")
        for module in (telegram_tasks, instagram_tasks, comment_tasks):
            mock.patch.object(module, "respond", self.respond).start()
        self.addCleanup(mock.patch.stopall)

        self.send_telegram = mock.patch.object(telegram_tasks, "send_telegram_message").start()
        mock.patch.object(telegram_tasks, "send_telegram_action").start()
        # handle_start_command sends through its own import, so patch that too —
        # otherwise a real request escapes to Telegram during the tests. Note the
        # `apps.` prefix: this codebase can import the same module under both
        # `shared.x` and `apps.shared.x`, which produces two distinct module
        # objects. Patch the one the task actually holds.
        self.send_greeting = mock.patch(
            "apps.shared.ai_service.conversation.send_telegram_message"
        ).start()
        self.instagram = mock.MagicMock()
        self.instagram.get_user_info.return_value = {"username": "customer"}
        for module in (instagram_tasks, comment_tasks):
            mock.patch.object(module, "instagram_service", self.instagram).start()
        for module in (telegram_tasks, instagram_tasks):
            mock.patch.object(module, "publish_message_to_ws").start()
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
            telegram_tasks.media, "analyze_image", return_value="A black iPhone 15 Pro."
        ).start()
        get = mock.patch.object(telegram_tasks.requests, "get").start()
        get.return_value.json.return_value = {"result": {"file_path": "photos/a.jpg"}}

    def test_photo_is_described_and_answered(self):
        tasks.process_photo_task(chat_id="123", photo_file_id="f1", bot_token=BOT_TOKEN)

        self.respond.assert_called_once()
        self.assertEqual(self.respond.call_args.args[2], "A black iPhone 15 Pro.")
        conversation = Conversation.objects.get(user_id="123")
        self.assertIn("[Image]", conversation.messages.first().message_content)

    def test_unreadable_photo_apologises_without_calling_the_agent(self):
        self.analyze.return_value = telegram_tasks.media.IMAGE_FAILED

        tasks.process_photo_task(chat_id="123", photo_file_id="f1", bot_token=BOT_TOKEN)

        self.respond.assert_not_called()
        self.send_telegram.assert_called_once()


class TelegramVoiceTests(ChannelTestCase):
    def setUp(self):
        super().setUp()
        get = mock.patch.object(telegram_tasks.requests, "get").start()
        get.return_value.json.return_value = {"result": {"file_path": "voice/a.ogg"}}
        get.return_value.content = b"ogg-bytes"
        mock.patch.object(
            telegram_tasks.conversation_service, "convert_ogg_to_mp3", return_value=b"mp3"
        ).start()
        self.transcribe = mock.patch.object(telegram_tasks.media, "transcribe_audio").start()
        self.queued = mock.patch.object(telegram_tasks.process_message_task, "delay").start()

    def test_voice_is_transcribed_and_handed_to_the_message_task(self):
        self.transcribe.return_value = ("Narxi qancha?", 0, 0)

        tasks.process_voice_task(chat_id="123", voice_file_id="v1", bot_token=BOT_TOKEN)

        self.queued.assert_called_once()
        self.assertEqual(self.queued.call_args.kwargs["user_message"], "Narxi qancha?")

    def test_failed_transcription_asks_the_customer_to_retry(self):
        self.transcribe.return_value = (telegram_tasks.media.TRANSCRIBE_FAILED, 0, 0)

        tasks.process_voice_task(chat_id="123", voice_file_id="v1", bot_token=BOT_TOKEN)

        self.queued.assert_not_called()
        self.send_telegram.assert_called_once()


class InstagramTests(ChannelTestCase):
    def messaging(self):
        return [{"sender": {"id": "ig-user-1"}}]

    def test_message_is_answered_and_sent(self):
        tasks.process_instagram_message(
            account_id=ACCOUNT_ID, combined_message="Salom", user_message=self.messaging()
        )

        self.respond.assert_called_once()
        self.instagram.send_message.assert_called_once()
        self.assertEqual(Conversation.objects.get(user_id="ig-user-1").platform, "instagram")

    def test_ai_disabled_stores_the_message_but_does_not_answer(self):
        self.assistant.ai_enabled = False
        self.assistant.save()

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

    def test_comment_on_known_media_without_configured_response_is_ignored(self):
        """Regression: a comment on a recorded post with no InstagramCommentResponse
        used to crash with AttributeError on None — it must be a quiet no-op."""
        from apps.integration.models import InstagramMedia

        InstagramMedia.objects.create(media_id="m1")
        comment_data = {
            "media": {"id": "m1"}, "id": "c1", "text": "hello", "from": {"id": "u1"},
        }

        tasks.process_instagram_comment(account_id=ACCOUNT_ID, comment_data=comment_data)

        self.instagram.send_comment_reply.assert_not_called()
        self.instagram.send_private_reply.assert_not_called()
        self.instagram.send_postback.assert_not_called()


class InstagramAccountResolutionTests(ChannelTestCase):
    """Regression: "Integration not found for Instagram account <id>".

    OAuth stores `/me.id` in instagram_user_id and `/me.user_id` in
    instagram_account_id. Every webhook path matched instagram_account_id only,
    so on accounts where the two identifiers differ, Meta's `entry.id` resolved
    to nothing and all traffic for that account was dropped.
    """

    URL = "/api/v1/integration/instagram/webhook/"
    APP_SECRET = "app-secret"

    def post_webhook(self, payload):
        import hashlib
        import hmac as hmac_lib
        import json as json_lib

        body = json_lib.dumps(payload)
        signature = "sha256=" + hmac_lib.new(
            self.APP_SECRET.encode(), body.encode(), hashlib.sha256,
        ).hexdigest()
        with self.settings(INSTAGRAM_APP_SECRET=self.APP_SECRET):
            return self.client.post(
                self.URL, data=body, content_type="application/json",
                HTTP_X_HUB_SIGNATURE_256=signature,
            )

    def test_task_resolves_an_account_held_in_the_other_id_column(self):
        integration = Integration.objects.get(
            integration_type=IntegrationTypes.INSTAGRAM.value
        )
        integration.instagram_user_id = "17841400375124995"
        integration.save()

        tasks.process_instagram_message(
            account_id="17841400375124995", combined_message="Salom",
            user_message=[{"sender": {"id": "ig-user-1"}}],
        )

        self.respond.assert_called_once()
        self.instagram.send_message.assert_called_once()

    def test_outbound_message_addresses_the_stored_account_id(self):
        integration = Integration.objects.get(
            integration_type=IntegrationTypes.INSTAGRAM.value
        )
        integration.instagram_user_id = "17841400375124995"
        integration.save()

        tasks.process_instagram_message(
            account_id="17841400375124995", combined_message="Salom",
            user_message=[{"sender": {"id": "ig-user-1"}}],
        )

        self.assertEqual(self.instagram.send_message.call_args.args[0], ACCOUNT_ID)

    def test_comment_task_resolves_the_other_id_column(self):
        integration = Integration.objects.get(
            integration_type=IntegrationTypes.INSTAGRAM.value
        )
        integration.instagram_user_id = "17841400375124995"
        integration.instagram_account_id = None
        integration.is_comment_response = True
        integration.save()

        with mock.patch.object(
            comment_tasks, "process_instagram_comment_message"
        ) as ai_reply:
            tasks.process_instagram_comment(
                account_id="17841400375124995",
                comment_data={"media": {"id": "m1"}, "id": "c1", "text": "hi",
                              "from": {"id": "u1"}},
            )

        # Resolution succeeded, so the task ran to the AI hand-off instead of
        # bailing out at "Integration not found".
        ai_reply.delay.assert_called_once()

    def test_webhook_resolves_an_account_held_in_the_other_id_column(self):
        integration = Integration.objects.get(
            integration_type=IntegrationTypes.INSTAGRAM.value
        )
        integration.instagram_user_id = "17841400375124995"
        integration.instagram_account_id = None
        integration.save()

        with mock.patch("apps.integration.views.redis_client") as redis, \
                mock.patch("apps.integration.views.process_collected_messages") as collector:
            redis.get.return_value = None  # not a duplicate delivery
            response = self.post_webhook({
                "entry": [{
                    "id": "17841400375124995",
                    "messaging": [{
                        "sender": {"id": "ig-user-1"},
                        "message": {"mid": "m-1", "text": "Salom"},
                    }],
                }]
            })

        self.assertEqual(response.status_code, 200)
        # Resolution succeeded, so the message was handed to the collector
        # instead of being dropped as an unknown account.
        collector.apply_async.assert_called_once()

    def test_unknown_account_is_acknowledged_not_404ed(self):
        """Meta throttles and eventually disables a subscription that keeps
        returning non-2xx, so an unroutable account must still be ack'd."""
        with mock.patch("apps.integration.views.redis_client"):
            response = self.post_webhook({
                "entry": [{
                    "id": "99999999999999999",
                    "messaging": [{
                        "sender": {"id": "ig-user-9"},
                        "message": {"mid": "m-9", "text": "Salom"},
                    }],
                }]
            })

        self.assertEqual(response.status_code, 200)


class InstagramIntegrationLifecycleTests(TestCase):
    """The OAuth callback must always land both identifiers, and deleting an
    integration must drop the Meta subscription that feeds it."""

    def test_callback_repairs_a_row_left_without_an_account_id(self):
        """get_or_create skipped its defaults when a row from an earlier failed
        attempt already matched, leaving instagram_account_id NULL forever."""
        from apps.user.models import User

        user = User.objects.create(phone_number="+998900000001")
        Integration.objects.create(
            user=user,
            name="half-written",
            integration_type=IntegrationTypes.INSTAGRAM.value,
            instagram_user_id="app-scoped-1",
            instagram_account_id=None,
        )

        integration, _ = Integration.objects.update_or_create(
            instagram_user_id="app-scoped-1",
            user=user,
            integration_type=IntegrationTypes.INSTAGRAM.value,
            defaults={
                "name": "ig", "api_token": "t",
                "instagram_account_id": "17841400375124995",
            },
        )

        self.assertEqual(integration.instagram_account_id, "17841400375124995")
        self.assertEqual(Integration.objects.count(), 1)

    def test_instagram_by_id_ignores_other_integration_types(self):
        Integration.objects.create(
            name="tg", integration_type=IntegrationTypes.TELEGRAM.value,
            instagram_account_id="17841400375124995",
        )
        self.assertFalse(Integration.instagram_by_id("17841400375124995").exists())

    def test_instagram_by_id_does_not_match_a_null_id(self):
        Integration.objects.create(
            name="ig", integration_type=IntegrationTypes.INSTAGRAM.value,
        )
        self.assertFalse(Integration.instagram_by_id(None).exists())

    def test_deleting_an_integration_unsubscribes_the_webhook(self):
        from apps.integration import views as integration_views

        integration = Integration.objects.create(
            name="ig", integration_type=IntegrationTypes.INSTAGRAM.value,
            api_token="ig-token", instagram_account_id="17841400375124995",
        )
        view = integration_views.IntegrationRetrieveUpdateDestroyView()
        view.get_object = lambda: integration

        with mock.patch.object(integration_views, "instagram_service") as service:
            view.destroy(mock.MagicMock())

        service.unsubscribe_webhooks.assert_called_once_with("ig-token")
        self.assertFalse(Integration.objects.filter(name="ig").exists())


class TaskRegistrationTests(TestCase):
    """The queue routing and beat schedule address tasks by their registered
    names — the tasks/ package split must keep every name stable."""

    def test_all_routed_integration_tasks_are_registered(self):
        from config.celery import app as celery_app

        registered = celery_app.tasks
        for task_name in celery_app.conf.task_routes:
            if task_name.startswith("apps.integration.tasks."):
                self.assertIn(task_name, registered)

    def test_beat_scheduled_billz_task_keeps_its_name(self):
        self.assertEqual(
            tasks.update_billz_products_hourly.name,
            "apps.integration.tasks.update_billz_products_hourly",
        )


class InstagramUserInfoTests(TestCase):
    def test_get_user_info_returns_empty_dict_on_network_error(self):
        """The profile lookup must fail soft — a network error should not kill
        the message-processing task that calls it."""
        import requests as requests_lib

        from shared.addons.instagram import InstagramService

        with mock.patch(
            "shared.addons.instagram.requests.get",
            side_effect=requests_lib.RequestException("boom"),
        ):
            self.assertEqual(InstagramService().get_user_info("tok", "u1"), {})


class BillzClientTests(TestCase):
    def test_fetch_all_products_simplifies_and_stops_after_last_page(self):
        from shared.addons import billz

        raw_product = {
            "id": "p1",
            "name": "T-shirt",
            "sku": "SKU1",
            "custom_fields": [
                {"custom_field_system_name": "ЦВЕТ", "custom_field_value": "Black"},
                {"custom_field_system_name": "РАЗМЕР", "custom_field_value": "L"},
            ],
            "shop_prices": [{"shop_name": "Main", "retail_price": 100}],
            "categories": [{"name": "Clothes"}],
        }
        response = mock.MagicMock()
        response.json.return_value = {"products": [raw_product]}

        with mock.patch("shared.addons.billz.requests.get", return_value=response) as get:
            products = billz.fetch_all_products("token")

        # Fewer products than the page limit → exactly one request.
        self.assertEqual(get.call_count, 1)
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["name"], "T-shirt")
        self.assertEqual(products[0]["color"], "Black")
        self.assertEqual(products[0]["size"], "L")
        self.assertEqual(products[0]["shops"][0]["retail_currency"], "UZS")

    def test_fetch_all_products_fails_soft_on_network_error(self):
        import requests as requests_lib

        from shared.addons import billz

        with mock.patch(
            "shared.addons.billz.requests.get",
            side_effect=requests_lib.RequestException("down"),
        ):
            self.assertEqual(billz.fetch_all_products("token"), [])


class InstagramWebhookSignatureTests(TestCase):
    """H3 (2026-07-22) — the webhook must fail closed.

    With no INSTAGRAM_APP_SECRET configured it used to skip verification and
    accept forged events (driving the AI and burning tokens)."""

    URL = "/api/v1/integration/instagram/webhook/"

    def post(self, body: str, **extra):
        return self.client.post(
            self.URL, data=body, content_type="application/json", **extra,
        )

    def test_missing_secret_rejects_the_webhook(self):
        with self.settings(INSTAGRAM_APP_SECRET=""):
            response = self.post('{"entry": [{"id": "acc"}]}')
        self.assertEqual(response.status_code, 403)

    def test_bad_signature_is_rejected(self):
        with self.settings(INSTAGRAM_APP_SECRET="app-secret"):
            response = self.post(
                '{"entry": [{"id": "acc"}]}',
                HTTP_X_HUB_SIGNATURE_256="sha256=deadbeef",
            )
        self.assertEqual(response.status_code, 403)

    def test_valid_signature_is_accepted(self):
        import hashlib
        import hmac as hmac_lib

        body = '{"entry": [{"id": "acc"}]}'
        signature = "sha256=" + hmac_lib.new(
            b"app-secret", body.encode(), hashlib.sha256,
        ).hexdigest()
        with self.settings(INSTAGRAM_APP_SECRET="app-secret"):
            response = self.post(body, HTTP_X_HUB_SIGNATURE_256=signature)
        self.assertEqual(response.status_code, 200)

    def test_verify_handshake_requires_a_configured_token(self):
        with self.settings(INSTAGRAM_VERIFY_TOKEN=""):
            response = self.client.get(
                self.URL,
                {"hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "42"},
            )
        self.assertEqual(response.status_code, 403)


class IntegrationTenancyTests(TestCase):
    """Regressions for the 2026-07-25 endpoint sweep.

    Every automation detail view was `objects.all()` + `IsAuthenticated`, so any
    logged-in user could read, edit and DELETE another tenant's flows, steps,
    transitions, buttons, comment responses and media. `IntegrationRetrieve...`
    was worse: its `get_object` *returned* an `error_response(...)` — a DRF
    Response — which the handlers then used as a model instance, turning every
    cross-tenant request into a 500.
    """

    def setUp(self):
        from rest_framework.test import APIClient

        from apps.assistant.models import Assistant
        from apps.integration.models import (
            CommentResponseButton, Flow, InstagramCommentResponse, Step,
            Transition,
        )
        from apps.user.models import User
        from shared.addons.enums import IntegrationTypes

        self.owner = User.objects.create(username="tenancy-owner", auth_type="email")
        self.stranger = User.objects.create(username="tenancy-stranger", auth_type="email")
        self.assistant = Assistant.objects.create(
            name="Owned", company_name="C", user=self.owner, vector_id="vs_x",
        )
        self.integration = Integration.objects.create(
            assistant=self.assistant, user=self.owner, name="Owned IG",
            integration_type=IntegrationTypes.INSTAGRAM.value,
            api_token="SECRET-BOT-TOKEN",
        )
        self.response_obj = InstagramCommentResponse.objects.create(
            integration=self.integration, comment_message_template="hi",
        )
        self.flow = Flow.objects.create(comment_response=self.response_obj, title="F")
        self.step = Step.objects.create(flow=self.flow, message_content="s")
        self.transition = Transition.objects.create(from_to=self.step)
        self.button = CommentResponseButton.objects.create(text="b")
        self.button.steps.add(self.step)

        self.client = APIClient()

    def detail_urls(self):
        return [
            f"/api/v1/integration/integration/{self.integration.id}/",
            f"/api/v1/integration/instagram/comment-responses/{self.response_obj.id}/",
            f"/api/v1/integration/flow/{self.flow.id}/",
            f"/api/v1/integration/steps/{self.step.id}/",
            f"/api/v1/integration/transition/{self.transition.id}/",
            f"/api/v1/integration/buttons/{self.button.id}/",
        ]

    def test_a_stranger_cannot_read_another_tenants_objects(self):
        self.client.force_authenticate(self.stranger)
        for url in self.detail_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_a_stranger_cannot_delete_another_tenants_objects(self):
        self.client.force_authenticate(self.stranger)
        for url in self.detail_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.delete(url).status_code, 404)
        # and nothing was actually removed
        from apps.integration.models import Flow

        self.assertTrue(Integration.objects.filter(id=self.integration.id).exists())
        self.assertTrue(Flow.objects.filter(id=self.flow.id).exists())

    def test_the_owner_still_reads_their_own_objects(self):
        self.client.force_authenticate(self.owner)
        for url in self.detail_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_a_stranger_cannot_list_another_tenants_integrations(self):
        self.client.force_authenticate(self.stranger)
        response = self.client.get(
            f"/api/v1/integration/assistant/{self.assistant.id}/integration/",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.data), [])

    def test_the_bot_token_is_never_returned(self):
        """`api_token` is a credential — write-only, or a leaked list response
        hands an attacker control of the victim's Telegram bot."""
        self.client.force_authenticate(self.owner)
        response = self.client.get(
            f"/api/v1/integration/integration/{self.integration.id}/",
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "SECRET-BOT-TOKEN")


class CommentResponseUpdateTests(TestCase):
    """Regressions for `InstagramCommentResponseSerializer.update`.

    The old implementation ran `instance.instagram_media.all().delete()` — a hard
    delete of the `InstagramMedia` **rows**, not just the M2M links — and then
    re-created each incoming media with `objects.create()`. Because `media_id` is
    `unique=True`, editing a trigger that referenced a post another trigger also
    used raised an uncaught `IntegrityError` (HTTP 500). The same delete also
    destroyed that other trigger's media, ran before `current_media_ids` was
    read from the relation (making the update-in-place branch dead code), and
    fired even when the request never mentioned media at all.
    """

    MEDIA_ID = "shared-media-1"

    def setUp(self):
        from rest_framework.test import APIClient

        from apps.assistant.models import Assistant
        from apps.user.models import User
        from shared.addons.enums import IntegrationTypes

        self.owner = User.objects.create(username="cr-update-owner", auth_type="email")
        self.assistant = Assistant.objects.create(
            name="Owned", company_name="C", user=self.owner, vector_id="vs_x",
        )
        self.integration = Integration.objects.create(
            assistant=self.assistant, user=self.owner, name="IG",
            integration_type=IntegrationTypes.INSTAGRAM.value,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def media_payload(self):
        return [{
            "id": self.MEDIA_ID,
            "media_id": self.MEDIA_ID,
            "media_type": "IMAGE",
            "media_url": "https://example.com/1.jpg",
            "username": "shop",
            "caption": "shared post",
            "comments_count": 4,
            "like_count": 9,
        }]

    def create_trigger(self, word, media=None):
        response = self.client.post(
            f"/api/v1/integration/{self.integration.id}/instagram/comment-responses/",
            {
                "comment_message_template": f"reply {word}",
                "private_message_template": f"dm {word}",
                "trigger_words_list": [word],
                "instagram_media_list": media if media is not None else [],
                "is_respond_to_all_comments": False,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["data"]["id"] if "data" in response.data else response.data["id"]

    def patch_trigger(self, trigger_id, body):
        return self.client.patch(
            f"/api/v1/integration/instagram/comment-responses/{trigger_id}/",
            body,
            format="json",
        )

    def test_editing_a_trigger_whose_media_another_trigger_holds(self):
        """This is the case that used to be a 500 `UniqueViolation`."""
        from apps.integration.models import InstagramCommentResponse, InstagramMedia

        other = self.create_trigger("beta", self.media_payload())
        mine = self.create_trigger("alpha")

        response = self.patch_trigger(mine, {
            "comment_message_template": "reply alpha",
            "private_message_template": "dm alpha",
            "instagram_media_list": self.media_payload(),
        })
        self.assertEqual(response.status_code, 200, response.data)

        # One row, shared by both triggers — not duplicated, not re-created.
        self.assertEqual(InstagramMedia.objects.filter(media_id=self.MEDIA_ID).count(), 1)
        for trigger_id in (mine, other):
            trigger = InstagramCommentResponse.objects.get(id=trigger_id)
            self.assertEqual(
                [m.media_id for m in trigger.instagram_media.all()], [self.MEDIA_ID],
            )

    def test_a_partial_patch_keeps_relations_it_never_mentions(self):
        from apps.integration.models import InstagramCommentResponse

        trigger_id = self.create_trigger("alpha", self.media_payload())

        response = self.patch_trigger(trigger_id, {
            "comment_message_template": "edited",
            "private_message_template": "dm alpha",
        })
        self.assertEqual(response.status_code, 200, response.data)

        trigger = InstagramCommentResponse.objects.get(id=trigger_id)
        self.assertEqual(
            [w.trigger_word for w in trigger.trigger_words.all()], ["alpha"],
        )
        self.assertEqual(
            [m.media_id for m in trigger.instagram_media.all()], [self.MEDIA_ID],
        )

    def test_an_explicit_empty_media_list_unlinks_without_touching_other_triggers(self):
        from apps.integration.models import InstagramCommentResponse, InstagramMedia

        other = self.create_trigger("beta", self.media_payload())
        mine = self.create_trigger("alpha", self.media_payload())

        response = self.patch_trigger(mine, {
            "comment_message_template": "no media",
            "private_message_template": "dm alpha",
            "instagram_media_list": [],
        })
        self.assertEqual(response.status_code, 200, response.data)

        self.assertEqual(
            InstagramCommentResponse.objects.get(id=mine).instagram_media.count(), 0,
        )
        # The row survives because the other trigger still points at it.
        self.assertTrue(InstagramMedia.objects.filter(media_id=self.MEDIA_ID).exists())
        self.assertEqual(
            InstagramCommentResponse.objects.get(id=other).instagram_media.count(), 1,
        )

    def test_dropping_the_last_reference_deletes_the_orphaned_row(self):
        from apps.integration.models import InstagramMedia

        trigger_id = self.create_trigger("alpha", self.media_payload())

        response = self.patch_trigger(trigger_id, {
            "comment_message_template": "no media",
            "private_message_template": "dm alpha",
            "instagram_media_list": [],
        })
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(InstagramMedia.objects.filter(media_id=self.MEDIA_ID).exists())

    def test_trigger_words_are_replaced_not_appended(self):
        from apps.integration.models import InstagramCommentResponse

        trigger_id = self.create_trigger("alpha")

        response = self.patch_trigger(trigger_id, {
            "comment_message_template": "reply",
            "private_message_template": "dm",
            "trigger_words_list": ["gamma", "delta"],
        })
        self.assertEqual(response.status_code, 200, response.data)

        trigger = InstagramCommentResponse.objects.get(id=trigger_id)
        self.assertEqual(
            sorted(w.trigger_word for w in trigger.trigger_words.all()),
            ["delta", "gamma"],
        )
