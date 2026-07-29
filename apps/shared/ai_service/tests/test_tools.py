"""Tool handler tests — the side effects the agent is allowed to have."""
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.assistant.models import FollowUpConfig, FollowUpLog, FollowUpStage, Message
from apps.integration.models import Integration, TelegramGroupIntegration
from apps.shared.addons.enums import ConversationStatuses, IntegrationTypes, SenderTypes
from apps.shared.ai_service import tools

from .factories import make_assistant, make_conversation


class BuildToolsTests(TestCase):
    def setUp(self):
        self.assistant = make_assistant()

    def names(self, assistant):
        return [t.get("name") or t.get("type") for t in tools.build_tools(assistant)]

    def test_core_tools_are_always_offered(self):
        offered = self.names(self.assistant)

        for name in ("create_lead", "escalate_to_human", "get_conversation_summary"):
            self.assertIn(name, offered)

    def test_follow_up_appears_only_when_enabled(self):
        self.assertNotIn("schedule_follow_up", self.names(self.assistant))

        FollowUpConfig.objects.create(assistant=self.assistant, is_enabled=True)
        self.assistant.refresh_from_db()

        self.assertIn("schedule_follow_up", self.names(self.assistant))

    def test_disabled_follow_up_config_does_not_offer_the_tool(self):
        FollowUpConfig.objects.create(assistant=self.assistant, is_enabled=False)
        self.assistant.refresh_from_db()

        self.assertNotIn("schedule_follow_up", self.names(self.assistant))


class CreateLeadTests(TestCase):
    def setUp(self):
        self.assistant = make_assistant()
        self.conversation = make_conversation(self.assistant)
        self.args = {
            "full_name": "Aziz Karimov",
            "phone_number": "+998901234567",
            "product": "iPhone 15 Pro, black",
        }

    def test_lead_is_created_with_conversation_context(self):
        result = tools.execute("create_lead", self.assistant, self.conversation, self.args)

        lead = self.assistant.leads.get()
        self.assertEqual(result["status"], "recorded")
        self.assertEqual(lead.full_name, "Aziz Karimov")
        self.assertEqual(lead.platform, "telegram")
        self.assertEqual(lead.username, "customer")
        self.assertEqual(lead.metadata, self.args)

    def test_only_approved_groups_are_notified(self):
        integration = Integration.objects.create(
            assistant=self.assistant,
            integration_type=IntegrationTypes.TELEGRAM.value,
            api_token="bot-token",
        )
        TelegramGroupIntegration.objects.create(
            integration=integration, group_id="-100", is_approved=True
        )
        TelegramGroupIntegration.objects.create(
            integration=integration, group_id="-200", is_approved=False
        )

        with mock.patch("apps.shared.addons.telegram.send_telegram_message") as send:
            tools.execute("create_lead", self.assistant, self.conversation, self.args)

        self.assertEqual(send.call_count, 1)
        self.assertEqual(send.call_args.args[0], "-100")

    def test_assistant_without_telegram_still_records_the_lead(self):
        """Finding 2.10: this used to raise after the Lead row was written."""
        result = tools.execute("create_lead", self.assistant, self.conversation, self.args)

        self.assertEqual(result["status"], "recorded")
        self.assertEqual(self.assistant.leads.count(), 1)

    def test_a_failing_notification_does_not_lose_the_lead(self):
        integration = Integration.objects.create(
            assistant=self.assistant,
            integration_type=IntegrationTypes.TELEGRAM.value,
            api_token="bot-token",
        )
        TelegramGroupIntegration.objects.create(
            integration=integration, group_id="-100", is_approved=True
        )

        with mock.patch(
            "apps.shared.addons.telegram.send_telegram_message",
            side_effect=RuntimeError("telegram down"),
        ):
            result = tools.execute("create_lead", self.assistant, self.conversation, self.args)

        self.assertEqual(result["status"], "recorded")
        self.assertEqual(self.assistant.leads.count(), 1)


class EscalateTests(TestCase):
    def setUp(self):
        self.assistant = make_assistant()
        self.conversation = make_conversation(self.assistant)

    def test_escalation_changes_the_conversation_status(self):
        with mock.patch("apps.shared.addons.redis.publish_message_to_ws_assistant"):
            result = tools.execute(
                "escalate_to_human", self.assistant, self.conversation,
                {"reason": "Customer asked for a manager"},
            )

        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.status, ConversationStatuses.ESCALATED.value)
        self.assertEqual(result["status"], "escalated")

    def test_escalation_survives_a_websocket_failure(self):
        with mock.patch(
            "apps.shared.addons.redis.publish_message_to_ws_assistant",
            side_effect=ConnectionError("down"),
        ):
            result = tools.execute(
                "escalate_to_human", self.assistant, self.conversation, {"reason": "x"}
            )

        self.assertEqual(result["status"], "escalated")
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.status, ConversationStatuses.ESCALATED.value)


