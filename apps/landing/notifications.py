"""Telegram fan-out to the verified sales groups.

Two things post into the same groups — the landing lead form and the enterprise
("custom") pricing request from `apps/payment` — so the send loop itself lives
here rather than inside either caller.

Every send is best-effort: the record it announces is already stored, so a
Telegram outage must never turn it into an error for the person who filled in
the form.

Callers are responsible for escaping their own interpolated values —
`parse_mode` is HTML and every field involved is public-form free text.
"""
import logging
import os

from apps.landing.models import LeadNotificationGroup
from apps.shared import http

logger = logging.getLogger(__name__)

LEAD_BOT_TOKEN = os.environ.get("LEAD_BOT_TOKEN", "")


def send_to_lead_groups(text: str) -> None:
    """Broadcast one HTML message to every verified sales group."""
    if not LEAD_BOT_TOKEN:
        return

    for group in LeadNotificationGroup.objects.filter(is_active=True):
        try:
            http.post(
                f"https://api.telegram.org/bot{LEAD_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": group.group_id,
                    "text": text,
                    "parse_mode": "HTML",
                },
                timeout=5,
            )
        except Exception:
            logger.exception("Failed to notify lead group %s", group.group_id)
