# GlitchTip Operator Runbook

GlitchTip v6 error tracking in the `error-tracking` namespace.
Public URL: `https://errors.solid-stats.ru` (DNS-gated — see §Cutover).

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
  3. glitchtip-migrate Job runs migrate --noinput THEN createcachetable (92-glitchtip-migrate.yaml)
     → initContainer polls pg_isready before migrate starts
     → createcachetable creates the django_cache DB table the PostgreSQL-only cache
       backend needs; WITHOUT it the worker's task consumer crashes on first cache
       write and the queue never drains (verified live, 16-04). This is why migrate
       MUST run before web/worker start — the migrate Job is the gate.

  4. glitchtip-seed Job runs manage.py createsuperuser --noinput (93-glitchtip-seed.yaml)
     → initContainer polls showmigrations to confirm migrate is complete

Wave 2 — Operator (16-04, run manually after CI deploy):
  5. Create org + project + DSN directly against the models (the v6 REST org-creation
     API is gated by enableOrganizationCreation=false, so use manage.py shell):
       kubectl exec deploy/glitchtip-web -n error-tracking -- ./manage.py shell -c "<<py>>"
     creating Organization(name=...), Team, Project, and reading the auto-created
     ProjectKey.public_key. The live staging values: org slug `solidstats`,
     project slug `staging`, PROJECT_ID `1`. The DSN is
     `http://<ProjectKey.public_key>@errors.solid-stats.ru/1`.
```

`ENABLE_USER_REGISTRATION=False` is set from the very first boot on both web and worker.

Caveat (verified live, 16-04): GlitchTip's `/api/settings/` reports
`enableUserRegistration: true` while **zero users exist** — the "first user can always
self-register" bootstrap in `apps/users/utils.py` (`settings.ENABLE_USER_REGISTRATION
or not User.objects.exists()`). The Django setting is correctly `False` the whole time;
once the seed superuser exists the flag reads `false`. So the ERR-02 assertion is only
meaningful after the seed Job has run — `validate-phase-16.sh` runs seed first.

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
3. POSTs to `http://localhost:18000/api/PROJECT_ID/envelope/?sentry_key=PUBLIC_KEY`
   — GlitchTip authenticates ingest by the `?sentry_key=` query param (what real
   Sentry SDKs send), NOT by the `dsn` field in the envelope header; the header-only
   form returns 403 (verified live, 16-04).
4. Asserts HTTP 200 or 202 (not 403 — a 403 means the DSN public key is wrong or the
   `?sentry_key=` query param is missing)
5. If `SUPERUSER_TOKEN` is set, polls `/api/0/projects/<org>/<project>/issues/` to
   confirm the event appears (defaults to `solidstats`/`staging`, overridable via
   `GLITCHTIP_ORG_SLUG`/`GLITCHTIP_PROJECT_SLUG`)

---

## Public URL Cutover (Operator-Gated)

The `errors.solid-stats.ru` subdomain is not yet routed to GlitchTip.
Phase 14 provisioned the TLS cert and set a 503 placeholder in nginx. Phase 16-05
completes the cutover once the operator adds the DNS A record.

### Prerequisites

- DNS A record for `errors.solid-stats.ru` pointing to the staging VPS IP
  (`89.223.124.200`) is set and has propagated
- GlitchTip pods are Running and the migrate Job has completed (ERR-01 passes)
- The Phase 14 Let's Encrypt cert for `errors.solid-stats.ru` is in the
  certbot lineage (already issued in Phase 14)

### Cutover command

Run from the operator workstation (WireGuard tunnel up to staging VPS):

```bash
DOMAIN=errors.solid-stats.ru \
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
# Verify TLS + response (v6 config endpoint is /api/settings/, NOT /api/0/config/)
curl -s https://errors.solid-stats.ru/api/settings/ | python3 -m json.tool

# Expected: HTTP 200 with {"enableUserRegistration": false, "version": "6.1.8", ...}
# Health endpoint for probes / quick liveness: GET /_health/ → 200 "ok"
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
| `GLITCHTIP_DOMAIN` | `https://errors.solid-stats.ru` | hardcoded |
| `TRUSTED_PROXIES` | `"*"` | hardcoded — required behind nginx |
| `SERVER_ROLE` | `web` or `worker` | hardcoded per Deployment — `bin/start.sh` dispatches on it (confirmed live) |

Secrets are rendered at CI deploy time by `scripts/render-obs-secrets.py` from GitHub
environment secrets. No values appear in git or CI logs.

**Image / security context notes (verified live, 16-04):**
- Image tag is `glitchtip/glitchtip:6.1.8` — **no `v` prefix** (the repo dropped it
  after v6.0.3; `v6.1.8` is a Docker Hub 404).
- The image's `app` user is **uid/gid 5000**. Because the pods run `runAsNonRoot:true`
  and the image names the user (not a numeric uid), every glitchtip-image container
  pins `runAsUser:5000`/`runAsGroup:5000` explicitly or kubelet fails with
  `CreateContainerConfigError`. The migrate Job's pg_isready initContainer overrides
  to uid 70 (the postgres user).
- Probes use `/_health/` (200 "ok"); the v6 public config is `/api/settings/`.

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

Either the `?sentry_key=` query param is missing (GlitchTip ignores the `dsn` field
in the envelope header for auth) or the public key does not match the project.
`test-glitchtip-ingest.sh` already appends `?sentry_key=PUBLIC_KEY`; if calling the
endpoint by hand, include it. Retrieve the correct DSN from the GlitchTip UI or the
16-04 ProjectKey, then re-run:

```bash
GLITCHTIP_DSN=http://CORRECT_PUBKEY@host/PROJECT_ID bash scripts/test-glitchtip-ingest.sh
```

### Forced error accepted (HTTP 200) but no issue ever appears

The envelope is enqueued to the `ingest` queue but the worker is not draining it.
Root cause (seen live in 16-04): the worker booted before the `django_cache` table
existed, so its task consumer thread crashed on the first cache write while the
scheduler thread kept logging `Enqueuing due task`. The migrate Job now runs
`createcachetable`, so a fresh deploy is fine. If you hit it on an existing cluster,
ensure the table exists and restart the worker:

```bash
kubectl exec deploy/glitchtip-web -n error-tracking -- ./manage.py createcachetable
kubectl rollout restart deploy/glitchtip-worker -n error-tracking
# worker log should then show: "Processing batch of N tasks from queue ingest"
```

### Web pod OOMKilled

Granian + Django needs at least 256 Mi. Increase the web Deployment memory limit in
`k8s/observability/91-glitchtip.yaml` and re-apply. Current limits: `300m/384Mi`.
Check with: `kubectl top pod -n error-tracking`
