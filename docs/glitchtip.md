# GlitchTip Operator Runbook

GlitchTip v6 error tracking in the `error-tracking` namespace.
Public URL: `https://errors.stats-staging.solid-stats.ru` (DNS-gated — see §Cutover).

---

## GitHub Actions Secrets

Five secrets must be set in the GitHub `staging` environment before the first CI deploy.
No values are stored in git — the CI renderer reads them from env at deploy time.

### New secrets required for GlitchTip (Phase 16)

| Secret | Description | How to generate |
|--------|-------------|-----------------|
| `GLITCHTIP_SECRET_KEY` | Django `SECRET_KEY` (50-char random string) | `python3 -c "import secrets; print(secrets.token_urlsafe(37))"` |
| `GLITCHTIP_POSTGRES_PASSWORD` | Password for the `glitchtip` PostgreSQL user | `python3 -c "import secrets; print(secrets.token_urlsafe(24))"` |
| `GLITCHTIP_SUPERUSER_EMAIL` | Email address of the initial superuser | Operator email (e.g. `admin@your-domain.example`) |
| `GLITCHTIP_SUPERUSER_PASSWORD` | Password for the initial superuser | `python3 -c "import secrets; print(secrets.token_urlsafe(24))"` |

### Error-tracking CI deployer token

| Secret | Description | How to mint |
|--------|-------------|-------------|
| `K8S_OBS_ET_TOKEN` | ServiceAccount token for the `error-tracking`-scoped `obs-ci-deployer` | See below |

```bash
# Mint the error-tracking obs-ci-deployer token (run from operator workstation with cluster access)
kubectl -n error-tracking get secret obs-ci-deployer-token \
  -o jsonpath='{.data.token}' | base64 -d
```

Copy the output and set it as the `K8S_OBS_ET_TOKEN` secret in the GitHub `staging` environment.
This token is scoped only to the `error-tracking` namespace Role — it cannot touch `monitoring`
or app namespaces.

### Existing secrets (already set)

`K8S_OBS_TOKEN`, `K8S_CA_CERT`, `GRAFANA_ADMIN_PASSWORD`, `PG_MONITOR_PASSWORD`,
`WG_PRIVATE_KEY`, `WG_PEER_PUBLIC_KEY`, `WG_ENDPOINT` — set during Phase 13/14.

---

## First-Run Order

GlitchTip requires a strict init sequence. CI enforces it automatically:

```
Wave 1 — CI apply (deploy-observability.yml):
  1. glitchtip-postgres StatefulSet starts (90-glitchtip-postgres.yaml)
  2. glitchtip-web + glitchtip-worker start — wait on postgres readiness (91-glitchtip.yaml)
  3. glitchtip-migrate Job runs manage.py migrate --noinput (92-glitchtip-migrate.yaml)
     → initContainer polls pg_isready before migrate starts
     → web/worker initContainers poll showmigrations before serving traffic

  4. glitchtip-seed Job runs manage.py createsuperuser --noinput (93-glitchtip-seed.yaml)
     → initContainer polls showmigrations to confirm migrate is complete

Wave 2 — Operator (16-04, run manually after CI deploy):
  5. Create org + project + DSN via GlitchTip API (scripts/seed-glitchtip-org.sh)
     → stores DSN in a known location for the validate script
```

`ENABLE_USER_REGISTRATION=False` is set from the very first boot on both web and worker.
Registration is closed before any superuser exists — no window where an anonymous user
could register.

---

## Verification

### Automated live check (ERR-01/02/03)

Requires kubectl access to the cluster (WireGuard tunnel up):

```bash
# Full check — ERR-01 pods + ERR-02 registration closed + ERR-03 forced error
GLITCHTIP_DSN=http://PUBKEY@host/PROJECT_ID \
SUPERUSER_TOKEN=<bearer-token-from-16-04> \
bash scripts/validate-phase-16.sh
```

Flags:
- `--quick` — skip ERR-03 forced-error ingest test
- `--public` — use the public `errors.` URL instead of port-forward (post-cutover only)

### Forced-error ingest test (ERR-03)

Tests that GlitchTip accepts a real Sentry envelope via port-forward:

```bash
# Requires the project DSN from 16-04 seed output
GLITCHTIP_DSN=http://PUBKEY@host/PROJECT_ID \
SUPERUSER_TOKEN=<bearer-token> \
bash scripts/test-glitchtip-ingest.sh
```

The script:
1. Opens `kubectl port-forward svc/glitchtip-web 18000:8000 -n error-tracking`
2. Builds a 3-line Sentry envelope (header + item header + event payload)
3. POSTs to `http://localhost:18000/api/PROJECT_ID/envelope/`
4. Asserts HTTP 200 or 202 (not 403 — a 403 means the DSN public key is wrong)
5. If `SUPERUSER_TOKEN` is set, polls the issues API to confirm the event appears

