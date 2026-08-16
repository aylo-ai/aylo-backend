"""Agent loop tests.

Every test here runs offline against a fake OpenAI client. Tests named after a
finding number are regressions for the bugs listed in the investigation report.
"""
from unittest import mock

from django.test import TestCase

from apps.shared.ai_service import agent as agent_module
from apps.shared.ai_service.agent import Agent, AgentResult

from .factories import (
    bad_request,
    make_assistant,
    make_conversation,
    make_response,
    rate_limited,
    server_error,
)


class AgentTestCase(TestCase):
    """Base class that stubs out OpenAI, Redis and sleeping."""

    def setUp(self):
        self.assistant = make_assistant()
        self.conversation = make_conversation(self.assistant)

        self.client = mock.MagicMock()
        client_patch = mock.patch.object(
            agent_module, "get_client", return_value=self.client
        )
        client_patch.start()
        self.addCleanup(client_patch.stop)

        redis_patch = mock.patch("apps.shared.addons.redis.redis_client")
        self.redis = redis_patch.start()
        self.redis.get.return_value = None
        self.addCleanup(redis_patch.stop)

        sleep_patch = mock.patch.object(agent_module.time, "sleep")
        self.sleep = sleep_patch.start()
        self.addCleanup(sleep_patch.stop)

        self.agent = Agent()

    # helpers ------------------------------------------------------------

    def set_responses(self, *responses):
        self.client.responses.create.side_effect = list(responses)

    @property
    def calls(self):
        return self.client.responses.create.call_args_list

    def kwargs_at(self, index):
        return self.calls[index].kwargs

    def run_turn(self, text="Hello") -> AgentResult:
        return self.agent.run(self.assistant, self.conversation, text)


class ChainTests(AgentTestCase):
    def test_first_turn_sends_instructions(self):
        self.set_responses(make_response(text="Hi there!"))

        result = self.run_turn()

        self.assertEqual(result.text, "Hi there!")
        kwargs = self.kwargs_at(0)
        self.assertNotIn("previous_response_id", kwargs)
        self.assertEqual(kwargs["input"][0]["role"], "developer")
        self.assertIn("Repli", kwargs["input"][0]["content"])

    def test_follow_up_reuses_chain_without_resending_instructions(self):
        self.set_responses(
            make_response(response_id="resp_1", text="Hi!"),
            make_response(response_id="resp_2", text="Sure."),
        )

        self.run_turn("Hello")
        self.conversation.refresh_from_db()
        self.run_turn("Do you have iPhones?")

        second = self.kwargs_at(1)
        self.assertEqual(second["previous_response_id"], "resp_1")
        self.assertEqual([m["role"] for m in second["input"]], ["user"])

    def test_chain_is_persisted_to_the_database(self):
        """Postgres is the source of truth, so a Redis flush cannot lose context."""
        self.set_responses(make_response(response_id="resp_9", text="Hi!"))

        self.run_turn()

        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.previous_response_id, "resp_9")
        self.assertIsNotNone(self.conversation.instructions_version)

    def test_editing_the_assistant_restarts_the_chain(self):
        """Finding 2.7: prompt edits used to take up to 24h to apply."""
        self.set_responses(
            make_response(response_id="resp_1", text="Hi!"),
            make_response(response_id="resp_2", text="Updated!"),
        )
        self.run_turn("Hello")
        self.conversation.refresh_from_db()

        self.assistant.system_prompt = "You sell laptops now."
        self.assistant.save()

        self.run_turn("Still there?")

        second = self.kwargs_at(1)
        self.assertNotIn("previous_response_id", second)
        self.assertIn("laptops", second["input"][0]["content"])

    def test_stale_chain_is_dropped_and_retried(self):
        """Finding 2.4: a bad response id used to brick the chat for 24 hours."""
        self.conversation.previous_response_id = "resp_gone"
        self.conversation.instructions_version = self.assistant.updated_time
        self.conversation.save()

        self.set_responses(
            bad_request("Previous response with id 'resp_gone' not found."),
            make_response(response_id="resp_new", text="Back online."),
        )

        result = self.run_turn("Hello?")

        self.assertEqual(result.text, "Back online.")
        self.assertFalse(result.used_fallback)
        self.assertNotIn("previous_response_id", self.kwargs_at(1))
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.previous_response_id, "resp_new")

    def test_unrelated_bad_request_is_not_retried(self):
        self.conversation.previous_response_id = "resp_1"
        self.conversation.instructions_version = self.assistant.updated_time
        self.conversation.save()
        self.set_responses(bad_request("Unsupported parameter: 'temperature'"))

        result = self.run_turn()

        self.assertTrue(result.used_fallback)
        self.assertEqual(len(self.calls), 1)


