# i18n: language selection was dead, catalogs were a year stale

**Date:** 2026-07-30
**Scope:** `config/settings.py`, `config/middleware.py`, `locale/**`, `apps/{integration,payment,user}`

Nothing in this area raised an error — it just answered in the wrong language.
Three independent failures stacked up, and any one of them alone would have been
enough to make the other four languages pointless.

## Severity 1 — no request was ever translated

`config.middleware.LanguageMiddleware` ran ahead of Django's `LocaleMiddleware`
and did this:

```python
if language in dict(settings.LANGUAGES):
    activate(language)
deactivate()            # ← before get_response(request)
return self.get_response(request)
```

It activated the language and threw it away one line later, before the view ran.
It would not have mattered anyway: it read `request.META["Accept-Language"]`,
but Django exposes that header as `META["HTTP_ACCEPT_LANGUAGE"]`, so `language`
was always `None`. It also imported `from config import settings` — the module,
not the configured settings object.

**Fix:** deleted. `django.middleware.locale.LocaleMiddleware` was already
installed directly below it, correctly positioned between `SessionMiddleware`
and `CommonMiddleware`, and does exactly this job.

## Severity 1 — the Korean catalog was filed under Kannada

`locale/kn/` contained Korean (`한국어`). `kn` is the ISO code for Kannada;
Korean is `ko`. A client asking for `ko` got nothing; a client asking for
Kannada got Korean.

**Fix:** `git mv locale/kn locale/ko`, and `('kn', _('Korean'))` → `('ko', _('Korean'))`.

## Severity 1 — `LANGUAGES` was defined twice

`config/settings.py` defined `LANGUAGES` at line 272 (six entries, lazily
translated names) and again at line 466 in the modeltranslation block (five
entries, plain strings). The second silently won, so Korean was not a selectable
language at all and the language names were never translated.

**Fix:** one definition, lazy names, ordered `uz, ru, en, kk, ko` to match the
locale directories.

## Severity 2 — 106 strings had no catalog entry

The catalogs were extracted on 2025-06-10 and never regenerated. An AST sweep of
every `gettext`/`gettext_lazy` call found 106 msgids present in the code and
absent from all five catalogs — the whole of Leads, Flows, Steps, Buttons,
Trigger words, Comment responses, Broadcasts, Follow-ups, Billz and the Google
OAuth paths. Every one was served as raw Uzbek to Russian, English, Kazakh and
Korean users. 18 catalog entries pointed at code that no longer exists.

**Fix:** all 106 translated into all five languages; the 18 dead entries dropped.

## Severity 2 — `_()` wrapped f-strings, and six messages lost `_()` entirely

```python
message=_(f"{default_card.card_number[:4]}{'*' * 8}...")   # payment/views.py
```

An f-string interpolates *before* `gettext` sees it, so the lookup key was the
card number itself — a msgid that can never match. Same bug in
`user/services/notifications.py` (two messages, one of which was not wrapped at
all). Separately, six messages in `integration/views.py` had been reduced to
`message=("Access token topilmadi")` — plain parenthesised strings — while their
translations sat unused in all five catalogs.

**Fix:** placeholders moved out of the lookup
(`_("{card} karta ...").format(card=...)`), and the six `_()` wrappers restored.

## Wording corrections

| Language | Was | Now |
|---|---|---|
| kk | `Карта нөірі 16 цифрдан...` | `Карта нөмірі ...` (missing м) |
| kk | `Сұраныс объектісі қажет` | `Сұраныс нысаны қажет` (Kazakh, not Russian, term) |
| ru | `Этот email уже зарегистрирован` | `Этот адрес электронной почты уже зарегистрирован` (matches the rest of the catalog) |
| ru | `ID токен не найден` | `ID-токен не найден` |
| uz | `Foydalanuvchi ilovani deauthorized qildi` | `Foydalanuvchi ilova ruxsatini bekor qildi` |
| uz | `Hodim muvaffaqiyatli o'chirildi` | `Xodim ...` (matches `Xodimlar ro'yxati`) |
| all | `TokenEror - Noto'g'ri refresh token` / `Exception - ...` | one clean `Noto'g'ri refresh token`; the exception class moved to the log |

Every catalog also had a placeholder header block (`PACKAGE VERSION`,
`FULL NAME <EMAIL@ADDRESS>`) and — in all five files — an **empty `Language:`
header**. All five now carry the real code, a real team name, and the correct
`Plural-Forms` (ru keeps the 3-form Slavic rule, ko is `nplurals=1`).

