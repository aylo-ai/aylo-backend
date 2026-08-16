"""Tests for the dashboard chat and knowledge-base file upload.

Both paths used to raise AttributeError against methods that no longer existed on
`assistant_service`; the first test in each class is the regression for that.
"""
from unittest import mock

from django.test import TestCase

from apps.assistant.models import (
    Assistant, AssistantFileUpload, Conversation, Lead, Message,
)
from django.test import override_settings

from apps.assistant.serializers import AssistantFileUploadSerializer, MessageSerializer
from apps.shared.addons.enums import ConversationStatuses, SenderTypes, SubscriptionStatuses
from apps.shared.ai_service.agent import AgentResult

# The project stores uploads on S3. Tests run offline, so file-writing paths get
# an in-memory backend instead of a bucket that isn't there.
IN_MEMORY_STORAGE = override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
)


def make_subscribed_user(username="owner", email="owner@example.com"):
    """A user with an active subscription — the serializers validate one."""
    from apps.payment.models import Subscription
    from apps.user.models import User

    subscription = Subscription.objects.create(
        status=SubscriptionStatuses.ACTIVE.value, remained_request_count=1000,
    )
    return User.objects.create(
        username=username, auth_type="email", email=email,
        subscription=subscription,
    )


class MessageSerializerTests(TestCase):
    """POST conversations/<id>/messages/ — the dashboard / website chat."""

    def setUp(self):
        self.assistant = Assistant.objects.create(
            name="Aylo Bot", company_name="Aylo",
            fallback_message="Sorry, try again shortly.", vector_id="vs_test",
            user=make_subscribed_user(),
        )
        self.conversation = Conversation.objects.create(
            assistant=self.assistant, platform="website",
            status=ConversationStatuses.OPEN.value,
        )
        self.run = mock.patch(
            "apps.assistant.serializers.agent.run",
            return_value=AgentResult(text="It costs $999.", input_tokens=120, output_tokens=25),
        ).start()
        self.addCleanup(mock.patch.stopall)

    def send(self, content="How much is the iPhone?"):
        serializer = MessageSerializer(
            data={"sender": SenderTypes.USER.value, "message_content": content},
            context={"conversation_id": str(self.conversation.id), "request": mock.Mock()},
        )
        serializer.is_valid(raise_exception=True)
        return serializer.save()

    def test_sending_a_message_returns_the_agent_reply(self):
        reply = self.send()

        self.assertEqual(reply.message_content, "It costs $999.")
        self.assertEqual(reply.sender, SenderTypes.ASSISTANT.value)
        self.run.assert_called_once()

    def test_both_messages_are_stored(self):
        self.send("How much is the iPhone?")

        contents = list(
            self.conversation.messages.order_by("created_time").values_list(
                "message_content", flat=True
            )
        )
        self.assertEqual(contents, ["How much is the iPhone?", "It costs $999."])

    def test_token_usage_is_recorded_on_the_reply(self):
        reply = self.send()

        self.assertEqual(reply.input_tokens, 120)
        self.assertEqual(reply.output_tokens, 25)

    def test_escalated_conversation_does_not_call_the_agent(self):
        self.conversation.status = ConversationStatuses.ESCALATED.value
        self.conversation.save()

        result = self.send("Hello?")

        self.run.assert_not_called()
        self.assertEqual(result.sender, SenderTypes.USER.value)
        self.assertEqual(Message.objects.count(), 1)

    def test_inactive_assistant_does_not_call_the_agent(self):
        self.assistant.is_active = False
        self.assistant.save()

        self.send("Hello?")

        self.run.assert_not_called()


class ConversationCreateTests(TestCase):
    def test_new_conversation_starts_with_no_agent_state(self):
        from apps.assistant.serializers import ConversationSerializer

        assistant = Assistant.objects.create(
            name="Aylo Bot", company_name="Aylo", vector_id="vs_test", ai_enabled=False,
        )
        with mock.patch("apps.assistant.serializers.publish_message_to_ws_assistant"):
            conversation = ConversationSerializer().create({"assistant": assistant})

        self.assertIsNone(conversation.previous_response_id)
        self.assertIsNone(conversation.instructions_version)


class MessageQuotaTests(TestCase):
    """Message.save() charges the owner's request quota — safely (finding C1)."""

    def _assistant(self, remained=None):
        from apps.payment.models import Subscription
        from apps.user.models import User

        subscription = None
        if remained is not None:
            subscription = Subscription.objects.create(
                status=SubscriptionStatuses.ACTIVE.value, remained_request_count=remained,
            )
        user = User.objects.create(
            username=f"owner-{remained}", auth_type="email",
            email=f"owner-{remained}@example.com", subscription=subscription,
        )
        return Assistant.objects.create(name="Bot", company_name="Aylo", user=user)

    def _conversation(self, assistant):
        return Conversation.objects.create(
            assistant=assistant, platform="website", status=ConversationStatuses.OPEN.value,
        )

    def _reply(self, conversation, sender=SenderTypes.ASSISTANT.value):
        return Message.objects.create(
            conversation=conversation, sender=sender, message_content="hi",
        )

    def test_assistant_reply_without_a_subscription_does_not_crash(self):
        conv = self._conversation(self._assistant(remained=None))
        message = self._reply(conv)
        self.assertTrue(Message.objects.filter(pk=message.pk).exists())

    def test_assistant_reply_charges_one_request(self):
        assistant = self._assistant(remained=100)
        self._reply(self._conversation(assistant))
        assistant.user.subscription.refresh_from_db()
        self.assertEqual(assistant.user.subscription.remained_request_count, 99)

    def test_user_message_does_not_charge(self):
        assistant = self._assistant(remained=100)
        self._reply(self._conversation(assistant), sender=SenderTypes.USER.value)
        assistant.user.subscription.refresh_from_db()
        self.assertEqual(assistant.user.subscription.remained_request_count, 100)

    def test_editing_a_reply_does_not_charge_again(self):
        assistant = self._assistant(remained=100)
        message = self._reply(self._conversation(assistant))
        message.is_read = True
        message.save()
        assistant.user.subscription.refresh_from_db()
        self.assertEqual(assistant.user.subscription.remained_request_count, 99)

    def test_quota_never_goes_negative(self):
        assistant = self._assistant(remained=0)
        self._reply(self._conversation(assistant))
        assistant.user.subscription.refresh_from_db()
        self.assertEqual(assistant.user.subscription.remained_request_count, 0)

    def test_hitting_the_threshold_notifies_the_owner(self):
        from apps.user.models import Notification

        assistant = self._assistant(remained=11)  # 11 -> 10 triggers the warning
        self._reply(self._conversation(assistant))
        self.assertEqual(Notification.objects.filter(user=assistant.user).count(), 1)