class ToolLoopTests(AgentTestCase):
    def test_search_then_lead_in_one_turn(self):
        """Finding 2.6: only one round of tool use was possible before."""
        self.set_responses(
            make_response(
                response_id="r1",
                function_calls=[(
                    "create_lead",
                    {"full_name": "Aziz", "phone_number": "+998901234567", "product": "iPhone 15"},
                    "call_1",
                )],
            ),
            make_response(
                response_id="r2",
                function_calls=[("get_conversation_summary", {"limit": 5}, "call_2")],
            ),
            make_response(response_id="r3", text="All set, Aziz!"),
        )

        result = self.run_turn("I'll take it. Aziz, +998901234567")

        self.assertEqual(result.text, "All set, Aziz!")
        self.assertEqual(result.tool_calls, ["create_lead", "get_conversation_summary"])
        self.assertEqual(self.assistant.leads.count(), 1)

    def test_tools_are_passed_on_every_call(self):
        """The old code dropped `tools` after the first hop, ending the loop early."""
        self.set_responses(
            make_response(
                response_id="r1",
                function_calls=[("escalate_to_human", {"reason": "asked"}, "c1")],
            ),
            make_response(response_id="r2", text="A colleague will help."),
        )

        self.run_turn("I want a human")

        for kwargs in (self.kwargs_at(0), self.kwargs_at(1)):
            self.assertTrue(kwargs["tools"])
            self.assertEqual(kwargs["temperature"], agent_module.TEMPERATURE)

    def test_tool_output_is_fed_back_to_the_model(self):
        self.set_responses(
            make_response(
                response_id="r1",
                function_calls=[("escalate_to_human", {"reason": "angry"}, "call_x")],
            ),
            make_response(response_id="r2", text="Handing over."),
        )

        self.run_turn("This is unacceptable")

        payload = self.kwargs_at(1)["input"]
        self.assertEqual(payload[0]["type"], "function_call_output")
        self.assertEqual(payload[0]["call_id"], "call_x")
        self.assertIn("escalated", payload[0]["output"])

    def test_loop_stops_at_the_iteration_cap(self):
        looping = [
            make_response(
                response_id=f"r{i}",
                function_calls=[("get_conversation_summary", {}, f"c{i}")],
            )
            for i in range(agent_module.MAX_TOOL_ITERATIONS)
        ]
        self.set_responses(*looping, make_response(response_id="final", text="Here's what I know."))

        result = self.run_turn("Loop forever")

        self.assertEqual(result.text, "Here's what I know.")
        self.assertEqual(len(self.calls), agent_module.MAX_TOOL_ITERATIONS + 1)
        self.assertEqual(self.kwargs_at(-1)["tool_choice"], "none")

    def test_failing_tool_is_reported_to_the_model_not_raised(self):
        self.set_responses(
            make_response(
                response_id="r1",
                function_calls=[("create_lead", {"full_name": "X"}, "c1")],
            ),
            make_response(response_id="r2", text="Sorry, something went wrong."),
        )
        from apps.assistant import ai_tools

        boom = mock.Mock(side_effect=RuntimeError("db down"))
        agent_module.tool_registry.register("create_lead", ai_tools.CREATE_LEAD_SCHEMA, boom)
        self.addCleanup(ai_tools.register_tools)

        result = self.run_turn("Book it")

        self.assertFalse(result.used_fallback)
        self.assertIn("error", self.kwargs_at(1)["input"][0]["output"])

    def test_unknown_tool_does_not_crash_the_turn(self):
        self.set_responses(
            make_response(
                response_id="r1", function_calls=[("do_magic", {}, "c1")]
            ),
            make_response(response_id="r2", text="I can't do that."),
        )

        result = self.run_turn("Do magic")

        self.assertEqual(result.text, "I can't do that.")
        self.assertIn("Unknown tool", self.kwargs_at(1)["input"][0]["output"])