class SummaryTests(TestCase):
    def setUp(self):
        self.assistant = make_assistant()
        self.conversation = make_conversation(self.assistant)
        for i in range(5):
            Message.objects.create(
                conversation=self.conversation,
                sender=SenderTypes.USER.value,
                message_content=f"message {i}",
            )

    def test_summary_returns_messages_oldest_first(self):
        result = tools.execute("get_conversation_summary", self.assistant, self.conversation, {})

        contents = [m["content"] for m in result["messages"]]
        self.assertEqual(contents, [f"message {i}" for i in range(5)])

    def test_limit_is_respected_and_returns_the_most_recent(self):
        result = tools.execute(
            "get_conversation_summary", self.assistant, self.conversation, {"limit": 2}
        )

        self.assertEqual([m["content"] for m in result["messages"]], ["message 3", "message 4"])

    def test_absurd_limits_are_clamped(self):
        result = tools.execute(
            "get_conversation_summary", self.assistant, self.conversation, {"limit": 10_000}
        )

        self.assertLessEqual(len(result["messages"]), tools.MAX_SUMMARY_MESSAGES)

    def test_non_numeric_limit_falls_back_to_the_default(self):
        result = tools.execute(
            "get_conversation_summary", self.assistant, self.conversation, {"limit": "lots"}
        )

        self.assertEqual(len(result["messages"]), 5)


class FollowUpTests(TestCase):
    def setUp(self):
        self.assistant = make_assistant()
        self.conversation = make_conversation(self.assistant)

    def test_follow_up_is_scheduled_at_the_first_active_stage(self):
        config = FollowUpConfig.objects.create(assistant=self.assistant, is_enabled=True)
        FollowUpStage.objects.create(
            config=config, stage_number=1, delay_hours=24, message_template="Still there?"
        )
        FollowUpStage.objects.create(
            config=config, stage_number=2, delay_hours=72, message_template="Last call"
        )
        self.assistant.refresh_from_db()

        result = tools.execute(
            "schedule_follow_up", self.assistant, self.conversation, {"reason": "thinking"}
        )

        log = FollowUpLog.objects.get(conversation=self.conversation)
        self.assertEqual(result["in_hours"], 24)
        self.assertEqual(log.stage.stage_number, 1)
        self.assertGreater(log.scheduled_at, timezone.now())

    def test_inactive_first_stage_is_skipped(self):
        config = FollowUpConfig.objects.create(assistant=self.assistant, is_enabled=True)
        FollowUpStage.objects.create(
            config=config, stage_number=1, delay_hours=24,
            message_template="x", is_active=False,
        )
        FollowUpStage.objects.create(
            config=config, stage_number=2, delay_hours=72, message_template="y"
        )
        self.assistant.refresh_from_db()

        result = tools.execute(
            "schedule_follow_up", self.assistant, self.conversation, {"reason": "thinking"}
        )

        self.assertEqual(result["in_hours"], 72)

    def test_missing_configuration_is_reported_as_an_error(self):
        result = tools.execute(
            "schedule_follow_up", self.assistant, self.conversation, {"reason": "thinking"}
        )

        self.assertIn("error", result)
        self.assertFalse(FollowUpLog.objects.exists())

    def test_enabled_config_without_stages_is_reported_as_an_error(self):
        FollowUpConfig.objects.create(assistant=self.assistant, is_enabled=True)
        self.assistant.refresh_from_db()

        result = tools.execute(
            "schedule_follow_up", self.assistant, self.conversation, {"reason": "thinking"}
        )

        self.assertIn("error", result)


class ExecuteTests(TestCase):
    def setUp(self):
        self.assistant = make_assistant()
        self.conversation = make_conversation(self.assistant)

    def test_unknown_tool_returns_an_error(self):
        result = tools.execute("nope", self.assistant, self.conversation, {})

        self.assertIn("Unknown tool", result["error"])

    def test_handler_exceptions_are_converted_to_errors(self):
        boom = mock.Mock(side_effect=RuntimeError("db is on fire"))
        with mock.patch.dict(tools.TOOL_HANDLERS, {"create_lead": boom}):
            result = tools.execute("create_lead", self.assistant, self.conversation, {})

        self.assertIn("db is on fire", result["error"])

    def test_none_arguments_are_treated_as_empty(self):
        result = tools.execute("get_conversation_summary", self.assistant, self.conversation, None)

        self.assertEqual(result["messages"], [])
