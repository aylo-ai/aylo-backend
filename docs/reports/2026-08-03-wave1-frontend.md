# Wave 1 — Frontend audit (aylo-frontend)

**Date:** 2026-08-03 · **Scope:** `/home/shahzod/mywork/aylo-frontend`, read-only. No code changed.
**Evidence gathered by running:** `npm run typecheck` (clean), `npm run lint` (clean),
`npm run build` (succeeds), `npm test` (95 tests / 10 files, all pass), `npm run i18n:check`.

## Disagreement with the brief

The brief asks about websocket reconnect/backoff. **The frontend does not talk to
`repli-websocket` at all** — a grep for `WebSocket|socket.io|ws://|wss://` over `src/` returns only
three comments, and `CLAUDE.md:218-219` records "no websockets" as a deliberate decision. Everything
live is REST polling. The reconnect questions are therefore answered as "polling failure behaviour".

## Findings

| # | Sev | Title | File:line | Impact | Fix |
|---|---|---|---|---|---|
| 1 | P1 | `safeNext` open redirect via backslash | `src/lib/auth/onboarding.ts:67-70` | `?next=/\evil.com` passes the guard; `new URL("/\evil.com", origin)` resolves to `https://evil.com/` (verified in Node). Reachable end-to-end: `/api/auth/google?next=/\evil.com` → cookie (`google/route.ts:30-37`) → `google/callback/route.ts:66` redirects the freshly signed-in user off-site. Phishing amplifier on a trusted domain. | Resolve and compare origins: `new URL(value, "http://x").origin === "http://x"`, or reject `[\\\t\r\n]`. Extend `onboarding.test.ts:52`, which only covers `//evil.com`. |
| 2 | P1 | `next` used unvalidated in the OTP flow | `src/components/features/auth/VerifyCodeForm.tsx:24,56` | `router.replace(next \|\| "/home")` with `next` straight from `useSearchParams()` — no `safeNext`, so a fully absolute `https://evil.com` is accepted and Next hard-navigates. Narrower than #1 (victim needs a live OTP) but the guard is simply absent. | Route it through the same hardened `safeNext`. |
| 3 | P1 | Inbox polling fans out ~26 backend requests every 5s | `src/lib/data/conversations.ts:181-243`; `ChatsInbox.tsx:26,94` | `fetchInboxConversations` issues 1 list call + up to 25 per-conversation message calls (`UNREAD_FANOUT_LIMIT`) purely to compute unread badges, on a 5s `refetchInterval`. **Estimate:** ~5.2 req/s to Django per open inbox tab; 20 concurrent operators ≈ 104 req/s. The code comments the cause itself (`conversations.ts:174-179`). | Backend: add `unread_message_count` to `ConversationSerializer` (already computed in `MessageBulkReadView`). Frontend then drops the fan-out entirely. This is the single highest-value fix in the report. |
| 4 | P1 | i18n is 12% adopted and `i18n:check` reports it as 100% | `scripts/i18n-check.mjs:33-40`; `messages/en.ts` (70 keys); `ChatsInbox.tsx:274,291,339,394` | Only 18 of 157 components call `t()`; the rest hardcode English (`"Chats"`, `"No chats yet."`, `"Couldn't send the message."`). The check compares catalog *parity*, not extraction coverage, so it prints `uz/ru/en 100% ✓` over an untranslated product. uz/ru users get an English dashboard. | Keep the parity check, add an extraction check (fail on JSX text literals outside `t()`). Then extract screen by screen, inbox first. |
| 5 | P1 | A dropped connection renders as "No chats yet" | `ChatsInbox.tsx:354-359,446-452` | Server-action network failures reject, so `data` is `undefined`: `isPending` is false, `conversationsError` is null (it only reads `data.success`), list is `[]` → the operator sees the empty state, not an error. An outage is indistinguishable from having no customers. | Surface `conversationsQuery.isError`; add an offline/stale banner (`useIsFetching` + `onlineManager`) and keep last-known data visible. |
| 6 | P2 | No security headers at all | `next.config.ts:1-23` (no `headers()`) | No CSP, `X-Frame-Options`, or `Referrer-Policy`. The dashboard is framable (clickjacking on the Agent-Answer toggle / delete actions), and the PII-bearing URLs in #9 leak via `Referer`. | Add a `headers()` block. CSP needs a nonce for the theme script at `app/layout.tsx:59`. |
| 7 | P2 | No timeout on any backend call | `src/lib/api/backend.ts:82-101` | Node `fetch` has no default timeout. A hung Django socket hangs the Next request forever; with 4–5s polling, sockets accumulate until the Node process is exhausted. | `signal: AbortSignal.timeout(10_000)`; the existing `catch` already returns a clean 503. |
| 8 | P2 | Unvalidated `assistantId` interpolated into the upstream path | `src/app/api/leads/export/route.ts:15,42` | `../` in the param traverses to a different Django path (`fetch` normalizes it) with the caller's own token. Self-scoped, GET-only, so no privilege escalation — but it is unvalidated attacker input in a URL, and a UUID regex already exists next door at `instagram-oauth.ts:52-53`. | Reject anything that isn't a UUID, matching `parseTarget`. |
| 9 | P2 | Customer PII in URLs | `VerifyCodeForm.tsx:23` (`?identity=`); `LeadsTable.tsx:140-143,167-169` (`?query=`) | The user's email/phone and operator lead searches (phone/email) land in the address bar → browser history, proxy and access logs, and `Referer` on any outbound link (compounded by #6). | Carry `identity` in a short-lived httpOnly cookie like the Google `next`; keep the lead search client-side or POST it. |
| 10 | P2 | The notification bell never refreshes | `use-notifications.ts:52-59`; `QueryProvider.tsx:22-24` | No `refetchInterval`, and the provider sets `refetchOnWindowFocus: false` globally. With `staleTime: 30_000` and nothing to trigger a refetch, the unread count is frozen for the life of the page. | Give this one query a `refetchInterval` (60s) or re-enable focus refetch for it. |
| 11 | P2 | Whole message history re-fetched every 4s, unpaginated and unvirtualized | `conversations.ts:246-253`; `ChatsInbox.tsx:27,608-612` | `fetchMessagesRaw` returns every message in the thread; the list renders every one as a DOM node. A long thread transfers and re-renders its full history 15×/minute. TanStack's structural sharing spares React when nothing changed, but not the network or the DOM node count. | Paginate (`?after=<id>`) and virtualize past ~200 messages. |
| 12 | P2 | `Alert` exists but 46 files hand-roll it without dark-mode variants | `ChatsInbox.tsx:327` vs `ui/Alert.tsx:54-56` | The primitive ships `dark:border-red-900/50 dark:bg-red-950/40`; the copies are bare `border-red-200 bg-red-50 text-red-700`. 229 raw palette classes sit outside the token system, and 46 files that use them define no `dark:` variant — those banners break in dark mode. | Replace hand-rolled banners with `<Alert>`; lint-ban raw palette classes outside `components/ui`. |
| 13 | P3 | Forced scroll-to-bottom fights the operator | `ChatsInbox.tsx:140-142` | Every new polled message yanks the viewport down, even mid-scroll through history. | Only auto-scroll when already pinned to the bottom. |
| 14 | P3 | `next` is dropped in the OTP flow | `SignInForm.tsx:38-39,76` | Forwarded to Google but not to `/verify-code`, so an OTP sign-in from a deep link always lands on `/home`. | Add `next` to the `URLSearchParams` at line 75. |
| 15 | P3 | Docs referenced as mandatory don't exist | `CLAUDE.md:12,59,198` | `PROGRESS.md` and `INTEGRATION.md` are absent from the repo, yet CLAUDE.md makes reading them a precondition for design and integration work. `design/` **does** exist (67 PNGs, vs the "~68" claimed at `CLAUDE.md:8`), and `error-design/` exists but is **empty** — so a design pass has no error-state reference to work from. | Restore or delete the references; populate or drop `error-design/`. |
| 16 | P3 | Zero test coverage for the inbox | `src/components/features/chats/` (no test file) | All 95 tests are auth/theme/validation. The polling, optimistic-update and read-receipt logic — the most stateful code in the app — is untested. | Test the cache-rollback paths in `ChatsInbox.tsx:157-235` first. |

