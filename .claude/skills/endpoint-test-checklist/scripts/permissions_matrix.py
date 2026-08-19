#!/usr/bin/env python3
"""Regenerate docs/testing/ENDPOINT_PERMISSIONS.md from the live URL resolver.

Walks django.urls.get_resolver() the same way the checklist script and
api-doctor do, reads each view's `permission_classes`, and classifies it into
a human-readable access level. Views that override `get_permissions()` (so
the class attribute alone doesn't tell the whole story) are flagged — their
"Effective access" text is hand-maintained in OVERRIDE_NOTES below because it
requires reading the view body, not just introspecting the class.

Run from the repo root with the project virtualenv:
    .venv/bin/python .claude/skills/endpoint-test-checklist/scripts/permissions_matrix.py
"""
import os
import subprocess
import sys
from collections import defaultdict
from datetime import date

REPO_ROOT = subprocess.run(
    ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
).stdout.strip()
OUT_PATH = os.path.join(REPO_ROOT, "docs", "testing", "ENDPOINT_PERMISSIONS.md")

APP_LABELS = {
    "assistant": "assistant — assistants, conversations, messages, leads, follow-ups",
    "blog": "blog — marketing content",
    "dashboard": "dashboard — admin/staff console",
    "integration": "integration — Telegram, Instagram, amoCRM, Billz, broadcasts",
    "landing": "landing — public marketing site leads",
    "payment": "payment — subscriptions, cards, transactions",
    "user": "user — auth, accounts, staff, notifications",
}

# Human label for each permission class name found on `permission_classes`.
LEVELS = {
    "AllowAny": "Public — no auth required",
    "IsAuthenticated": "Any authenticated user — must be owner-scoped in get_queryset/get_object",
    "IsDashboardUser": "Dashboard staff (any of: staff, support_agent, manager, admin, super_admin)",
    "IsAdmin": "Admin or super_admin only",
    "IsSuperAdmin": "Super_admin only",
    "IsManager": "Manager only",
    "IsSupportAgent": "Support_agent only",
    "IsCustomer": "Customer role only",
    "IsAdminOrCustomer": "Admin or customer — must be owner-scoped (created_by) in get_queryset",
    "CanManageUsers": "Admin or super_admin — user identity/role/active-state management",
    "CanManageFinance": "Admin or super_admin — billing/subscription/transaction management",
    "CanModerateConversations": "Manager/admin/super_admin + support_agent — conversation moderation",
}

