import logging
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from django.conf import settings

logger = logging.getLogger(__name__)


class Tier(str, Enum):
    FAST = "fast"
    STANDARD = "standard"
    DEEP = "deep"


TIER_ORDER: List[Tier] = [Tier.FAST, Tier.STANDARD, Tier.DEEP]

DEFAULT_TIER_MODELS = {
    Tier.FAST.value: "gpt-4o-mini",
    Tier.STANDARD.value: "gpt-4o",
    Tier.DEEP.value: "gpt-4o",
}

LONG_INPUT_CHARS = 400

TRIVIAL_INPUT_CHARS = 24


@dataclass(frozen=True)
class Decision:
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
        fallback = models.get(Tier.DEEP.value) or DEFAULT_TIER_MODELS[Tier.DEEP.value]
        logger.error(
            "No model configured for tier %s; falling back to %s. Check AI_TIER_MODELS.",
            tier.value, fallback,
        )
        return fallback
    return model


def routing_enabled() -> bool:
    return bool(getattr(settings, "AI_TIER_ROUTING_ENABLED", True))


def choose(assistant, conversation, user_input: str) -> Decision:
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
    try:
        index = TIER_ORDER.index(current)
    except ValueError:  # pragma: no cover - defensive
        index = 0

    current_model = model_for(current)
    for tier in TIER_ORDER[index + 1:]:
        model = model_for(tier)
        if model != current_model:
            return Decision(tier, model, reason)

    return None
