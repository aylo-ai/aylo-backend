from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings

from apps.shared.addons.enums import AgentRunOutcomes
from apps.shared.ai_service import agent as agent_module
from apps.shared.ai_service import pipeline, pricing, routing
from apps.shared.ai_service.telemetry import RunRecorder
from apps.shared.models import AgentRun, AgentRunStep

from .factories import make_response
from .test_agent import AgentTestCase

TIERS = {"fast": "gpt-4o-mini", "standard": "gpt-4o", "deep": "gpt-4o"}
DISTINCT_TIERS = {"fast": "gpt-4o-mini", "standard": "gpt-4o", "deep": "o3-deep"}


class PricingTests(TestCase):
    def test_cost_uses_separate_input_and_output_rates(self):
        self.assertAlmostEqual(
            pricing.cost_usd("gpt-4o", 1_000_000, 1_000_000), 12.50, places=6
        )

    def test_cached_input_is_discounted_not_free(self):
        cost = pricing.cost_usd("gpt-4o", 0, 0, cached_input_tokens=1_000_000)
        self.assertAlmostEqual(cost, 1.25, places=6)
        self.assertGreater(cost, 0, "cached tokens are discounted, not free")

    def test_an_unknown_model_costs_none_not_zero(self):
        self.assertIsNone(pricing.cost_usd("not-a-real-model", 1000, 1000))

    def test_an_unknown_leg_makes_the_whole_total_unknown(self):
        self.assertIsNone(pricing.add_costs(0.5, None, 0.25))
        self.assertAlmostEqual(pricing.add_costs(0.5, 0.25), 0.75, places=6)

    def test_the_cheap_tier_is_actually_cheaper(self):
        fast = pricing.cost_usd(TIERS["fast"], 10_000, 1_000)
        standard = pricing.cost_usd(TIERS["standard"], 10_000, 1_000)
        self.assertLess(fast, standard)


@override_settings(AI_TIER_MODELS=DISTINCT_TIERS, AI_TIER_ROUTING_ENABLED=True)
class RoutingTests(TestCase):
    def test_a_short_message_starts_on_the_cheap_tier(self):
        decision = routing.choose(mock.Mock(model_tier=""), None, "salom")
        self.assertIs(decision.tier, routing.Tier.FAST)
        self.assertEqual(decision.model, DISTINCT_TIERS["fast"])

    def test_a_long_message_starts_higher(self):
        decision = routing.choose(mock.Mock(model_tier=""), None, "x" * 500)
        self.assertIs(decision.tier, routing.Tier.STANDARD)
        self.assertIn("long input", decision.reason)

    def test_an_assistant_can_pin_its_tier(self):
        decision = routing.choose(mock.Mock(model_tier="deep"), None, "hi")
        self.assertIs(decision.tier, routing.Tier.DEEP)

    def test_escalation_walks_up_one_tier(self):
        step = routing.escalate(routing.Tier.FAST, "empty reply")
        self.assertIs(step.tier, routing.Tier.STANDARD)
        self.assertEqual(step.reason, "empty reply")

    def test_escalation_stops_at_the_top(self):
        self.assertIsNone(routing.escalate(routing.Tier.DEEP, "empty reply"))

    @override_settings(AI_TIER_MODELS=TIERS)
    def test_escalation_skips_a_tier_pointing_at_the_same_model(self):
        self.assertIsNone(routing.escalate(routing.Tier.STANDARD, "empty reply"))

    @override_settings(AI_TIER_ROUTING_ENABLED=False)
    def test_the_kill_switch_sends_everything_to_standard(self):
        decision = routing.choose(mock.Mock(model_tier=""), None, "salom")
        self.assertIs(decision.tier, routing.Tier.STANDARD)

    @override_settings(AI_TIER_MODELS={"fast": "", "standard": "gpt-4o", "deep": "o3-deep"})
    def test_a_missing_model_falls_back_instead_of_failing_the_turn(self):
        self.assertEqual(routing.model_for(routing.Tier.FAST), "o3-deep")


