# Wave 1 — backend performance & correctness audit

**Date:** 2026-08-03 · **Branch:** `dev` · **Read-only pass — no code changed.**

## Disagreements with the brief

1. **No encrypted column is used in a `WHERE` clause.** `Integration.api_token` is a
   plain `TextField` (`apps/integration/models.py:31`). The blind-index question is
   premature — but see item 2: if tokens are ever encrypted (they hold full control of a
   customer's bot), `filter(api_token=...)` becomes unindexable and an HMAC-SHA256
   `api_token_hash` column with a unique index is the fix to land *at the same time*.
2. **`EXPLAIN` has never been run** on anything — no plan, benchmark or `assertNumQueries`
   exists outside tests. Every latency claim below is structural, not measured.
3. WS-5/6/7 (the optimization waves) of `2026-08-01-work-board.md` are **not done** —
   no report exists for them. Most data-layer findings below are their scope.

## Dependency map

```
config(settings, celery) ──> apps.shared{http, addons.redis, ai_service, permissions}
                                   ^                    |
   Meta/Telegram ──> integration.views ──> integration.tasks ──> ai_service.agent
                            |                    |                    |
                            v                    v                    v
                    integration.gateways   assistant.services   assistant.ai_tools
                            |                    |                    |
                            +-----> integration.models <──> assistant.models <──> payment.models
   dashboard.* ──reads──> assistant + integration + payment + user (no writes back)
```

**Three worst coupling problems**

| # | Problem | Evidence |
|---|---|---|
| 1 | Hard model-layer cycle held open by a *type annotation*. `assistant/models.py` imports `Integration` at module level; `integration/models.py` refers back with the string `'assistant.Assistant'`. The import's only use is the annotation on line 93. | `apps/assistant/models.py:6,93` ↔ `apps/integration/models.py:16` |
| 2 | Bidirectional app dependency on the hot message path: `assistant` imports an `integration` gateway, `integration` imports an `assistant` service. | `apps/assistant/services/conversation.py:23` ↔ `apps/integration/tasks/telegram.py:9` |
| 3 | `shared` stays "underneath apps" only because 31 imports are hidden inside function bodies. An import error therefore surfaces at message time in a Celery worker, not at boot. | `apps/shared/ai_service/agent.py:63,80,93,333-335`; `grep -c` = 31 tree-wide |

## Ranked findings

| # | Sev | Problem → evidence → fix | Eff | Win |
|---|---|---|---|---|
| 1 | P1 | **Instagram tokens are never refreshed.** `instagram_refresh_token()` is called once at exchange and its return value discarded (`gateways/instagram.py:39`); `CELERY_BEAT_SCHEDULE` has 4 entries, none of them a refresh (`config/settings.py:464-481`). Meta long-lived IG tokens expire (~60d) → every IG integration silently goes dark. Fix: beat task refreshing before expiry, storing the new token under `select_for_update`. | S | Prevents total IG outage. Whether it has already bitten prod is UNVERIFIED — compare `integration.updated_time` against "unroutable webhook" log volume. |
| 2 | P1 | **Seq scan on an unindexed `TEXT` column, up to 4× per Telegram message.** `Integration.objects.filter(api_token=...)` (`views/telegram.py:41`), then `Assistant.objects.filter(integrations__api_token=...)` again in each task (`tasks/telegram.py:29,78,106`). `Meta.indexes` covers only the two IG columns (`integration/models.py:70-75`). Fix: `AddIndexConcurrently` on `api_token`; pass `integration_id` to the task instead of re-resolving the token. | S | O(n) → O(log n) on every inbound TG message. Absolute win unmeasured. |
| 3 | P1 | **Dedupe is check-then-set, and the Telegram key is globally scoped.** `redis.get()` then `setex()` (`views/instagram_webhook.py:146-149`, `views/telegram.py:48-52`) — two concurrent retries both pass. Worse, `update_id` is unique *per bot*, so `tg_dedup:{update_id}` collides across bots and drops **legitimate** messages. Fix: `set(key, "1", nx=True, ex=300)`; key `tg_dedup:{integration.id}:{update_id}`. | S | Removes silent cross-bot message loss — grows quadratically with bot count. |
| 4 | P1 | **Redis is an unguarded, un-timed dependency of the webhook.** `Redis(...)` has no `socket_timeout`/`socket_connect_timeout` (`shared/addons/redis.py:16-22`) and the webhook calls it bare (`instagram_webhook.py:146-192`, `telegram.py:49-113`). A Redis hang parks one of 4 sync gunicorn workers (`gunicorn_conf.py:33,47`) until `timeout=600` fires; a Redis error 500s the delivery and Meta throttles then disables the subscription. Fix: 2s socket timeouts + `health_check_interval`; fail *open* (process without dedupe) instead of 500. | S | Removes the single likeliest cause of a full webhook outage. |
| 5 | P1 | **The debounce collector loses messages.** `lrange(0,-1)` then `delete` are separate round-trips (`tasks/collector.py:35-42`); anything `rpush`ed between them is deleted unread. Fix: `LPOP key count`, or `MULTI` `LRANGE`+`DEL`. | S | Eliminates a silent drop under exactly the burst the debounce exists for. |
| 6 | P1 | **`process_monthly_subscriptions` can double-charge.** No row lock on the subscription, `len(users)` materialises the whole queryset, `retry_count += 1; save()` is a non-atomic read-modify-write, and `Transaction` has no per-period idempotency key (`payment/tasks.py:18-60`). Two beat instances or one manual re-run charges twice. Fix: `select_for_update(skip_locked=True)` inside the atomic block, `F()` for the counter, unique `(subscription, billing_period)`. | M | Closes a real money-loss path. |
| 7 | P2 | **Broadcast: serial, sleeping, non-idempotent.** One task loops all recipients with `time.sleep(0.04–0.1)` and `max_retries=2` (`tasks/broadcast.py:47-97`) — a retry re-sends to everyone already messaged. Fix: fan out chunked per-recipient tasks on the `broadcast` queue with a per-recipient sent marker. | M | N×0.1s of worker occupancy → parallel; stops duplicate customer DMs. |
| 8 | P2 | **Dashboard N+1 and unbounded aggregates.** 4 count/max queries *per row* (`dashboard/serializers/integrations.py:67-102`); `sum([m.input_tokens for m in assistant_msgs])` materialises every message a user ever had (`serializers/users.py:47-60`); `messages.count()` twice per conversation (`serializers/conversations.py:27-40`); a full-table `Message.objects.count()` on every list (`views/conversations.py:39-45`); `obj.subscription.pricing_package` with no `select_related` (`serializers/users.py:76-85`). Fix: `annotate(Count(..., filter=Q(...)))`, `aggregate(Sum(...))`, `select_related`. | M | 4N+ queries per page → ~3. |
| 9 | P2 | **Missing composite index `(conversation, -created_time)` on `messages`.** The only index is `created_time` alone (`assistant/models.py:184-186`), which cannot serve a per-conversation sort. Hot users: two correlated subqueries per conversation in `_schedule_follow_ups` (`assistant/tasks.py:139-146`), `_is_conversation_eligible` (`:264`), `ConversationMessagesListView` (`assistant/views.py:227`), `publish_message_to_ws_assistant` (`shared/addons/redis.py:78`). Fix: add it CONCURRENTLY. | S | Filter+sort → index seek on the largest table. |
| 10 | P2 | **N+1 inside the follow-up scheduler.** A `FollowUpLog` query per idle conversation, per config, every 30 min (`assistant/tasks.py:174-178`). Fix: one prefetch of `(conversation_id, stage_number)` pairs per config. | S | Query count → O(configs). |
| 11 | P2 | **No `CACHES` setting anywhere** → DRF throttling uses per-process `LocMemCache`. With 4 workers, `otp_send: 5/minute` (`config/settings.py:98-113`) is really up to 20/minute and resets on deploy. Fix: `RedisCache` on the existing Redis. | S | Makes every declared rate limit real. |
| 12 | P2 | **No `CONN_MAX_AGE`** (`config/settings.py:175-185`) → TCP+auth handshake per request and per task, under `ATOMIC_REQUESTS=True`. Fix: `CONN_MAX_AGE=60`. | S | Removes a handshake from every webhook. Magnitude unmeasured. |
| 13 | P2 | **No 429 / rate-limit handling on Meta or Telegram.** Non-200 is logged and discarded (`gateways/instagram.py:130-135,173-179`); `shared/http.py:44-51` retries only 500/502/503/504 with `read=0`, ignores `Retry-After`, and no per-IG-account budget is tracked. A 429 storm becomes silent message loss. Fix: honour `Retry-After` / `X-Business-Use-Case-Usage`, backoff-with-jitter in the *task* (not the HTTP layer — a retry there would re-store the customer message), Redis token bucket per account. | M | Turns loss into delay. |
| 14 | P2 | **LLM spend is unbounded and un-budgeted.** With `previous_response_id` set only the new turn is sent (`agent.py:151-157`), so the server-side chain grows for 7 days (`CHAIN_TTL_SECONDS`) and is re-billed as input every turn; `MAX_TOOL_ITERATIONS=5` allows 6 calls per reply; blocking, non-streaming, worst case ≈190s (`timeout=60` × `MAX_ATTEMPTS=3` + backoff). No per-tenant token budget; fallback on outage is a canned string (`agent.py:117`). Cost per reply is **unmeasured** but recoverable: `Message.input_tokens/output_tokens` are stored — `AVG()` over the last week settles it. Two dashboards also price the same tokens differently — $2.5/$10 per 1M (`serializers/overview.py:58`) vs $5/$20 (`serializers/conversations.py:32`, `users.py:57`) — and `_usage` treats cached input as free (`agent.py:277`), which understates cost if it is discounted rather than free (UNVERIFIED). | M | Cost control + one honest number. |
| 15 | P2 | **Raw DM text accumulates in Redis with no TTL.** `rpush(f"messages:{chat_id}", ...)` and `set(f"last_seen:...")` never expire (`telegram.py:109-110`, `instagram_webhook.py:188-189`); only `collecting:` has one. If a collector run is skipped the customer's message text sits in Redis indefinitely. Fix: `EXPIRE` on both keys. Conversely, what *should* be cached and is not: the default `PromptTemplate` fetched per turn (`prompts.py:47`) and the per-webhook `Integration` lookup. | S | Bounded retention of customer content. |
| 16 | P3 | **Observability: you could not debug this at 3am.** `sentry-sdk==2.29.1` is installed (`requirements.txt:104`) but never initialised — no `sentry_sdk.init` anywhere; `LOGGING` is commented out (`config/settings.py:349-388`); `print()` remains in production paths (`shared/addons/redis.py:30,35,41,47`, `gateways/telegram.py:88-118`, `assistant/tasks.py:34,41`); no correlation id links a webhook delivery → Celery task → OpenAI call; no queue-depth or task-latency metric. Fix: init Sentry, restore `LOGGING` with a request-id filter, thread a `delivery_id` through `.delay()`. | M | The difference between "a customer says the bot is silent" and an answer. |

## Best win / effort

1. **#4 Redis timeouts + fail-open in the webhook** — S, removes the likeliest total-outage mode.
2. **#3 Atomic, per-bot dedupe key** — S, stops silent loss of real customer messages.
3. **#2 Index `integration.api_token` + pass `integration_id` to tasks** — S, kills a seq scan on every Telegram message.
4. **#9 `(conversation, -created_time)` index on `messages`** — S, one migration, helps five hot call sites.
5. **#1 Instagram token-refresh beat task** — S, prevents the whole IG channel expiring.

**Measure first, in this order:** `EXPLAIN (ANALYZE, BUFFERS)` on the four queries in #2/#9;
`AVG(input_tokens), AVG(output_tokens)` on `messages` for #14; Celery queue depth for #7.