## Answers to the brief

**1. State management.** Source of truth is the backend, read through server-only `apiFetch`
(`lib/api/client.ts`) and exposed to the client only via Server Actions (`lib/chats/actions.ts`).
No server state is mirrored into `useState` — client state is confined to `input`, filters, and
`mobilePane` (`ChatsInbox.tsx:70-77`). This is the right architecture and it is followed
consistently. TanStack Query: one client in `QueryProvider.tsx` (`staleTime: 30_000`,
`refetchOnWindowFocus: false`, `retry: 1`); keys are `["chat-conversations", agentFilter]` and
`["chat-messages", conversationId]`, memoized and consistently reused for optimistic writes.
Stale-data risks are #3, #5, #10 above.

**2. Real-time.** Polling only — 5s conversations, 4s messages, via `refetchInterval`
(`ChatsInbox.tsx:94,101`). TanStack's default `refetchIntervalInBackground: false` correctly pauses
polling in a hidden tab. There is no backoff, no offline detection, and no UI for a dropped
connection (#5). Note the reads are `POST` Server Action round-trips, so they can't be HTTP-cached
or deduped at the edge.

**3. Client security.** Clean on the things that matter most: **the Instagram/Telegram
`api_token` never reaches the browser** — it is explicitly dropped in `lib/data/integrations.ts:5-6,32`
and masked in the UI (`TelegramConnectDrawer.tsx:83`); no `client_secret`/`app_secret` appears
anywhere in `src/`. JWTs are httpOnly, `sameSite: lax`, `secure` in production, and never touch JS
(`lib/api/auth-cookies.ts:33-41`); refresh is silent in `middleware.ts:83-90` and once-per-401 in
`client.ts:96-112`. `middleware.ts` gates `(dashboard)`/`(onboarding)`, bounces authed users off
auth pages, and clears stale cookies — it checks cookie *presence* only, with real validation
deferred to `requireUser()`, which is documented at `middleware.ts:75-77` and correct.
**XSS: DM content is safe.** The only `dangerouslySetInnerHTML` is the theme bootstrap
(`app/layout.tsx:59`) built from constants (`lib/theme.ts:14-26`); message bodies render as text
children (`ChatsInbox.tsx:691`). No `localStorage` use beyond the theme key. Remaining gaps are
#1, #2, #6, #8, #9.

**4. Performance.** Bundle is healthy: 102 kB shared First Load JS; heaviest route `/home` at 145 kB,
then `/automation` 134 kB, `/agents/new` 131 kB. Three biggest contributors are all framework:
`chunks/4bd1b696` 54.2 kB (React + react-dom), `chunks/1255` 46.3 kB (App Router + TanStack Query),
middleware 34.6 kB. Zero third-party UI/chart/date libraries — charts are hand-rolled SVG.
Re-renders: `MessageBubble` is unmemoized but structural sharing means an unchanged poll doesn't
re-render; the real costs are #11 (no virtualization) and #3 (request fan-out). Images: `next/image`
in 2 places, one documented `<img>` exception for rotating `*.cdninstagram.com` hosts
(`PostThumbnail.tsx:9-18`) — a sound call. **LCP/INP are UNVERIFIED** — no field data and no running
instance was measured. The structural risk is server-side: every dashboard route is dynamic and TTFB
is gated on Django, which #3 actively degrades.

**5. Component hygiene.** 83 client components vs 17 server ones under `components/features` — heavy
for an App Router app, though most are genuinely interactive. Main issues are #12 (Alert duplication)
and prop drilling in `ThreadView` (12 props, `ChatsInbox.tsx:522-535`). No dead mock-data modules:
all 13 `lib/*-data.ts` files have live importers. Lint and typecheck are clean.

**6. i18n readiness.** `npm run i18n:check` output verbatim: `English catalog: 70 keys` /
`ar kk ru uz 70/70 100% ✓`. That green is misleading — see #4. Structurally the system is well
built (flat keys, `Intl.PluralRules`, server-side locale resolution, English fallback, logical CSS
properties for RTL); it is the adoption that is at 12%. Note also that
`CLAUDE.md:135-136` marks every non-English catalog "needs native review", so uz/ru are not
production-ready even for the 70 keys that exist.