@override_settings(AI_TIER_MODELS=DISTINCT_TIERS, AI_TIER_ROUTING_ENABLED=True)
class EscalationTests(AgentTestCase):
    def test_a_good_cheap_answer_is_not_escalated(self):
        self.set_responses(make_response(response_id="r1", text="Ish vaqtimiz 9:00-18:00."))

        result = self.run_turn("ish vaqti")

        self.assertEqual(len(self.calls), 1)
        self.assertFalse(result.escalated)
        self.assertEqual(self.kwargs_at(0)["model"], DISTINCT_TIERS["fast"])

    def test_an_empty_cheap_answer_is_retried_on_a_stronger_model(self):
        self.set_responses(
            make_response(response_id="r1", text=""),
            make_response(response_id="r2", text="Ish vaqtimiz 9:00-18:00."),
        )

        result = self.run_turn("ish vaqti")

        self.assertEqual(result.text, "Ish vaqtimiz 9:00-18:00.")
        self.assertTrue(result.escalated)
        self.assertEqual(self.kwargs_at(0)["model"], DISTINCT_TIERS["fast"])
        self.assertEqual(self.kwargs_at(1)["model"], DISTINCT_TIERS["standard"])

    def test_the_retry_abandons_the_failed_branch(self):
        self.set_responses(
            make_response(response_id="r1", text=""),
            make_response(response_id="r2", text="Better."),
        )

        self.run_turn("ish vaqti")

        self.assertNotIn("previous_response_id", self.kwargs_at(1))

    def test_a_still_empty_answer_at_the_top_tier_falls_back(self):
        self.set_responses(
            make_response(response_id="r1", text=""),
            make_response(response_id="r2", text=""),
            make_response(response_id="r3", text=""),
        )

        result = self.run_turn("ish vaqti")

        self.assertTrue(result.used_fallback)

    def test_the_tool_cap_does_not_escalate_by_default(self):
        looping = [
            make_response(
                response_id=f"r{i}",
                function_calls=[("get_conversation_summary", {}, f"c{i}")],
            )
            for i in range(agent_module.MAX_TOOL_ITERATIONS)
        ]
        self.set_responses(*looping, make_response(response_id="final", text="Known."))

        result = self.run_turn("Loop")

        self.assertEqual(result.text, "Known.")
        self.assertFalse(result.escalated)

    @override_settings(AI_ESCALATE_ON_TOOL_CAP=True)
    def test_the_tool_cap_escalates_when_that_is_switched_on(self):
        looping = [
            make_response(
                response_id=f"r{i}",
                function_calls=[("get_conversation_summary", {}, f"c{i}")],
            )
            for i in range(agent_module.MAX_TOOL_ITERATIONS)
        ]
        self.set_responses(
            *looping,
            make_response(response_id="final", text="Weak."),
            make_response(response_id="strong", text="Strong."),
        )

        result = self.run_turn("Loop")

        self.assertTrue(result.escalated)
        self.assertEqual(result.text, "Strong.")


