# 2026-07-30 — `ERR_CERT_COMMON_NAME_INVALID` on api.aylo.uz

## Symptom

Browsers rejected `https://api.aylo.uz` with
`net::ERR_CERT_COMMON_NAME_INVALID` ("Your connection is not private") right
after the nginx site config was installed on the dev host (143.198.112.70).

## Root cause

`deployment/nginx/api.aylo.uz.conf` defined a **port 80 block only** — its header
delegated the TLS block to `certbot --nginx`, which never ran against the new
file. On the host, `sites-enabled/` held:

| File | Listens | server_name |
|---|---|---|
| `api.aylo.uz` | 80 | `api.aylo.uz` |
| `aylo-backend` (legacy) | 80 `default_server` | `143.198.112.70 _` |
| `aylo-frontend` | **443 ssl**, 80 | `app.aylo.uz` |

`aylo-frontend` was the only block listening on 443, so nginx used it as the
implicit default server for every TLS handshake — including ones for
`api.aylo.uz` — and answered with the `app.aylo.uz` certificate. The name in the
certificate did not match the host in the URL, which is exactly what
`ERR_CERT_COMMON_NAME_INVALID` reports.

A valid Let's Encrypt certificate for `api.aylo.uz` already existed
(`/etc/letsencrypt/live/api.aylo.uz/`, issued 2026-07-27, expires 2026-10-25,
SAN `DNS:api.aylo.uz`); nothing in nginx referenced it.

## Fix

Added an explicit `listen 443 ssl` server block for `api.aylo.uz` that carries
the whole site (static, media, `/_logs/`, gunicorn proxy) and points at the
existing certificate, and reduced the port 80 block to a redirect.

- The redirect uses **308**, not certbot's 301, so a webhook `POST` arriving over
  plain http keeps its method and body instead of being replayed as a `GET`.
- Certificate config is now version-controlled in the repo rather than injected
  by `certbot --nginx`. The header documents `certbot certonly --nginx` for
  issuance; renewal is unaffected (the nginx authenticator injects its challenge
  block temporarily).

## Files changed

| File | Change |
|---|---|
| `deployment/nginx/api.aylo.uz.conf` | Site moved into a new `443 ssl` block with the api.aylo.uz cert; port 80 reduced to a 308 redirect; install notes updated to `certbot certonly` |

Deployed to 143.198.112.70 as `/etc/nginx/sites-available/api.aylo.uz`; the
previous version was backed up to `/root/api.aylo.uz.bak.<timestamp>`.

## Verification

```
$ nginx -t
nginx: configuration file /etc/nginx/nginx.conf test is successful
$ systemctl reload nginx        # exit 0

$ openssl s_client -connect api.aylo.uz:443 -servername api.aylo.uz | openssl x509 -noout -subject -ext subjectAltName
subject=CN = api.aylo.uz
X509v3 Subject Alternative Name:
    DNS:api.aylo.uz

$ curl -s -o /dev/null -w '%{http_code}\n' https://api.aylo.uz/health/
200                              # full chain validation, no -k
$ curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' http://api.aylo.uz/health/
308 https://api.aylo.uz/health/
$ curl -s -o /dev/null -w '%{http_code}\n' https://app.aylo.uz/
307                              # frontend unchanged
```

No Python tests apply — the change is nginx configuration; `nginx -t` plus the
live probes above are the equivalent check.

## Open items (need a human decision)

1. **The legacy `aylo-backend` block is still the port 80 `default_server`**, with
   `server_name 143.198.112.70 _` proxying straight to gunicorn. That is the
   exact fall-through `deployment/nginx/00-catchall.conf` exists to stop: junk
   Host headers still burn a worker producing `DisallowedHost` 400s. Installing
   `00-catchall.conf` and removing `sites-enabled/aylo-backend` closes it — its
   443 half can now load, since the api.aylo.uz cert it references exists.
2. **No `default_server` on 443.** `https://143.198.112.70` still gets the
   `app.aylo.uz` certificate. Harmless for users, resolved by item 1.
3. **Dozzle `/_logs/` has no IP allowlist** — the `allow`/`deny` lines are still
   commented out, so the login page is exposed to the internet (now at least
   only over TLS). Fill in the deploy egress IPs.
