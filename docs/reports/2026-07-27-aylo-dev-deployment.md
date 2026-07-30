# Deployment of the backend to `api.aylo.uz` (dev host)

**Date:** 2026-07-27
**Host:** `143.198.112.70` (DigitalOcean, Ubuntu 24.04, 1 vCPU / 2 GB / 48 GB)
**Domain:** `https://api.aylo.uz`
**Repo/remote:** `aylo-backend` → `github.com/aylo-ai/aylo-backend`, branch `dev`

## Summary

The dev backend now runs on `api.aylo.uz` behind nginx + Let's Encrypt TLS, deployed
by the `Deploy Dev Backend` GitHub Actions workflow on every push to `dev`. The
workflow previously failed on every run; the cause and four further defects found
during the deploy are below.

## Issues found and fixed

| # | Severity | Issue | Root cause | Fix |
|---|---|---|---|---|
| 1 | Blocker | GH Actions run failed in 12s: `Error: can't connect without a private SSH key or password` | `aylo-ai/aylo-backend` had **no repository secrets at all** — `secrets.SSH_HOST_PRIVATE_KEY` interpolated to an empty string, so `scp-action` had no credential | Generated a dedicated ed25519 deploy key, installed the public half in `/root/.ssh/authorized_keys` on the host, set `SSH_HOST_DEV`, `SSH_HOST_DEV_USERNAME`, `SSH_HOST_PRIVATE_KEY` on the repo |
| 2 | Blocker | Celery workers looped on `Cannot connect to redis://localhost:6379/0` and processed nothing | The env file carried a stale `CELERY_BROKER_URL=redis://localhost:6379/0`, which wins over the value `settings.py` derives from `REDIS_HOST`. Inside a container `localhost` is the container itself | Server env now sets `CELERY_BROKER_URL=redis://redis:6379/0` (the compose service name) |
| 3 | High (security) | The production `.env` was **baked into the image layer** (`/app/.env`, mode 600, all API keys) — anyone with the image has every secret | `Dockerfile` does `COPY . /app` and there was no `.dockerignore` | Added `.dockerignore` excluding `.env`, `.git`, `.venv`, media, caches. Verified after rebuild: `/app/.env` no longer exists in the image |
| 4 | High | Stack would OOM on this host: 4 gunicorn + 4 + 2 celery processes on 2 GB | `compose.yml` and `gunicorn_conf.py` are sized for the production box | Added `deployment/compose.dev-host.yml` (celery `--concurrency` 2/1, per-service `mem_limit`), made gunicorn read `WEB_CONCURRENCY` (set to 2), added a 4 GB swapfile |
| 5 | Medium | Workflow reported success even when the app failed to boot | No verification after `docker compose up` | Added a health-check step that polls `/health/` for 150s and dumps `web-green` logs before failing the run |
| 6 | Low | `ALLOWED_HOSTS` default contained a dead ngrok host and no aylo domain | Leftover from local debugging | Default is now `.aylo.uz,.repli.uz,localhost,127.0.0.1`; `aylo.uz` origins added to `CORS_ALLOWED_ORIGINS` and `CSRF_TRUSTED_ORIGINS` |

## What was installed on the host

| Component | Version / detail | Why |
|---|---|---|
| Docker Engine + compose plugin | 29.6.2 / v5.3.1, from `download.docker.com` | The box had Docker **as a snap**; snap confinement blocks the `/var/www/static` and `/var/www/media` bind mounts in `compose.yml`. The snap was purged and replaced with `docker-ce` |
| nginx | 1.24.0 | Only public listener; app binds `127.0.0.1:8002` |
| certbot + python3-certbot-nginx | 2.9.0 | TLS for `api.aylo.uz`, auto-renew timer installed |
| ufw | active: OpenSSH + Nginx Full only | 8001/8002 stay loopback-only |
| swap | 4 GB `/swapfile`, persisted in `/etc/fstab` | 2 GB RAM is not enough for a docker build |
| Docker log rotation | `/etc/docker/daemon.json`, 50 MB × 3 | Stops logs filling the 48 GB disk |
| Weekly image prune | `/etc/cron.weekly/docker-prune` | Reclaims layers left by rebuilds |
| Everything else | Postgres 17 and Redis run **as containers** from `compose.yml` — not installed on the host | |