@override_settings(AI_TIER_MODELS=DISTINCT_TIERS, AI_TIER_ROUTING_ENABLED=True)
class RunTelemetryTests(AgentTestCase):
    def test_a_turn_writes_one_run_row_with_timing_and_cost(self):
        self.set_responses(make_response(response_id="r1", text="Salom!"))

        self.run_turn("salom")

        run = AgentRun.objects.get()
        self.assertEqual(run.outcome, AgentRunOutcomes.OK.value)
        self.assertEqual(run.final_model, DISTINCT_TIERS["fast"])
        self.assertEqual(run.api_calls, 2, "triage + act; retrieve is not a model call")
        self.assertEqual(run.plan["complexity"], "normal")
        self.assertFalse(run.escalated)
        self.assertGreaterEqual(run.duration_ms, 0)

    def test_each_model_call_gets_its_own_step_row(self):
        self.set_responses(
            make_response(
                response_id="r1",
                function_calls=[("get_conversation_summary", {}, "c1")],
            ),
            make_response(response_id="r2", text="Done."),
        )

        self.run_turn("summarise")

        run = AgentRun.objects.get()
        steps = list(AgentRunStep.objects.filter(run=run).order_by("sequence"))
        self.assertEqual(
            [step.stage for step in steps],
            ["triage", "retrieve", "act", "act"],
            "every stage gets its own row so a slow turn can be attributed",
        )
        act = [step for step in steps if step.stage == "act"]
        self.assertEqual(act[0].tool_calls, ["get_conversation_summary"])
        self.assertEqual(act[1].tool_calls, [])

    def test_an_escalated_turn_records_both_tiers_and_the_reason(self):
        self.set_responses(
            make_response(response_id="r1", text=""),
            make_response(response_id="r2", text="Better."),
        )

        self.run_turn("ish vaqti")

        run = AgentRun.objects.get()
        self.assertTrue(run.escalated)
        self.assertEqual(run.initial_tier, routing.Tier.FAST.value)
        self.assertEqual(run.final_tier, routing.Tier.STANDARD.value)
        self.assertEqual(run.escalation_reason, "empty reply")
        self.assertEqual(run.api_calls, 3, "triage + the failed act + the escalated act")

    def test_a_crashed_turn_is_still_recorded(self):
        self.client.responses.create.side_effect = RuntimeError("boom")

        self.run_turn("salom")

        run = AgentRun.objects.get()
        self.assertEqual(run.outcome, AgentRunOutcomes.ERROR.value)
        self.assertIn("boom", run.error)

    def test_an_unpriced_model_records_null_cost_not_zero(self):
        with override_settings(AI_TIER_MODELS={**DISTINCT_TIERS, "fast": "mystery-model"}):
            self.set_responses(make_response(response_id="r1", text="Salom!"))
            self.run_turn("salom")

        self.assertIsNone(AgentRun.objects.get().cost_usd)

    def test_cost_is_recorded_for_a_priced_model(self):
        self.set_responses(
            make_response(response_id="r1", text="Salom!", input_tokens=1000, output_tokens=500)
        )

        self.run_turn("salom")

        run = AgentRun.objects.get()
        self.assertIsNotNone(run.cost_usd)
        self.assertGreater(run.cost_usd, Decimal("0"))

    def test_telemetry_failure_never_breaks_the_turn(self):
        self.set_responses(make_response(response_id="r1", text="Salom!"))

        with mock.patch.object(
            AgentRun.objects, "create", side_effect=RuntimeError("db down")
        ):
            result = self.run_turn("salom")

        self.assertEqual(result.text, "Salom!")
        self.assertFalse(result.used_fallback)


class RecorderSummaryTests(TestCase):
    def test_the_summary_carries_timing_cost_and_routing(self):
        recorder = RunRecorder(
            conversation_id="c1", assistant_id="a1",
            initial_tier="fast", routing_reason="short input",
        )
        step = recorder.start_step("fast", "gpt-4o-mini")
        step.input_tokens, step.output_tokens = 1000, 200
        step.duration_ms = 42

        summary = recorder.summary()

        self.assertEqual(summary["event"], "agent_run")
        self.assertEqual(summary["initial_tier"], "fast")
        self.assertEqual(summary["routing_reason"], "short input")
        self.assertEqual(summary["api_calls"], 1)
        self.assertEqual(summary["input_tokens"], 1000)
        self.assertGreater(summary["cost_usd"], 0)
        self.assertEqual(summary["steps"][0]["duration_ms"], 42)

    def test_escalation_is_visible_in_the_summary(self):
        recorder = RunRecorder(
            conversation_id="c1", assistant_id="a1",
            initial_tier="fast", routing_reason="short input",
        )
        recorder.start_step("fast", "gpt-4o-mini")
        recorder.note_escalation("standard", "empty reply")
        recorder.start_step("standard", "gpt-4o")

        summary = recorder.summary()

        self.assertTrue(summary["escalated"])
        self.assertEqual(summary["escalation_reason"], "empty reply")
        self.assertEqual(summary["final_tier"], "standard")


