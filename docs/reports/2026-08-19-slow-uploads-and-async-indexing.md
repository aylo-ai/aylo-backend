# Slow MinIO uploads and the 6 MB 500 — 2026-08-19

Reported: "uploading a file is very slow, and a 6 MB file returns 500 Internal
Server Error" on the knowledge-base upload endpoint.

## What was actually slow

MinIO was not. Measured against the running local instance with a 6 MB payload:

| Step | Time |
|---|---|
| Write 6 MB to MinIO (`ContentFile`) | 0.13 s |
| Write 6 MB as a `TemporaryUploadedFile` (what a >5 MB multipart upload is) | 0.10 s |
| `exists()` (`file_overwrite = False` does one per save) | 0.003 s |
| Presign a URL | 0.001 s |
| Fetch the object back through the presigned URL | 0.01 s |
| `manage.py check_minio` | all checks passed |

The cost was everything the upload request did *after* the file was already
stored, in `AssistantFileUploadSerializer.create()`:

1. Save to MinIO — fast.
2. Presign the object and **download the entire file back over HTTP**, through
   nginx, into `response.content`.
3. Copy those bytes into a `BytesIO` for the OpenAI SDK, which encodes another
   copy into a multipart body — roughly **3–4 resident copies of the file** in
   the gunicorn worker that was already holding the upload.
4. `vector_stores.files.upload_and_poll()` — upload to OpenAI and **poll until
   indexing completes**. `INDEX_TIMEOUT_SECONDS = 120` and
   `INDEX_POLL_SECONDS = 2` were declared in `knowledge_base.py` and read by
   nothing, so this had no deadline at all.

All of it inside the request, and inside the `ATOMIC_REQUESTS` transaction. So
the user waited on an OpenAI vector-store index, not on storage, and one stuck
file parked a worker (and a Postgres transaction) indefinitely. On the deploy
host — 1 vCPU / 2 GB, `web-green` capped at `mem_limit: 640m`, `WEB_CONCURRENCY=2`
per `docs/reports/2026-07-27-aylo-dev-deployment.md` — the transient copies in
step 3 are also the most likely cause of the 500: a worker killed mid-request.

## The 500 was a timeout, not an exception

Confirmed with the reporter. Nothing in the request path raises on a 6 MB file —
the request simply did not finish, and the caller gave up. The budgets in play:

| Layer | Limit | Where |
|---|---|---|
| OpenAI SDK, per HTTP call | 60 s, `max_retries=0` | `ai_service/client.py` |
| `upload_and_poll` loop | **none** | `INDEX_TIMEOUT_SECONDS` was never read |
| gunicorn worker | 600 s | `deployment/gunicorn_conf.py` |
| nginx `location /` | 600 s read/send | `deployment/nginx/api.aylo.uz.conf` |

So the server was willing to sit on the request for ten minutes while it uploaded
to OpenAI and waited for chunking. Whatever gave up first — the browser, the
frontend HTTP client, or a proxy in between — surfaced as a 500 to the user. The
file was usually stored and indexed fine; only the response was lost.

This is why the fix is structural rather than a bigger timeout. The upload request
now does storage write + insert + enqueue, all of it milliseconds, so there is
nothing left to time out.

## Findings and fixes

| # | Severity | Issue | Fix |
|---|---|---|---|
| 1 | High | Upload request did a full HTTP round trip to fetch back a file it had just written, then indexed it inline. Request latency = OpenAI indexing time; ~4× file size resident in the web worker | Indexing moved to `apps.assistant.tasks.index_assistant_file` on the `sync` queue. The request now ends when the bytes are in MinIO |
| 2 | High | Posting **more than one file** to `assistant/<id>/upload-file/` was an unconditional 500: `create()` returned a `list`, and the view then called `serializer.data`, which asked the list for `.id` | `create()` returns one instance and exposes the set as `uploaded_files`; the view serialises with `many=True` |
| 3 | High | `upload_and_poll()` has no overall deadline — a file OpenAI never finishes chunking held a worker forever. `INDEX_TIMEOUT_SECONDS`/`INDEX_POLL_SECONDS` were dead constants | `_poll()` polls explicitly against both constants and gives up, letting Celery retry |
| 4 | Medium | Dashboard admin uploads (`DashboardAssistantFileUploadSerializer`) **never indexed at all** — the row was written and no vector store ever saw the file | `create()` queues `index_assistant_file` the same way the customer path does |
| 5 | Medium | The same dashboard serializer validated size only (hand-rolled 30 MB check), so it accepted extensions the customer path refuses — including `.html`, a stored-XSS payload when served from this origin | Uses `validate_document()`, the shared size + allowlist check |
| 6 | Medium | The client had no way to know whether a document was searchable, which was implicit while indexing was synchronous | New `AssistantFileUpload.index_status` (`pending`/`indexing`/`indexed`/`failed`/`skipped`), read-only on every serializer |
| 7 | High | **Introduced by this change, then fixed:** the gates on conversations and integrations tested `assistant.vector_id`, which the upload request used to set inline. With indexing queued it is null for a moment, so uploading a file and immediately starting a conversation answered "Assistant uchun fayl yuklash kerak" | New `knowledge_base.has_knowledge_base()` — an existing store *or* an uploaded document — used at all three gates |
| 8 | Low | `replace_files()` and `_download()` had no callers | Deleted |
| 9 | Low | Six `print()` calls in `daily_statistics_assistant`, against CLAUDE.md §3 | Replaced with lazy `logger` calls |

### Indexing is queued `on_commit`

