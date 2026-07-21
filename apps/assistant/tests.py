"""Tests for the dashboard chat and knowledge-base file upload.

Both paths used to raise AttributeError against methods that no longer existed on
`assistant_service`; the first test in each class is the regression for that.
"""
from unittest import mock

from django.test import TestCase

from apps.assistant.models import (
    Assistant, AssistantFileUpload, Conversation, Message,
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
