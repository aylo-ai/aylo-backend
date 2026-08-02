"""Translation catalogs must stay in step with the code that reads them.

The catalogs were last extracted in June 2025 and then drifted: by July 2026,
106 `_()` strings in the tree had no entry in any catalog, so every language
served the raw Uzbek source; 18 catalog entries pointed at code that no longer
existed; two `_()` calls wrapped f-strings, making their lookup key the
*interpolated* text; and six messages had lost their `_()` wrapper entirely
while their translations sat unused in all five catalogs.

None of that raises an error at runtime — it just silently answers in the wrong
language. These tests are the alarm.
"""
import ast
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)
LOCALE = ROOT / "locale"
GETTEXT_CALLS = {"_", "gettext", "gettext_lazy", "ugettext", "ugettext_lazy"}
PLACEHOLDER = re.compile(r"%\([^)]*\)[sd]|%[sd]|\{[^}]*\}")


def source_files():
    for base in ("apps", "config"):
        for path in sorted((ROOT / base).rglob("*.py")):
            if "migrations" not in path.parts:
                yield path


def extract_msgids():
    """msgid -> [(file, line)], the way xgettext/makemessages sees the tree."""
    found = {}
    for path in source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = str(path.relative_to(ROOT))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name not in GETTEXT_CALLS or not node.args:
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found.setdefault(arg.value, []).append((rel, arg.lineno))
    return found


def parse_catalog(lang):
    """msgid -> msgstr, plus the header block, for one language."""
    text = (LOCALE / lang / "LC_MESSAGES" / "django.po").read_text(encoding="utf-8")
    entries, header = {}, ""
    unquote = lambda s: "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', s))
    for block in re.split(r"\n\n+", text):
        msgid = re.findall(r'^msgid ((?:"(?:[^"\\]|\\.)*"\s*)+)', block, re.M)
        msgstr = re.findall(r'^msgstr ((?:"(?:[^"\\]|\\.)*"\s*)+)', block, re.M)
        if not msgid or not msgstr:
            continue
        key = unquote(msgid[0])
        if key:
            entries[key] = unquote(msgstr[0])
        else:
            header = block
    return entries, header


class SourceStringTests(SimpleTestCase):
    def test_no_fstring_is_passed_to_gettext(self):
        """`_(f"...")` interpolates before the lookup, so it never translates."""
        offenders = []
        for path in source_files():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
                if name in GETTEXT_CALLS and node.args:
                    if isinstance(node.args[0], ast.JoinedStr):
                        rel = path.relative_to(ROOT)
                        offenders.append(f"{rel}:{node.args[0].lineno}")
        self.assertEqual(offenders, [], f"f-string passed to gettext at: {offenders}")

    def test_every_translatable_string_has_a_catalog_entry(self):
        """The regression that made all five catalogs a year out of date."""
        in_code = extract_msgids()
        in_catalog, _header = parse_catalog("ru")
        missing = sorted(set(in_code) - set(in_catalog))
        self.assertEqual(
            missing, [],
            f"{len(missing)} msgid(s) in code but not in the catalogs — they will "
            f"be served as raw Uzbek in every language: {missing[:5]}",
        )

    def test_catalogs_carry_no_entries_for_deleted_code(self):
        in_code = extract_msgids()
        in_catalog, _header = parse_catalog("ru")
        dead = sorted(set(in_catalog) - set(in_code))
        self.assertEqual(dead, [], f"catalog entries with no source: {dead[:5]}")


