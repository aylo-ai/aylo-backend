from uuid import uuid4

from django.db import models

from apps.shared.addons.enums import AgentRunOutcomes, AgentTiers


class BaseModel(models.Model):
    id = models.UUIDField(unique=True, primary_key=True, default=uuid4, editable=False)
    created_time = models.DateTimeField(auto_now_add=True)
    updated_time = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class AgentRun(BaseModel):
    conversation_id = models.UUIDField(db_index=True)
    assistant_id = models.UUIDField(db_index=True)

    initial_tier = models.CharField(max_length=16, choices=AgentTiers.choices())
    final_tier = models.CharField(max_length=16, choices=AgentTiers.choices())
    final_model = models.CharField(max_length=64)
    routing_reason = models.CharField(max_length=128, blank=True, default="")
    escalated = models.BooleanField(default=False, db_index=True)
    escalation_reason = models.CharField(max_length=128, blank=True, default="")

    plan = models.JSONField(default=dict, blank=True)

    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    cached_input_tokens = models.IntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)

    api_calls = models.IntegerField(default=0)
    tool_calls = models.JSONField(default=list, blank=True)

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
            models.Index(fields=["-created_time"]),
            models.Index(fields=["assistant_id", "-created_time"]),
            models.Index(fields=["-duration_ms"]),
        ]

    def __str__(self):
        return f"AgentRun {self.id} ({self.final_model}, {self.duration_ms}ms)"


class AgentRunStep(BaseModel):
    run = models.ForeignKey(AgentRun, on_delete=models.CASCADE, related_name="steps")
    sequence = models.IntegerField()

    stage = models.CharField(max_length=16, default="act", db_index=True)
    tier = models.CharField(max_length=16, choices=AgentTiers.choices())
    model = models.CharField(max_length=64)

    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    cached_input_tokens = models.IntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=12, decimal_places=8, null=True, blank=True)

    duration_ms = models.IntegerField(default=0)
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