class ToolAssemblyTests(AgentTestCase):
    def test_missing_vector_id_omits_file_search(self):
        """Finding 2.2: the first turn used to crash when vector_id was None."""
        self.assistant.vector_id = None
        self.assistant.save()
        self.set_responses(make_response(text="Hello!"))

        result = self.run_turn()

        self.assertEqual(result.text, "Hello!")
        types = [t.get("type") for t in self.kwargs_at(0)["tools"]]
        self.assertNotIn("file_search", types)

    def test_legacy_gemini_vector_id_is_not_sent_to_openai(self):
        """OpenAI rejects `fileSearchStores/...` outright; the assistant must keep
        answering while its knowledge base is re-indexed."""
        self.assistant.vector_id = "fileSearchStores/t1np2pyb1ciw-8ixt75wk0kd5"
        self.assistant.save()
        self.set_responses(make_response(text="Hello!"))

        result = self.run_turn()

        self.assertEqual(result.text, "Hello!")
        self.assertFalse(result.used_fallback)
        types = [t.get("type") for t in self.kwargs_at(0)["tools"]]
        self.assertNotIn("file_search", types)

    def test_vector_id_enables_file_search(self):
        self.set_responses(make_response(text="Hello!"))

        self.run_turn()

        file_search = next(
            t for t in self.kwargs_at(0)["tools"] if t.get("type") == "file_search"
        )
        self.assertEqual(file_search["vector_store_ids"], ["vs_test"])

    def test_web_search_follows_the_assistant_flag(self):
        self.set_responses(make_response(text="a"), make_response(text="b"))

        self.run_turn()
        self.assertNotIn("web_search", [t.get("type") for t in self.kwargs_at(0)["tools"]])

        self.assistant.web_search_tool = True
        self.assistant.save()
        self.run_turn()
        self.assertIn("web_search", [t.get("type") for t in self.kwargs_at(1)["tools"]])

    def test_follow_up_tool_requires_configuration(self):
        self.set_responses(make_response(text="a"))

        self.run_turn()

        names = [t.get("name") for t in self.kwargs_at(0)["tools"]]
        self.assertNotIn("schedule_follow_up", names)


class ResilienceTests(AgentTestCase):
    def test_run_never_raises_and_returns_the_fallback(self):
        """Finding 2.3: an exception here used to trigger a Celery retry that
        stored the customer's message a second time."""
        self.client.responses.create.side_effect = ValueError("kaboom")

        result = self.run_turn()

        self.assertEqual(result.text, self.assistant.fallback_message)
        self.assertTrue(result.used_fallback)

    def test_rate_limit_is_retried_then_succeeds(self):
        self.set_responses(rate_limited(), rate_limited(), make_response(text="Finally."))

        result = self.run_turn()

        self.assertEqual(result.text, "Finally.")
        self.assertEqual(self.sleep.call_count, 2)

    def test_server_errors_are_retried(self):
        self.set_responses(server_error(), make_response(text="Recovered."))

        self.assertEqual(self.run_turn().text, "Recovered.")

    def test_retries_give_up_after_the_limit(self):
        self.client.responses.create.side_effect = rate_limited()

        result = self.run_turn()

        self.assertTrue(result.used_fallback)
        self.assertEqual(len(self.calls), agent_module.MAX_ATTEMPTS)

    def test_empty_output_returns_the_fallback(self):
        """Finding 2.5: the bot used to go silent instead of saying anything."""
        self.set_responses(make_response(text=None))

        result = self.run_turn()

        self.assertEqual(result.text, self.assistant.fallback_message)
        self.assertTrue(result.used_fallback)

    def test_assistant_without_a_fallback_still_says_something(self):
        self.assistant.fallback_message = ""
        self.assistant.save()
        self.client.responses.create.side_effect = ValueError("kaboom")

        self.assertEqual(self.run_turn().text, agent_module.DEFAULT_FALLBACK)

    def test_redis_outage_does_not_break_the_turn(self):
        self.redis.get.side_effect = ConnectionError("redis down")
        self.redis.set.side_effect = ConnectionError("redis down")
        self.set_responses(make_response(response_id="r1", text="Still working."))

        result = self.run_turn()

        self.assertEqual(result.text, "Still working.")
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.previous_response_id, "r1")


