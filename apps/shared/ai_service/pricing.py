import logging
from dataclasses import dataclass
from typing import Dict, Optional

logger = logging.getLogger(__name__)

PER_MILLION = 1_000_000


@dataclass(frozen=True)
class Price:
    input_usd: float
    output_usd: float
    cached_input_usd: Optional[float] = None

    def cached_or_input(self) -> float:
        return self.input_usd if self.cached_input_usd is None else self.cached_input_usd


PRICES: Dict[str, Price] = {
    "gpt-4o": Price(input_usd=2.50, output_usd=10.00, cached_input_usd=1.25),
    "gpt-4o-mini": Price(input_usd=0.15, output_usd=0.60, cached_input_usd=0.075),
    "luna": Price(input_usd=1.00, output_usd=6.00),
    "terra": Price(input_usd=2.50, output_usd=15.00),
}

ALIASES: Dict[str, str] = {
    "gpt-5.6-luna": "luna",
    "gpt-5.6-lune": "luna",
    "gpt-5.6-terra": "terra",
}

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
    price = price_for(model)
    if price is None:
        return None

    return (
        input_tokens * price.input_usd
        + cached_input_tokens * price.cached_or_input()
        + output_tokens * price.output_usd
    ) / PER_MILLION


def add_costs(*values: Optional[float]) -> Optional[float]:
    if any(value is None for value in values):
        return None
    return sum(values)  # type: ignore[arg-type]