@IN_MEMORY_STORAGE
class FileUploadTests(TestCase):
    def setUp(self):
        self.assistant = Assistant.objects.create(
            name="Aylo Bot", company_name="Aylo", user=make_subscribed_user(),
        )
        self.ensure = mock.patch(
            "apps.assistant.serializers.knowledge_base.ensure_store", return_value="vs_new"
        ).start()
        self.add_file = mock.patch(
            "apps.assistant.serializers.knowledge_base.add_file", return_value="file-1"
        ).start()
        self.addCleanup(mock.patch.stopall)

    def upload(self, name="catalogue.txt"):
        from django.core.files.uploadedfile import SimpleUploadedFile

        upload = SimpleUploadedFile(name, b"iPhone 15 Pro - 12,500,000 UZS")
        request = mock.Mock()
        request.build_absolute_uri.side_effect = lambda url: f"https://example.com{url}"
        serializer = AssistantFileUploadSerializer(
            data={"assistant": str(self.assistant.id), "file": upload},
            context={"assistant": self.assistant, "files": [upload], "request": request},
        )
        serializer.is_valid(raise_exception=True)
        return serializer.save()

    def test_uploaded_file_is_indexed_and_the_id_is_stored(self):
        result = self.upload()

        self.ensure.assert_called_once_with(self.assistant)
        self.add_file.assert_called_once()
        self.assertEqual(result.file_id, "file-1")

    def test_a_failed_index_still_keeps_the_upload_row(self):
        self.add_file.return_value = None

        result = self.upload()

        self.assertIsNone(result.file_id)
        self.assertEqual(AssistantFileUpload.objects.count(), 1)

    def test_an_indexing_error_does_not_break_the_upload(self):
        self.add_file.side_effect = RuntimeError("openai down")

        result = self.upload()

        self.assertEqual(AssistantFileUpload.objects.count(), 1)
        self.assertIsNone(result.file_id)


