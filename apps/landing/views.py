import os
import json
import requests
from datetime import datetime
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.http import JsonResponse, HttpResponse

from landing.models import LandingLead, LeadNotificationGroup
from landing.serializers import LandingLeadSerializer

LEAD_BOT_TOKEN = os.environ.get("LEAD_BOT_TOKEN", "")
LEAD_BOT_PASSWORD = os.environ.get("LEAD_BOT_PASSWORD", "repli2024")


class LandingLeadCreateView(APIView):
    """Public endpoint — no auth required. Creates a lead from landing page."""
    permission_classes = [AllowAny]
    throttle_scope = "landing_lead"

    def post(self, request):
        serializer = LandingLeadSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        lead = serializer.save()
        notify_telegram_groups(lead)

        return Response(
            {"message": "Rahmat! Tez orada siz bilan bog'lanamiz.", "id": str(lead.id)},
            status=status.HTTP_201_CREATED,
        )


def notify_telegram_groups(lead: LandingLead):
    """Send lead info to all active notification groups."""
    if not LEAD_BOT_TOKEN:
        return

    groups = LeadNotificationGroup.objects.filter(is_active=True)
    if not groups.exists():
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    tg_line = f"@{lead.telegram_username}" if lead.telegram_username else "—"

    text = (
        f"🔔 <b>Yangi lead!</b>\n\n"
        f"👤 <b>Ism:</b> {lead.full_name}\n"
        f"📞 <b>Telefon:</b> {lead.phone_number}\n"
        f"✈️ <b>Telegram:</b> {tg_line}\n"
        f"📄 <b>Sahifa:</b> {lead.source_page or '—'}\n"
        f"🕐 <b>Vaqt:</b> {now}"
    )

    for group in groups:
        try:
            requests.post(
                f"https://api.telegram.org/bot{LEAD_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": group.group_id,
                    "text": text,
                    "parse_mode": "HTML",
                },
                timeout=5,
            )
        except Exception as e:
            print(f"[-] Failed to notify group {group.group_id}: {e}")


@method_decorator(csrf_exempt, name="dispatch")
class LeadBotWebhookView(APIView):
    """
    Telegram webhook for the lead notification bot.
    Handles /start <password> in groups to verify and register them.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            data = request.data if isinstance(request.data, dict) else json.loads(request.body)
        except Exception:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        message = data.get("message") or data.get("my_chat_member")
        if not message:
            return Response(status=status.HTTP_200_OK)

        # Handle bot added/removed from group
        if "my_chat_member" in data:
            return self._handle_member_update(data["my_chat_member"])

        chat = message.get("chat", {})
        text = message.get("text", "").strip()
        chat_type = chat.get("type", "")
        chat_id = str(chat.get("id", ""))
        chat_title = chat.get("title", "")

        # Only handle group/supergroup messages
        if chat_type not in ("group", "supergroup"):
            # For private messages, send help
            if chat_type == "private":
                self._send(chat_id, "Bu bot faqat guruhlar uchun. Meni guruhga qo'shing va parol kiriting.")
            return Response(status=status.HTTP_200_OK)

        # Handle /start or /verify command with password
        if text.startswith("/verify") or text.startswith("/start"):
            parts = text.split(maxsplit=1)
            if len(parts) < 2:
                self._send(chat_id, "⚠️ Parolni kiriting:\n<code>/verify parol</code>")
                return Response(status=status.HTTP_200_OK)

            password = parts[1].strip()
            if password == LEAD_BOT_PASSWORD:
                group, created = LeadNotificationGroup.objects.get_or_create(
                    group_id=chat_id,
                    defaults={"group_title": chat_title, "is_active": True},
                )
                if not created:
                    group.is_active = True
                    group.group_title = chat_title
                    group.save()

                self._send(chat_id, "✅ Guruh tasdiqlandi! Endi yangi leadlar shu guruhga yuboriladi.")
            else:
                self._send(chat_id, "❌ Parol noto'g'ri. Qayta urinib ko'ring.")

            return Response(status=status.HTTP_200_OK)

        return Response(status=status.HTTP_200_OK)

    def _handle_member_update(self, member_data):
        chat = member_data.get("chat", {})
        new_status = member_data.get("new_chat_member", {}).get("status", "")
        chat_id = str(chat.get("id", ""))
        chat_title = chat.get("title", "")

        if new_status in ("member", "administrator"):
            self._send(
                chat_id,
                "👋 Salom! Men Repli AI lead notification botiman.\n\n"
                "Leadlarni shu guruhga olish uchun parolni kiriting:\n"
                "<code>/verify parol</code>",
            )
        elif new_status in ("left", "kicked"):
            LeadNotificationGroup.objects.filter(group_id=chat_id).update(is_active=False)

        return Response(status=status.HTTP_200_OK)

    def _send(self, chat_id, text):
        if not LEAD_BOT_TOKEN:
            return
        try:
            requests.post(
                f"https://api.telegram.org/bot{LEAD_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                timeout=5,
            )
        except Exception as e:
            print(f"[-] Send error: {e}")
