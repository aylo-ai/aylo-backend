#!/usr/bin/env python3
"""Regenerate docs/testing/ENDPOINT_TEST_CHECKLIST.md from the live URL resolver.

Preserves every existing Coverage/Reviewed cell it can match by (path, view) —
regeneration must never silently erase a human's review mark or an agent's
"written (...)" annotation. New routes get a fresh heuristic Coverage guess
and an empty Reviewed box. Routes that vanished from the resolver are moved to
a "Removed since last generation" section instead of being dropped, so nothing
reviewed disappears without the human noticing.

Run from the repo root with the project virtualenv:
    .venv/bin/python .claude/skills/endpoint-test-checklist/scripts/regenerate.py
"""
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date

REPO_ROOT = subprocess.run(
    ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
).stdout.strip()
CHECKLIST_PATH = os.path.join(REPO_ROOT, "docs", "testing", "ENDPOINT_TEST_CHECKLIST.md")

APP_LABELS = {
    "assistant": "assistant — assistants, conversations, messages, leads, follow-ups",
    "blog": "blog — marketing content",
    "dashboard": "dashboard — admin/staff console",
    "integration": "integration — Telegram, Instagram, amoCRM, Billz, broadcasts",
    "landing": "landing — public marketing site leads",
    "payment": "payment — subscriptions, cards, transactions",
    "user": "user — auth, accounts, staff, notifications",
}


def live_endpoints():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    sys.path.insert(0, REPO_ROOT)
    import django

    django.setup()
    from django.urls import get_resolver
    from django.urls.resolvers import URLPattern, URLResolver

    rows = []

    def walk(res, prefix=""):
        for p in res.url_patterns:
            if isinstance(p, URLResolver):
                walk(p, prefix + str(p.pattern))
            elif isinstance(p, URLPattern):
                cls = getattr(p.callback, "cls", None) or getattr(p.callback, "view_class", None)
                if not cls:
                    continue
                mod = cls.__module__
                if not mod.startswith("apps."):
                    continue  # skip admin/drf-spectacular/static/etc.
                methods = [m.upper() for m in ("get", "post", "put", "patch", "delete") if hasattr(cls, m)]
                if not methods:
                    continue
                app = mod.split(".")[1]
                rows.append((app, prefix + str(p.pattern), ",".join(methods), cls.__name__, mod))

    walk(get_resolver())
    return rows


def parse_existing(path):
    """Return {(path, view): {"coverage": str, "reviewed": str}} from the current file."""
    existing = {}
    if not os.path.exists(path):
        return existing
    row_re = re.compile(r"^\|\s*([^|]+?)\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|\s*(.+?)\s*\|\s*(\[[ xX][^\]]*\][^|]*?)\s*\|\s*$")
    with open(path) as f:
        for line in f:
            m = row_re.match(line)
            if not m:
                continue
            _methods, url_path, view, coverage, reviewed = m.groups()
            existing[(url_path, view)] = {"coverage": coverage, "reviewed": reviewed}
    return existing


def heuristic_coverage(view, url_path, test_files):
    m = re.search(r"<", url_path)
    prefix = (url_path[: m.start()] if m else url_path).rstrip("/")
    for tf in test_files:
        out = subprocess.run(
            ["grep", "-lE", f"{re.escape(view)}|{re.escape(prefix)}", tf],
            capture_output=True, text=True,
        ).stdout
        if out.strip():
            rel = os.path.relpath(tf, REPO_ROOT)
            return f"heuristic ({rel})"
    return "none"