## Per-language before → after

| Language | Entries before | Entries after | Empty msgstr | Fuzzy | Compiles |
|---|---|---|---|---|---|
| uz | 182 | 271 | 0 | 0 | ✅ 271 translated |
| ru | 182 | 271 | 0 | 0 | ✅ 271 translated |
| en | 182 | 271 | 2 → 0 | 0 | ✅ 271 translated |
| kk | 182 | 271 | 0 | 0 | ✅ 271 translated |
| ko (was kn) | 182 | 271 | 0 | 0 | ✅ 271 translated |

Every catalog previously carried the stock `#, fuzzy` header flag; none do now.

## Files changed

| File | Change |
|---|---|
| `config/middleware.py` | **Deleted** — broken and redundant |
| `config/settings.py` | One `LANGUAGES`, `kn`→`ko`, middleware entry removed, modeltranslation note |
| `locale/kn/` → `locale/ko/` | Renamed to the real Korean code |
| `locale/*/LC_MESSAGES/django.po` | Rebuilt: 271 entries, real headers, source order |
| `apps/payment/views.py` | f-string out of `_()` |
| `apps/user/services/notifications.py` | Two f-strings out of `_()`, one message wrapped for the first time |
| `apps/user/views.py` | Exception names out of user-facing text; logged instead |
| `apps/integration/views.py` | Six `_()` wrappers restored |
| `apps/shared/tests/test_i18n_catalogs.py` | New — 14 tests |
| `.claude/agents/i18n-translator.md` | New — the agent that owns this area, with the glossary this pass settled |

## Tests

```
$ .venv/bin/python manage.py test --keepdb
Found 224 test(s).
System check identified no issues (0 silenced).
........................................................................
----------------------------------------------------------------------
Ran 224 tests in 9.254s

OK
```

The 14 new tests assert what silently rotted: every `_()` literal in the tree has
a catalog entry, no catalog entry outlives its source, no `_()` wraps an
f-string, `LANGUAGES` is defined exactly once and matches the locale
directories, `ko` exists and `kn` does not, no empty or fuzzy translations,
`Language:` headers are filled, all five catalogs cover identical msgids,
placeholders survive translation, and `LocaleMiddleware` stays between
`SessionMiddleware` and `CommonMiddleware`.

`gettext` is not installed on the dev host, so the catalogs were built directly
rather than through `makemessages`. They were then compiled with the real
`msgfmt` inside the project image (`repli-backend-test:latest`, which ships
gettext as production does):

```
uz: 271 translated messages.    ru: 271 translated messages.
en: 271 translated messages.    kk: 271 translated messages.
ko: 271 translated messages.
```

and checked end to end against compiled `.mo` files:

```
'Lead muvaffaqiyatli yaratildi'
   uz: Lead muvaffaqiyatli yaratildi     ru: Лид успешно создан
   en: Lead successfully created         kk: Лид сәтті жасалды
   ko: 리드가 성공적으로 생성되었습니다
'{card} karta asosiy kartaga muvaffaqiyatli o'zgartirildi'
   ru: Карта 8600********1234 успешно назначена основной
```

## Open items

1. **120 more user-facing strings are not wrapped in `_()` at all** — 66 in
   `apps/dashboard/views.py` ("Users retrieved successfully", "Assistant not
   found", …) and ~50 in the amoCRM section of `apps/integration/views.py`.
   They are English-only today. Wrapping them adds ~116 msgids and ~580
   translations; it is a coherent second pass, not a footnote to this one, and
   `test_every_translatable_string_has_a_catalog_entry` will hold the line as
   soon as they are wrapped. **This is the next job for the i18n agent.**
2. **Uzbek product nouns need a native speaker.** `Flow`, `Step`, `Transition`,
   `Lead`, `Broadcast`, `Trigger word`, `Postback` and `Follow-up` are left in
   English in the Uzbek catalog rather than inventing terms. Russian, Kazakh and
   Korean use proper words (сценарий / шаг / переход / лид / рассылка /
   триггерное слово /팔로우업).
3. **`MODELTRANSLATION_LANGUAGES` deliberately still reads `('en','uz','ru','kk','ar')`**
   and no longer follows `LANGUAGES`. Those codes are database columns —
   `blog` and `payment` carry migrated `*_ar` fields. Aligning them (drop `ar`,
   add `ko`) is a destructive migration and needs a human decision.
4. The Korean and Kazakh translations were produced without a native reviewer.
   The safest to double-check are the follow-up, flow/step/transition and
   postback strings, where the source itself is jargon.
