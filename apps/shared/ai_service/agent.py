"""The agent.

One entry point that matters: `respond(assistant, conversation, user_input)`.
It runs the agentic loop, stores the reply, publishes it to the websocket, and
returns the text to send. It never raises and never returns an empty string —
callers can always forward what they get back.

The loop keeps handing tool results to the model until the model stops asking for
tools, so it can look something up and then act on what it found in a single turn.
"""
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from openai import APIStatusError, APITimeoutError, BadRequestError, RateLimitError

from . import tools as tool_registry
from .client import CHAT_MODEL, get_client
from .prompts import build_instructions

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 5
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (1, 2, 4)
TEMPERATURE = 0.7
CHAIN_TTL_SECONDS = 60 * 60 * 24 * 7

DEFAULT_FALLBACK = "Sorry, I'm having trouble right now. Let me get a colleague to help you."


@dataclass
class AgentResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: List[str] = field(default_factory=list)
    used_fallback: bool = False


# --------------------------------------------------------------------------
# Chain state: Postgres is the source of truth, Redis is a cache in front of it
# --------------------------------------------------------------------------

def _chain_key(conversation) -> str:
    return f"agent:chain:{conversation.id}"


def load_chain(assistant, conversation) -> Optional[str]:
    """Return the response id to continue from, or None to start fresh.

    Returns None when the assistant was edited after this chain started, so the
    new instructions take effect on the very next message.
    """
    started = conversation.instructions_version
    if started is None or assistant.updated_time > started:
        if started is not None:
            logger.info("Assistant %s changed since chain start; restarting chain", assistant.id)
        return None

    from shared.addons.redis import redis_client

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

    from shared.addons.redis import redis_client

    try:
        redis_client.set(_chain_key(conversation), response_id, ex=CHAIN_TTL_SECONDS)
    except Exception as exc:
        logger.warning("Redis unavailable writing chain for %s: %s", conversation.id, exc)


def clear_chain(conversation) -> None:
    conversation.previous_response_id = None
    conversation.instructions_version = None
    conversation.save(update_fields=["previous_response_id", "instructions_version", "updated_time"])

    from shared.addons.redis import redis_client

    try:
        redis_client.delete(_chain_key(conversation))
    except Exception as exc:
        logger.warning("Redis unavailable clearing chain for %s: %s", conversation.id, exc)


# --------------------------------------------------------------------------
# Agent
# --------------------------------------------------------------------------

class Agent:
    def __init__(self, model: str = CHAT_MODEL):
        self.model = model

    # -- public ----------------------------------------------------------

    def run(self, assistant, conversation, user_input: str) -> AgentResult:
        """Run one turn. Never raises."""
        try:
            return self._run_with_chain_reset(assistant, conversation, user_input)
        except Exception:
            logger.exception("Agent failed for conversation %s", conversation.id)
            return AgentResult(text=self._fallback(assistant), used_fallback=True)

    # -- internals -------------------------------------------------------

    def _fallback(self, assistant) -> str:
        return (assistant.fallback_message or "").strip() or DEFAULT_FALLBACK

    def _run_with_chain_reset(self, assistant, conversation, user_input: str) -> AgentResult:
        """Run the turn; if the stored chain is rejected, drop it and try once more.

        Without this a single bad response id would break every future message in
        the conversation.
        """
        previous_id = load_chain(assistant, conversation)
        try:
            return self._run(assistant, conversation, user_input, previous_id)
        except BadRequestError as exc:
            if previous_id is None or not self._is_stale_chain(exc):
                raise
            logger.warning(
                "Stale previous_response_id on conversation %s; restarting chain", conversation.id
            )
            clear_chain(conversation)
            return self._run(assistant, conversation, user_input, None)

    @staticmethod
    def _is_stale_chain(exc: BadRequestError) -> bool:
        text = str(exc).lower()
        return "previous_response" in text or "not found" in text

    def _run(self, assistant, conversation, user_input: str, previous_id: Optional[str]) -> AgentResult:
        tools = tool_registry.build_tools(assistant)
        instructions_version = assistant.updated_time

        if previous_id:
            payload: List[Dict[str, Any]] = [{"role": "user", "content": user_input}]
        else:
            payload = [
                {"role": "developer", "content": build_instructions(assistant)},
                {"role": "user", "content": user_input},
            ]

        input_tokens = 0
        output_tokens = 0
        called: List[str] = []
        response = None

        for iteration in range(MAX_TOOL_ITERATIONS):
            response = self._create(payload, tools, previous_id)
            previous_id = response.id

            used_in, used_out = self._usage(response)
            input_tokens += used_in
            output_tokens += used_out

            calls = [item for item in response.output if getattr(item, "type", None) == "function_call"]
            if not calls:
                break

            payload = []
            for call in calls:
                called.append(call.name)
                result = tool_registry.execute(
                    call.name, assistant, conversation, self._arguments(call)
                )
                payload.append({
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(result, default=str),
                })

            if iteration == MAX_TOOL_ITERATIONS - 1:
                logger.warning(
                    "Conversation %s hit the tool iteration cap; asking for a final answer",
                    conversation.id,
                )
                response = self._create(payload, tools, previous_id, tool_choice="none")
                previous_id = response.id
                used_in, used_out = self._usage(response)
                input_tokens += used_in
                output_tokens += used_out

        save_chain(conversation, previous_id, instructions_version)

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
            )

        return AgentResult(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tool_calls=called,
        )

    def _create(self, payload, tools, previous_id: Optional[str], tool_choice: str = "auto"):
        """Call the API, retrying transient failures.

        Retrying here rather than in Celery matters: a Celery retry would re-run
        the whole task and store the customer's message a second time.
        """
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "input": payload,
            "tools": tools,
            "tool_choice": tool_choice,
            "temperature": TEMPERATURE,
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
        """Billable tokens for one call. Cached input tokens are not charged."""
        usage = getattr(response, "usage", None)
        if usage is None:
            return 0, 0

        raw_in = getattr(usage, "input_tokens", 0) or 0
        details = getattr(usage, "input_tokens_details", None)
        cached = getattr(details, "cached_tokens", 0) or 0
        return max(raw_in - cached, 0), getattr(usage, "output_tokens", 0) or 0

    @staticmethod
    def _extract_text(response) -> str:
        """Pull the assistant's words out of the response.

        The reply is plain text by design, so there is nothing to unwrap. The one
        thing we guard is a model that ignored that and emitted a JSON envelope
        anyway — we would rather send its `reply` field than raw braces.
        """
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
    """Safety net for a model that wrapped its reply in JSON despite the prompt."""
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


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def respond(assistant, conversation, user_input: str) -> str:
    """Run a turn, persist the reply and publish it. Returns the text to send."""
    from shared.addons.enums import SenderTypes
    from shared.addons.redis import publish_message_to_ws
    from shared.ai_service.conversation import conversation_service

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
