"""Regression tests: the Telegram webhook helpers must not leak the bot token.

`set_telegram_webhook` is called with a URL whose path embeds the bot token
(see `apps/integration/serializers.py`), and `getWebhookInfo` echoes that URL
back in its response body. Both used to be `print()`ed, putting a live
credential into stdout and therefore into the container logs.
"""
import io
from contextlib import redirect_stdout
from unittest import mock

from django.test import TestCase

from shared.addons.telegram import get_webhook_info, set_telegram_webhook

BOT_TOKEN = "1234567:AAHsecrettokenvalue"
WEBHOOK_URL = f"https://api.aylo.uz/api/v1/integration/telegram/webhook/{BOT_TOKEN}/"


class TelegramWebhookLoggingTests(TestCase):
    def test_set_webhook_does_not_print_the_token(self):
        response = mock.Mock(status_code=200)
        response.json.return_value = {"ok": True}

        buffer = io.StringIO()
        with mock.patch("shared.addons.telegram.requests.post", return_value=response):
            with redirect_stdout(buffer):
                code = set_telegram_webhook(BOT_TOKEN, WEBHOOK_URL)

        self.assertEqual(code, 200)
        self.assertNotIn(BOT_TOKEN, buffer.getvalue())

    def test_set_webhook_failure_does_not_print_the_token(self):
        response = mock.Mock(status_code=401)
        response.json.return_value = {"ok": False, "description": WEBHOOK_URL}

        buffer = io.StringIO()
        with mock.patch("shared.addons.telegram.requests.post", return_value=response):
            with redirect_stdout(buffer):
                code = set_telegram_webhook(BOT_TOKEN, WEBHOOK_URL)

        self.assertEqual(code, 400)
        self.assertNotIn(BOT_TOKEN, buffer.getvalue())

    def test_get_webhook_info_does_not_print_the_registered_url(self):
        response = mock.Mock(status_code=200)
        response.json.return_value = {"ok": True, "result": {"url": WEBHOOK_URL}}

        buffer = io.StringIO()
        with mock.patch("shared.addons.telegram.requests.get", return_value=response):
            with redirect_stdout(buffer):
                code = get_webhook_info(BOT_TOKEN)

        self.assertEqual(code, 200)
        self.assertNotIn(BOT_TOKEN, buffer.getvalue())

    def test_get_webhook_info_failure_does_not_print_the_registered_url(self):
        response = mock.Mock(status_code=404)
        response.json.return_value = {"ok": False, "description": WEBHOOK_URL}

        buffer = io.StringIO()
        with mock.patch("shared.addons.telegram.requests.get", return_value=response):
            with redirect_stdout(buffer):
                code = get_webhook_info(BOT_TOKEN)

        self.assertEqual(code, 400)
        self.assertNotIn(BOT_TOKEN, buffer.getvalue())
