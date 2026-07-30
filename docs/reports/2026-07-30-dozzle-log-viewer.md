# Dozzle log viewer — lightweight and locked down

**Date:** 2026-07-30
**Scope:** `compose.yml`, `deployment/dozzle/`, `deployment/nginx/api.aylo.uz.conf`

Container logs on the dev host were only reachable over SSH (`docker compose
logs -f`). This adds a browser log viewer that does not become a way into the
host: two small containers, opt-in behind a compose profile, with the Docker
socket kept out of the web-facing process entirely.

## What was added

| Piece | Why |
|---|---|
| `dozzle` service (profile `logs`) | Log UI, ~30 MB image, published on `127.0.0.1:8080` only |
| `docker-socket-proxy` service | Read-only HAProxy in front of `/var/run/docker.sock`; Dozzle talks to it over TCP and never sees the socket |
| `logs-net` network | Dozzle and the proxy are isolated from `backend-net` — no route to postgres, redis or the app containers |
| `deployment/dozzle/setup.sh` | Creates the login; password read from stdin, stored bcrypt-hashed, role `none` |
| `/_logs/` block in the nginx site | Single public entry point, TLS-terminated, websocket upgrade, optional IP allowlist |

## Security decisions

| Control | Setting | Effect |
|---|---|---|
| Socket exposure | `DOZZLE_REMOTE_HOST=tcp://docker-socket-proxy:2375` | The internet-facing container has no Docker socket to abuse |
| API allowlist | `CONTAINERS=1 INFO=1 POST=0` | Verified: `/containers/json` → 200, `/images/json` → 403, `POST /containers/x/stop` → 403 |
| Authentication | `DOZZLE_AUTH_PROVIDER=simple`, `DOZZLE_AUTH_TTL=8h` | Verified: unauthenticated → 307 to login, API → 401, wrong password → 401 |
| User role | `--user-roles none` in `setup.sh` | Dozzle grants `all` (shell + actions) by default — this is the flag that actually takes them away, independent of the env vars below |
| Actions / shell | `DOZZLE_ENABLE_ACTIONS=false`, `DOZZLE_ENABLE_SHELL=false` | No start/stop/restart, no container shells |
| Visibility | `DOZZLE_FILTER=label=com.docker.compose.project=repliuz` | Verified: only the 2 project containers listed on a host running 10 |
| Network exposure | `ports: 127.0.0.1:8080`, proxy has no `ports` | Same rule as `web-blue`/`web-green`: nginx is the sole public listener |
| Container hardening | `read_only: true`, `cap_drop: [ALL]`, `tmpfs` | Empty capability bounding set, immutable rootfs |
| Secrets | `users.yml` gitignored, mode 600 when created as root | Password hashes never enter git |
| Footprint | `mem_limit` 128m / 32m in `compose.dev-host.yml` | Fits the 1 vCPU / 2 GB dev box |

## Two things that had to be worked out on the box

**`no-new-privileges` is not in the compose file.** It makes `execve` fail with
`EPERM` for *every* image on this kernel (7.0.0-28-generic) — reproduced with
plain `alpine:3`, and not caused by AppArmor or seccomp. Both containers
crash-looped with `exec /dozzle: operation not permitted`. `cap_drop: ALL`
already empties the bounding set, so a setuid binary gains nothing without it.
The option is left as a commented block in `compose.yml` with the one-liner to
test host support.

**`users.yml` permissions interact with `cap_drop: ALL`.** Dozzle runs as root
in-container but without `CAP_DAC_OVERRIDE`, so it cannot read a `0600` file
owned by another uid. Deploying as root (mode 600, root-owned) is the correct
path; `setup.sh` detects a non-root invoker and falls back to 644 with a warning
rather than leaving a container that will not start.

## Files changed

| File | Change |
|---|---|
| `compose.yml` | `dozzle` + `docker-socket-proxy` services, `logs-net` network |
| `deployment/compose.dev-host.yml` | Memory caps for both new services |
| `deployment/dozzle/setup.sh` | New — generates `users.yml` |
| `deployment/nginx/api.aylo.uz.conf` | `/_logs/` + `/_logs` redirect, install notes |
| `.gitignore` | Ignore `deployment/dozzle/users.yml` |
| `apps/shared/tests/test_deployment_compose.py` | New — 13 hardening assertions |

## Tests

`apps/shared/tests/test_deployment_compose.py` asserts the isolation that a
convenience edit would quietly undo: no socket mount on Dozzle, `POST=0` and a
two-key allowlist on the proxy, auth provider set, actions/shell off, loopback
publish, `logs-net` only, pinned images, the nginx base path matching
`DOZZLE_BASE`, websocket headers present, and `users.yml` gitignored.

```
$ .venv/bin/python manage.py test apps.shared.tests.test_deployment_compose --keepdb
Found 13 test(s).
System check identified no issues (0 silenced).
.............
----------------------------------------------------------------------
Ran 13 tests in 0.255s

OK
```

Runtime behaviour was also verified against live containers on the dev machine:
login flow (200 + JWT with 8h expiry, 401 on a wrong password), authenticated
event stream returning only `repliuz-*` containers, and the proxy's 403s listed
above.

## Deploy steps

```bash
./deployment/dozzle/setup.sh admin "Your Name"   # as root on the server
docker compose --profile logs up -d
cp deployment/nginx/api.aylo.uz.conf /etc/nginx/sites-available/api.aylo.uz
nginx -t && systemctl reload nginx
```

## Open items

- **IP allowlist is commented out.** The `allow`/`deny` lines in the `/_logs/`
  block need the addresses you actually administer from. Until then the login
  page is the only barrier — a strong password matters.
- **Serving under `api.aylo.uz/_logs/`** reuses the existing certificate. A
  separate `logs.aylo.uz` host would isolate it further at the cost of DNS and
  a cert.
- **`no-new-privileges`** should be switched on if the production host passes
  the check noted in `compose.yml`.