class EndpointScopingTests(TestCase):
    """A1/A2 (2026-07-22) — chat endpoints require auth and are tenant-scoped.

    Message create/list used to be AllowAny (anyone could run the agent on the
    owner's quota and read any history), and conversation/lead detail views
    fetched by pk with no ownership filter.
    """

    def setUp(self):
        from rest_framework.test import APIClient
        from apps.user.models import User

        self.owner = make_subscribed_user()
        self.assistant = Assistant.objects.create(
            name="Aylo Bot", company_name="Aylo", user=self.owner,
        )
        self.conversation = Conversation.objects.create(
            assistant=self.assistant, platform="website",
            status=ConversationStatuses.OPEN.value,
        )
        self.stranger = User.objects.create(
            username="stranger", auth_type="email", email="stranger@example.com",
        )
        self.client = APIClient()

    def test_anonymous_cannot_post_messages(self):
        response = self.client.post(
            f"/api/v1/chat/conversation/{self.conversation.id}/message/",
            {"sender": SenderTypes.USER.value, "message_content": "hi"},
        )
        self.assertEqual(response.status_code, 401)

    def test_anonymous_cannot_create_conversations(self):
        response = self.client.post(
            f"/api/v1/chat/assistant/{self.assistant.id}/conversation/", {},
        )
        self.assertEqual(response.status_code, 401)

    def test_stranger_cannot_post_into_another_tenants_conversation(self):
        self.client.force_authenticate(self.stranger)
        response = self.client.post(
            f"/api/v1/chat/conversation/{self.conversation.id}/message/",
            {"sender": SenderTypes.USER.value, "message_content": "hi"},
        )
        self.assertEqual(response.status_code, 404)

    def test_stranger_cannot_read_another_tenants_conversation(self):
        self.client.force_authenticate(self.stranger)
        response = self.client.get(f"/api/v1/chat/conversation/{self.conversation.id}/")
        self.assertEqual(response.status_code, 404)

    def test_stranger_sees_no_messages_from_another_tenant(self):
        Message.objects.create(
            conversation=self.conversation, sender=SenderTypes.USER.value,
            message_content="my secret order",
        )
        self.client.force_authenticate(self.stranger)
        response = self.client.get(
            f"/api/v1/chat/conversation/{self.conversation.id}/messages/",
        )
        self.assertNotContains(response, "my secret order",
                               status_code=response.status_code)

    def test_owner_still_reads_their_conversation(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get(f"/api/v1/chat/conversation/{self.conversation.id}/")
        self.assertEqual(response.status_code, 200)

    def test_stranger_cannot_export_another_tenants_leads(self):
        self.client.force_authenticate(self.stranger)
        response = self.client.get(
            f"/api/v1/chat/assistant/{self.assistant.id}/export-leads/",
        )
        self.assertEqual(response.status_code, 404)


class ChatEndpointRegressionTests(TestCase):
    """Regressions for the 2026-07-25 endpoint sweep.

    Each of these reproduced a live defect: an endpoint that answered 400 to
    every request, one that succeeded while discarding what it was given, and
    one that wrote a file every tenant shared.
    """

    def setUp(self):
        from rest_framework.test import APIClient

        self.owner = make_subscribed_user()
        self.assistant = Assistant.objects.create(
            name="Aylo Bot", company_name="Aylo", vector_id="vs_test",
            user=self.owner,
        )
        self.conversation = Conversation.objects.create(
            assistant=self.assistant, status=ConversationStatuses.ESCALATED.value,
        )
        self.message = Message.objects.create(
            conversation=self.conversation, sender=SenderTypes.USER.value,
            message_content="original",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        # Conversation creation publishes to the websocket relay; there is no
        # Redis in an offline test run.
        mock.patch("apps.assistant.serializers.publish_message_to_ws_assistant").start()
        self.addCleanup(mock.patch.stopall)

        # Creating a conversation publishes it to the websocket channel. Redis is
        # infrastructure, not behaviour under test, and CLAUDE.md §5 requires the
        # suite to run offline — without this the test needs a live Redis.
        mock.patch(
            "apps.assistant.serializers.publish_message_to_ws_assistant"
        ).start()
        self.addCleanup(mock.patch.stopall)

    def test_a_message_can_be_edited(self):
        """`MessageSerializer.validate` resolved the conversation only from the
        create view's context, so every update 400'd with "Conversation
        topilmadi" — the endpoint was unusable."""
        response = self.client.patch(
            f"/api/v1/chat/message/{self.message.id}/",
            {"message_content": "edited"}, format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.message.refresh_from_db()
        self.assertEqual(self.message.message_content, "edited")

    def test_a_lead_is_attached_to_the_assistant_from_the_url(self):
        """The lead used to be saved with `assistant=NULL`, which made it
        invisible to the list endpoint and unreachable by id forever."""
        response = self.client.post(
            f"/api/v1/chat/assistant/{self.assistant.id}/leads/",
            {"full_name": "Ali"}, format="json",
        )

        self.assertEqual(response.status_code, 201)
        lead = Lead.objects.get(full_name="Ali")
        self.assertEqual(lead.assistant, self.assistant)

    def test_a_lead_cannot_be_pointed_at_someone_elses_assistant(self):
        """`assistant` was writable, so the body could override the URL and
        bypass the ownership check the view had just performed."""
        from apps.user.models import User

        other = User.objects.create(username="other", auth_type="email")
        victim = Assistant.objects.create(name="Victim", company_name="V", user=other)

        response = self.client.post(
            f"/api/v1/chat/assistant/{self.assistant.id}/leads/",
            {"full_name": "Redirected", "assistant": str(victim.id)}, format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Lead.objects.get(full_name="Redirected").assistant, self.assistant)

    def test_creating_a_conversation_keeps_the_fields_it_was_given(self):
        """`create()` hard-coded platform=website and dropped every other
        validated field, so the caller's data silently vanished."""
        response = self.client.post(
            f"/api/v1/chat/assistant/{self.assistant.id}/conversation/",
            {"platform": "telegram", "username": "visitor", "user_id": "tg-1"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        created = Conversation.objects.get(user_id="tg-1")
        self.assertEqual(created.platform, "telegram")
        self.assertEqual(created.username, "visitor")

    def test_exporting_leads_writes_no_file_to_disk(self):
        """The workbook was saved as `leads_export_<date>.xlsx` in the process
        CWD — one path shared by every tenant, so concurrent exports raced."""
        import os

        Lead.objects.create(assistant=self.assistant, full_name="Ali")
        before = set(os.listdir("."))

        response = self.client.get(
            f"/api/v1/chat/assistant/{self.assistant.id}/export-leads/",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [f for f in set(os.listdir(".")) - before if f.startswith("leads_export")],
            [],
        )

    def test_put_requires_the_whole_object(self):
        """Every `update()` override hard-coded `partial=True`, so PUT silently
        behaved as PATCH and never enforced required fields."""
        response = self.client.put(
            f"/api/v1/chat/assistant/{self.assistant.id}/",
            {"name": "Only a name"}, format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_patch_still_accepts_a_single_field(self):
        response = self.client.patch(
            f"/api/v1/chat/assistant/{self.assistant.id}/",
            {"name": "Renamed"}, format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assistant.refresh_from_db()
        self.assertEqual(self.assistant.name, "Renamed")


class MassAssignmentTenancyTests(TestCase):
    """Tenancy columns were writable through the customer-facing serializers.

    Each of these had passed the view's ownership check on the row the caller
    *did* own — the escalation was in the body, re-pointing that row at another
    tenant afterwards.
    """

    def setUp(self):
        from rest_framework.test import APIClient

        from apps.payment.models import Subscription
        from apps.user.models import User

        def subscribed(username):
            subscription = Subscription.objects.create(
                status=SubscriptionStatuses.ACTIVE.value, remained_request_count=1000,
            )
            return User.objects.create(
                username=username, auth_type="email", subscription=subscription,
            )

        self.owner = subscribed("ma-owner")
        self.victim = subscribed("ma-victim")

        self.assistant = Assistant.objects.create(
            name="Mine", company_name="C", user=self.owner, vector_id="vs_a",
        )
        self.victim_assistant = Assistant.objects.create(
            name="Theirs", company_name="V", user=self.victim, vector_id="vs_b",
        )
        self.conversation = Conversation.objects.create(
            assistant=self.assistant, status=ConversationStatuses.ESCALATED.value,
        )
        self.victim_conversation = Conversation.objects.create(
            assistant=self.victim_assistant, status=ConversationStatuses.ESCALATED.value,
        )
        self.message = Message.objects.create(
            conversation=self.conversation, sender=SenderTypes.USER.value,
            message_content="original",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def test_an_assistant_cannot_be_handed_to_another_account(self):
        """`user` was writable, so a PATCH moved the assistant into the
        victim's account: it then counted against their assistant quota and
        every integration hung off it billed their subscription."""
        response = self.client.patch(
            f"/api/v1/chat/assistant/{self.assistant.id}/",
            {"user": str(self.victim.id)}, format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assistant.refresh_from_db()
        self.assertEqual(self.assistant.user_id, self.owner.id)

        # The rest of the same PATCH still applies — this is a read-only field,
        # not a rejected request.
        renamed = self.client.patch(
            f"/api/v1/chat/assistant/{self.assistant.id}/",
            {"name": "Renamed"}, format="json",
        )
        self.assertEqual(renamed.status_code, 200)
        self.assistant.refresh_from_db()
        self.assertEqual(self.assistant.name, "Renamed")

    def test_a_conversation_cannot_be_re_parented_onto_another_assistant(self):
        response = self.client.patch(
            f"/api/v1/chat/conversation/{self.conversation.id}/",
            {"assistant": str(self.victim_assistant.id),
             "status": ConversationStatuses.CLOSED.value},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.assistant_id, self.assistant.id)
        # …and the legitimate half of the same request went through.
        self.assertEqual(self.conversation.status, ConversationStatuses.CLOSED.value)

    def test_a_message_cannot_be_moved_into_another_tenants_thread(self):
        response = self.client.patch(
            f"/api/v1/chat/message/{self.message.id}/",
            {"conversation": str(self.victim_conversation.id),
             "message_content": "edited"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.message.refresh_from_db()
        self.assertEqual(self.message.conversation_id, self.conversation.id)
        self.assertEqual(self.message.message_content, "edited")
        self.assertEqual(self.victim_conversation.messages.count(), 0)


class FollowUpStageOwnershipTests(TestCase):
    """`FollowUpStageListCreateView.create` filtered on
    `Q(user=request.user) | Q(user=request.user.created_by)`; with `created_by`
    unset the second leg is `Q(user=None)` and matches every ownerless
    assistant."""

    def setUp(self):
        from rest_framework.test import APIClient

        from apps.user.models import User

        self.user = User.objects.create(username="fu-user", auth_type="email")
        self.ownerless = Assistant.objects.create(
            name="Ownerless", company_name="O", user=None, vector_id="vs_o",
        )
        self.own = Assistant.objects.create(
            name="Own", company_name="O", user=self.user, vector_id="vs_p",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def payload(self):
        return {"stage_number": 1, "delay_hours": 2, "message_template": "hi"}

    def test_an_ownerless_assistant_is_not_configurable(self):
        from apps.assistant.models import FollowUpStage

        refused = self.client.post(
            f"/api/v1/chat/assistant/{self.ownerless.id}/follow-up/stages/",
            self.payload(), format="json",
        )
        self.assertEqual(refused.status_code, 404)
        self.assertFalse(
            FollowUpStage.objects.filter(config__assistant=self.ownerless).exists()
        )

        allowed = self.client.post(
            f"/api/v1/chat/assistant/{self.own.id}/follow-up/stages/",
            self.payload(), format="json",
        )
        self.assertEqual(allowed.status_code, 201, allowed.data)


class MessageCreateWithoutRequestTests(TestCase):
    """`create()` bound `_` as a local (`transcribed_text, _, _ = ...`), which
    made the `_("Request obyekti kerak")` guard above it raise
    UnboundLocalError — a 500 where a 400 was intended."""

    def test_a_missing_request_raises_the_validation_error(self):
        from apps.shared.addons.validations import CustomValidationError

        serializer = MessageSerializer()
        with self.assertRaises(CustomValidationError):
            serializer.create({"sender": SenderTypes.USER.value})
# ---------------------------------------------------------------------------
# Tenant isolation (IDOR) and mass assignment
# ---------------------------------------------------------------------------


def _row_ids(response):
    """Ids out of a list response, whatever wrapper the view happens to use.

    Some list views return DRF's bare array, others wrap it in
    `success_response(data=[...])`. Tests should not care which.
    """
    payload = response.json()
    if isinstance(payload, dict):
        payload = payload.get("data") or []
    if isinstance(payload, dict):
        payload = payload.get("results") or []
    return {str(row["id"]) for row in payload}


class TenantFixtureMixin:
    """Two unrelated tenants, each with a full object graph.

    `victim` owns everything the tests try to reach; `intruder` is a perfectly
    ordinary paying customer of the same platform, which is exactly the threat
    model — not an anonymous stranger, but the account next door.
    """

    def build_tenants(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.utils.timezone import now
        from rest_framework.test import APIClient

        from apps.assistant.models import FollowUpConfig, FollowUpLog, FollowUpStage

        self.victim = make_subscribed_user("victim", "victim@example.com")
        self.intruder = make_subscribed_user("intruder", "intruder@example.com")

        self.assistant = Assistant.objects.create(
            name="Victim Bot", company_name="Victim Co", user=self.victim,
            vector_id="vs_victim",
        )
        self.conversation = Conversation.objects.create(
            assistant=self.assistant, platform="website",
            status=ConversationStatuses.OPEN.value, username="victim-visitor",
        )
        self.message = Message.objects.create(
            conversation=self.conversation, sender=SenderTypes.USER.value,
            message_content="card ending 4242",
        )
        self.lead = Lead.objects.create(
            assistant=self.assistant, full_name="Victim Lead",
            phone_number="+998901112233",
        )
        self.file = AssistantFileUpload.objects.create(
            assistant=self.assistant,
            file=SimpleUploadedFile("pricing.txt", b"internal pricing"),
            filename="pricing.txt", file_id="file-victim",
        )
        self.config = FollowUpConfig.objects.create(
            assistant=self.assistant, target_statuses=[ConversationStatuses.OPEN.value],
        )
        self.stage = FollowUpStage.objects.create(
            config=self.config, stage_number=1, delay_hours=2,
            message_template="Still interested?",
        )
        self.log = FollowUpLog.objects.create(
            conversation=self.conversation, stage=self.stage, scheduled_at=now(),
        )

        # The intruder's own, legitimate objects — used to prove that a
        # correctly scoped *parent* does not launder access to a foreign child.
        self.intruder_assistant = Assistant.objects.create(
            name="Intruder Bot", company_name="Intruder Co", user=self.intruder,
            vector_id="vs_intruder",
        )
        self.intruder_conversation = Conversation.objects.create(
            assistant=self.intruder_assistant, platform="website",
            status=ConversationStatuses.OPEN.value,
        )

        self.client = APIClient()


@IN_MEMORY_STORAGE
class TenantIsolationTests(TenantFixtureMixin, TestCase):
    """Every `/api/v1/chat/…` object is reachable only by its own tenant.

    The recurring bug class in this app (see `EndpointScopingTests`) is a
    `get_queryset` that returns `Model.objects.all()` while the view looks the
    object up by URL pk. Partial fixes that scope only list/retrieve are common,
    so update *and* delete are asserted explicitly for every resource.

    404, never 403: a 403 on an object the caller cannot see still confirms that
    the id exists.
    """

    def setUp(self):
        self.build_tenants()
        self.client.force_authenticate(self.intruder)
        self.delete_store = mock.patch(
            "apps.assistant.views.knowledge_base.delete_store"
        ).start()
        self.delete_file = mock.patch(
            "apps.assistant.views.knowledge_base.delete_file"
        ).start()
        self.addCleanup(mock.patch.stopall)

    # --- Assistant ---------------------------------------------------------

    def test_assistant_list_hides_other_tenants(self):
        response = self.client.get("/api/v1/chat/assistant/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(_row_ids(response), {str(self.intruder_assistant.id)})

    def test_assistant_retrieve_is_404(self):
        response = self.client.get(f"/api/v1/chat/assistant/{self.assistant.id}/")
        self.assertEqual(response.status_code, 404)

    def test_assistant_patch_is_404(self):
        response = self.client.patch(
            f"/api/v1/chat/assistant/{self.assistant.id}/",
            {"name": "Owned"}, format="json",
        )

        self.assertEqual(response.status_code, 404)
        self.assistant.refresh_from_db()
        self.assertEqual(self.assistant.name, "Victim Bot")

    def test_assistant_delete_is_404(self):
        response = self.client.delete(f"/api/v1/chat/assistant/{self.assistant.id}/")

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Assistant.objects.filter(pk=self.assistant.pk).exists())
        self.delete_store.assert_not_called()

    def test_token_stats_cover_only_the_callers_assistants(self):
        response = self.client.get("/api/v1/chat/assistant/token-stats/")

        self.assertEqual(response.status_code, 200)
        returned = {row["assistant_id"] for row in response.json()["data"]}
        self.assertEqual(returned, {str(self.intruder_assistant.id)})

    # --- Conversation ------------------------------------------------------

    def test_conversation_list_under_a_foreign_assistant_is_empty(self):
        response = self.client.get(
            f"/api/v1/chat/assistant/{self.assistant.id}/conversation/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(_row_ids(response), set())

    def test_conversation_create_under_a_foreign_assistant_is_404(self):
        response = self.client.post(
            f"/api/v1/chat/assistant/{self.assistant.id}/conversation/", {},
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.assistant.conversations.count(), 1)

    def test_conversation_retrieve_is_404(self):
        response = self.client.get(
            f"/api/v1/chat/conversation/{self.conversation.id}/"
        )
        self.assertEqual(response.status_code, 404)

    def test_conversation_patch_is_404(self):
        response = self.client.patch(
            f"/api/v1/chat/conversation/{self.conversation.id}/",
            {"status": ConversationStatuses.CLOSED.value}, format="json",
        )

        self.assertEqual(response.status_code, 404)
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.status, ConversationStatuses.OPEN.value)

    def test_conversation_delete_is_404(self):
        response = self.client.delete(
            f"/api/v1/chat/conversation/{self.conversation.id}/"
        )

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Conversation.objects.filter(pk=self.conversation.pk).exists())

    # --- Message -----------------------------------------------------------

    def test_message_list_for_a_foreign_conversation_is_empty(self):
        for suffix in ("message", "messages"):
            with self.subTest(route=suffix):
                response = self.client.get(
                    f"/api/v1/chat/conversation/{self.conversation.id}/{suffix}/"
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(_row_ids(response), set())

    def test_message_create_in_a_foreign_conversation_is_404(self):
        response = self.client.post(
            f"/api/v1/chat/conversation/{self.conversation.id}/message/",
            {"sender": SenderTypes.USER.value, "message_content": "hi"},
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.conversation.messages.count(), 1)

    def test_message_retrieve_is_404(self):
        response = self.client.get(f"/api/v1/chat/message/{self.message.id}/")
        self.assertEqual(response.status_code, 404)

    def test_message_patch_is_404(self):
        response = self.client.patch(
            f"/api/v1/chat/message/{self.message.id}/",
            {"message_content": "tampered"}, format="json",
        )

        self.assertEqual(response.status_code, 404)
        self.message.refresh_from_db()
        self.assertEqual(self.message.message_content, "card ending 4242")

    def test_message_delete_is_404(self):
        response = self.client.delete(f"/api/v1/chat/message/{self.message.id}/")

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Message.objects.filter(pk=self.message.pk).exists())

    def test_bulk_read_through_an_owned_conversation_cannot_reach_foreign_messages(self):
        """Nested route, own parent, foreign child: the intruder owns the
        conversation in the URL and supplies the victim's message id in the
        body. The `conversation__id` leg of the UPDATE has to hold."""
        with mock.patch("apps.assistant.views.publish_new_message_to_ws"):
            response = self.client.patch(
                f"/api/v1/chat/conversation/{self.intruder_conversation.id}/messages/bulk-read/",
                {"message_ids": [str(self.message.id)]}, format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["updated_count"], 0)
        self.message.refresh_from_db()
        self.assertFalse(self.message.is_read)

    def test_bulk_read_on_a_foreign_conversation_is_404(self):
        response = self.client.patch(
            f"/api/v1/chat/conversation/{self.conversation.id}/messages/bulk-read/",
            {"message_ids": [str(self.message.id)]}, format="json",
        )

        self.assertEqual(response.status_code, 404)
        self.message.refresh_from_db()
        self.assertFalse(self.message.is_read)

    # --- Lead --------------------------------------------------------------

    def test_lead_list_under_a_foreign_assistant_is_empty(self):
        response = self.client.get(
            f"/api/v1/chat/assistant/{self.assistant.id}/leads/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(_row_ids(response), set())

    def test_lead_list_under_an_owned_assistant_excludes_foreign_leads(self):
        response = self.client.get(
            f"/api/v1/chat/assistant/{self.intruder_assistant.id}/leads/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(str(self.lead.id), _row_ids(response))

    def test_lead_retrieve_is_404(self):
        response = self.client.get(f"/api/v1/chat/lead/{self.lead.id}/")
        self.assertEqual(response.status_code, 404)

    def test_lead_patch_is_404(self):
        response = self.client.patch(
            f"/api/v1/chat/lead/{self.lead.id}/",
            {"full_name": "Stolen"}, format="json",
        )

        self.assertEqual(response.status_code, 404)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.full_name, "Victim Lead")

    def test_lead_delete_is_404(self):
        response = self.client.delete(f"/api/v1/chat/lead/{self.lead.id}/")

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Lead.objects.filter(pk=self.lead.pk).exists())

    def test_lead_export_for_a_foreign_assistant_is_404(self):
        response = self.client.get(
            f"/api/v1/chat/assistant/{self.assistant.id}/export-leads/"
        )
        self.assertEqual(response.status_code, 404)

    # --- Knowledge base ----------------------------------------------------

    def test_file_list_under_a_foreign_assistant_is_empty(self):
        response = self.client.get(
            f"/api/v1/chat/assistant/{self.assistant.id}/upload-file/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(_row_ids(response), set())

    def test_file_upload_to_a_foreign_assistant_is_404(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        response = self.client.post(
            f"/api/v1/chat/assistant/{self.assistant.id}/upload-file/",
            {"file": SimpleUploadedFile("evil.txt", b"payload")},
            format="multipart",
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.assistant.files.count(), 1)

    def test_file_replace_on_a_foreign_assistant_is_404(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        response = self.client.post(
            f"/api/v1/chat/assistant/{self.assistant.id}/update-file/",
            {"file": SimpleUploadedFile("evil.txt", b"payload")},
            format="multipart",
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.assistant.files.count(), 1)

    def test_file_retrieve_is_404(self):
        response = self.client.get(f"/api/v1/chat/assistant-files/{self.file.id}/")
        self.assertEqual(response.status_code, 404)

    def test_file_patch_is_404(self):
        response = self.client.patch(
            f"/api/v1/chat/assistant-files/{self.file.id}/",
            {"filename": "renamed.txt"}, format="json",
        )

        self.assertEqual(response.status_code, 404)
        self.file.refresh_from_db()
        self.assertEqual(self.file.filename, "pricing.txt")

    def test_file_delete_is_404(self):
        response = self.client.delete(f"/api/v1/chat/assistant-files/{self.file.id}/")

        self.assertEqual(response.status_code, 404)
        self.assertTrue(AssistantFileUpload.objects.filter(pk=self.file.pk).exists())
        # A 404 that still purged the document from the victim's vector store
        # would be a destructive IDOR wearing a 404 costume.
        self.delete_file.assert_not_called()

    # --- Follow-ups --------------------------------------------------------

    def test_follow_up_config_retrieve_is_404(self):
        response = self.client.get(
            f"/api/v1/chat/assistant/{self.assistant.id}/follow-up/"
        )
        self.assertEqual(response.status_code, 404)

    def test_follow_up_config_patch_is_404(self):
        response = self.client.patch(
            f"/api/v1/chat/assistant/{self.assistant.id}/follow-up/",
            {"is_enabled": True}, format="json",
        )

        self.assertEqual(response.status_code, 404)
        self.config.refresh_from_db()
        self.assertFalse(self.config.is_enabled)

    def test_follow_up_stage_list_under_a_foreign_assistant_is_empty(self):
        response = self.client.get(
            f"/api/v1/chat/assistant/{self.assistant.id}/follow-up/stages/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(_row_ids(response), set())

    def test_follow_up_stage_create_under_a_foreign_assistant_is_404(self):
        response = self.client.post(
            f"/api/v1/chat/assistant/{self.assistant.id}/follow-up/stages/",
            {"stage_number": 2, "delay_hours": 1, "message_template": "spam"},
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.config.stages.count(), 1)

    def test_follow_up_stage_create_on_an_ownerless_assistant_is_404(self):
        """`Assistant.user` is nullable. The create handler used a hand-rolled
        `Q(user=request.user) | Q(user=request.user.created_by)`, and
        `created_by` is None for every ordinary customer — so the second leg
        collapsed to `user IS NULL` and matched every ownerless assistant."""
        from apps.assistant.models import FollowUpConfig

        orphan = Assistant.objects.create(
            name="Orphan Bot", company_name="Orphan Co", user=None,
        )

        response = self.client.post(
            f"/api/v1/chat/assistant/{orphan.id}/follow-up/stages/",
            {"stage_number": 1, "delay_hours": 1, "message_template": "spam"},
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(FollowUpConfig.objects.filter(assistant=orphan).exists())

    def test_ownerless_assistants_are_not_listed(self):
        orphan = Assistant.objects.create(
            name="Orphan Bot", company_name="Orphan Co", user=None,
        )

        response = self.client.get("/api/v1/chat/assistant/")

        self.assertNotIn(str(orphan.id), _row_ids(response))

    def test_follow_up_stage_retrieve_is_404(self):
        response = self.client.get(f"/api/v1/chat/follow-up/stage/{self.stage.id}/")
        self.assertEqual(response.status_code, 404)

    def test_follow_up_stage_patch_is_404(self):
        response = self.client.patch(
            f"/api/v1/chat/follow-up/stage/{self.stage.id}/",
            {"message_template": "spam"}, format="json",
        )

        self.assertEqual(response.status_code, 404)
        self.stage.refresh_from_db()
        self.assertEqual(self.stage.message_template, "Still interested?")

    def test_follow_up_stage_delete_is_404(self):
        from apps.assistant.models import FollowUpStage

        response = self.client.delete(
            f"/api/v1/chat/follow-up/stage/{self.stage.id}/"
        )

        self.assertEqual(response.status_code, 404)
        self.assertTrue(FollowUpStage.objects.filter(pk=self.stage.pk).exists())

    def test_follow_up_logs_under_a_foreign_assistant_are_empty(self):
        response = self.client.get(
            f"/api/v1/chat/assistant/{self.assistant.id}/follow-up/logs/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(_row_ids(response), set())


@IN_MEMORY_STORAGE
class MassAssignmentTests(TenantFixtureMixin, TestCase):
    """A caller may not repoint an object at another tenant through the body.

    Each test is authenticated as the *owner* of the object it edits — the
    ownership check passes, and the only thing standing between the request and
    a cross-tenant write is the serializer's `read_only_fields`.
    """

    def setUp(self):
        self.build_tenants()
        self.client.force_authenticate(self.intruder)

    def test_assistant_owner_cannot_be_reassigned(self):
        response = self.client.patch(
            f"/api/v1/chat/assistant/{self.intruder_assistant.id}/",
            {"user": str(self.victim.id)}, format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.intruder_assistant.refresh_from_db()
        self.assertEqual(self.intruder_assistant.user, self.intruder)

    def test_assistant_cannot_be_created_for_another_user(self):
        response = self.client.post(
            "/api/v1/chat/assistant/",
            {"name": "Planted", "company_name": "X", "user": str(self.victim.id)},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Assistant.objects.get(name="Planted").user, self.intruder)

    def test_conversation_cannot_be_moved_to_another_tenants_assistant(self):
        response = self.client.patch(
            f"/api/v1/chat/conversation/{self.intruder_conversation.id}/",
            {"assistant": str(self.assistant.id)}, format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.intruder_conversation.refresh_from_db()
        self.assertEqual(
            self.intruder_conversation.assistant, self.intruder_assistant
        )

    def test_conversation_create_ignores_an_assistant_in_the_body(self):
        with mock.patch("apps.assistant.serializers.publish_message_to_ws_assistant"):
            response = self.client.post(
                f"/api/v1/chat/assistant/{self.intruder_assistant.id}/conversation/",
                {"user_id": "planted", "assistant": str(self.assistant.id)},
                format="json",
            )

        self.assertEqual(response.status_code, 201)
        created = Conversation.objects.get(user_id="planted")
        self.assertEqual(created.assistant, self.intruder_assistant)

    def test_message_cannot_be_moved_into_another_tenants_conversation(self):
        own_message = Message.objects.create(
            conversation=self.intruder_conversation,
            sender=SenderTypes.USER.value, message_content="mine",
        )

        response = self.client.patch(
            f"/api/v1/chat/message/{own_message.id}/",
            {"conversation": str(self.conversation.id)}, format="json",
        )

        self.assertEqual(response.status_code, 200)
        own_message.refresh_from_db()
        self.assertEqual(own_message.conversation, self.intruder_conversation)

    def test_lead_cannot_be_moved_to_another_tenants_assistant(self):
        own_lead = Lead.objects.create(
            assistant=self.intruder_assistant, full_name="Mine",
        )

        response = self.client.patch(
            f"/api/v1/chat/lead/{own_lead.id}/",
            {"assistant": str(self.assistant.id)}, format="json",
        )

        self.assertEqual(response.status_code, 200)
        own_lead.refresh_from_db()
        self.assertEqual(own_lead.assistant, self.intruder_assistant)

    def test_knowledge_base_file_cannot_be_moved_to_another_tenant(self):
        """`AssistantFileUpload.assistant` was writable and the detail view
        hands the body straight to `ModelSerializer.update()`, so a PATCH filed
        the intruder's document under the victim's assistant — and the next
        DELETE would have called `knowledge_base.delete_file()` against the
        victim's vector store."""
        from django.core.files.uploadedfile import SimpleUploadedFile

        own_file = AssistantFileUpload.objects.create(
            assistant=self.intruder_assistant,
            file=SimpleUploadedFile("mine.txt", b"mine"), filename="mine.txt",
        )

        response = self.client.patch(
            f"/api/v1/chat/assistant-files/{own_file.id}/",
            {"assistant": str(self.assistant.id)}, format="json",
        )

        self.assertEqual(response.status_code, 200)
        own_file.refresh_from_db()
        self.assertEqual(own_file.assistant, self.intruder_assistant)
        self.assertEqual(self.assistant.files.count(), 1)

    def test_follow_up_stage_cannot_be_reparented_to_another_tenants_config(self):
        from apps.assistant.models import FollowUpConfig, FollowUpStage

        own_config = FollowUpConfig.objects.create(
            assistant=self.intruder_assistant,
            target_statuses=[ConversationStatuses.OPEN.value],
        )
        own_stage = FollowUpStage.objects.create(
            config=own_config, stage_number=1, delay_hours=1,
            message_template="mine",
        )

        response = self.client.patch(
            f"/api/v1/chat/follow-up/stage/{own_stage.id}/",
            {"config": str(self.config.id)}, format="json",
        )

        self.assertEqual(response.status_code, 200)
        own_stage.refresh_from_db()
        self.assertEqual(own_stage.config, own_config)

    def test_follow_up_config_cannot_be_pointed_at_another_assistant(self):
        response = self.client.patch(
            f"/api/v1/chat/assistant/{self.intruder_assistant.id}/follow-up/",
            {"is_enabled": True, "assistant": str(self.assistant.id)},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.config.refresh_from_db()
        self.assertFalse(self.config.is_enabled)
        self.assertEqual(
            self.intruder_assistant.follow_up_config.assistant, self.intruder_assistant
        )

    def test_stage_created_under_an_owned_assistant_ignores_a_config_in_the_body(self):
        response = self.client.post(
            f"/api/v1/chat/assistant/{self.intruder_assistant.id}/follow-up/stages/",
            {
                "stage_number": 1, "delay_hours": 1, "message_template": "mine",
                "config": str(self.config.id),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.config.stages.count(), 1)


@IN_MEMORY_STORAGE
class OwnerAccessTests(TenantFixtureMixin, TestCase):
    """The other half of the isolation contract: over-scoping is also a bug.

    Every resource the intruder is locked out of above must still be fully
    usable by the tenant it belongs to — including DELETE.
    """

    def setUp(self):
        self.build_tenants()
        self.client.force_authenticate(self.victim)
        self.delete_store = mock.patch(
            "apps.assistant.views.knowledge_base.delete_store"
        ).start()
        self.delete_file = mock.patch(
            "apps.assistant.views.knowledge_base.delete_file"
        ).start()
        self.addCleanup(mock.patch.stopall)

    def test_owner_lists_and_reads_their_assistant(self):
        listed = self.client.get("/api/v1/chat/assistant/")
        detail = self.client.get(f"/api/v1/chat/assistant/{self.assistant.id}/")

        self.assertEqual(_row_ids(listed), {str(self.assistant.id)})
        self.assertEqual(detail.status_code, 200)

    def test_owner_can_delete_their_assistant(self):
        response = self.client.delete(f"/api/v1/chat/assistant/{self.assistant.id}/")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Assistant.objects.filter(pk=self.assistant.pk).exists())
        self.delete_store.assert_called_once_with("vs_victim")

    def test_owner_can_read_update_and_delete_their_conversation(self):
        base = f"/api/v1/chat/conversation/{self.conversation.id}/"

        self.assertEqual(self.client.get(base).status_code, 200)
        patched = self.client.patch(
            base, {"status": ConversationStatuses.CLOSED.value}, format="json",
        )
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(self.client.delete(base).status_code, 204)
        self.assertFalse(Conversation.objects.filter(pk=self.conversation.pk).exists())

    def test_owner_can_read_and_delete_their_message(self):
        base = f"/api/v1/chat/message/{self.message.id}/"

        self.assertEqual(self.client.get(base).status_code, 200)
        self.assertEqual(self.client.delete(base).status_code, 204)
        self.assertFalse(Message.objects.filter(pk=self.message.pk).exists())

    def test_owner_can_bulk_read_their_messages(self):
        with mock.patch("apps.assistant.views.publish_new_message_to_ws"):
            response = self.client.patch(
                f"/api/v1/chat/conversation/{self.conversation.id}/messages/bulk-read/",
                {"message_ids": [str(self.message.id)]}, format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["updated_count"], 1)
        self.message.refresh_from_db()
        self.assertTrue(self.message.is_read)

    def test_owner_can_read_update_and_delete_their_lead(self):
        base = f"/api/v1/chat/lead/{self.lead.id}/"

        self.assertEqual(self.client.get(base).status_code, 200)
        patched = self.client.patch(base, {"full_name": "Renamed"}, format="json")
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(self.client.delete(base).status_code, 204)
        self.assertFalse(Lead.objects.filter(pk=self.lead.pk).exists())

    def test_owner_can_export_their_leads(self):
        response = self.client.get(
            f"/api/v1/chat/assistant/{self.assistant.id}/export-leads/"
        )
        self.assertEqual(response.status_code, 200)

    def test_owner_can_read_rename_and_delete_their_file(self):
        base = f"/api/v1/chat/assistant-files/{self.file.id}/"

        self.assertEqual(self.client.get(base).status_code, 200)
        patched = self.client.patch(base, {"filename": "renamed.txt"}, format="json")
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(self.client.delete(base).status_code, 200)
        self.assertFalse(AssistantFileUpload.objects.filter(pk=self.file.pk).exists())
        self.delete_file.assert_called_once_with("vs_victim", "file-victim")

    def test_owner_can_manage_their_follow_up_stages(self):
        listed = self.client.get(
            f"/api/v1/chat/assistant/{self.assistant.id}/follow-up/stages/"
        )
        self.assertEqual(_row_ids(listed), {str(self.stage.id)})

        base = f"/api/v1/chat/follow-up/stage/{self.stage.id}/"
        self.assertEqual(self.client.get(base).status_code, 200)
        patched = self.client.patch(base, {"delay_hours": 5}, format="json")
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(self.client.delete(base).status_code, 204)

    def test_owner_can_read_their_follow_up_config_and_logs(self):
        config = self.client.get(
            f"/api/v1/chat/assistant/{self.assistant.id}/follow-up/"
        )
        logs = self.client.get(
            f"/api/v1/chat/assistant/{self.assistant.id}/follow-up/logs/"
        )

        self.assertEqual(config.status_code, 200)
        self.assertEqual(_row_ids(logs), {str(self.log.id)})


@IN_MEMORY_STORAGE
class StaffTenantAccessTests(TenantFixtureMixin, TestCase):
    """A customer's staff account works inside that customer's tenant only.

    `owned_assistants()` adds the `created_by` leg for staff; these assert it
    grants exactly one tenant and not, via `Q(user=None)`, the ownerless ones.
    """

    def setUp(self):
        from apps.shared.addons.enums import UserRoles
        from apps.user.models import User

        self.build_tenants()
        self.staff = User.objects.create(
            username="victim-staff", auth_type="email",
            email="staff@victim.example.com",
            user_role=UserRoles.STAFF.value, created_by=self.victim,
        )
        self.client.force_authenticate(self.staff)

    def test_staff_sees_their_employers_assistants(self):
        response = self.client.get("/api/v1/chat/assistant/")

        self.assertEqual(_row_ids(response), {str(self.assistant.id)})

    def test_staff_can_read_their_employers_conversation(self):
        response = self.client.get(
            f"/api/v1/chat/conversation/{self.conversation.id}/"
        )
        self.assertEqual(response.status_code, 200)

    def test_staff_cannot_reach_another_tenant(self):
        response = self.client.get(
            f"/api/v1/chat/assistant/{self.intruder_assistant.id}/"
        )
        self.assertEqual(response.status_code, 404)

    def test_staff_cannot_delete_the_employers_assistant(self):
        response = self.client.delete(
            f"/api/v1/chat/assistant/{self.assistant.id}/"
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Assistant.objects.filter(pk=self.assistant.pk).exists())
