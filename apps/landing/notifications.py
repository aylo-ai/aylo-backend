import logging
import os

from apps.landing.models import LeadNotificationGroup
from apps.shared import http

logger = logging.getLogger(__name__)

LEAD_BOT_TOKEN = os.environ.get("LEAD_BOT_TOKEN", "")


def send_to_lead_groups(text: str) -> None:
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
