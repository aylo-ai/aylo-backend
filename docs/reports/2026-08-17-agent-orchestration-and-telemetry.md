# Request pipeline: triage → retrieve → act, with tiering and telemetry

**Date:** 2026-08-17
**Scope:** `apps/shared/ai_service/` — the production loop answering end users on
Telegram/Instagram.

## 1. What every turn used to cost

One model, one path, regardless of the message. `"salom"` and a five-part order
dispute both got `gpt-4o` carrying the full system prompt, every tool schema the
assistant owns, and the `file_search` tool. Two costs fell on **every** message:

- **Input tokens** — tool schemas and instructions re-sent whether or not the
  turn could ever use them.
- **Round trips** — knowledge lookups went *through* the model: emit a
  `file_search` call, wait, get called again with the results. Two model calls to
  answer one question out of a document.

Nothing recorded how long a turn took, what it cost, or which turns were
expensive.

## 2. The pipeline

```
user message
     │
     ▼
 ┌─────────┐   plan     ┌──────────┐  passages  ┌─────────┐   escalate on
 │ triage  │──────────▶ │ retrieve │──────────▶ │   act   │──▶ empty reply
 │ (Luna)  │            │ (no LLM) │            │ (tier)  │
 └─────────┘            └──────────┘            └─────────┘
     │ greeting → reply, turn ends here
     ▼
```

**triage** — one call on the cheap tier, ~200-token prompt, no tools. Returns a
`Plan`: what the turn needs, how hard it is, and for a greeting the reply itself,
which ends the turn there.

**retrieve** — *not a model call*. When the plan wants knowledge, the vector store
is queried directly (`vector_stores.search`) and passages go into the prompt. That
is the round trip removed: the model sees the documents on its first call.

**act** — the agentic tool loop, carrying only the schemas the plan justified, on
the tier its complexity earned. Escalates once if it produces nothing usable.

### The rule that makes it safe

Triage is a cheap model making a judgement call, so it will be wrong sometimes.
**Every failure degrades toward the old behaviour, never away from it.** An
unparseable plan, a timeout, a missing field, an exception — all produce
`Plan.permissive()`: knowledge on, tools on, normal complexity, which is exactly
what the loop did before. A broken router costs one cheap call and nothing else.

The mirror: triage may never *end* a turn on a guess. A `direct_reply` is
accepted only on a `trivial` turn — if the cheap model tries to answer a
complaint directly, the answer is discarded and the turn goes through `act`.

## 3. Models and what tiering is actually worth

| Tier | Model | Input /1M | Output /1M |
|---|---|---|---|
| fast, standard | **Luna** | $1.00 | $6.00 |
| deep | **Terra** | $2.50 | $15.00 |

Terra is **2.5×** Luna, not the 16× gap of `gpt-4o-mini`→`gpt-4o`. Two
consequences, and they point in opposite directions from the usual advice:

1. **Escalation is cheap.** A wrong cheap guess costs 2.5×, not 16×, so the
   pipeline can afford to be optimistic. Worth revisiting
   `AI_ESCALATE_ON_TOOL_CAP=True` once there is data.
2. **Tier choice is not the main lever any more.** With only 2.5× between tiers,
   the bigger win is the *token and round-trip reduction* — skipping tool
   schemas, and pre-retrieval removing a whole model call — which applies on
   every turn regardless of tier.

Because `fast` and `standard` are both Luna, escalation automatically skips the
duplicate tier and goes straight to Terra.

> ⚠ **The model ids are unverified.** `gpt-5.6-lune` / `terra` are written
> through to the API verbatim; there is no API key in this environment to check
> them against, and a wrong id 404s on the first customer turn. Run
> **`python manage.py check_ai_models`** on a machine with a key before relying
> on them — it asks the provider which ids are real and refuses to guess.
> `pricing.ALIASES` maps the `gpt-5.6-*` spellings onto the price rows.

## 4. Files

| File | Change |
|---|---|
| `ai_service/pipeline.py` | **new** — `Plan`, triage, direct vector retrieval, tool scoping, complexity→tier |
| `ai_service/routing.py` | **new** — tiers, cheap pre-routing, escalation walk, kill switch |
| `ai_service/pricing.py` | **new** — USD/token table incl. Luna/Terra, cache-aware, unknown-model handling |
| `ai_service/telemetry.py` | **new** — `RunRecorder`: per-stage timings, tokens, cost, structured log + DB |
| `ai_service/agent.py` | orchestrates the stages; per-step timing; parallel tool execution; `_attempt` returns the chain id so the caller picks the winning attempt |
| `shared/models.py` | **new** `AgentRun` (+`plan`), `AgentRunStep` (+`stage`) |
| `shared/management/commands/check_ai_models.py` | **new** — verifies configured ids exist and are priced; exit 1 if not |
| `config/settings.py` | `AI_TIER_MODELS`, `AI_PIPELINE_ENABLED`, `AI_TIER_ROUTING_ENABLED`, `AI_ESCALATE_ON_TOOL_CAP`, `AI_PARALLEL_TOOLS` |

