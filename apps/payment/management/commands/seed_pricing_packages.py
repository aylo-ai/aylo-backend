"""Seed the pricing packages a new customer picks from after sign-up.

`POST /api/v1/payment/subscriptions/create/` only accepts an existing, active
`PricingPackage`, so a fresh database has nothing for the sign-up flow's plan
step to offer. This command creates the standard Free / Basic / Pro ladder and
is idempotent — it matches on package name and updates in place, so it is safe
to re-run after changing a price or a limit.
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
    {"name": "Lidlar eksporti", "icon": "download"},
    {"name": "Jamoa a'zolari", "icon": "users"},
    {"name": "Ustuvor qo'llab-quvvatlash", "icon": "headset"},
]

PACKAGES = [
    {
        "name": "Free",
        "type": PricingPackageType.FREE.value,
        "price": 0,
        "discount_price": None,
        "description": "Repli AI bilan tanishish uchun — bitta agent va asosiy integratsiya.",
        "request_count": 100,
        "duration_days": 30,
        "is_popular": False,
        "features": ["AI agent", "Veb-sayt vidjeti", "Bilimlar bazasi"],
    },
    {
        "name": "Basic",
        "type": PricingPackageType.CUSTOM.value,
        "price": 199000,
        "discount_price": 149000,
        "description": "O'sib borayotgan biznes uchun — messenjerlar va lidlar bilan to'liq ish.",
        "request_count": 2000,
        "duration_days": 30,
        "is_popular": True,
        "features": [
            "AI agent",
            "Telegram integratsiyasi",
            "Instagram integratsiyasi",
            "Veb-sayt vidjeti",
            "Bilimlar bazasi",
            "Lidlar eksporti",
        ],
    },
    {
        "name": "Pro",
        "type": PricingPackageType.PRO.value,
        "price": 499000,
        "discount_price": None,
        "description": "Katta hajmdagi murojaatlar, jamoa bilan ishlash va ustuvor yordam.",
        "request_count": 10000,
        "duration_days": 30,
        "is_popular": False,
        "features": [feature["name"] for feature in FEATURES],
    },
]


class Command(BaseCommand):
    help = "Create or update the Free / Basic / Pro pricing packages."

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
            self.stdout.write(
                self.style.SUCCESS(
                    f"{'Created' if created else 'Updated'} {package.name} "
                    f"({package.price} {package.currency}, "
                    f"{package.request_count} requests)"
                )
            )