class CatalogHealthTests(SimpleTestCase):
    def setUp(self):
        self.codes = [code for code, _name in settings.LANGUAGES]

    def test_languages_and_locale_directories_agree(self):
        """A language with no catalog silently falls back to the source strings."""
        on_disk = sorted(p.name for p in LOCALE.iterdir() if p.is_dir())
        self.assertEqual(sorted(self.codes), on_disk)

    def test_korean_uses_its_real_iso_code(self):
        """The Korean catalog lived under `kn` — which is Kannada."""
        self.assertIn("ko", self.codes)
        self.assertNotIn("kn", self.codes)
        self.assertFalse((LOCALE / "kn").exists())

    def test_languages_is_defined_once(self):
        """A second `LANGUAGES = ...` further down settings.py silently wins."""
        source = (ROOT / "config" / "settings.py").read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"^LANGUAGES\s*=", source, re.M)), 1)

    def test_no_translation_is_empty(self):
        for lang in self.codes:
            entries, _header = parse_catalog(lang)
            empty = [k for k, v in entries.items() if not v]
            self.assertEqual(empty, [], f"{lang}: untranslated entries {empty[:5]}")

    def test_no_entry_is_left_fuzzy(self):
        """gettext ignores a fuzzy entry at runtime — it reads as untranslated."""
        for lang in self.codes:
            text = (LOCALE / lang / "LC_MESSAGES" / "django.po").read_text(encoding="utf-8")
            self.assertNotIn("#, fuzzy", text, f"{lang} has fuzzy entries")

    def test_headers_name_the_actual_language(self):
        """Every catalog shipped with an empty `Language:` header."""
        for lang in self.codes:
            _entries, header = parse_catalog(lang)
            self.assertIn(f'"Language: {lang}\\n"', header, f"{lang}: wrong Language header")
            self.assertIn("Plural-Forms:", header, f"{lang}: no Plural-Forms")
            self.assertNotIn("PACKAGE VERSION", header, f"{lang}: placeholder metadata")

    def test_all_catalogs_cover_the_same_msgids(self):
        reference, _header = parse_catalog("uz")
        for lang in self.codes:
            entries, _h = parse_catalog(lang)
            self.assertEqual(
                set(entries), set(reference),
                f"{lang} is out of step with the uz catalog",
            )

    def test_placeholders_survive_translation(self):
        """A dropped {name} or %s raises KeyError/TypeError at format time."""
        for lang in self.codes:
            entries, _header = parse_catalog(lang)
            for msgid, msgstr in entries.items():
                self.assertEqual(
                    sorted(PLACEHOLDER.findall(msgid)),
                    sorted(PLACEHOLDER.findall(msgstr)),
                    f"{lang}: placeholders differ for {msgid!r} -> {msgstr!r}",
                )


class SubscriptionStatusMessageTests(SimpleTestCase):
    """`SubscriptionValidationMixin` tells the user *why* their subscription
    is unusable, and the four causes must stay distinguishable in every
    language. A cancelled subscription reported as "not active", or a
    never-paid one reported as "tokens exhausted", sends the user to the wrong
    screen — which is the bug the two newest msgids were added to fix.
    """

    STATUS_MSGIDS = [
        "Sizning obunangiz bekor qilingan. Iltimos, yangi obuna tanlang.",
        "To'lov hali amalga oshirilmagan. Iltimos, to'lovni yakunlang.",
        "Sizning obunangiz faol emas. Iltimos, obunangizni faollashtiring.",
        "Sizning obunangiz tokeni tugagan. Iltimos, obunangizni yangilang.",
        "Sizning obunangiz muddati tugagan. Iltimos, obunangizni yangilang.",
    ]

    def setUp(self):
        self.codes = [code for code, _name in settings.LANGUAGES]

    def test_every_status_cause_is_translated_in_every_language(self):
        for lang in self.codes:
            entries, _header = parse_catalog(lang)
            for msgid in self.STATUS_MSGIDS:
                self.assertIn(msgid, entries, f"{lang}: no entry for {msgid!r}")
                self.assertTrue(entries[msgid], f"{lang}: empty translation for {msgid!r}")

    def test_translated_languages_do_not_echo_the_uzbek_source(self):
        """An untouched msgstr reads as Uzbek to a Russian or Korean user."""
        for lang in self.codes:
            if lang == "uz":
                continue
            entries, _header = parse_catalog(lang)
            echoed = [m for m in self.STATUS_MSGIDS if entries.get(m) == m]
            self.assertEqual(echoed, [], f"{lang}: untranslated Uzbek served for {echoed}")

    def test_each_cause_reads_differently(self):
        """Distinct causes that share wording are indistinguishable to the user."""
        for lang in self.codes:
            entries, _header = parse_catalog(lang)
            rendered = [entries[m] for m in self.STATUS_MSGIDS]
            self.assertEqual(
                len(set(rendered)), len(rendered),
                f"{lang}: subscription status messages collide: {rendered}",
            )


class LanguageSelectionTests(SimpleTestCase):
    def test_locale_middleware_is_installed_and_ordered(self):
        """Activation only works between SessionMiddleware and CommonMiddleware."""
        mw = list(settings.MIDDLEWARE)
        locale = "django.middleware.locale.LocaleMiddleware"
        self.assertIn(locale, mw)
        self.assertLess(mw.index("django.contrib.sessions.middleware.SessionMiddleware"),
                        mw.index(locale))
        self.assertLess(mw.index(locale),
                        mw.index("django.middleware.common.CommonMiddleware"))

    def test_the_broken_hand_rolled_middleware_is_gone(self):
        """It called activate() then deactivate() before running the view."""
        self.assertNotIn("config.middleware.LanguageMiddleware", settings.MIDDLEWARE)
        self.assertFalse((ROOT / "config" / "middleware.py").exists())

    def test_default_language_has_a_catalog(self):
        base = settings.LANGUAGE_CODE.split("-")[0]
        self.assertIn(base, [code for code, _name in settings.LANGUAGES])
