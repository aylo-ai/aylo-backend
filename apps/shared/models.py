from uuid import uuid4

from django.db import models

from apps.shared.addons.enums import AgentRunOutcomes, AgentTiers


class BaseModel(models.Model):
    id = models.UUIDField(unique=True, primary_key=True, default=uuid4, editable=False)
    created_time = models.DateTimeField(auto_now_add=True)
    updated_time = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# Agent telemetry
# ---------------------------------------------------------------------------
#
# One `AgentRun` per user turn, one `AgentRunStep` per model call inside it.
# The split is what makes the data answer the question you actually have: a run
# row tells you what a turn cost, and the step rows tell you *why* -- which tier
# answered, whether it escalated, and where the seconds went.
#
# `conversation_id` and `assistant_id` are plain UUID columns, not ForeignKeys,
# for two reasons. `apps.shared` sits underneath every app (see the docstring in
# ai_service/tools.py); a FK to `assistant` would invert that and make every
# shared migration depend on it. And telemetry should outlive its subject -- a
# deleted conversation must not take the record of what it cost with it.


class AgentRun(BaseModel):
    """One agentic turn, start to finish."""

    conversation_id = models.UUIDField(db_index=True)
    assistant_id = models.UUIDField(db_index=True)

    # Routing
    initial_tier = models.CharField(max_length=16, choices=AgentTiers.choices())
    final_tier = models.CharField(max_length=16, choices=AgentTiers.choices())
    final_model = models.CharField(max_length=64)
    routing_reason = models.CharField(max_length=128, blank=True, default="")
    escalated = models.BooleanField(default=False, db_index=True)
    escalation_reason = models.CharField(max_length=128, blank=True, default="")

    # What triage decided the turn needed: intent, needs_knowledge, needs_tools,
    # complexity, and whether triage answered it outright. Kept even when the
    # plan was wrong -- a consistently wrong plan is only visible in the data if
    # the wrong ones are stored too.
    plan = models.JSONField(default=dict, blank=True)

    # Cost and effort
    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    cached_input_tokens = models.IntegerField(default=0)
    # NULL means "a model in this run has no price entry", which is deliberately
    # distinct from 0.0. See ai_service/pricing.py.
    cost_usd = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)

    api_calls = models.IntegerField(default=0)
    tool_calls = models.JSONField(default=list, blank=True)

    # Outcome
    duration_ms = models.IntegerField(default=0)
    outcome = models.CharField(
        max_length=16,
        choices=AgentRunOutcomes.choices(),
        default=AgentRunOutcomes.OK.value,
        db_index=True,
    )
    error = models.TextField(blank=True, default="")

    class Meta:
        db_table = "agent_runs"
        indexes = [
            # The three queries this table exists for: spend over time, spend by
            # assistant, and "show me the slow ones".
            models.Index(fields=["-created_time"]),
            models.Index(fields=["assistant_id", "-created_time"]),
            models.Index(fields=["-duration_ms"]),
        ]

    def __str__(self):
        return f"AgentRun {self.id} ({self.final_model}, {self.duration_ms}ms)"


class AgentRunStep(BaseModel):
    """One model call within a run."""

    run = models.ForeignKey(AgentRun, on_delete=models.CASCADE, related_name="steps")
    sequence = models.IntegerField()

    # triage | retrieve | act -- see ai_service/pipeline.py.
    stage = models.CharField(max_length=16, default="act", db_index=True)
    tier = models.CharField(max_length=16, choices=AgentTiers.choices())
    model = models.CharField(max_length=64)

    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    cached_input_tokens = models.IntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)

    duration_ms = models.IntegerField(default=0)
    # Tools the model asked for in this step, and how long running them took.
    tool_calls = models.JSONField(default=list, blank=True)
    tools_duration_ms = models.IntegerField(default=0)

    error = models.TextField(blank=True, default="")

    class Meta:
        db_table = "agent_run_steps"
        ordering = ["sequence"]
        indexes = [
            models.Index(fields=["run", "sequence"]),
        ]

    def __str__(self):
        return f"step {self.sequence} of {self.run_id} ({self.model})"