@override_settings(AI_TIER_MODELS=DISTINCT_TIERS, AI_TIER_ROUTING_ENABLED=True)
class OrderFlowTests(AgentTestCase):
    FLOW = {"1": "Ask which model", "2": "Ask the quantity", "3": "Collect the phone number"}

    def setUp(self):
        super().setUp()
        self.assistant.steps = self.FLOW
        self.assistant.save()

    def _instructions_at(self, index):
        payload = self.kwargs_at(index)["input"]
        developer = [item for item in payload if item.get("role") == "developer"]
        return developer[0]["content"] if developer else ""

    def test_the_configured_flow_reaches_the_model(self):
        self.set_responses(make_response(response_id="r1", text="Qaysi model?"))

        self.run_turn("salom")

        instructions = self._instructions_at(0)
        self.assertIn("Order flow to follow", instructions)
        self.assertIn("Collect the phone number", instructions)

    def test_an_assistant_without_a_flow_sends_no_flow_section(self):
        self.assistant.steps = {}
        self.assistant.save()
        self.set_responses(make_response(response_id="r1", text="Salom!"))

        self.run_turn("salom")

        self.assertNotIn("Order flow to follow", self._instructions_at(0))

    def test_the_flow_survives_escalation(self):
        self.set_responses(
            make_response(response_id="r1", text=""),
            make_response(response_id="r2", text="Qaysi model?"),
        )

        result = self.run_turn("salom")

        self.assertTrue(result.escalated)
        self.assertIn("Collect the phone number", self._instructions_at(1))

    def test_editing_the_flow_restarts_the_chain_so_it_takes_effect(self):
        self.conversation.previous_response_id = "old-response"
        self.conversation.instructions_version = self.assistant.updated_time
        self.conversation.save()

        self.assistant.steps = {"1": "Ask for the delivery address first"}
        self.assistant.save()

        self.set_responses(make_response(response_id="r1", text="Manzilingiz?"))
        self.run_turn("salom")

        instructions = self._instructions_at(0)
        self.assertIn("delivery address", instructions)
        self.assertNotIn("previous_response_id", self.kwargs_at(0))

    def test_a_warm_chain_does_not_resend_the_flow(self):
        self.conversation.previous_response_id = "warm"
        self.conversation.instructions_version = self.assistant.updated_time
        self.conversation.save()
        self.redis.get.return_value = None

        self.set_responses(make_response(response_id="r2", text="Nechta?"))
        self.run_turn("2 dona")

        self.assertEqual(self._instructions_at(0), "")
        self.assertEqual(self.kwargs_at(0)["previous_response_id"], "warm")


class ConfiguredModelsTests(TestCase):
    def test_every_configured_tier_model_has_a_price(self):
        for tier, model in routing.tier_models().items():
            with self.subTest(tier=tier):
                self.assertIsNotNone(
                    pricing.price_for(model),
                    f"tier {tier} uses {model!r}, which has no entry in pricing.PRICES "
                    f"— every run would record cost_usd = NULL",
                )

    def test_the_cheap_tier_is_not_more_expensive_than_the_deep_one(self):
        models = routing.tier_models()
        fast = pricing.price_for(models["fast"])
        deep = pricing.price_for(models["deep"])
        self.assertLessEqual(fast.output_usd, deep.output_usd)


PLAN_TRIVIAL = '{"intent":"greeting","needs_knowledge":false,"needs_tools":false,"complexity":"trivial","direct_reply":"Salom! Qanday yordam bera olaman?"}'
PLAN_HARD = '{"intent":"complaint","needs_knowledge":true,"needs_tools":true,"complexity":"hard","direct_reply":""}'
PLAN_NO_TOOLS = '{"intent":"question","needs_knowledge":true,"needs_tools":false,"complexity":"normal","direct_reply":""}'
PLAN_NOTHING = '{"intent":"question","needs_knowledge":false,"needs_tools":false,"complexity":"normal","direct_reply":""}'


