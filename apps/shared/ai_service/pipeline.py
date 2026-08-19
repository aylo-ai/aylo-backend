import json
import logging
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional, Sequence

from django.conf import settings

from . import routing
from .client import get_client

logger = logging.getLogger(__name__)

TRIAGE = "triage"
RETRIEVE = "retrieve"
ACT = "act"

TRIVIAL = "trivial"
NORMAL = "normal"
HARD = "hard"

COMPLEXITY_TIERS = {
    TRIVIAL: routing.Tier.FAST,
    NORMAL: routing.Tier.FAST,
    HARD: routing.Tier.DEEP,
}

MAX_PASSAGES = 5
MAX_PASSAGE_CHARS = 1500

TRIAGE_INSTRUCTIONS = """\
You are the router for a customer-support assistant. You do not talk to the
customer unless the message is trivial.

Classify the message and reply with ONLY a JSON object:

{
  "intent": "greeting|question|order|complaint|other",
  "needs_knowledge": true|false,
  "needs_tools": true|false,
  "complexity": "trivial|normal|hard",
  "direct_reply": ""
}

- needs_knowledge: true if answering needs facts from the company's documents
  (products, prices, policies, hours).
- needs_tools: true if the assistant must DO something - record a lead, fetch a
  summary, escalate to a human, schedule a follow-up.
- complexity: "trivial" for greetings and thanks; "hard" for multi-part
  requests, complaints, or anything needing several steps.
- direct_reply: fill this in ONLY for a greeting or a thank-you, in the
  customer's language. Leave it "" for everything else. If you are not certain,
  leave it "".

When unsure, prefer true for needs_knowledge and needs_tools."""


@dataclass(frozen=True)
class Plan:
    intent: str = "other"
    needs_knowledge: bool = True
    needs_tools: bool = True
    complexity: str = NORMAL
    direct_reply: str = ""
    source: str = "triage"

    @classmethod
    def permissive(cls, source: str) -> "Plan":
        return cls(
            intent="other", needs_knowledge=True, needs_tools=True,
            complexity=NORMAL, direct_reply="", source=source,
        )

    @property
    def tier(self) -> routing.Tier:
        return COMPLEXITY_TIERS.get(self.complexity, routing.Tier.FAST)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "needs_knowledge": self.needs_knowledge,
            "needs_tools": self.needs_tools,
            "complexity": self.complexity,
            "answered_directly": bool(self.direct_reply),
            "source": self.source,
        }


def enabled() -> bool:
    return bool(getattr(settings, "AI_PIPELINE_ENABLED", True))


def triage(user_input: str, recorder, create) -> Plan:
    if not enabled():
        return Plan.permissive("pipeline disabled")

    model = routing.model_for(routing.Tier.FAST)
    step = recorder.start_step(routing.Tier.FAST.value, model)
    step.stage = TRIAGE

    payload = [
        {"role": "developer", "content": TRIAGE_INSTRUCTIONS},
        {"role": "user", "content": (user_input or "")[:2000]},
    ]

    try:
        response = create(payload, [], None, model, tool_choice="none")
    except Exception as exc:  # noqa: BLE001 - triage must never break a turn
        logger.warning("Triage call failed (%s); using a permissive plan", exc)
        step.error = str(exc)[:500]
        return Plan.permissive("triage failed")

    return _parse_plan(response, step)


def _parse_plan(response, step) -> Plan:
    from .agent import Agent

    used_in, used_out = Agent._usage(response)
    step.input_tokens, step.output_tokens = used_in, used_out

    text = Agent._extract_text(response)
    if not text:
        return Plan.permissive("triage returned nothing")

    try:
        data = json.loads(_strip_fences(text))
    except (json.JSONDecodeError, TypeError):
        logger.warning("Triage did not return JSON: %r", text[:200])
        return Plan.permissive("triage output unparseable")

    if not isinstance(data, dict):
        return Plan.permissive("triage output was not an object")

    complexity = str(data.get("complexity") or NORMAL).lower()
    if complexity not in COMPLEXITY_TIERS:
        complexity = NORMAL

    reply = data.get("direct_reply")
    reply = reply.strip() if isinstance(reply, str) else ""
    if reply and complexity != TRIVIAL:
        logger.info("Triage offered a direct reply on a %s turn; ignoring it", complexity)
        reply = ""

    return Plan(
        intent=str(data.get("intent") or "other").lower(),
        needs_knowledge=_flag(data.get("needs_knowledge"), default=True),
        needs_tools=_flag(data.get("needs_tools"), default=True),
        complexity=complexity,
        direct_reply=reply,
    )


def _flag(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1"}
    return default


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    return text.strip()


def retrieve(assistant, user_input: str, recorder) -> str:
    from . import tools as tool_registry

    vector_id = getattr(assistant, "vector_id", None)
    if not tool_registry.is_openai_store(vector_id):
        return ""

    step = recorder.start_step(routing.Tier.FAST.value, "vector_store.search")
    step.stage = RETRIEVE

    try:
        results = get_client().vector_stores.search(
            vector_store_id=vector_id,
            query=(user_input or "")[:1000],
            max_num_results=MAX_PASSAGES,
        )
        passages = _passages(results)
    except Exception as exc:  # noqa: BLE001 - degrade to tool-based search
        logger.warning("Vector search failed for assistant %s: %s", assistant.id, exc)
        step.error = str(exc)[:500]
        return ""

    if not passages:
        return ""

    step.tool_calls = ["vector_store.search"]
    return "# Relevant company documents\n\n" + "\n\n---\n\n".join(passages)


def _passages(results) -> List[str]:
    out: List[str] = []
    for item in getattr(results, "data", []) or []:
        chunks = [
            part.text for part in (getattr(item, "content", None) or [])
            if getattr(part, "type", None) == "text" and getattr(part, "text", None)
        ]
        if not chunks:
            continue
        body = "\n".join(chunks)[:MAX_PASSAGE_CHARS]
        name = getattr(item, "filename", None) or ""
        out.append(f"## {name}\n{body}" if name else body)
    return out


def scope_tools(schemas: Sequence[dict], plan: Plan, retrieved: bool) -> List[dict]:
    kept = []
    for schema in schemas:
        kind = schema.get("type")

        if kind == "file_search":
            if not plan.needs_knowledge or retrieved:
                continue
            kept.append(schema)
            continue

        if kind == "function":
            if not plan.needs_tools:
                continue
            kept.append(schema)
            continue

        kept.append(schema)

    return kept


def tier_for(plan: Plan, decision) -> Any:
    wanted = plan.tier
    if routing.TIER_ORDER.index(wanted) <= routing.TIER_ORDER.index(decision.tier):
        return decision
    return routing.Decision(
        wanted, routing.model_for(wanted), f"plan complexity: {plan.complexity}"
    )
