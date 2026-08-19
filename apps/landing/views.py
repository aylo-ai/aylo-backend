import hmac
import html
import json
import logging
import os
from datetime import datetime

from django.conf import settings
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import csrf_exempt
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from apps.landing.models import LandingLead, LeadNotificationGroup
from apps.landing.notifications import send_to_lead_groups
from apps.landing.serializers import LandingLeadSerializer
from apps.shared import http
from apps.shared.addons.validations import error_response, success_response

logger = logging.getLogger(__name__)

LEAD_BOT_TOKEN = os.environ.get("LEAD_BOT_TOKEN", "")
LEAD_BOT_PASSWORD = os.environ.get("LEAD_BOT_PASSWORD", "")


class LandingLeadCreateView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "landing_lead"

    def post(self, request):
        serializer = LandingLeadSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                data=serializer.errors,
                message=_("Ma'lumotlar noto'g'ri"),
                code=400,
            )

        lead = serializer.save()
        notify_telegram_groups(lead)

        return success_response(
            data={"id": str(lead.id)},
            message=_("Rahmat! Tez orada siz bilan bog'lanamiz."),
            code=201,
        )


def notify_telegram_groups(lead: LandingLead):
    if not LEAD_BOT_TOKEN:
        return

    groups = LeadNotificationGroup.objects.filter(is_active=True)
    if not groups.exists():
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    full_name = html.escape(lead.full_name or "")
    phone_number = html.escape(lead.phone_number or "")
    source_page = html.escape(lead.source_page or "") or "—"
    tg_line = f"@{html.escape(lead.telegram_username)}" if lead.telegram_username else "—"

    text = (
        f"🔔 <b>Yangi lead!</b>\n\n"
        f"👤 <b>Ism:</b> {full_name}\n"
        f"📞 <b>Telefon:</b> {phone_number}\n"
        f"✈️ <b>Telegram:</b> {tg_line}\n"
        f"📄 <b>Sahifa:</b> {source_page}\n"
        f"🕐 <b>Vaqt:</b> {now}"
    )

    send_to_lead_groups(text)


@method_decorator(csrf_exempt, name="dispatch")
class LeadBotWebhookView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "lead_bot"

    def _verify_secret_token(self, request):
        expected = getattr(settings, "LEAD_BOT_WEBHOOK_SECRET", "")
        if not expected:
            logger.error("LEAD_BOT_WEBHOOK_SECRET is not configured; rejecting webhook")
            return False
        provided = request.META.get("HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN", "")
        if not provided:
            return False
        return hmac.compare_digest(provided, expected)

    def post(self, request):
        if not self._verify_secret_token(request):
            return error_response(message=_("Invalid webhook credentials"), code=403)

        try:
            return self._handle(request)
        except Exception:
            logger.exception("Lead bot webhook handling failed")
            return success_response(message=_("Xabar qabul qilindi"), code=200)

    def _handle(self, request):
        try:
            data = request.data if isinstance(request.data, dict) else json.loads(request.body)
        except Exception:
            return error_response(message=_("Ma'lumot yaroqsiz"), code=400)

        message = data.get("message") or data.get("my_chat_member")
        if not message:
            return success_response(message=_("Xabar mavjud emas"), code=200)

        if "my_chat_member" in data:
            return self._handle_member_update(data["my_chat_member"])

        chat = message.get("chat", {})
        text = (message.get("text") or "").strip()
        chat_type = chat.get("type", "")
        chat_id = str(chat.get("id", ""))
        chat_title = chat.get("title", "")

        if chat_type not in ("group", "supergroup"):
            if chat_type == "private":
                self._send(chat_id, "Bu bot faqat guruhlar uchun. Meni guruhga qo'shing va parol kiriting.")
            return success_response(message=_("Xabar qabul qilindi"), code=200)

        if text.startswith("/verify") or text.startswith("/start"):
            parts = text.split(maxsplit=1)
            if len(parts) < 2:
                self._send(chat_id, "⚠️ Parolni kiriting:\n<code>/verify parol</code>")
                return success_response(message=_("Parol kiritilmagan"), code=200)

            password = parts[1].strip()
            if self._password_matches(password):
                group, created = LeadNotificationGroup.objects.get_or_create(
                    group_id=chat_id,
                    defaults={"group_title": chat_title, "is_active": True},
                )
                if not created:
                    group.is_active = True
                    group.group_title = chat_title
                    group.save()

                logger.info("Lead notification group %s verified", chat_id)
                self._send(chat_id, "✅ Guruh tasdiqlandi! Endi yangi leadlar shu guruhga yuboriladi.")
            else:
                logger.warning("Lead notification group %s failed password verification", chat_id)
                self._send(chat_id, "❌ Parol noto'g'ri. Qayta urinib ko'ring.")

            return success_response(message=_("Xabar qabul qilindi"), code=200)

        return success_response(message=_("Xabar qabul qilindi"), code=200)

    @staticmethod
    def _password_matches(password):
        if not LEAD_BOT_PASSWORD:
            logger.error("LEAD_BOT_PASSWORD is not configured; refusing group verification")
            return False
        return hmac.compare_digest(str(password), LEAD_BOT_PASSWORD)

    def _handle_member_update(self, member_data):
        chat = member_data.get("chat", {})
        new_status = member_data.get("new_chat_member", {}).get("status", "")
        chat_id = str(chat.get("id", ""))

        if new_status in ("member", "administrator"):
            self._send(
                chat_id,
                "👋 Salom! Men Repli AI lead notification botiman.\n\n"
                "Leadlarni shu guruhga olish uchun parolni kiriting:\n"
                "<code>/verify parol</code>",
            )
        elif new_status in ("left", "kicked"):
            LeadNotificationGroup.objects.filter(group_id=chat_id).update(is_active=False)

        return success_response(message=_("Xabar qabul qilindi"), code=200)

    def _send(self, chat_id, text):
        if not LEAD_BOT_TOKEN:
            return
        try:
            http.post(
                f"https://api.telegram.org/bot{LEAD_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                timeout=5,
            )
        except Exception:
            logger.exception("Failed to reply to Telegram chat %s", chat_id)