class OutputTests(AgentTestCase):
    def test_plain_text_is_passed_through_untouched(self):
        self.set_responses(make_response(text="Narxi 12 000 000 so'm 😊"))

        self.assertEqual(self.run_turn().text, "Narxi 12 000 000 so'm 😊")

    def test_json_envelope_is_unwrapped_not_sent_raw(self):
        """Finding 2.8: customers used to receive raw JSON."""
        self.set_responses(
            make_response(text='{"intent": "get_price", "entities": {}, "reply": "It costs $999."}')
        )

        self.assertEqual(self.run_turn().text, "It costs $999.")

    def test_fenced_json_envelope_is_unwrapped(self):
        self.set_responses(
            make_response(text='```json\n{"reply": "Hi!", "intent": "greeting"}\n```')
        )

        self.assertEqual(self.run_turn().text, "Hi!")

    def test_json_without_a_reply_field_is_left_alone(self):
        self.set_responses(make_response(text='{"price": 999}'))

        self.assertEqual(self.run_turn().text, '{"price": 999}')

    def test_text_that_merely_contains_braces_is_untouched(self):
        self.set_responses(make_response(text="Use {size} to pick a size."))

        self.assertEqual(self.run_turn().text, "Use {size} to pick a size.")


class UsageTests(AgentTestCase):
    def test_tokens_are_summed_across_the_whole_loop(self):
        """Finding 2.9: only the last call's usage used to be recorded."""
        self.set_responses(
            make_response(
                response_id="r1",
                function_calls=[("get_conversation_summary", {}, "c1")],
                input_tokens=100, output_tokens=20,
            ),
            make_response(response_id="r2", text="Done.", input_tokens=150, output_tokens=30),
        )

        result = self.run_turn()

        self.assertEqual(result.input_tokens, 250)
        self.assertEqual(result.output_tokens, 50)

    def test_cached_tokens_are_not_billed(self):
        self.set_responses(
            make_response(text="Hi.", input_tokens=1000, cached_tokens=800, output_tokens=10)
        )

        self.assertEqual(self.run_turn().input_tokens, 200)

    def test_missing_usage_does_not_crash(self):
        response = make_response(text="Hi.")
        response.usage = None
        self.set_responses(response)

        result = self.run_turn()

        self.assertEqual(result.text, "Hi.")
        self.assertEqual(result.input_tokens, 0)


class RespondTests(AgentTestCase):
    def test_respond_stores_and_publishes_the_reply(self):
        self.set_responses(make_response(text="Hello!"))

        with mock.patch("apps.shared.addons.redis.publish_message_to_ws") as publish:
            text = agent_module.respond(self.assistant, self.conversation, "Hi")

        self.assertEqual(text, "Hello!")
        message = self.conversation.messages.get()
        self.assertEqual(message.message_content, "Hello!")
        self.assertEqual(message.sender, "assistant")
        publish.assert_called_once()

    def test_respond_stores_the_fallback_when_the_api_fails(self):
        self.client.responses.create.side_effect = ValueError("kaboom")

        with mock.patch("apps.shared.addons.redis.publish_message_to_ws"):
            text = agent_module.respond(self.assistant, self.conversation, "Hi")

        self.assertEqual(text, self.assistant.fallback_message)
        self.assertEqual(self.conversation.messages.count(), 1)

    def test_respond_survives_a_websocket_failure(self):
        self.set_responses(make_response(text="Hello!"))

        with mock.patch(
            "apps.shared.addons.redis.publish_message_to_ws", side_effect=ConnectionError("down")
        ):
            text = agent_module.respond(self.assistant, self.conversation, "Hi")

        self.assertEqual(text, "Hello!")
