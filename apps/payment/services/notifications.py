"""Sales alerts for the custom ("for companies") pricing tier.

The request is already stored by the time this runs, so every failure here is
logged and swallowed — sales can still read the row in the dashboard.
"""
import html
import logging

from django.utils import timezone

from apps.landing.notifications import send_to_lead_groups
from apps.payment.models import CustomPackageRequest

logger = logging.getLogger(__name__)


def notify_custom_package_request(request_obj: CustomPackageRequest) -> None:
    """Announce a new custom-package request in the verified sales groups."""
    try:
        # Every field below is free text from a public form, rendered with
        # parse_mode=HTML. Unescaped, a company named `<a href="...">click</a>`
        # forges links and markup inside the sales team's Telegram group — the
        # same defect that was fixed for the landing lead form.
        company = html.escape(request_obj.company_name or "")
        contact = html.escape(request_obj.full_name or "")
        phone = html.escape(request_obj.phone_number or "")
        email = html.escape(request_obj.email or "") or "—"
        comment = html.escape(request_obj.comment or "") or "—"
        package = request_obj.pricing_package
        package_name = html.escape(package.name) if package else "—"
        volume = (
            f"{request_obj.expected_conversations}"
            if request_obj.expected_conversations
            else "—"
        )

        send_to_lead_groups(
            f"🏢 <b>Yangi korporativ ariza!</b>\n\n"
            f"🏛 <b>Kompaniya:</b> {company}\n"
            f"👤 <b>Aloqa uchun:</b> {contact}\n"
            f"📞 <b>Telefon:</b> {phone}\n"
            f"✉️ <b>Email:</b> {email}\n"
            f"💬 <b>Kutilayotgan suhbatlar:</b> {volume}\n"
            f"📦 <b>Paket:</b> {package_name}\n"
            f"📝 <b>Izoh:</b> {comment}\n"
            f"🕐 <b>Vaqt:</b> {timezone.localtime().strftime('%Y-%m-%d %H:%M')}"
        )
    except Exception:
        logger.exception(
            "Failed to announce custom package request %s", request_obj.id,
        )