# Views where get_permissions() is overridden: class-attribute permission_classes
# is only the fallback. Filled in by hand after reading the view source — keep
# this in sync when a view's per-method logic changes.
OVERRIDE_NOTES = {
    "FeatureListCreateView": "GET → Public (AllowAny); POST → Admin/super_admin only (IsAdmin)",
    "PricingPackageListCreateView": "GET → Public (AllowAny); POST → Admin/super_admin only (IsAdmin)",
    "PrivacyPolicyListCreateView": "GET → Public (AllowAny); POST → Admin/super_admin only (IsAdmin)",
    "UserAgreementListCreateView": "GET → Public (AllowAny); POST → Admin/super_admin only (IsAdmin)",
    "DashboardUserDetail": "GET → Dashboard staff (IsDashboardUser); PUT/PATCH/DELETE → Admin/super_admin only (CanManageUsers) — fixed 2026-07-31, was IsDashboardUser on all methods",
    "DashboardSubscriptionDetail": "GET → Dashboard staff (IsDashboardUser); PUT/PATCH/DELETE → Admin/super_admin only (CanManageFinance) — fixed 2026-07-31, was IsDashboardUser on all methods",
    "DashboardTransactionDetail": "GET → Dashboard staff (IsDashboardUser); PUT/PATCH/DELETE → Admin/super_admin only (CanManageFinance) — fixed 2026-07-31, was IsDashboardUser on all methods",
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
                    continue
                methods = [m.upper() for m in ("get", "post", "put", "patch", "delete") if hasattr(cls, m)]
                if not methods:
                    continue
                app = mod.split(".")[1]
                perm_classes = getattr(cls, "permission_classes", [])
                perm_names = [getattr(c, "__name__", str(c)) for c in perm_classes]
                overridden = "get_permissions" in cls.__dict__
                rows.append((app, prefix + str(p.pattern), ",".join(methods), cls.__name__, perm_names, overridden))

    walk(get_resolver())
    return rows


def describe(view_name, perm_names, overridden):
    if overridden:
        note = OVERRIDE_NOTES.get(view_name)
        if note:
            return note
        return f"Method-dependent (get_permissions overridden — base: {', '.join(perm_names) or '(none)'}). Read the view."
    if not perm_names:
        return "**No permission_classes set — defaults to AllowAny under DRF.** Verify this is intentional."
    labels = [LEVELS.get(n, f"`{n}` (undocumented — add to LEVELS in this script)") for n in perm_names]
    return "; ".join(labels)


def main():
    rows = live_endpoints()
    by_app = defaultdict(list)
    for app, path, methods, view, perms, overridden in rows:
        by_app[app].append((path, methods, view, perms, overridden))

    out = []
    out.append("# Endpoint Permission Matrix\n")
    out.append(
        f"Auto-generated from the live URL resolver on {date.today().isoformat()} — every view's actual "
        "`permission_classes` (or, where `get_permissions()` is overridden, a hand-maintained note on the "
        "real per-method split). Regenerate with:\n\n"
        "```bash\n"
        ".venv/bin/python .claude/skills/endpoint-test-checklist/scripts/permissions_matrix.py\n"
        "```\n"
    )
    out.append(
        "If a view's `get_permissions()` changes, update `OVERRIDE_NOTES` in that script — the "
        "generator can't infer per-method logic by introspection, only the fallback class list.\n"
    )
    out.append("## Access levels, from broadest to narrowest\n")
    out.append(
        "1. **Public** — no auth. Must still degrade to a clean 4xx on bad input, never 500.\n"
        "2. **Any authenticated user** — gate is role-agnostic; correctness depends entirely on the view's "
        "`get_queryset`/`get_object` scoping the row to `request.user`. A permission class alone never proves "
        "tenancy — check the view body.\n"
        "3. **Dashboard staff** (`IsDashboardUser`) — any of staff/support_agent/manager/admin/super_admin. "
        "Appropriate for read/list and low-stakes actions only.\n"
        "4. **Function-scoped admin** (`CanManageUsers`, `CanManageFinance`, `CanModerateConversations`) — "
        "admin/super_admin (plus support_agent for moderation), scoped to one domain. Prefer these over `IsAdmin` "
        "when the action is squarely in their domain — they self-document *why* it's gated.\n"
        "5. **`IsAdmin`** — admin/super_admin, for anything not covered by a function-scoped class (exports, "
        "audit logs, system health).\n"
        "6. **`IsSuperAdmin`** — narrowest; use sparingly, only for the handful of super-admin-only actions.\n"
    )
    out.append(
        "## Known-fixed issue (2026-07-31)\n\n"
        "`DashboardUserDetail`, `DashboardSubscriptionDetail`, `DashboardTransactionDetail` used to gate "
        "**every** method — including PUT/PATCH/DELETE — with plain `IsDashboardUser`, so any support_agent "
        "could PATCH a user's `user_role` to `super_admin` or delete a user/subscription/transaction outright, "
        "bypassing the narrower `CanManageUsers`/`CanManageFinance` endpoints built for exactly those actions. "
        "Fixed via `get_permissions()` overrides — see `docs/reports/2026-07-31-dashboard-permission-escalation.md`. "
        "**When adding a new `RetrieveUpdateDestroyAPIView` over a sensitive model (money, identity/role), default "
        "to a per-method `get_permissions()` split rather than one class for all methods — GET can be broader than "
        "the rest.**\n"
    )

    for app in sorted(by_app):
        label = APP_LABELS.get(app, app)
        out.append(f"\n## `{app}` — {label}\n")
        out.append("| Method | Path | View | Effective access |")
        out.append("|---|---|---|---|")
        for path, methods, view, perms, overridden in sorted(by_app[app]):
            out.append(f"| {methods} | `{path}` | `{view}` | {describe(view, perms, overridden)} |")

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        f.write("\n".join(out))

    print(f"wrote {len(rows)} rows to {os.path.relpath(OUT_PATH, REPO_ROOT)}")


if __name__ == "__main__":
    main()
