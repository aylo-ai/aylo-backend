# drf-spectacular schema warnings & errors cleanup

**Date:** 2026-07-22
**Scope:** OpenAPI schema generation (`manage.py spectacular`) across all apps

## Summary

Schema generation was emitting a large volume of warnings and errors. Two root
causes, both cosmetic to the running API but noisy on every schema build and
producing an inaccurate/incomplete OpenAPI document:

1. **`SerializerMethodField` without a return type hint** → *"unable to resolve
   type hint for function `get_*`. Defaulting to string."* spectacular cannot
   introspect a plain method's return type, so it guessed `string` (often wrong —
   dicts, ints, lists).
2. **`APIView` subclasses with no `serializer_class`** → *"unable to guess
   serializer … Ignoring view for now."* These views return the
   `success_response`/`error_response` envelope and never had a serializer, so
   spectacular dropped them from the schema entirely.

Both classes are now **0**.

| Metric | Before | After |
|---|---|---|
| `unable to resolve type hint` warnings | ~50 | **0** |
| `unable to guess serializer` errors | ~40 | **0** |

## Fixes

### 1. Method-field type hints
Added `@extend_schema_field(OpenApiTypes.*)` to every `SerializerMethodField`
getter, with the type chosen from the actual return value:
`STR` for names/strings, `INT` for counts, `NUMBER` for money aggregates,
`OBJECT` for dict/list payloads, and nested serializers where applicable
(e.g. `get_messages` → `MessageSerializer(many=True)`).

### 2. APIView schema declaration
Added a class-level `@extend_schema(request=None, responses=OpenApiTypes.OBJECT)`
to each envelope-returning `APIView`. `request=None` is the honest declaration —
these views read `request.data` manually without a serializer, so there is
nothing for spectacular to introspect; `responses=OBJECT` documents the JSON
envelope. This removes the error and keeps the view in the schema.

## Files changed

| File | Change |
|---|---|
| `apps/assistant/serializers.py` | import + 2 method-field hints |
| `apps/assistant/views.py` | import + 1 view (`AssistantTokenStatsView`) |
| `apps/dashboard/serializers.py` | import + 42 method-field hints |
| `apps/dashboard/views.py` | import + 19 views |
| `apps/user/serializers.py` | import + 5 method-field hints |
| `apps/user/views.py` | import + 2 views (`GoogleLoginView`, `GoogleAuthCallbackView`) |
| `apps/integration/views.py` | import + 12 views (Instagram/Telegram webhooks, amoCRM, broadcasts) |
| `apps/landing/views.py` | import + 2 views |
| `apps/payment/views.py` | import + 1 view (`SubscriptionCancellationView`) |

No behavioral/runtime code changed — additions are schema-generation metadata only.

## Tests

No new tests: the change touches only OpenAPI schema metadata, not runtime
behaviour. Verified via schema generation + full regression run of the touched
apps.

```
$ .venv/bin/python manage.py spectacular ...
Warnings: 11 (7 unique)      # all pre-existing, unrelated — see Open items
Errors:   0 (0 unique)

$ .venv/bin/python manage.py test apps.assistant apps.dashboard apps.user \
      apps.integration apps.payment apps.landing --keepdb
Ran 42 tests in 3.970s
OK
```

`manage.py check` → *System check identified no issues.*

## Open items (need a human decision)

The remaining **11 warnings (7 unique)** are a **separate, pre-existing** issue,
not addressed here:

1. **Duplicate component names** — `Notification`, `UserShort` etc. registered
   twice from the dual import paths (`user.serializers` vs `apps.user.serializers`,
   documented in CLAUDE.md §5). Fix is structural: standardise imports/`urls.py`
   on a single path, or set `SPECTACULAR_SETTINGS` component name overrides.
2. **Enum name collisions** — multiple `status` choice sets resolved to
   auto-generated names (`StatusF4eEnum`, …). Fix: add `ENUM_NAME_OVERRIDES`
   entries in settings.

Both are cosmetic to schema accuracy and were out of scope for this pass. Flagging
for a follow-up if a clean, collision-free schema is desired.