## 5. What a turn looks like in the log

```json
{"event": "agent_run", "duration_ms": 1930,
 "api_calls": 2, "stages": ["triage", "retrieve", "act"],
 "plan": {"intent": "question", "needs_knowledge": true, "needs_tools": false,
          "complexity": "normal", "answered_directly": false},
 "initial_tier": "fast", "final_tier": "fast", "cost_usd": 0.0031,
 "steps": [{"stage": "triage", "duration_ms": 210, "input_tokens": 190},
           {"stage": "retrieve", "duration_ms": 95},
           {"stage": "act", "duration_ms": 1620, "input_tokens": 1430}]}
```

`api_calls` counts **model** calls only — `retrieve` is a vector-store query, and
counting it would make pre-retrieval (which removes a model call) look like it
added one.

## 6. Tests

```
$ .venv/bin/python manage.py test apps.shared.ai_service --keepdb
Ran 113 tests — OK
```

55 pre-existing + 58 new. The 55 originals were **not** rewritten: `AgentTestCase`
now prepends a triage response and exposes `calls` as act-stage calls only, so
every one of them still asserts what it always did, but now through the real
pipeline.

Full suite: **575 tests, 16 failing — the same 16 that failed before this work**,
none in `ai_service`. See §7.

Two bugs the tests caught in this work, both fixed:

- **Zero-token steps made the whole run's cost NULL.** `retrieve` has no price
  entry (it is not a model), and `add_costs` propagates the unknown — so every
  turn that used the knowledge base reported no cost at all. A step that spent no
  tokens now costs 0.0 regardless of model.
- **Escalating on the tool-iteration cap was the wrong trade.** An existing test
  caught it. Re-running the whole turn — every call and every tool — on the
  slowest kind of turn there is, to replace an answer that already exists, is
  wrong for a chat product. Now off by default behind `AI_ESCALATE_ON_TOOL_CAP`.

## 7. Pre-existing failures, unchanged by this work

| Failure | Cause |
|---|---|
| `apps.integration.tests` won't import | `SyntaxError: '(' was never closed` committed to `origin/dev` |
| `CardTokenBindingTests` ×3 | **Production bug — §8** |
| `PaymeVerificationThrottleTests` ×2 | Throttle returns 400 before 429 |
| `test_i18n_catalogs` ×3, `DashboardSmokeTests` | Catalog drift |
| nginx/Dozzle ×5 | Log-viewer allowlist commented out; Telegram bot tokens in the access log |

## 8. Open items

**S1 — Severe, production: saving a card 500s.** `apps/payment/serializers.py:221`
runs `Card.objects.filter(card_token=value)`, but `card_token` is an
`EncryptedTextField` with no `card_token_hash` companion, so it raises
`FieldError`. The repo already has the pattern (`apps/integration/models.py`
pairs `api_token`/`api_token_hash`). Needs a migration plus backfill — payment
path, wants sign-off.

**S2 — Verify the model ids** with `manage.py check_ai_models`. Until then a
wrong id fails on the first real turn.

**S3 — Tune triage on real data.** The prompt is a first draft. The questions the
`agent_runs` table now answers:

```sql
-- is the cheap router actually ending turns, or just adding a call?
SELECT plan->>'answered_directly' AS ended_at_triage, COUNT(*),
       AVG(duration_ms), SUM(cost_usd)
FROM agent_runs GROUP BY 1;

-- how often is the plan wrong enough to need a stronger model?
SELECT COUNT(*) FILTER (WHERE escalated) * 100.0 / COUNT(*) FROM agent_runs;

-- where does the time actually go?
SELECT stage, COUNT(*), AVG(duration_ms) FROM agent_run_steps GROUP BY stage;
```

If `answered_directly` is near zero, triage is pure overhead — raise its
willingness to answer, or disable it with `AI_PIPELINE_ENABLED=False`.

**S4 — Retrieval quality is unmeasured.** Pre-retrieval sends the top 5 passages
whether or not they are relevant, where `file_search` let the model judge. Worth
comparing answer quality before trusting it on knowledge-heavy assistants.