class PlanParsingTests(TestCase):
    def _parse(self, text):
        step = pipeline.RunStepStub() if hasattr(pipeline, "RunStepStub") else _Step()
        return pipeline._parse_plan(make_response(text=text), step)

    def test_a_well_formed_plan_is_used(self):
        plan = self._parse(PLAN_HARD)
        self.assertEqual(plan.complexity, "hard")
        self.assertTrue(plan.needs_tools)

    def test_a_fenced_plan_is_still_read(self):
        plan = self._parse(f"```json\n{PLAN_HARD}\n```")
        self.assertEqual(plan.complexity, "hard")

    def test_unparseable_output_falls_back_to_permissive(self):
        plan = self._parse("I think this is a complaint, actually")
        self.assertTrue(plan.needs_knowledge)
        self.assertTrue(plan.needs_tools)
        self.assertEqual(plan.source, "triage output unparseable")

    def test_an_empty_reply_falls_back_to_permissive(self):
        self.assertTrue(self._parse("").needs_tools)

    def test_a_json_array_falls_back_to_permissive(self):
        self.assertTrue(self._parse('["nope"]').needs_tools)

    def test_a_missing_flag_defaults_to_on_not_off(self):
        plan = self._parse('{"intent":"question","complexity":"normal"}')
        self.assertTrue(plan.needs_knowledge)
        self.assertTrue(plan.needs_tools)

    def test_an_unknown_complexity_becomes_normal(self):
        self.assertEqual(self._parse('{"complexity":"apocalyptic"}').complexity, "normal")

    def test_a_direct_reply_on_a_non_trivial_turn_is_discarded(self):
        plan = self._parse(
            '{"complexity":"hard","direct_reply":"Your refund is approved."}'
        )
        self.assertEqual(plan.direct_reply, "")

    def test_hard_turns_map_to_the_deep_tier(self):
        self.assertIs(self._parse(PLAN_HARD).tier, routing.Tier.DEEP)

    def test_normal_turns_stay_on_the_cheap_tier(self):
        self.assertIs(self._parse(PLAN_NO_TOOLS).tier, routing.Tier.FAST)


class _Step:
    input_tokens = output_tokens = 0
    stage = "triage"
    error = ""


class ToolScopingTests(TestCase):
    SCHEMAS = [
        {"type": "file_search", "vector_store_ids": ["vs_1"]},
        {"type": "web_search"},
        {"type": "function", "name": "create_lead"},
    ]

    def test_a_turn_needing_nothing_carries_no_function_schemas(self):
        plan = pipeline.Plan(needs_knowledge=False, needs_tools=False)
        kept = pipeline.scope_tools(self.SCHEMAS, plan, retrieved=False)
        self.assertEqual([s.get("type") for s in kept], ["web_search"])

    def test_successful_retrieval_removes_file_search(self):
        plan = pipeline.Plan(needs_knowledge=True, needs_tools=True)
        kept = pipeline.scope_tools(self.SCHEMAS, plan, retrieved=True)
        self.assertNotIn("file_search", [s.get("type") for s in kept])

    def test_failed_retrieval_keeps_file_search_as_a_fallback(self):
        plan = pipeline.Plan(needs_knowledge=True, needs_tools=True)
        kept = pipeline.scope_tools(self.SCHEMAS, plan, retrieved=False)
        self.assertIn("file_search", [s.get("type") for s in kept])

    def test_a_permissive_plan_keeps_everything(self):
        kept = pipeline.scope_tools(self.SCHEMAS, pipeline.Plan.permissive("x"), retrieved=False)
        self.assertEqual(len(kept), len(self.SCHEMAS))


