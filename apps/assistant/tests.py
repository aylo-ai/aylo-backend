"""Tests for the dashboard chat and knowledge-base file upload.

Both paths used to raise AttributeError against methods that no longer existed on
`assistant_service`; the first test in each class is the regression for that.
"""
from unittest import mock

from django.test import TestCase

from apps.assistant.models import (
    Assistant, AssistantFileUpload, Conversation, Lead, Message,
)
from apps.assistant.serializers import AssistantFileUploadSerializer, MessageSerializer
from shared.addons.enums import ConversationStatuses, SenderTypes, SubscriptionStatuses
from shared.ai_service.agent import AgentResult


def make_subscribed_user():
    """A user with an active subscription — the serializers validate one."""
    from apps.payment.models import Subscription
    from apps.user.models import User

    subscription = Subscription.objects.create(
        status=SubscriptionStatuses.ACTIVE.value, remained_request_count=1000,
    )
    return User.objects.create(
        username="owner", auth_type="email", email="owner@example.com",
        subscription=subscription,
    )


class MessageSerializerTests(TestCase):
    """POST conversations/<id>/messages/ — the dashboard / website chat."""

    def setUp(self):
        self.assistant = Assistant.objects.create(
            name="Repli Bot", company_name="Repli",
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
            name="Repli Bot", company_name="Repli", vector_id="vs_test", ai_enabled=False,
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
        return Assistant.objects.create(name="Bot", company_name="Repli", user=user)

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


class FileUploadTests(TestCase):
    def setUp(self):
        self.assistant = Assistant.objects.create(
            name="Repli Bot", company_name="Repli", user=make_subscribed_user(),
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
            name="Repli Bot", company_name="Repli", user=self.owner,
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
            name="Repli Bot", company_name="Repli", vector_id="vs_test",
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
