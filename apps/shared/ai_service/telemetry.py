import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional

from apps.shared.addons.enums import AgentRunOutcomes

from . import pricing

logger = logging.getLogger(__name__)

COST_EXPONENT = Decimal("0.00000001")


def _ms(seconds: float) -> int:
    return int(round(seconds * 1000))


@dataclass
class StepRecord:
    sequence: int
    tier: str
    model: str
    stage: str = "act"
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    tool_calls: List[str] = field(default_factory=list)
    tools_duration_ms: int = 0
    error: str = ""

    @property
    def cost_usd(self) -> Optional[float]:
        if not (self.input_tokens or self.output_tokens or self.cached_input_tokens):
            return 0.0
        return pricing.cost_usd(
            self.model, self.input_tokens, self.output_tokens, self.cached_input_tokens
        )


class RunRecorder:
    def __init__(self, conversation_id, assistant_id, initial_tier: str, routing_reason: str):
        self.conversation_id = conversation_id
        self.assistant_id = assistant_id
        self.initial_tier = initial_tier
        self.routing_reason = routing_reason

        self.final_tier = initial_tier
        self.final_model = ""
        self.escalated = False
        self.escalation_reason = ""
        self.plan: Optional[Dict[str, Any]] = None
        self.outcome = AgentRunOutcomes.OK.value
        self.error = ""

        self.steps: List[StepRecord] = []
        self._started = time.perf_counter()


    def start_step(self, tier: str, model: str) -> StepRecord:
        step = StepRecord(sequence=len(self.steps) + 1, tier=tier, model=model)
        self.steps.append(step)
        self.final_tier = tier
        self.final_model = model
        return step

    def note_escalation(self, to_tier: str, reason: str) -> None:
        self.escalated = True
        self.escalation_reason = reason
        logger.info(
            "Escalating conversation %s to tier %s: %s",
            self.conversation_id, to_tier, reason,
        )

    def note_outcome(self, outcome: str, error: str = "") -> None:
        self.outcome = outcome
        self.error = error


    @property
    def duration_ms(self) -> int:
        return _ms(time.perf_counter() - self._started)

    @property
    def input_tokens(self) -> int:
        return sum(step.input_tokens for step in self.steps)

    @property
    def output_tokens(self) -> int:
        return sum(step.output_tokens for step in self.steps)

    @property
    def cached_input_tokens(self) -> int:
        return sum(step.cached_input_tokens for step in self.steps)

    @property
    def model_calls(self) -> int:
        return sum(1 for step in self.steps if step.stage != "retrieve")

    @property
    def tool_calls(self) -> List[str]:
        return [name for step in self.steps for name in step.tool_calls]

    @property
    def cost_usd(self) -> Optional[float]:
        return pricing.add_costs(*(step.cost_usd for step in self.steps))

    def summary(self) -> Dict[str, Any]:
        return {
            "event": "agent_run",
            "conversation_id": str(self.conversation_id),
            "assistant_id": str(self.assistant_id),
            "outcome": self.outcome,
            "duration_ms": self.duration_ms,
            "api_calls": self.model_calls,
            "stages": [step.stage for step in self.steps],
            "initial_tier": self.initial_tier,
            "final_tier": self.final_tier,
            "final_model": self.final_model,
            "escalated": self.escalated,
            "escalation_reason": self.escalation_reason,
            "routing_reason": self.routing_reason,
            "plan": self.plan,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "cost_usd": self.cost_usd,
            "tool_calls": self.tool_calls,
            "steps": [
                {
                    "sequence": step.sequence,
                    "stage": step.stage,
                    "tier": step.tier,
                    "model": step.model,
                    "duration_ms": step.duration_ms,
                    "tools_duration_ms": step.tools_duration_ms,
                    "input_tokens": step.input_tokens,
                    "output_tokens": step.output_tokens,
                    "tool_calls": step.tool_calls,
                }
                for step in self.steps
            ],
        }


    def finish(self) -> None:
        summary = self.summary()

        logger.info("agent_run %s", summary)

        self._persist(summary)

    def _persist(self, summary: Dict[str, Any]) -> None:
        try:
            from apps.shared.models import AgentRun, AgentRunStep

            run = AgentRun.objects.create(
                conversation_id=self.conversation_id,
                assistant_id=self.assistant_id,
                initial_tier=self.initial_tier,
                final_tier=self.final_tier,
                final_model=self.final_model or "",
                routing_reason=self.routing_reason[:128],
                escalated=self.escalated,
                escalation_reason=self.escalation_reason[:128],
                plan=self.plan or {},
                input_tokens=self.input_tokens,
                output_tokens=self.output_tokens,
                cached_input_tokens=self.cached_input_tokens,
                cost_usd=_as_decimal(self.cost_usd),
                api_calls=self.model_calls,
                tool_calls=self.tool_calls,
                duration_ms=summary["duration_ms"],
                outcome=self.outcome,
                error=self.error[:2000],
            )

            AgentRunStep.objects.bulk_create([
                AgentRunStep(
                    run=run,
                    sequence=step.sequence,
                    stage=step.stage,
                    tier=step.tier,
                    model=step.model,
                    input_tokens=step.input_tokens,
                    output_tokens=step.output_tokens,
                    cached_input_tokens=step.cached_input_tokens,
                    cost_usd=_as_decimal(step.cost_usd),
                    duration_ms=step.duration_ms,
                    tool_calls=step.tool_calls,
                    tools_duration_ms=step.tools_duration_ms,
                    error=step.error[:2000],
                )
                for step in self.steps
            ])
        except Exception as exc:  # noqa: BLE001 — telemetry must not break a turn
            logger.warning(
                "Could not persist agent run for conversation %s: %s",
                self.conversation_id, exc,
            )


def _as_decimal(value: Optional[float]) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value)).quantize(COST_EXPONENT)
    except Exception:  # noqa: BLE001 - never lose a run over a rounding edge case
        return None