---

## Public URL Cutover (Operator-Gated)

The `errors.stats-staging.solid-stats.ru` subdomain is not yet routed to GlitchTip.
Phase 14 provisioned the TLS cert and set a 503 placeholder in nginx. Phase 16-05
completes the cutover once the operator adds the DNS A record.

### Prerequisites

- DNS A record for `errors.stats-staging.solid-stats.ru` pointing to the staging VPS IP
  (`89.223.124.200`) is set and has propagated
- GlitchTip pods are Running and the migrate Job has completed (ERR-01 passes)
- The Phase 14 Let's Encrypt cert for `errors.stats-staging.solid-stats.ru` is in the
  certbot lineage (already issued in Phase 14)

### Cutover command

Run from the operator workstation (WireGuard tunnel up to staging VPS):

```bash
DOMAIN=errors.stats-staging.solid-stats.ru \
ADMIN_EMAIL=your-email@example.com \
UPSTREAM=$(kubectl get svc glitchtip-web -n error-tracking \
  -o jsonpath='{.spec.clusterIP}:{.spec.ports[0].port}') \
bash scripts/bootstrap-obs-edge.sh
```

`bootstrap-obs-edge.sh` will:
1. Retrieve the GlitchTip web ClusterIP from the cluster
2. Update the nginx vhost at `config/nginx/sites-available/errors-stats-staging-solid-stats.conf`
   replacing the 503 placeholder with a `proxy_pass` to `http://UPSTREAM`
3. Reload nginx (`nginx -s reload`)
4. The existing Let's Encrypt cert (from Phase 14) is already in place — no new cert needed

See `docs/obs-edge-bootstrap.md` for full details on the bootstrap script.

### Smoke test after cutover

```bash
# Verify TLS + response
curl -I https://errors.stats-staging.solid-stats.ru/api/0/config/

# Expected: HTTP/2 200 with {"user_registration_enabled":false,...}
```

---

## Environment Variables Reference

Key GlitchTip v6 env vars set in `k8s/observability/91-glitchtip.yaml`:

| Variable | Value | Source |
|----------|-------|--------|
| `SECRET_KEY` | 50-char random | `glitchtip-secrets` Secret |
| `DATABASE_URL` | `postgresql://glitchtip:PWD@glitchtip-postgres.error-tracking.svc:5432/glitchtip?sslmode=disable` | `glitchtip-secrets` Secret |
| `VALKEY_URL` | `""` (empty) | hardcoded in manifest — activates PostgreSQL-only mode |
| `ENABLE_USER_REGISTRATION` | `"False"` | hardcoded — never open from boot |
| `GLITCHTIP_DOMAIN` | `https://errors.stats-staging.solid-stats.ru` | hardcoded |
| `TRUSTED_PROXIES` | `"*"` | hardcoded — required behind nginx |
| `SERVER_ROLE` | `web` or `worker` | hardcoded per Deployment |

Secrets are rendered at CI deploy time by `scripts/render-obs-secrets.py` from GitHub
environment secrets. No values appear in git or CI logs.

---

## Troubleshooting

### Worker CrashLoopBackOff — redis.exceptions.ConnectionError

`VALKEY_URL` must be explicitly set to `""` (empty string) on the worker container.
If the env var is absent, GlitchTip v6 defaults to `redis://valkey:6379/0` and crashes.
Check: `kubectl get deploy glitchtip-worker -n error-tracking -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="VALKEY_URL")].value}'`
Expected output: (empty)

### migrate Job fails — relation does not exist

The seed Job (93) ran before migrate (92) completed. The seed Job's initContainer
polls `manage.py showmigrations` to gate on this, but if it was applied before postgres
was ready the initContainer may have timed out. Delete and re-apply the seed Job:

```bash
kubectl delete job glitchtip-seed -n error-tracking
kubectl apply -f k8s/observability/93-glitchtip-seed.yaml
```

### Envelope POST returns 403

The `GLITCHTIP_DSN` public key does not match the project. Retrieve the correct DSN
from the GlitchTip UI or from the 16-04 seed script output, then re-run:

```bash
GLITCHTIP_DSN=http://CORRECT_PUBKEY@host/PROJECT_ID bash scripts/test-glitchtip-ingest.sh
```

### Web pod OOMKilled

Granian + Django needs at least 256 Mi. Increase the web Deployment memory limit in
`k8s/observability/91-glitchtip.yaml` and re-apply. Current limits: `300m/384Mi`.
Check with: `kubectl top pod -n error-tracking`
