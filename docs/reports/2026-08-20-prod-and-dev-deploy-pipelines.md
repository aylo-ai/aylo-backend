# Prod and dev deploy pipelines — backend and frontend

**Date:** 2026-08-20
**Scope:** `aylo-backend` and `aylo-frontend` GitHub Actions pipelines

## Goal

`main` deploys to production, `dev` deploys to a second (dev) server, with the
same pipeline shape in both repos. Previously **both** backend workflows fired on
`main` — the working SSH pipeline was named `dev-deploy.yml` but deployed on
`main`, and the legacy GCP `ci_cd.yml` deployed on `main` too, so every push to
`main` ran two competing deploys. Neither repo had a `dev`-branch pipeline.

## What changed

### Backend (`aylo-backend`)

| Issue | Fix |
|---|---|
| Two workflows deployed on `main` at once (`ci_cd.yml` + `dev-deploy.yml`) | `ci_cd.yml` deleted; one deploy per branch |
| The working pipeline was misnamed `dev-deploy.yml` but ran on `main` | Logic extracted into a reusable workflow `deploy.yml` (`workflow_call`), called by `deploy-prod.yml` (`main`) and `deploy-dev.yml` (`dev`) |
| Prod/dev would have shared the memory-capped `compose.dev-host.yml` (640 MB web, 384 MB postgres) | Compose override is now an input: prod gets a new `deployment/compose.prod-host.yml` (restart policies, pg healthcheck, no memory caps), dev keeps `compose.dev-host.yml` |
| `deployment/deploy.sh` had no caller after `ci_cd.yml` went, and edited a stale nginx path (`/etc/nginx/sites-available/api.repli.uz`, pre-rebrand) | Deleted |
| Backup/rollback paths were hardcoded to `/opt/aylo` and `backend`/`backend.bak` | Derived from the `deploy_dir` input, so a server with a different layout needs no edit |
| An unset host secret failed deep inside the SSH action | A guard step fails first with the exact missing secret names |

Reusable-workflow inputs: `environment`, `deploy_dir`, `secrets_dir`,
`compose_override`, `profile`, `health_port`. Secrets: `ssh_host`,
`ssh_username`, `ssh_key`.

### Frontend (`aylo-frontend`)

| Issue | Fix |
|---|---|
| Only a production pipeline existed | New `deploy-dev.yml`: chains off a successful publish of `dev`, deploys over SSH to the dev server, pulls the immutable `sha-` tag from GHCR, polls `/api/health`, prunes on success |
| `deploy.yml` was the only deploy, so the name said nothing about its target | Renamed `deploy-prod.yml`, workflow name `Deploy frontend (production)`; concurrency group `frontend-deploy-production` |
| `ci.yml` and `publish.yml` only ran on `main`, so a `dev` push had no gate and no image | Both now include `dev`. `latest` still only moves on the default branch; `dev` gets its own branch tag |
| No GHCR credential on the dev server | The workflow's built-in `GITHUB_TOKEN` is forwarded over the SSH session (`packages: read`) and logged out at the end of the step — nothing long-lived is stored on the box |

Production still runs on the droplet's own self-hosted runner (no SSH keys); dev
runs over SSH because the dev box has no runner.

## Files changed

| Repo | File | Change |
|---|---|---|
| backend | `.github/workflows/deploy.yml` | new — reusable deploy (build, health, rollback, verify) |
| backend | `.github/workflows/deploy-prod.yml` | new — `main` → prod server |
| backend | `.github/workflows/deploy-dev.yml` | new — `dev` → dev server |
| backend | `.github/workflows/ci_cd.yml` | deleted — legacy GCP self-hosted deploy on `main` |
| backend | `.github/workflows/dev-deploy.yml` | deleted — superseded by the three above |
| backend | `deployment/compose.prod-host.yml` | new — prod host overrides |
| backend | `deployment/deploy.sh` | deleted — no callers, stale nginx path |
| frontend | `.github/workflows/deploy-dev.yml` | new — `dev` → dev server over SSH |
| frontend | `.github/workflows/deploy-prod.yml` | renamed from `deploy.yml`, retargeted names |
| frontend | `.github/workflows/ci.yml` | gate `dev` too |
| frontend | `.github/workflows/publish.yml` | publish `dev` too |
| frontend | `DEPLOYMENT.md` | pipeline table, rollback commands, new dev-server section |

## Secrets to configure

Same key on both servers, one host/user pair per environment.

| Secret | Repo | Value |
|---|---|---|
| `SSH_HOST_PROD` | backend | production server host |
| `SSH_HOST_PROD_USERNAME` | backend | deploy user on production |
| `SSH_HOST_DEV` | backend, frontend | dev server host |
| `SSH_HOST_DEV_USERNAME` | backend, frontend | deploy user on dev |
| `SSH_HOST_PRIVATE_KEY` | backend, frontend | private key authorised on both |

`SSH_HOST_DEV` currently points at the server the old `dev-deploy.yml` deployed
to. That server is now the **production** target, so its host/user must be
copied into `SSH_HOST_PROD` / `SSH_HOST_PROD_USERNAME`, and `SSH_HOST_DEV` must
be re-pointed at the new dev box. Until that is done, `deploy-dev.yml` would
deploy the `dev` branch onto production.

## Tests

No application code changed — these are CI/CD workflow and compose files, which
the Django suite does not cover. What was verified instead:

| Check | Result |
|---|---|
| YAML parse, all 7 workflow files + both compose overrides | pass |
| Reusable-workflow `inputs`/`secrets` vs. both callers' `with`/`secrets` | exact match, no missing or extra keys |
| `docker compose -f compose.yml -f deployment/compose.prod-host.yml --profile green config` | pass (exit 0) |
| Dangling references to deleted `deploy.sh` / renamed `deploy.yml` | none outside `docs/reports/` history |

The Django suite was not run: it needs postgres on `127.0.0.1:55432`, which is
not up in this environment, and no Python was touched by this change.

## Open items for a human

| # | Item |
|---|---|
| 1 | **Re-point the secrets before pushing to `dev`** (see table above), otherwise `dev` deploys onto production. |
| 2 | **Confirm the production nginx upstream port.** The pipeline runs the `green` profile on `127.0.0.1:8002`. The deleted `deploy.sh` alternated blue (8001) / green (8002), so if prod nginx currently points at 8001, either flip the vhost to 8002 or set `profile: blue` / `health_port: "8001"` in `deploy-prod.yml`. |
| 3 | **Create `/opt/aylo/.secrets/backend.env` on the production server** if it is not there — prod previously read `/home/mukhammad.irmatov/backend_drf/.secrets/.env`. |
| 4 | **Create the frontend `dev` branch** — it does not exist yet, so `deploy-dev.yml` has nothing to fire on. |
| 5 | **Dev server prep for the frontend:** Docker, deploy user in `docker`, `/opt/aylo/frontend/.env` (chmod 600) with a real `API_BASE_URL`, nginx → `127.0.0.1:3000`. |
| 6 | `appleboy/ssh-action@master` / `scp-action@master` are unpinned, as they already were. Pinning to a release tag removes a supply-chain risk; it was left alone here so the pipeline keeps resolving exactly as it does today. |
| 7 | The backend has **no test gate** — pushing to `main` deploys without running the suite. Worth adding a `test` job (postgres + redis services) that `deploy-prod.yml` depends on. |
| 8 | Production frontend uses `runs-on: self-hosted` with no label. If a runner is ever registered on the dev box too, jobs could land on the wrong machine — add a distinguishing label then. |
