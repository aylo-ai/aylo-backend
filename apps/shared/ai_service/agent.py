import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings
from openai import APIStatusError, APITimeoutError, BadRequestError, RateLimitError

from apps.shared.addons.enums import AgentRunOutcomes

from . import routing
from . import pipeline
from . import tools as tool_registry
from .client import CHAT_MODEL, get_client
from .prompts import build_instructions
from .telemetry import RunRecorder

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 5
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (1, 2, 4)
CHAIN_TTL_SECONDS = 60 * 60 * 24 * 7

MAX_PARALLEL_TOOLS = 4

DEFAULT_FALLBACK = "Sorry, I'm having trouble right now. Let me get a colleague to help you."


@dataclass
class AgentResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: List[str] = field(default_factory=list)
    used_fallback: bool = False
    hit_iteration_cap: bool = False
    model: str = ""
    escalated: bool = False
    plan: Optional[Dict[str, Any]] = None
    answered_by_triage: bool = False


def _chain_key(conversation) -> str:
    return f"agent:chain:{conversation.id}"


def load_chain(assistant, conversation) -> Optional[str]:
    started = conversation.instructions_version
    if started is None or assistant.updated_time > started:
        if started is not None:
            logger.info("Assistant %s changed since chain start; restarting chain", assistant.id)
        return None

    from apps.shared.addons.redis import redis_client

    try:
        cached = redis_client.get(_chain_key(conversation))
        if cached:
            return cached
    except Exception as exc:
        logger.warning("Redis unavailable reading chain for %s: %s", conversation.id, exc)

    return conversation.previous_response_id or None


def save_chain(conversation, response_id: str, instructions_version) -> None:
    conversation.previous_response_id = response_id
    conversation.instructions_version = instructions_version
    conversation.save(update_fields=["previous_response_id", "instructions_version", "updated_time"])

    from apps.shared.addons.redis import redis_client

    try:
        redis_client.set(_chain_key(conversation), response_id, ex=CHAIN_TTL_SECONDS)
    except Exception as exc:
        logger.warning("Redis unavailable writing chain for %s: %s", conversation.id, exc)


def clear_chain(conversation) -> None:
    conversation.previous_response_id = None
    conversation.instructions_version = None
    conversation.save(update_fields=["previous_response_id", "instructions_version", "updated_time"])

    from apps.shared.addons.redis import redis_client

    try:
        redis_client.delete(_chain_key(conversation))
    except Exception as exc:
        logger.warning("Redis unavailable clearing chain for %s: %s", conversation.id, exc)