Layout on the host:

| Path | Contents |
|---|---|
| `/opt/aylo/backend` | Repo checkout (deploy target) |
| `/opt/aylo/.secrets/backend.env` | Runtime env, mode 600, outside the repo tree; copied to `.env` by the workflow |
| `/var/www/static`, `/var/www/media` | Bind-mounted into web + celery containers |
| `/etc/nginx/sites-available/api.aylo.uz` | From `deployment/nginx/api.aylo.uz.conf`, TLS block added by certbot |

## Files changed

| File | Change |
|---|---|
| `.github/workflows/dev-deploy.yml` | Deploy paths → `/opt/aylo`, applies the host overlay, adds `concurrency` group, `command_timeout: 30m`, and a health-check step |
| `.dockerignore` | **New** — keeps `.env`, `.git`, `.venv`, media and caches out of the image |
| `deployment/compose.dev-host.yml` | **New** — small-host compose overlay (worker counts, memory caps, postgres healthcheck) |
| `deployment/nginx/api.aylo.uz.conf` | **New** — nginx site: static/media aliases, 100 MB uploads, 600s proxy timeouts matching gunicorn |
| `deployment/gunicorn_conf.py` | `workers` now reads `WEB_CONCURRENCY` (default 4); dropped the unused `cpu_count` import |
| `config/settings.py` | `aylo.uz` added to `ALLOWED_HOSTS` default, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`; removed dead ngrok host |

## Verification

Test suite, run inside the deployed container:

```
$ docker compose exec -T web-green python manage.py test apps --keepdb --noinput
Found 166 test(s).
System check identified no issues (0 silenced).
Ran 166 tests in 5.379s

OK
```

Live checks against the public domain:

| Check | Result |
|---|---|
| `https://api.aylo.uz/health/` | `200` `{"status": "healthy"}` |
| `http://…` → `https://…` | `301` redirect (certbot) |
| TLS cert | `CN=api.aylo.uz`, Let's Encrypt, expires 2026-10-25 |
| Django admin `/acer-laptop/samsung-g10/login/` | `200` |
| `GET /api/v1/user/privacy-policy/` | `200` (DB-backed read) |
| `GET /api/v1/user/auth/profile/` without token | `401` |
| `POST /api/v1/user/auth/send-otp/` empty body | `400`, Uzbek message via the `error_response` helper |
| `Host: evil.com` | `400` — `ALLOWED_HOSTS` enforced |
| Static asset via nginx | `200` |
| Celery worker | `Connected to redis://redis:6379/0`, `celery@… ready` |
| Container memory | web 271 MB, celery 229/161 MB, postgres 37 MB, redis 5 MB — all under their caps |

## Open items (need a human decision)

1. **`REDIS_PASSWORD` is empty** in the env file, so Redis runs with `--requirepass ""`.
   It is not published to the host and is only reachable on the compose network, but it
   should get a real password (update `CELERY_BROKER_URL` to match at the same time).
2. **`DEBUG=True` in the local `.env`** — the server copy is `False`. The committed
   `.env` habits should move to a checked-in `.env.example` so required keys are documented.
3. **No `.env.example` in the repo** — the 46 required keys currently live only in
   someone's local file and in `/opt/aylo/.secrets/backend.env`.
4. **`app.aylo.uz` also resolves to this host** but nothing serves it; the nginx
   default server (the IP block) answers it today.
5. **Secrets rotation:** the SSH password shared for this work (`shahzod`/`admin123`)
   is unused — the host only accepts key auth — but it should be rotated anyway.
6. **Prod workflow `ci_cd.yml`** still points at the repli GCP runner and
   `/home/mukhammad.irmatov/...`; it was left untouched.
