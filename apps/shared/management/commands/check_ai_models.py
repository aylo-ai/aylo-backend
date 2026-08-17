"""Verify that every configured model id actually exists, before users find out.

A wrong model id is a uniquely bad failure. It passes every test -- the suite
mocks the API -- deploys cleanly, and then 404s on the first real customer turn,
where the agent's fail-soft design turns it into the fallback message. The
symptom is "the bot got dumber", with nothing in the logs naming the cause.

Nothing in the codebase can confirm an id is real; only the provider knows. So
this asks it::

    python manage.py check_ai_models

Exit status is 0 only when every configured tier resolves, which makes it usable
as a deploy gate::

    python manage.py check_ai_models && ./deployment/deploy.sh

It also reports missing price entries. Those do not break a turn -- cost is
recorded as NULL by design rather than a wrong number -- but a tier with no
price is a tier you cannot evaluate, which defeats the point of tiering.
"""
from django.core.management.base import BaseCommand

from apps.shared.ai_service import pricing, routing


class Command(BaseCommand):
    help = "Check that every model configured in AI_TIER_MODELS exists and is priced."

    def add_arguments(self, parser):
        parser.add_argument(
            "--list",
            action="store_true",
            help="also print every model id the account can reach",
        )

    def handle(self, *args, **options):
        configured = routing.tier_models()

        self.stdout.write("configured tiers:")
        for tier in routing.TIER_ORDER:
            self.stdout.write(f"  {tier.value:<9} {configured.get(tier.value) or '(unset)'}")
        self.stdout.write("")

        available = self._available_models()
        if available is None:
            return  # _available_models already explained and exited

        if options["list"]:
            self.stdout.write(f"{len(available)} model(s) reachable:")
            for model_id in sorted(available):
                self.stdout.write(f"  {model_id}")
            self.stdout.write("")

        missing = []
        unpriced = []

        for tier in routing.TIER_ORDER:
            model = configured.get(tier.value)
            if not model:
                continue

            if model in available:
                self.stdout.write(self.style.SUCCESS(f"[ok  ] {tier.value}: {model} exists"))
            else:
                missing.append((tier.value, model))
                self.stdout.write(self.style.ERROR(f"[FAIL] {tier.value}: {model} NOT FOUND"))
                for suggestion in self._closest(model, available):
                    self.stdout.write(f"         did you mean: {suggestion}")

            if pricing.price_for(model) is None:
                unpriced.append(model)

        self._report(missing, unpriced)

    # -- helpers -----------------------------------------------------------

    def _available_models(self):
        from apps.shared.ai_service.client import get_client

        try:
            return {model.id for model in get_client().models.list()}
        except Exception as exc:  # noqa: BLE001 — any failure here is fatal to the check
            self.stderr.write(
                self.style.ERROR(f"Could not reach the provider: {type(exc).__name__}: {exc}")
            )
            self.stderr.write(
                "Set OPENAI_API_KEY and re-run. Without it the model ids cannot be "
                "verified, and an unverified id fails on the first customer turn."
            )
            raise SystemExit(2)

    @staticmethod
    def _closest(model, available, limit=3):
        """Cheap suggestions for a typo'd id. Prefix match beats edit distance
        here because provider ids are versioned (`name-YYYY-MM-DD`)."""
        stem = model.split("-")[0].lower()
        return sorted(m for m in available if m.lower().startswith(stem))[:limit]

    def _report(self, missing, unpriced):
        if unpriced:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"{len(unpriced)} model(s) have no price entry: {', '.join(sorted(set(unpriced)))}"
                )
            )
            self.stdout.write(
                "  Runs will record cost_usd = NULL (deliberately, not 0.0). "
                "Add them to apps/shared/ai_service/pricing.py to get real numbers."
            )

        self.stdout.write("")
        if missing:
            self.stderr.write(
                self.style.ERROR(
                    f"{len(missing)} tier(s) point at a model that does not exist: "
                    + ", ".join(f"{tier}={model}" for tier, model in missing)
                )
            )
            self.stderr.write(
                "Every turn routed to one of these would 404 and fall back. "
                "Fix AI_TIER_MODELS before deploying."
            )
            raise SystemExit(1)

        self.stdout.write(self.style.SUCCESS("all configured tiers resolve to a real model"))