class Agent:
    def __init__(self, model: str = CHAT_MODEL):
        self.model = model


    def run(self, assistant, conversation, user_input: str) -> AgentResult:
        decision = routing.choose(assistant, conversation, user_input)
        recorder = RunRecorder(
            conversation_id=conversation.id,
            assistant_id=assistant.id,
            initial_tier=decision.tier.value,
            routing_reason=decision.reason,
        )

        try:
            plan = pipeline.triage(user_input, recorder, self._create)
            recorder.plan = plan.as_dict()

            if plan.direct_reply:
                recorder.note_outcome(AgentRunOutcomes.OK.value)
                return AgentResult(
                    text=plan.direct_reply,
                    input_tokens=recorder.input_tokens,
                    output_tokens=recorder.output_tokens,
                    model=recorder.final_model,
                    plan=plan.as_dict(),
                    answered_by_triage=True,
                )

            decision = pipeline.tier_for(plan, decision)

            context = (
                pipeline.retrieve(assistant, user_input, recorder)
                if plan.needs_knowledge else ""
            )

            result = self._run_with_chain_reset(
                assistant, conversation, user_input, decision, recorder, plan, context
            )
            result.plan = plan.as_dict()
            recorder.note_outcome(
                AgentRunOutcomes.FALLBACK.value if result.used_fallback
                else AgentRunOutcomes.OK.value
            )
            return result
        except Exception as exc:
            logger.exception("Agent failed for conversation %s", conversation.id)
            recorder.note_outcome(AgentRunOutcomes.ERROR.value, error=str(exc))
            return AgentResult(text=self._fallback(assistant), used_fallback=True)
        finally:
            recorder.finish()


    def _fallback(self, assistant) -> str:
        return (assistant.fallback_message or "").strip() or DEFAULT_FALLBACK

    @staticmethod
    def _needs_escalation(result: AgentResult) -> str:
        if result.used_fallback:
            return "empty reply"
        if result.hit_iteration_cap and getattr(settings, "AI_ESCALATE_ON_TOOL_CAP", False):
            return "hit tool iteration cap"
        return ""

    def _run_with_chain_reset(
        self, assistant, conversation, user_input: str, decision, recorder, plan, context
    ) -> AgentResult:
        previous_id = load_chain(assistant, conversation)
        try:
            return self._run_tiered(
                assistant, conversation, user_input, previous_id, decision, recorder, plan, context
            )
        except BadRequestError as exc:
            if previous_id is None or not self._is_stale_chain(exc):
                raise
            logger.warning(
                "Stale previous_response_id on conversation %s; restarting chain", conversation.id
            )
            clear_chain(conversation)
            return self._run_tiered(
                assistant, conversation, user_input, None, decision, recorder, plan, context
            )

    def _run_tiered(
        self, assistant, conversation, user_input: str, previous_id, decision, recorder,
        plan, context,
    ) -> AgentResult:
        instructions_version = assistant.updated_time

        result, final_id = self._attempt(
            assistant, conversation, user_input, previous_id, decision, recorder, plan, context
        )

        reason = self._needs_escalation(result)
        if reason:
            escalation = routing.escalate(decision.tier, reason)
            if escalation is not None:
                recorder.note_escalation(escalation.tier.value, reason)
                result, final_id = self._attempt(
                    assistant, conversation, user_input, previous_id, escalation, recorder,
                    plan, context,
                )
                result.escalated = True
            else:
                logger.info(
                    "Conversation %s would escalate (%s) but is already at the top tier",
                    conversation.id, reason,
                )

        if final_id:
            save_chain(conversation, final_id, instructions_version)

        return result

    @staticmethod
    def _is_stale_chain(exc: BadRequestError) -> bool:
        text = str(exc).lower()
        return "previous_response" in text or "not found" in text

    def _attempt(
        self, assistant, conversation, user_input: str, previous_id: Optional[str],
        decision, recorder, plan=None, context="",
    ) -> Tuple[AgentResult, Optional[str]]:
        plan = plan or pipeline.Plan.permissive("no plan")
        model = decision.model

        tools = pipeline.scope_tools(
            tool_registry.build_tools(assistant), plan, retrieved=bool(context)
        )

        if previous_id:
            payload: List[Dict[str, Any]] = [{"role": "user", "content": user_input}]
        else:
            payload = [
                {"role": "developer", "content": build_instructions(assistant)},
                {"role": "user", "content": user_input},
            ]

        if context:
            payload.insert(len(payload) - 1, {"role": "developer", "content": context})

        input_tokens = 0
        output_tokens = 0
        called: List[str] = []
        response = None
        hit_cap = False

        for iteration in range(MAX_TOOL_ITERATIONS):
            step = recorder.start_step(decision.tier.value, model)
            started = time.perf_counter()
            response = self._create(payload, tools, previous_id, model)
            step.duration_ms = int(round((time.perf_counter() - started) * 1000))
            previous_id = response.id

            used_in, used_out = self._usage(response)
            step.input_tokens, step.output_tokens = used_in, used_out
            step.cached_input_tokens = self._cached_tokens(response)
            input_tokens += used_in
            output_tokens += used_out

            calls = [item for item in response.output if getattr(item, "type", None) == "function_call"]
            if not calls:
                break

            step.tool_calls = [call.name for call in calls]
            called.extend(step.tool_calls)


            tools_started = time.perf_counter()
            payload = self._execute_calls(calls, assistant, conversation)
            step.tools_duration_ms = int(round((time.perf_counter() - tools_started) * 1000))

            if iteration == MAX_TOOL_ITERATIONS - 1:
                hit_cap = True
                logger.warning(
                    "Conversation %s hit the tool iteration cap; asking for a final answer",
                    conversation.id,
                )
                final_step = recorder.start_step(decision.tier.value, model)
                started = time.perf_counter()
                response = self._create(payload, tools, previous_id, model, tool_choice="none")
                final_step.duration_ms = int(round((time.perf_counter() - started) * 1000))
                previous_id = response.id
                used_in, used_out = self._usage(response)
                final_step.input_tokens, final_step.output_tokens = used_in, used_out
                final_step.cached_input_tokens = self._cached_tokens(response)
                input_tokens += used_in
                output_tokens += used_out

        text = self._extract_text(response)
        if not text:
            logger.warning(
                "Empty reply for conversation %s; output was %r",
                conversation.id, getattr(response, "output", None),
            )
            return AgentResult(
                text=self._fallback(assistant),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                tool_calls=called,
                used_fallback=True,
                hit_iteration_cap=hit_cap,
                model=model,
            ), previous_id

        return AgentResult(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tool_calls=called,
            hit_iteration_cap=hit_cap,
            model=model,
        ), previous_id

    def _execute_calls(self, calls, assistant, conversation) -> List[Dict[str, Any]]:
        if len(calls) == 1 or not self._parallel_tools_enabled():
            results = [self._execute_one(call, assistant, conversation) for call in calls]
        else:
            with ThreadPoolExecutor(max_workers=min(len(calls), MAX_PARALLEL_TOOLS)) as pool:
                results = list(pool.map(
                    lambda call: self._execute_one(call, assistant, conversation), calls
                ))

        return [
            {
                "type": "function_call_output",
                "call_id": call.call_id,
                "output": json.dumps(result, default=str),
            }
            for call, result in zip(calls, results)
        ]

    def _execute_one(self, call, assistant, conversation) -> Dict[str, Any]:
        from django.db import connection

        opened = connection.connection is None
        try:
            return tool_registry.execute(
                call.name, assistant, conversation, self._arguments(call)
            )
        finally:
            if opened:
                try:
                    connection.close()
                except Exception:  # noqa: BLE001 - cleanup must not mask a result
                    pass

    @staticmethod
    def _parallel_tools_enabled() -> bool:
        return bool(getattr(settings, "AI_PARALLEL_TOOLS", True))

    def _create(self, payload, tools, previous_id: Optional[str], model: Optional[str] = None,
                tool_choice: str = "auto"):
        kwargs: Dict[str, Any] = {
            "model": model or self.model,
            "input": payload,
            "tools": tools,
            "tool_choice": tool_choice,
            "store": True,
        }
        if previous_id:
            kwargs["previous_response_id"] = previous_id

        last_exc = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                return get_client().responses.create(**kwargs)
            except (RateLimitError, APITimeoutError) as exc:
                last_exc = exc
            except APIStatusError as exc:
                if exc.status_code < 500:
                    raise
                last_exc = exc

            delay = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
            logger.warning(
                "OpenAI call failed (attempt %s/%s): %s; retrying in %ss",
                attempt + 1, MAX_ATTEMPTS, last_exc, delay,
            )
            time.sleep(delay)

        raise last_exc

    @staticmethod
    def _arguments(call) -> Dict[str, Any]:
        try:
            return json.loads(call.arguments or "{}")
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("Could not parse arguments for %s: %s", call.name, exc)
            return {}

    @staticmethod
    def _usage(response) -> Tuple[int, int]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return 0, 0

        raw_in = getattr(usage, "input_tokens", 0) or 0
        details = getattr(usage, "input_tokens_details", None)
        cached = getattr(details, "cached_tokens", 0) or 0
        return max(raw_in - cached, 0), getattr(usage, "output_tokens", 0) or 0

    @staticmethod
    def _cached_tokens(response) -> int:
        usage = getattr(response, "usage", None)
        details = getattr(usage, "input_tokens_details", None) if usage else None
        return getattr(details, "cached_tokens", 0) or 0

    @staticmethod
    def _extract_text(response) -> str:
        if response is None:
            return ""

        chunks: List[str] = []
        for item in getattr(response, "output", []) or []:
            if getattr(item, "type", None) != "message":
                continue
            if getattr(item, "role", None) != "assistant":
                continue
            for content in getattr(item, "content", []) or []:
                if getattr(content, "type", None) == "output_text" and content.text:
                    chunks.append(content.text)

        text = "\n".join(chunks).strip()
        return _unwrap_json_envelope(text)


def _unwrap_json_envelope(text: str) -> str:
    if not text.startswith("{") and not text.startswith("```"):
        return text

    cleaned = text
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return text

    if isinstance(parsed, dict) and isinstance(parsed.get("reply"), str):
        logger.info("Model returned a JSON envelope; unwrapped the reply field")
        return parsed["reply"].strip()
    return text


agent = Agent()


def respond(assistant, conversation, user_input: str) -> str:
    from apps.assistant.services.conversation import conversation_service
    from apps.shared.addons.enums import SenderTypes
    from apps.shared.addons.redis import publish_message_to_ws

    result = agent.run(assistant, conversation, user_input)

    data = conversation_service.create_message(
        conversation=conversation,
        sender=SenderTypes.ASSISTANT.value,
        content=result.text,
        audio_file=None,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )
    try:
        publish_message_to_ws(
            conversation.id, result.text, sender="assistant",
            assistant_id=assistant.id, data=data,
        )
    except Exception as exc:
        logger.warning("Failed to publish reply for %s: %s", conversation.id, exc)

    return result.text