@override_settings(AI_TIER_MODELS=DISTINCT_TIERS, AI_TIER_ROUTING_ENABLED=True)
class PipelineEndToEndTests(AgentTestCase):
    def test_a_greeting_is_answered_by_triage_alone(self):
        self.set_responses(plan=PLAN_TRIVIAL)

        result = self.run_turn("salom")

        self.assertEqual(result.text, "Salom! Qanday yordam bera olaman?")
        self.assertTrue(result.answered_by_triage)
        self.assertEqual(len(self.all_calls), 1, "a greeting must cost exactly one call")
        self.assertEqual(self.kwargs_at_all(0)["model"], DISTINCT_TIERS["fast"])
        self.assertEqual(self.kwargs_at_all(0)["tools"], [])

    def test_a_hard_turn_is_acted_on_by_the_deep_tier(self):
        self.set_responses(
            make_response(response_id="r1", text="Kechirasiz, tekshiraman."),
            plan=PLAN_HARD,
        )

        self.run_turn("buyurtmam kelmadi va pul yechildi, nima qilay?")

        self.assertEqual(self.kwargs_at_all(0)["model"], DISTINCT_TIERS["fast"], "triage is cheap")
        self.assertEqual(self.kwargs_at(0)["model"], DISTINCT_TIERS["deep"], "act is not")

    def test_a_plan_needing_no_tools_sends_no_function_schemas(self):
        self.set_responses(make_response(response_id="r1", text="Ish vaqti 9-18."), plan=PLAN_NO_TOOLS)

        self.run_turn("ish vaqtingiz qanday?")

        names = [t.get("name") for t in self.kwargs_at(0)["tools"] if t.get("name")]
        self.assertEqual(names, [], "no function schema should be sent")

    def test_retrieved_passages_are_put_in_the_prompt(self):
        self.client.vector_stores.search.return_value = _search_results(
            [("hours.pdf", "We are open 09:00-18:00.")]
        )
        self.set_responses(make_response(response_id="r1", text="9:00-18:00."), plan=PLAN_NO_TOOLS)

        self.run_turn("ish vaqtingiz qanday?")

        payload = self.kwargs_at(0)["input"]
        blob = " ".join(item.get("content", "") for item in payload if isinstance(item, dict))
        self.assertIn("We are open 09:00-18:00.", blob)
        self.assertNotIn(
            "file_search", [t.get("type") for t in self.kwargs_at(0)["tools"]],
            "the documents are already here; the tool would buy a second call",
        )

    def test_a_failed_vector_search_still_answers(self):
        self.client.vector_stores.search.side_effect = RuntimeError("vector store down")
        self.set_responses(make_response(response_id="r1", text="Tekshiraman."), plan=PLAN_NO_TOOLS)

        result = self.run_turn("ish vaqtingiz qanday?")

        self.assertEqual(result.text, "Tekshiraman.")
        self.assertIn(
            "file_search", [t.get("type") for t in self.kwargs_at(0)["tools"]],
            "with no passages the model must be able to search for itself",
        )

    def test_a_turn_needing_no_knowledge_never_touches_the_vector_store(self):
        self.set_responses(make_response(response_id="r1", text="Ok."), plan=PLAN_NOTHING)

        self.run_turn("rahmat sizga")

        self.client.vector_stores.search.assert_not_called()

    def test_a_triage_crash_degrades_to_the_old_behaviour(self):
        self.client.responses.create.side_effect = [
            RuntimeError("triage exploded"),
            make_response(response_id="r1", text="Baribir javob."),
        ]

        result = self.run_turn("ish vaqtingiz qanday?")

        self.assertEqual(result.text, "Baribir javob.")
        self.assertEqual(result.plan["source"], "triage failed")
        self.assertTrue(result.plan["needs_tools"], "a failed plan must be permissive")

    def test_the_plan_is_recorded_on_the_run(self):
        self.set_responses(make_response(response_id="r1", text="Ok."), plan=PLAN_HARD)

        self.run_turn("buyurtmam kelmadi va pul yechildi")

        run = AgentRun.objects.get()
        self.assertEqual(run.plan["complexity"], "hard")
        self.assertEqual(run.plan["intent"], "complaint")

    @override_settings(AI_PIPELINE_ENABLED=False)
    def test_the_kill_switch_skips_triage_entirely(self):
        self.set_responses(make_response(response_id="r1", text="Salom!"), plan=None)

        result = self.run_turn("salom")

        self.assertEqual(result.text, "Salom!")
        self.assertEqual(len(self.all_calls), 1, "no triage call when disabled")


def _search_results(pairs):
    from types import SimpleNamespace
    return SimpleNamespace(data=[
        SimpleNamespace(
            filename=name,
            content=[SimpleNamespace(type="text", text=body)],
        )
        for name, body in pairs
    ])
