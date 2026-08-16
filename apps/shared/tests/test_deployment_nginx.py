"""The edge config is the only thing standing in front of the log viewer.

`deployment/nginx/api.aylo.uz.conf` is the sole public listener: Dozzle and
gunicorn both bind loopback only, so every access decision about `/_logs/` is
made by that file. It shipped once with the `allow` / `deny all` block commented
out and `proxy_pass http://127.0.0.1:8080;` live, which put every container's
logs on the public internet behind Dozzle's own login alone. These tests parse
the real file — not a copy — and fail that shape.

The second half asserts that requests to the legacy Telegram webhook route,
whose path segment *is* a customer's bot token, never reach the access log.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import Resolver404, resolve

ROOT = Path(settings.BASE_DIR)
CONF = ROOT / "deployment/nginx/api.aylo.uz.conf"

DOZZLE_UPSTREAM = "proxy_pass http://127.0.0.1:8080;"
TELEGRAM_WEBHOOK_PREFIX = "/api/v1/integration/telegram/webhook/"

# RFC 5737 / RFC 3849 documentation ranges. Real deployments never live here, so
# an `allow` pointing at one means a placeholder was shipped as if it were real.
DOCUMENTATION_PREFIXES = ("192.0.2.", "198.51.100.", "203.0.113.", "2001:db8:")

LOCATION_RE = re.compile(r"^[ \t]*location[ \t]+(?P<match>[^{]+?)[ \t]*\{", re.M)
MAP_RE = re.compile(r"^[ \t]*map[ \t]+(?P<source>\$\S+)[ \t]+(?P<target>\$\S+)[ \t]*\{", re.M)


def strip_comments(text):
    """Drop `#` comments. nginx has no string literal that can contain one."""
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def _body(text, start):
    """Return the brace-matched block body that opens at `start`."""
    depth, index = 1, start
    while depth and index < len(text):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
        index += 1
    return text[start : index - 1]


def blocks(text, pattern, key):
    return {m.group(key): _body(text, m.end()) for m in pattern.finditer(text)}


class DozzleAllowlistTests(SimpleTestCase):
    """Criterion (a) and (b): the viewer is allowlisted and fails closed."""

    def setUp(self):
        self.raw = CONF.read_text()
        self.conf = strip_comments(self.raw)
        self.locations = blocks(self.conf, LOCATION_RE, "match")
        # Only blocks that actually reach the viewer are load-bearing: `return`
        # in `location = /_logs` runs before the access phase, so an allow/deny
        # there would be inert and asserting on it would be theatre.
        self.logs_blocks = {
            match: body
            for match, body in self.locations.items()
            if DOZZLE_UPSTREAM in body
        }

    def test_the_viewer_is_reachable_from_exactly_one_place(self):
        self.assertEqual(
            len(self.logs_blocks), 1, "more than one location proxies to Dozzle"
        )

    def test_dozzle_upstream_is_never_proxied_from_an_unguarded_block(self):
        for match, body in self.locations.items():
            if DOZZLE_UPSTREAM in body:
                self.assertRegex(
                    body, r"deny\s+all;", f"location {match} proxies to Dozzle openly"
                )

    def test_deny_all_is_the_last_access_rule(self):
        """allow/deny is first-match — a deny above an allow silences the allow."""
        for match, body in self.logs_blocks.items():
            deny = re.search(r"deny\s+all;", body)
            self.assertIsNotNone(deny, f"location {match} has no deny all")
            for allow in re.finditer(r"allow\s+\S+;", body):
                self.assertLess(
                    allow.start(),
                    deny.start(),
                    f"{allow.group()} in {match} is unreachable below `deny all`",
                )

    def test_allowlist_holds_no_documentation_placeholder_address(self):
        """A shipped 203.0.113.x is a placeholder someone forgot to replace."""
        for match, body in self.logs_blocks.items():
            for allow in re.finditer(r"allow\s+(?P<addr>\S+);", body):
                address = allow.group("addr")
                self.assertFalse(
                    address.startswith(DOCUMENTATION_PREFIXES),
                    f"{address} in {match} is a documentation range, not a real host",
                )

    def test_the_deny_is_not_commented_out(self):
        """The exact regression: the guard shipped as a comment for a week."""
        for line in self.raw.splitlines():
            self.assertNotRegex(
                line.strip(),
                r"^#\s*(deny|allow)\b",
                "the /_logs access rules are commented out again",
            )


class TelegramWebhookAccessLogTests(SimpleTestCase):
    """Criterion (c): the bot token in the URL path never reaches a log file."""

    def setUp(self):
        self.conf = strip_comments(CONF.read_text())
        self.maps = blocks(self.conf, MAP_RE, "target")

    def _webhook_map(self):
        for target, body in self.maps.items():
            if TELEGRAM_WEBHOOK_PREFIX in body:
                return target, body
        self.fail(
            "no map keyed on the telegram webhook path — the bot token in the "
            "URL is being written to the access log"
        )

    def test_the_webhook_path_maps_to_no_logging(self):
        target, body = self._webhook_map()
        self.assertIn(
            f"map $uri {target}",
            self.conf,
            "match the normalized, decoded path so an encoded slash cannot "
            "carry the token past the regex",
        )
        self.assertRegex(
            body,
            rf"~[^\n]*{re.escape(TELEGRAM_WEBHOOK_PREFIX)}[^\n]*\s0;",
            f"the webhook regex in map {target} must map to 0 (do not log)",
        )
        self.assertRegex(body, r"default\s+1;", "everything else must still be logged")

    def test_the_access_log_is_conditional_on_that_map(self):
        target, _ = self._webhook_map()
        self.assertRegex(
            self.conf,
            rf"access_log\s+\S+\s+\S+\s+if={re.escape(target)};",
            f"access_log must be gated on {target}, or the map does nothing",
        )

    def test_the_mapped_prefix_is_a_real_route(self):
        """If the route moves, the suppression silently stops covering it."""
        try:
            match = resolve(f"{TELEGRAM_WEBHOOK_PREFIX}placeholder-value/")
        except Resolver404:
            self.skipTest(
                "legacy token route is gone (T-02) — delete the map with it"
            )
        self.assertEqual(match.func.view_class.__name__, "TelegramWebhookView")
