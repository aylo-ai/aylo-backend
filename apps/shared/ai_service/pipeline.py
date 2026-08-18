"""The request pipeline: what happens between a customer's message and a reply.

Before this, every turn took the same expensive path. One model, carrying the
full system prompt, every tool schema the assistant owns, and the `file_search`
tool, answered `"salom"` exactly the way it answered a five-part order dispute.
Two costs came out of that, on *every* message:

* **Input tokens.** Tool schemas and instructions are re-sent on the first call
  of every chain whether or not the turn could ever use them.
* **Round trips.** Knowledge-base lookups went through the model: it had to emit
  a `file_search` call, wait, then be called a second time with the results.
  That is two model calls to answer one question out of a document.

The pipeline replaces that with stages that a turn only pays for if it needs
them:

    triage  ──▶ retrieve ──▶ act ──▶ (escalate)
    (cheap)     (no LLM)     (tier by complexity)

**triage** is one call on the cheap tier with a ~200-token prompt and no tools.
It returns a `Plan`: what the turn needs, how hard it is, and -- for a greeting
or a thank-you -- the reply itself, which ends the turn there.

**retrieve** is not a model call at all. When the plan says the answer lives in
the knowledge base, the vector store is queried *directly* and the passages are
handed to the next stage as context. That is the round trip removed: the model
sees the documents on its first call instead of asking for them.

**act** runs the agentic tool loop, but only with the tools the plan justified,
on the tier the plan's complexity earned.

## The rule that keeps this safe

Triage is a cheap model making a judgement call, so it will sometimes be wrong.
Every failure mode therefore degrades *towards* the old behaviour, never away
from it: an unparseable plan, a timeout, a missing field, or an exception all
produce `Plan.permissive()` -- knowledge on, tools on, normal complexity, which
is exactly what the loop did before this module existed. A broken triage costs
one cheap call and changes nothing else.

The mirror of that rule is that triage may never *end* a turn on a guess: it can
only answer directly when it is confident and the turn is trivial, and even then
the answer is discarded if it came back empty.
"""
import json
import logging
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional, Sequence

from django.conf import settings

from . import routing
from .client import get_client

logger = logging.getLogger(__name__)

# Stage names. Recorded on every step so a slow turn can be attributed to the
# stage that actually took the time.
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

# Passages pulled from the vector store when the plan asks for knowledge. Enough
# to answer from, few enough that the context stays small -- the whole point of
# pre-retrieval is spending fewer tokens, not more.
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
    # Why this plan is what it is, for the run log.
    source: str = "triage"

    @classmethod
    def permissive(cls, source: str) -> "Plan":
        """Everything on. What the loop did before the pipeline existed.

        Every triage failure resolves to this, so the worst case of a broken
        cheap model is the old cost, not a worse answer.
        """
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
    """Kill switch. Off means the old single-stage behaviour, unchanged."""
    return bool(getattr(settings, "AI_PIPELINE_ENABLED", True))


# ---------------------------------------------------------------------------
# Stage 1: triage
# ---------------------------------------------------------------------------

def triage(user_input: str, recorder, create) -> Plan:
    """Classify the turn on the cheap tier. Never raises.

    `create` is injected rather than imported so the agent keeps ownership of
    retries, timeouts and telemetry, and so this stage is trivially testable.
    """
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
    from .agent import Agent  # local: avoids a circular import at module load

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
    # A direct answer is only trusted for the case it was allowed for. Anything
    # else means the cheap model answered a question it was told not to answer.
    if reply and complexity != TRIVIAL:
        logger.info("Triage offered a direct reply on a %s turn; ignoring it", complexity)
        reply = ""

    return Plan(
        intent=str(data.get("intent") or "other").lower(),
        # Absent means "the model did not say", which is not the same as false.
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


# ---------------------------------------------------------------------------
# Stage 2: retrieve  (no model call)
# ---------------------------------------------------------------------------

def retrieve(assistant, user_input: str, recorder) -> str:
    """Query the vector store directly and return passages as plain context.

    This is the round trip the pipeline exists to remove. Letting the model call
    `file_search` costs a full extra call: one to ask, one to answer with the
    results. Searching here means the documents are already in the first prompt.

    Returns "" on any failure -- a turn without its documents is worse than one
    with them, but far better than no turn at all, and `act` still carries
    `file_search` as a fallback when this comes back empty.
    """
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
        # Parsing is inside the try on purpose: a provider that changes the
        # result shape must degrade to `file_search`, not break the turn.
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


# ---------------------------------------------------------------------------
# Stage 3 support: scoping what `act` is allowed to carry
# ---------------------------------------------------------------------------

def scope_tools(schemas: Sequence[dict], plan: Plan, retrieved: bool) -> List[dict]:
    """Drop tool schemas this turn has no use for.

    Two independent savings, both on input tokens the old path always paid:

    * `needs_tools=False` removes every function schema. A turn asking about
      opening hours does not need the lead-capture schema in context.
    * A successful `retrieve` removes `file_search`, because the passages are
      already in the prompt. When retrieval came back empty the tool stays, so
      the model can still go looking itself.
    """
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

        # web_search and anything else provider-native: leave alone.
        kept.append(schema)

    return kept


def tier_for(plan: Plan, decision) -> Any:
    """Raise the routed tier to what the plan's complexity calls for.

    A floor rather than an override, for the same reason as everywhere else in
    this codebase: a long message that already routed high must not be pulled
    back down because triage called it `normal`.
    """
    wanted = plan.tier
    if routing.TIER_ORDER.index(wanted) <= routing.TIER_ORDER.index(decision.tier):
        return decision
    return routing.Decision(
        wanted, routing.model_for(wanted), f"plan complexity: {plan.complexity}"
    )
