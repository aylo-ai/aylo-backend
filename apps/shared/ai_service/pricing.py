"""What a turn actually cost, in dollars.

Token counts alone do not tell you where the money goes: an output token is
several times more expensive than an input one, and a cached input token is
cheaper still. Recording only totals hides exactly the thing you want to see
after a routing change -- whether the cheap tier is being used, and whether it
is being used on the turns that matter.

Prices are USD per **one million** tokens, matching how providers publish them,
and live here rather than in settings because they change on the provider's
schedule and belong under review, not in a `.env` an operator edits at 2am.

Two deliberate choices:

**An unknown model costs `None`, not zero.** A model id that is not in the table
returns `None` all the way up, and the run is recorded with `cost_usd = NULL`.
Defaulting to `0.0` would silently under-report the bill and make a mis-typed
model id look like the cheapest option in the dashboard -- the exact opposite of
what this module exists for.

**Cached input is priced separately.** The agent already subtracts cached tokens
from its billable input count, but a cached token is discounted, not free, so a
caller that has the split can pass it and get a real number.
"""
import logging
from dataclasses import dataclass
from typing import Dict, Optional

logger = logging.getLogger(__name__)

PER_MILLION = 1_000_000


@dataclass(frozen=True)
class Price:
    """USD per million tokens."""

    input_usd: float
    output_usd: float
    # Falls back to the full input price when a provider does not discount cache
    # reads, so an incomplete entry under-reports nothing.
    cached_input_usd: Optional[float] = None

    def cached_or_input(self) -> float:
        return self.input_usd if self.cached_input_usd is None else self.cached_input_usd


# Keep this sorted by family. Update it when the provider changes prices --
# a stale entry here is a wrong number in every report downstream.
PRICES: Dict[str, Price] = {
    "gpt-4o": Price(input_usd=2.50, output_usd=10.00, cached_input_usd=1.25),
    "gpt-4o-mini": Price(input_usd=0.15, output_usd=0.60, cached_input_usd=0.075),
    # Operator-supplied, 2026-08-17. No cache-read discount was quoted, so
    # cached input is priced at the full input rate -- which under-reports
    # nothing if a discount turns out to exist.
    "luna": Price(input_usd=1.00, output_usd=6.00),
    "terra": Price(input_usd=2.50, output_usd=15.00),
}

# Every id the tiers may be configured with must resolve above. Aliases live
# here rather than as duplicate PRICES rows so a price change cannot be applied
# to one spelling and missed on the other.
ALIASES: Dict[str, str] = {
    "gpt-5.6-luna": "luna",
    "gpt-5.6-lune": "luna",
    "gpt-5.6-terra": "terra",
}

# Warn once per unknown model rather than on every turn; a mis-typed model id
# would otherwise produce one log line per user message.
_warned_unknown: set = set()


def price_for(model: str) -> Optional[Price]:
    price = PRICES.get(model) or PRICES.get(ALIASES.get(model, ""))
    if price is None and model not in _warned_unknown:
        _warned_unknown.add(model)
        logger.warning(
            "No price entry for model %r — cost will be recorded as NULL. "
            "Add it to apps/shared/ai_service/pricing.py.",
            model,
        )
    return price


def cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
) -> Optional[float]:
    """Cost of one call, or None when the model's price is unknown.

    ``input_tokens`` is the *billable* (uncached) count, matching what
    ``Agent._usage`` already returns; ``cached_input_tokens`` is priced at the
    discounted rate on top of it.
    """
    price = price_for(model)
    if price is None:
        return None

    return (
        input_tokens * price.input_usd
        + cached_input_tokens * price.cached_or_input()
        + output_tokens * price.output_usd
    ) / PER_MILLION


def add_costs(*values: Optional[float]) -> Optional[float]:
    """Sum costs, propagating the unknown.

    If any leg of a run used an unpriced model the total is unknowable, and
    saying so beats reporting the sum of the legs that happened to be priced.
    """
    if any(value is None for value in values):
        return None
    return sum(values)  # type: ignore[arg-type]