def main():
    rows = live_endpoints()
    existing = parse_existing(CHECKLIST_PATH)
    seen_keys = {(path, view) for _app, path, _methods, view, _mod in rows}

    test_files = subprocess.run(
        ["bash", "-c", f"cd {REPO_ROOT} && grep -rl 'class .*Test' apps --include='*.py'"],
        capture_output=True, text=True,
    ).stdout.split()
    test_files = [os.path.join(REPO_ROOT, t) for t in test_files]

    by_app = defaultdict(list)
    for app, path, methods, view, mod in rows:
        by_app[app].append((path, methods, view, mod))

    out = []
    out.append("# Endpoint Test Checklist\n")
    out.append(
        f"Auto-generated from the live URL resolver on {date.today().isoformat()} by walking "
        "`django.urls.get_resolver()` the same way `api-doctor` does. This is the working "
        "checklist for the **[test-writer](../../.claude/agents/test-writer.md)** agent and "
        "for your own manual review — regenerate the table (not the `Reviewed` column) with the "
        "**endpoint-test-checklist** skill whenever routes change.\n"
    )
    out.append("## How to use this file\n")
    out.append(
        "- **Coverage** is a heuristic: it means the view class name or the endpoint's static path\n"
        "  prefix appears in *some* test file. It is **not** a claim that the behavior is correct or\n"
        "  complete — a route can show `heuristic` and still be undertested.\n"
        "- **Reviewed** is the column that matters and the only one you should hand-edit. Leave it `[ ]`\n"
        "  until *you* have exercised that endpoint (via the test suite or a live probe) and are satisfied\n"
        "  the test(s) actually assert the right thing. Flip it to `[x]` once you're sure, or leave a note\n"
        "  like `[x] 2026-08-01 — happy path only, no perm test` if coverage is partial.\n"
        "- When `test-writer` adds tests for a route, it sets **Coverage** to `written`, links the test\n"
        "  file, and leaves **Reviewed** untouched — review is always a human step, never something an\n"
        "  agent marks off on its own.\n"
        "- Do not hand-edit the Method/Path/View columns; they're regenerated from the resolver.\n"
    )

    total = 0
    covered_total = 0
    for app in sorted(by_app):
        label = APP_LABELS.get(app, app)
        out.append(f"\n## `{app}` — {label}\n")
        out.append("| Method | Path | View | Coverage | Reviewed |")
        out.append("|---|---|---|---|---|")
        covered = 0
        for path, methods, view, _mod in sorted(by_app[app]):
            key = (path, view)
            prior = existing.get(key)
            # A prior "written (...)" (test-writer's own claim) or a row the
            # human already checked off is authoritative and must survive a
            # regeneration untouched. Anything else — "none" or a stale
            # "heuristic (...)" guess — is not yet anyone's judgment call, so
            # it's safe (and correct) to recompute fresh every run; freezing
            # it here would mean new tests never show up without a human
            # first invalidating the row by hand.
            frozen = prior and (
                prior["coverage"].lower().startswith("written")
                or prior["reviewed"].lower().startswith("[x")
            )
            if frozen:
                coverage, reviewed = prior["coverage"], prior["reviewed"]
            else:
                coverage = heuristic_coverage(view, path, test_files)
                reviewed = prior["reviewed"] if prior else "[ ]"
            if coverage != "none":
                covered += 1
            out.append(f"| {methods} | `{path}` | `{view}` | {coverage} | {reviewed} |")
            total += 1
        covered_total += covered
        out.append(f"\n_{app}: {covered}/{len(by_app[app])} have some coverage; {len(by_app[app]) - covered} have none._\n")

    removed = [k for k in existing if k not in seen_keys]
    if removed:
        out.append("\n## Removed since last generation\n")
        out.append(
            "These rows were in the checklist before but no longer match a live route — the URL "
            "changed or the view was deleted. Confirm that's intentional, then delete the row by hand.\n"
        )
        out.append("| Path | View | Coverage | Reviewed |")
        out.append("|---|---|---|---|")
        for path, view in sorted(removed):
            prior = existing[(path, view)]
            out.append(f"| `{path}` | `{view}` | {prior['coverage']} | {prior['reviewed']} |")

    out.append("\n## Totals\n")
    out.append(f"- {total} endpoints across {len(by_app)} apps.")
    out.append(f"- {covered_total} have some coverage; **{total - covered_total} have none** — start `test-writer` there.")
    reviewed_count = sum(1 for v in existing.values() if v["reviewed"].lower().startswith("[x"))
    out.append(f"- {reviewed_count} carried over as `Reviewed` from the previous version of this file.\n")

    os.makedirs(os.path.dirname(CHECKLIST_PATH), exist_ok=True)
    with open(CHECKLIST_PATH, "w") as f:
        f.write("\n".join(out))

    print(f"wrote {total} rows ({covered_total} covered, {total - covered_total} none) to {os.path.relpath(CHECKLIST_PATH, REPO_ROOT)}")
    if removed:
        print(f"{len(removed)} row(s) moved to 'Removed since last generation' — review and delete if intentional")


if __name__ == "__main__":
    main()
