"""Seed the pricing packages a new customer picks from after sign-up.

`POST /api/v1/payment/subscriptions/create/` only accepts an existing, active
`PricingPackage`, so a fresh database has nothing for the sign-up flow's plan
step to offer. This command creates the standard Free / Pro / Korporativ ladder
and is idempotent — it matches on package name and updates in place, so it is
safe to re-run after changing a price or a limit.

The last tier is a *custom* package: it carries no chargeable price, the
self-service subscribe and upgrade paths refuse it, and an interested company
posts to `pricing-packages/<id>/request/` instead. See
`PricingPackage.is_custom`.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.payment.models import Feature, PricingPackage
from apps.shared.addons.enums import CurrencyType, PricingPackageType

FEATURES = [
    {"name": "AI agent", "icon": "sparkles"},
    {"name": "Telegram integratsiyasi", "icon": "telegram"},
    {"name": "Instagram integratsiyasi", "icon": "instagram"},
    {"name": "Veb-sayt vidjeti", "icon": "globe"},
    {"name": "Bilimlar bazasi", "icon": "book"},
    {"name": "Lidlarni boshqarish va eksport", "icon": "download"},
    {"name": "Follow-up avtomatlashtirish", "icon": "repeat"},
    {"name": "Ommaviy xabarnoma (broadcast)", "icon": "megaphone"},
    {"name": "amoCRM integratsiyasi", "icon": "link"},
    {"name": "Billz integratsiyasi", "icon": "shopping-bag"},
    {"name": "Jamoa a'zolari", "icon": "users"},
    {"name": "Ustuvor qo'llab-quvvatlash", "icon": "headset"},
]

# The paid tier's price is pinned to the "989,000 so'mdan boshlanadi" claim
# published in the marketing blog (apps/blog/management/commands/seed_blog_posts.py) —
# keep the two in sync if either changes.
PACKAGES = [
    {
        "name": "Free",
        "type": PricingPackageType.FREE.value,
        "price": 0,
        "discount_price": None,
        "description": (
            "Aylo AI bilan tanishish uchun — 1 ta AI agent, veb-sayt vidjeti va "
            "asosiy bilimlar bazasi bilan bepul sinab ko'ring."
        ),
        "request_count": 100,
        "duration_days": 30,
        "is_popular": False,
        "features": ["AI agent", "Veb-sayt vidjeti", "Bilimlar bazasi"],
    },
    {
        "name": "Pro",
        "type": PricingPackageType.PRO.value,
        "price": 989000,
        "discount_price": None,
        "description": (
            "Eng ko'p tanlanadigan paket — oyiga 5 000 ta suhbat, Telegram va "
            "Instagram orqali to'liq muloqot, lidlarni boshqarish, follow-up "
            "avtomatlashtirish va CRM integratsiyalari."
        ),
        "request_count": 5000,
        "duration_days": 30,
        "is_popular": True,
        "features": [
            "AI agent",
            "Telegram integratsiyasi",
            "Instagram integratsiyasi",
            "Veb-sayt vidjeti",
            "Bilimlar bazasi",
            "Lidlarni boshqarish va eksport",
            "Follow-up avtomatlashtirish",
            "Ommaviy xabarnoma (broadcast)",
            "amoCRM integratsiyasi",
            "Billz integratsiyasi",
        ],
    },
    {
        # No price: sales agrees it per company. `PricingPackage.is_custom`
        # keys off `type`, and the subscribe/upgrade endpoints refuse it — a
        # company posts to `pricing-packages/<id>/request/` instead.
        "name": "Korporativ",
        "type": PricingPackageType.CUSTOM.value,
        "price": 0,
        "discount_price": None,
        "description": (
            "Kompaniyalar uchun individual yechim — cheksiz suhbatlar, jamoa "
            "a'zolari, maxsus integratsiyalar va ustuvor qo'llab-quvvatlash. "
            "Narx va shartlar biznesingizga moslab kelishiladi."
        ),
        "request_count": 0,
        "duration_days": 30,
        "is_popular": False,
        "features": [feature["name"] for feature in FEATURES],
    },
]

# Tiers that were seeded by an earlier version of this command and are no longer
# part of the ladder. They are deactivated rather than deleted — existing
# subscriptions still point at them, and `Subscription.pricing_package` is the
# only record of what a customer actually bought.
RETIRED_PACKAGE_NAMES = ["Basic"]


class Command(BaseCommand):
    help = "Create or update the Free / Pro / Korporativ pricing packages."

    @transaction.atomic
    def handle(self, *args, **options):
        features = {}
        for spec in FEATURES:
            feature, _created = Feature.objects.update_or_create(
                name=spec["name"], defaults={"icon": spec["icon"], "is_active": True},
            )
            features[spec["name"]] = feature

        for spec in PACKAGES:
            package, created = PricingPackage.objects.update_or_create(
                name=spec["name"],
                defaults={
                    "type": spec["type"],
                    "price": spec["price"],
                    "discount_price": spec["discount_price"],
                    "currency": CurrencyType.UZS.value,
                    "description": spec["description"],
                    "request_count": spec["request_count"],
                    "duration_days": spec["duration_days"],
                    "is_popular": spec["is_popular"],
                    "is_active": True,
                },
            )
            package.features.set(features[name] for name in spec["features"])
            price = "negotiated" if package.is_custom else f"{package.price} {package.currency}"
            self.stdout.write(
                self.style.SUCCESS(
                    f"{'Created' if created else 'Updated'} {package.name} "
                    f"({price}, {package.request_count} requests)"
                )
            )

        retired = PricingPackage.objects.filter(
            name__in=RETIRED_PACKAGE_NAMES, is_active=True,
        ).update(is_active=False)
        if retired:
            self.stdout.write(
                self.style.WARNING(
                    f"Deactivated {retired} retired package(s): "
                    f"{', '.join(RETIRED_PACKAGE_NAMES)}"
                )
            )
