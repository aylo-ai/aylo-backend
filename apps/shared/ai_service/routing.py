"""Which model answers this turn, and when to pay for a better one.

Today every turn -- "salom", "ish vaqtingiz qanday?", and a five-tool lead
qualification -- goes to one model at one price. Most turns in a support inbox
are the cheap kind, so the single biggest lever on the bill is not a better
prompt, it is not sending the easy 80% to the expensive model.

The policy here is deliberately in two halves, because guessing and knowing are
different things:

**Pre-routing is a heuristic, and heuristics are wrong sometimes.** It runs on
signals already in hand (message length, whether this assistant even has tools,
whether the chain is warm) and costs nothing -- no classifier call, which would
add both latency and a second bill to every turn. It only ever picks the
*starting* tier.

**Escalation is reactive, and reactive is trustworthy.** Rather than predicting
difficulty, the loop notices that the cheap tier actually struggled -- it hit the
tool-iteration cap, or came back with nothing -- and re-runs the turn on a
stronger model. A wrong guess therefore costs one cheap call, not a wrong answer
to a customer.

That asymmetry is the whole design: be optimistic cheaply, be certain expensively,
and never let a bad guess reach the user.

Tiers are configured, not hardcoded, so changing models is a settings edit rather
than a code change.
"""
import logging
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from django.conf import settings

logger = logging.getLogger(__name__)


class Tier(str, Enum):
    """Ordered cheapest to most capable. Order matters -- `escalate` walks it."""

    FAST = "fast"
    STANDARD = "standard"
    DEEP = "deep"


TIER_ORDER: List[Tier] = [Tier.FAST, Tier.STANDARD, Tier.DEEP]

# Defaults are OpenAI ids because that is what this project runs. Override per
# environment with AI_TIER_MODELS in settings, e.g.
#     AI_TIER_MODELS = {"fast": "...", "standard": "...", "deep": "..."}
DEFAULT_TIER_MODELS = {
    Tier.FAST.value: "gpt-4o-mini",
    Tier.STANDARD.value: "gpt-4o",
    Tier.DEEP.value: "gpt-4o",
}

# A turn longer than this is doing more than greeting; start it one tier up.
# Characters, not tokens, on purpose: tokenising every inbound message to make a
# routing decision costs more than the decision saves.
LONG_INPUT_CHARS = 400

# Below this, a message is almost certainly a greeting or an acknowledgement.
TRIVIAL_INPUT_CHARS = 24


@dataclass(frozen=True)
class Decision:
    """A routing choice plus the reason, so the log can explain itself."""

    tier: Tier
    model: str
    reason: str

    @property
    def is_escalation(self) -> bool:
        return self.tier is not TIER_ORDER[0]


def tier_models() -> dict:
    configured = getattr(settings, "AI_TIER_MODELS", None) or {}
    return {**DEFAULT_TIER_MODELS, **configured}


def model_for(tier: Tier) -> str:
    models = tier_models()
    model = models.get(tier.value)
    if not model:
        # Never fail a customer turn over a config gap: fall back to the most
        # capable tier we know a model for and say so loudly.
        fallback = models.get(Tier.DEEP.value) or DEFAULT_TIER_MODELS[Tier.DEEP.value]
        logger.error(
            "No model configured for tier %s; falling back to %s. Check AI_TIER_MODELS.",
            tier.value, fallback,
        )
        return fallback
    return model


def routing_enabled() -> bool:
    """Kill switch. Off means every turn goes to the standard tier, as before.

    Worth keeping: if tiering ever degrades answer quality in production, the
    fix should be one setting, not a redeploy.
    """
    return bool(getattr(settings, "AI_TIER_ROUTING_ENABLED", True))


def choose(assistant, conversation, user_input: str) -> Decision:
    """Pick the starting tier for a turn. Cheap signals only -- no API call."""
    if not routing_enabled():
        tier = Tier.STANDARD
        return Decision(tier, model_for(tier), "routing disabled")

    forced = (getattr(assistant, "model_tier", "") or "").strip().lower()
    if forced in {tier.value for tier in TIER_ORDER}:
        tier = Tier(forced)
        return Decision(tier, model_for(tier), f"assistant pinned to {tier.value}")

    text = (user_input or "").strip()

    if len(text) >= LONG_INPUT_CHARS:
        return Decision(
            Tier.STANDARD, model_for(Tier.STANDARD), f"long input ({len(text)} chars)"
        )

    if len(text) <= TRIVIAL_INPUT_CHARS:
        return Decision(Tier.FAST, model_for(Tier.FAST), "short input")

    return Decision(Tier.FAST, model_for(Tier.FAST), "default start tier")


def escalate(current: Tier, reason: str) -> Optional[Decision]:
    """The next tier up, or None when already at the top.

    Returning None rather than raising matters: "we already tried the best model
    and it still struggled" is a normal outcome that the caller handles by
    falling back to a human, not an error.
    """
    try:
        index = TIER_ORDER.index(current)
    except ValueError:  # pragma: no cover - defensive
        index = 0

    # Skip tiers configured to the same model: escalating gpt-4o -> gpt-4o would
    # pay twice for an identical call and change nothing.
    current_model = model_for(current)
    for tier in TIER_ORDER[index + 1:]:
        model = model_for(tier)
        if model != current_model:
            return Decision(tier, model, reason)

    return None
