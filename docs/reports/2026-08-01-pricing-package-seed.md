# Pricing package seeding — 2026-08-01

## Issue

Production (`api.aylo.uz`) had **zero `PricingPackage` rows** — the sign-up
flow's plan-selection step had nothing to offer. The repo's seed data
(`apps/payment/management/commands/seed_pricing_packages.py`) also contradicted
already-published marketing: a live blog post
(`apps/blog/management/commands/seed_blog_posts.py`) promises "AI chatbot
imkoniyatlari oyiga atigi 299,000 so'mdan boshlanadi" (plans starting from
299,000 so'm/month), while the seed script's entry paid tier was priced at
199,000 (discount 149,000). The feature list was also thin: it only named 8
generic features and omitted amoCRM, Billz, broadcast campaigns, follow-up
automation, and team seats — all real, working capabilities confirmed in
`apps/integration/` and `apps/assistant/`.

## Fix

Updated `apps/payment/management/commands/seed_pricing_packages.py`:

| Plan | Type | Price | Discount | AI replies/mo | Duration | Popular |
|---|---|---|---|---|---|---|
| Free | `free` | 0 UZS | — | 100 | 30d | No |
| Basic | `custom` | 299,000 UZS | 239,000 | 2,000 | 30d | Yes |
| Pro | `pro` | 699,000 UZS | — | 10,000 | 30d | No |

Basic's price is pinned to the 299,000 figure already public in the blog.
Pro's price was raised from 499,000 → 699,000 to reflect the real feature gap
(amoCRM, Billz, broadcast, team seats, priority support) rather than just a
higher request quota.

Feature catalog expanded from 8 → 12 entries to match what the product
actually does:

- `Lidlar eksporti` → renamed `Lidlarni boshqarish va eksport` (the `Lead`
  model is a full pipeline, not just an export button)
- Added: `Follow-up avtomatlashtirish`, `Ommaviy xabarnoma (broadcast)`,
  `amoCRM integratsiyasi`, `Billz integratsiyasi`

Tier composition:
- **Free**: AI agent, website widget, knowledge base
- **Basic**: + Telegram, Instagram, lead management/export, follow-up automation
- **Pro**: + broadcast, amoCRM, Billz, team seats, priority support

`request_count` was confirmed (via code read) to decrement once per
AI-generated assistant reply (`apps/assistant/models.py` `Message.save()`),
not per user message or API call — this shaped how the quotas were sized.

## Deployment

The command was already present in the production image but had never been
run. Since the container has no git/bind-mount for application code (it's
baked into the image at `/opt/aylo/backend`, deployed via
`docker compose` — see `com.docker.compose.project.config_files`), the
updated file was `docker cp`'d directly into the running `aylochat-web-green-1`
container and the command executed there:

```bash
scp apps/payment/management/commands/seed_pricing_packages.py root@api.aylo.uz:/tmp/
ssh root@api.aylo.uz "docker cp /tmp/seed_pricing_packages.py aylochat-web-green-1:/app/apps/payment/management/commands/seed_pricing_packages.py"
ssh root@api.aylo.uz "docker exec aylochat-web-green-1 python manage.py seed_pricing_packages"
```

**This is a stopgap, not a real deploy** — the file live in the container will
be overwritten by whatever's in git on the next image rebuild. The repo file
must be committed and pushed through the normal pipeline so the running code
matches source control; it was left uncommitted per this repo's "commit only
when asked" convention.

Verified via `GET https://api.aylo.uz/api/v1/payment/pricing-packages/` —
all three plans return with the correct price, discount, and feature lists.

## Files changed

| File | Change |
|---|---|
| `apps/payment/management/commands/seed_pricing_packages.py` | Repriced Basic/Pro, expanded feature catalog from 8→12, rewrote descriptions |

## Tests

`.venv/bin/python manage.py test apps.payment --keepdb` — 22/22 passed
(unchanged; existing tests build their own `PricingPackage` fixtures inline
and don't depend on seed data, so no test changes were needed).

## Open items (need a human decision)

1. **Uncommitted change on the server.** The container currently runs a file
   that isn't in git yet. Commit + push + rebuild/redeploy through the normal
   pipeline to close this gap — otherwise the next deploy silently reverts
   pricing to whatever's last committed (in this case, nothing changes since
   the new file *is* what should be committed, but this must happen before
   any other deploy touches this container).
2. **No plan-tier enforcement exists in code.** `SubscriptionValidationMixin`
   only checks "is there an active subscription with quota left" — it does
   not check which plan a user is on before letting them use Telegram,
   Instagram, amoCRM, Billz, broadcasts, or add team members. A Free-tier
   user can currently use every integration the code allows. `validate_assistant_count`
   (caps at a hardcoded 5, not plan-based) exists but is dead code — never
   called. If the feature-gated pricing table above is meant to be
   enforced (not just displayed), that's a separate follow-up task.
3. **Translations.** Only the Uzbek (`_uz`) fields were populated via
   `MODELTRANSLATION_DEFAULT_LANGUAGE = 'uz'`. `en`/`ru`/`kk`/`ar` are blank.
   Not addressed here — flag if the dashboard/landing surfaces need them.
