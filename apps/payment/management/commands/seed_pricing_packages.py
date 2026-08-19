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
        "name": "Basic",
        "type": PricingPackageType.BASIC.value,
        "price": 699000,
        "discount_price": None,
        "description": (
            "Eng ko'p tanlanadigan paket — oyiga 2 000 ta suhbat, Telegram va "
            "Instagram orqali to'liq muloqot, lidlarni boshqarish, follow-up "
            "avtomatlashtirish va CRM integratsiyalari."
        ),
        "request_count": 2000,
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
        "name": "Pro",
        "type": PricingPackageType.CUSTOM.value,
        "price": 0,
        "discount_price": None,
        "description": (
            "Kompaniyalar uchun individual yechim — suhbatlar va tokenlar soni "
            "biznesingizga moslab kelishiladi, barcha imkoniyatlar to'liq "
            "ochiq: jamoa a'zolari, maxsus integratsiyalar va ustuvor "
            "qo'llab-quvvatlash."
        ),
        "request_count": 0,
        "duration_days": 30,
        "is_popular": False,
        "features": [feature["name"] for feature in FEATURES],
    },
]

RETIRED_PACKAGE_NAMES = ["Korporativ"]


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