`ATOMIC_REQUESTS` is on. Dispatching immediately would let a worker look for a
row whose transaction has not committed yet, or — on rollback — index a file whose
row no longer exists. `transaction.on_commit` callbacks are discarded on
rollback, which is exactly the required behaviour.

### Queue choice

`index_assistant_file` is routed to `sync`, not `ai`. It is slow and holds the
file in memory, so on `ai` it would sit in front of live chat replies. `sync` is
served by `celery_worker_low` (`--concurrency=1` on the dev host), which also
bounds how many documents can be resident at once.

## API change — the frontend needs one update

`POST /api/v1/chat/assistant/<id>/upload-file/` now returns **a list** under
`data`, matching the sibling `update-file` endpoint, instead of a single object.
It had to change: the single-object form is what made a multi-file post a 500.

Each row carries `index_status`. `201` means *stored*, not *searchable*. A client
that needs to show readiness polls `GET assistant/<id>/upload-file/` (or the
detail route) until `index_status` is `indexed`, `failed` or `skipped`.

Existing rows are backfilled in the migration rather than left at the `pending`
default: a row with a `file_id` is in a store by definition and becomes
`indexed`; one without becomes `failed`. Otherwise every already-indexed document
would look unindexed, and any retry affordance would re-upload whole knowledge
bases.

## Files changed

| File | Change |
|---|---|
| `apps/shared/ai_service/knowledge_base.py` | `add_stored_file()` reads from the storage backend; `add_file()`/`_download()`/`replace_files()` deleted; `_poll()` bounds indexing by `INDEX_TIMEOUT_SECONDS`; new `has_knowledge_base()` |
| `apps/integration/serializers.py` | Both integration gates use `has_knowledge_base()` |
| `apps/assistant/tasks.py` | New `index_assistant_file` task; `print()` → `logger` |
| `apps/assistant/serializers.py` | New `queue_file_uploads()` helper; both upload serializers store-and-queue instead of indexing inline; `index_status` exposed read-only |
| `apps/assistant/views.py` | `upload-file` serialises the full upload set with `many=True` |
| `apps/assistant/models.py` | `AssistantFileUpload.index_status` |
| `apps/assistant/migrations/0054_assistantfileupload_index_status.py` | **New** — field + backfill from `file_id` |
| `apps/shared/addons/enums.py` | New `FileIndexStatuses` |
| `config/celery.py` | Routes `index_assistant_file` to `sync` |
| `apps/dashboard/serializers/assistants.py` | Dashboard uploads validate properly and queue indexing |
| `apps/assistant/management/commands/migrate_knowledge_bases.py` | Uses `add_stored_file()` — no HTTP round trip |
| `apps/shared/ai_service/tests/test_knowledge_base.py` | **New** — 14 tests |
| `apps/assistant/tests.py` | `FileUploadTests` rewritten for the async path; new `IndexAssistantFileTaskTests` |

## Tests

`apps/shared/ai_service/tests/test_knowledge_base.py` (no database required):

```
Ran 14 tests in 0.007s

OK
```

Covering: bytes come from storage and `apps.shared.http.get` is never called; the
buffer keeps the original filename; unsupported extensions and empty objects are
never uploaded; storage and OpenAI failures degrade to `None` instead of raising;
`_poll` returns on completion, does not poll an already-finished file, uses
`INDEX_POLL_SECONDS`, and gives up at `INDEX_TIMEOUT_SECONDS` instead of looping
forever; and `has_knowledge_base` accepting a store, accepting a not-yet-indexed
upload, and rejecting an assistant with neither.

`apps/assistant/tests.py` — `FileUploadTests` (5) and `IndexAssistantFileTaskTests`
(6): the upload stores the row and queues the task; a conversation can start
before the indexing task has run (finding 7's regression); the request makes no OpenAI or
HTTP call of its own; a two-file post stores both and serialises (finding 2's
regression); the task records `file_id` + `indexed`, reads through the `FileField`
rather than a URL, marks `failed` on a `None` result or an OpenAI outage, `skipped`
for an unsupported extension, and treats an already-deleted row as a no-op.

> **Not yet run.** These need Postgres, which the local `.env` points at
> `127.0.0.1:55432` (the compose service). Run:
> ```bash
> docker compose up -d postgres
> .venv/bin/python manage.py test apps.assistant.tests apps.shared.ai_service --keepdb
> ```

## Open items for a human

| # | Item |
|---|---|
| 1 | **Client-side timeout.** The 500 was the caller giving up, not a server exception (see above), so it is worth checking what the frontend's HTTP timeout actually is — a 6 MB upload to MinIO is now sub-second, but a slow uplink still needs a sane budget. Nothing else was found: MinIO writes a 6 MB `TemporaryUploadedFile` in 0.10 s, and posting 1 MB and 6 MB through the real view both returned 201 |
| 2 | **`MINIO_PUBLIC_URL` is empty in `.env`.** Presigned URLs are then signed against `MINIO_ENDPOINT_URL`, so the `file` URL handed to a browser points at an address the client cannot reach. Should be `https://api.aylo.uz` wherever nginx fronts MinIO |
| 3 | `deployment/deploy.sh` edits `/etc/nginx/sites-available/api.repli.uz`, but the config in the repo is `deployment/nginx/api.aylo.uz.conf` — the file carrying `client_max_body_size 100M`. Worth confirming the live config is the one under version control |
| 4 | A `failed` row has no stored reason, only a log line. If the UI wants to explain a failure, `index_status` needs a companion `index_error` column |
| 5 | Nothing retries a `failed` row after Celery's 3 attempts. A periodic sweep, or a re-index endpoint, would close that |
| 6 | Finding 5 tightens dashboard uploads to the document allowlist. If admins legitimately upload other types today, that is now a 400 |
