# Phase 16: Error Tracking (GlitchTip) — Research

**Researched:** 2026-06-14
**Domain:** GlitchTip v6 on k3s — hand-authored Kubernetes manifests, PostgreSQL-only Celery-less mode, Sentry-compatible ingest, obs-edge nginx cutover
**Confidence:** MEDIUM (GlitchTip v6 install page confirmed; exact bin-script names and image SHA inferred from Docker Hub tags + blog post; some sizing values ASSUMED)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
All implementation choices are at Claude's discretion — discuss phase was skipped per user setting.

### Deploy into error-tracking namespace, reuse the obs secret/deploy pattern
GlitchTip runs in the `error-tracking` namespace (created in Phase 12, with its own obs-ci-deployer
RBAC), `priorityClassName: obs-background`, TIGHT limits. Manifests are hand-authored into
`k8s/observability/` and applied via the obs deploy path.
Secrets (Django SECRET_KEY, GlitchTip postgres password, superuser email/password) are rendered
from env into k8s Secrets (extend render-obs-secrets.py or a sibling renderer) — no values in git.

### Own PostgreSQL, separate from the app DB (ERR-01)
GlitchTip gets its OWN PostgreSQL StatefulSet in error-tracking — NOT the app's
solid-stats-staging postgres. PostgreSQL-only mode: GlitchTip v6 can use Postgres as the
task queue, cache, and session store (`VALKEY_URL=""`), so Valkey/Redis is disabled.
Components: web (granian ASGI), worker (`manage.py runworker --scheduler`), migrate Job + seed
Job (createsuperuser), + the dedicated postgres.

### Strict first-run order (ERR-01)
migrate → close registration → create superuser. ENABLE_USER_REGISTRATION=False from the first
boot, superuser seeded via a seed Job after migration completes.

### Public errors. URL is DNS-gated (operator) — like Phase 14
ERR-03's public TLS (`errors.stats-staging.solid-stats.ru`) reuses the Phase 14 obs-edge
bootstrap (errors. vhost placeholder already authored; swap the 503 for GlitchTip's ClusterIP).
DNS A record does NOT resolve yet (operator-controlled). Autonomous work: deploy GlitchTip
internally (ClusterIP) and run the forced-error test via port-forward / internal DSN.

### Deferred Ideas (OUT OF SCOPE)
- App-side Sentry SDK wiring (Phase 18)
- GlitchTip application-log ingestion (errors only; logs live in Loki)
- NetworkPolicies (Phase 17)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ERR-01 | GlitchTip runs with its own PostgreSQL (PostgreSQL-only mode, Valkey/Redis disabled) following strict first-run order (migrate → close registration → create superuser). | § GlitchTip v6 PostgreSQL-only mode; § First-run Job ordering; § Own PostgreSQL pattern |
| ERR-02 | Self-registration disabled; only the seeded local superuser can log in (verified against the registration endpoint). | § ENABLE_USER_REGISTRATION; § ERR-02 verification endpoint |
| ERR-03 | A project + DSN exist, and a deliberately forced staging test error appears in GlitchTip (errors. public URL + valid TLS). | § Sentry envelope ingest endpoint; § Org/project seed via API; § Autonomous vs operator steps |
</phase_requirements>

---

## Summary

GlitchTip v6 (current stable: `glitchtip/glitchtip:v6.1.8`, released 2026-06-06) is a major
rewrite that eliminates Celery and Redis as hard dependencies. The `django-vtasks` library
replaces Celery for task scheduling; `django-vcache` replaces the Redis cache layer. Setting
`VALKEY_URL=""` (empty string) activates PostgreSQL-only mode where Postgres handles task queue,
cache, and sessions — this is exactly what the phase needs. The web server changed from
Gunicorn/Uvicorn to Granian (Rust-based ASGI), controlled via `./bin/start.sh` with
`SERVER_ROLE` env var (`web` default, `worker` for the worker pod). The combined
`manage.py runworker --scheduler` command replaces both the old `celery worker` and `celery beat`,
so only two workload pods are needed: web + worker (plus the two one-shot Jobs).

The Sentry-compatible ingest endpoint is `POST /api/<project_id>/envelope/` authenticated via
DSN (the DSN public key is embedded in the envelope header). Creating an org + project + DSN
non-interactively requires hitting the GlitchTip REST API (Sentry-compatible) with a superuser
auth token. This is fully automatable in a seed script that runs after the migrate + superuser
Jobs complete.

**Primary recommendation:** Hand-author 4 resources in `k8s/observability/` under
`error-tracking` namespace: (1) GlitchTip postgres StatefulSet + Service mirroring
`10-postgres.yaml`, (2) GlitchTip web Deployment + worker Deployment + Service, (3) migrate
Job (init-order gate), (4) superuser seed Job. Extend `render-obs-secrets.py` to emit
`error-tracking` namespace secrets. Add validate-phase-16.sh. The errors. nginx vhost cutover
is an operator-gated step (DNS-dependent).

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Error event ingest (Sentry envelope) | GlitchTip web (in-cluster) | — | POST /api/PROJECT_ID/envelope/ handled by Django/Granian |
| Background task processing + scheduler | GlitchTip worker (in-cluster) | — | `manage.py runworker --scheduler` replaces celery+beat |
| Task queue / cache / sessions | GlitchTip postgres (in-cluster) | — | VALKEY_URL="" → postgres-only mode via django-vtasks/vcache |
| Error data persistence | GlitchTip postgres StatefulSet (in-cluster) | — | Dedicated PVC in error-tracking; separate from app DB |
| Registration lock | GlitchTip web env (ENABLE_USER_REGISTRATION=False) | — | Applied from first boot; verified via API endpoint |
| Superuser seeding | Kubernetes Job (one-shot post-migrate) | — | `manage.py createsuperuser --noinput` with DJANGO_SUPERUSER_* |
| TLS termination / public proxy | Host nginx (obs-edge) | — | Phase 14 errors. vhost — operator swaps 503 → proxy_pass |
| DNS / cert issuance | External registrar + host certbot | — | Operator-gated; Phase 14 bootstrap-obs-edge.sh used again |
| Secret injection | render-obs-secrets.py (CI) | GitHub env secrets | Mirrors Phase 13 pattern; extended for error-tracking ns |
| Manifest delivery | CI kubectl apply (obs-ci-deployer in error-tracking) | — | Existing Role/RoleBinding in 01-obs-rbac.yaml |

---

## Standard Stack

### Core Images
| Image | Tag / Version | Purpose | Source |
|-------|--------------|---------|--------|
| `glitchtip/glitchtip` | `v6.1.8` | Web + worker (same image, different SERVER_ROLE / command) | [CITED: hub.docker.com/r/glitchtip/glitchtip/tags] |
| `postgres` | `17-alpine` | GlitchTip's own PostgreSQL | [VERIFIED: k8s/staging/10-postgres.yaml — project already uses this image] |

**Why v6.1.8 not v5.x:** v6 eliminates the Redis/Celery dependency entirely via django-vtasks + django-vcache. `VALKEY_URL=""` is the canonical postgres-only switch, confirmed stable in v6.0. [CITED: glitchtip.com/blog/2026-02-03-glitchtip-6-released/]

**No new packages to install** — manifests are hand-authored YAML; the Python secret renderer uses only stdlib. No npm/pip/cargo audit needed.

### Package Legitimacy Audit

> No external packages are installed in this phase. GlitchTip is a Docker image pulled from Docker Hub. The `glitchtip/glitchtip` image is the official image maintained by the GlitchTip project (gitlab.com/glitchtip). No npm/PyPI/crates packages are added to the infrastructure repo itself.

| Image | Registry | Age | Pull count | Source | Verdict | Disposition |
|-------|----------|-----|-----------|--------|---------|-------------|
| `glitchtip/glitchtip:v6.1.8` | Docker Hub | 8 days | multi-million (official) | gitlab.com/glitchtip/glitchtip-backend | OK | Approved |
| `postgres:17-alpine` | Docker Hub | already used in project | — | official postgres | OK | Already in use |

---

## Architecture Patterns

### System Architecture Diagram

```
CI (GitHub Actions)
    │ render-obs-secrets.py (error-tracking ns)
    │ kubectl apply k8s/observability/9x-glitchtip-*.yaml
    ▼
┌─────────────── error-tracking namespace ───────────────────────────────┐
│                                                                         │
│  [Job: 90-glitchtip-migrate]  → runs manage.py migrate                 │
│         ↓ (completions:1, restartPolicy:Never)                         │
│  [Job: 91-glitchtip-seed]     → runs manage.py createsuperuser +       │
│                                  API calls: create org+project → DSN   │
│         ↓                                                               │
│  [StatefulSet: glitchtip-postgres] ←──────────────────────────┐        │
│  [Service: glitchtip-postgres :5432]                          │        │
│                                                               │        │
│  [Deployment: glitchtip-web]  (granian, port 8000)           │        │
│  SERVER_ROLE=web, VALKEY_URL=""                               │        │
│  DATABASE_URL → glitchtip-postgres.error-tracking.svc         ├── PVC  │
│                                                               │        │
│  [Deployment: glitchtip-worker]  (runworker --scheduler)      │        │
│  SERVER_ROLE=worker                                           │        │
│  DATABASE_URL → glitchtip-postgres.error-tracking.svc         │        │
│                                                               │        │
│  [Service: glitchtip-web :8000]  (ClusterIP)  ───────────────┘        │
└─────────────────────────────────────────────────────────────────────────┘
         │ (ClusterIP, internal only)          │ (port-forward for test)
         │                                     ▼
         │                        [Forced-error test script]
         │                        POST /api/PROJECT_ID/envelope/
         │                        (via port-forward to glitchtip-web svc)
         ▼
[Host nginx — errors.stats-staging.solid-stats.ru]  ← OPERATOR-GATED
    TLS: Let's Encrypt cert (Phase 14 bootstrap-obs-edge.sh)
    proxy_pass → glitchtip-web ClusterIP:8000
    (currently returns 503; Phase 16 swaps in proxy_pass when DNS resolves)
```

### Recommended File Layout

```
k8s/observability/
├── 90-glitchtip-postgres.yaml   # StatefulSet + Service for GlitchTip's own PG
├── 91-glitchtip.yaml            # web Deployment + worker Deployment + Service
├── 92-glitchtip-migrate.yaml    # one-shot migrate Job (first-run gate)
├── 93-glitchtip-seed.yaml       # one-shot superuser seed Job
config/nginx/sites-available/
└── errors-stats-staging-solid-stats.conf  # Phase 14 placeholder → Phase 16 updates proxy_pass
scripts/
├── render-obs-secrets.py        # EXTEND: add error-tracking secrets section
├── validate-phase-16.sh         # new: GlitchTip pod health + ERR-01/02/03 checks
└── test-glitchtip-ingest.sh     # new: forced-error test (port-forward + curl envelope)
docs/
└── glitchtip.md                 # operator runbook: first-run order, public URL cutover
```

### Pattern 1: GlitchTip PostgreSQL-Only Mode (v6)

**What:** Set `VALKEY_URL=""` to disable Valkey/Redis. GlitchTip v6 then uses Postgres via
django-vtasks and django-vcache for task queue, cache, and sessions. No separate broker pod needed.

**When to use:** Always for this phase (node headroom constraint; no Redis/Valkey).

```yaml
# Source: glitchtip.com/documentation/install/ + glitchtip.com/blog/2026-02-03-glitchtip-6-released/
env:
  - name: VALKEY_URL
    value: ""                          # empty string = postgres-only mode
  - name: DATABASE_URL
    valueFrom:
      secretKeyRef:
        name: glitchtip-secrets
        key: DATABASE_URL              # postgresql://glitchtip:PWD@glitchtip-postgres.error-tracking.svc:5432/glitchtip
  - name: SECRET_KEY
    valueFrom:
      secretKeyRef:
        name: glitchtip-secrets
        key: SECRET_KEY
  - name: GLITCHTIP_DOMAIN
    value: "https://errors.stats-staging.solid-stats.ru"
  - name: ENABLE_USER_REGISTRATION
    value: "False"                     # closes registration from first boot [CITED: glitchtip.com/documentation/install/]
  - name: EMAIL_BACKEND
    value: "django.core.mail.backends.console.EmailBackend"  # no SMTP needed for staging
  - name: DEFAULT_FROM_EMAIL
    value: "glitchtip@stats-staging.solid-stats.ru"
  - name: TRUSTED_PROXIES
    value: "*"                         # required for Granian behind nginx reverse proxy [CITED: glitchtip.com/blog/2026-02-03-glitchtip-6-released/]
  - name: PORT
    value: "8000"
```

### Pattern 2: web vs worker via SERVER_ROLE (v6)

**What:** GlitchTip v6 uses a single image with `./bin/start.sh` as the entrypoint.
`SERVER_ROLE=web` (default) starts Granian. `SERVER_ROLE=worker` runs `manage.py runworker --scheduler`.

```yaml
# Web Deployment
containers:
  - name: glitchtip-web
    image: glitchtip/glitchtip:v6.1.8
    command: ["./bin/start.sh"]
    env:
      - name: SERVER_ROLE
        value: "web"
      # ... shared env above ...
    ports:
      - name: http
        containerPort: 8000

# Worker Deployment
containers:
  - name: glitchtip-worker
    image: glitchtip/glitchtip:v6.1.8
    command: ["./bin/start.sh"]
    env:
      - name: SERVER_ROLE
        value: "worker"
      # ... shared env above (no PORT needed) ...
```

[ASSUMED] — `./bin/start.sh` + `SERVER_ROLE` dispatching confirmed from v6 release blog; exact
entrypoint path not verified via codebase grep. Planner should confirm with `docker run
glitchtip/glitchtip:v6.1.8 ls bin/` in Wave 1 or use `manage.py runworker --scheduler` directly
as a fallback worker command.

### Pattern 3: First-Run Job Ordering

**What:** Three-phase init enforced via Kubernetes Job dependencies and `initContainers`.

**Ordering strategy:** The migrate Job completes (restartPolicy: Never, backoffLimit: 3).
The web + worker Deployments use an initContainer that checks DB migration state before
starting. The seed Job (superuser + API org/project) depends on the migrate Job completing
AND the web pod being ready (readinessProbe).

**Simpler alternative (preferred for this scale):** Apply manifests in two `kubectl apply`
waves in CI / operator steps:

```
Wave A (CI apply):
  - 90-glitchtip-postgres.yaml     (StatefulSet + PVC)
  - 91-glitchtip.yaml              (web + worker — both have initContainer: wait-for-migrate)
  - 92-glitchtip-migrate.yaml      (migrate Job)

Wave B (CI apply, after migrate Job completes):
  - 93-glitchtip-seed.yaml         (createsuperuser + API seed)
```

The migrate Job uses `initContainer` waiting for postgres readiness, then runs
`./manage.py migrate`. The web/worker Deployments use an initContainer that polls
`./manage.py showmigrations | grep '\[ \]'` to confirm all migrations are applied.

**Actual migrate Job spec:**
```yaml
# Source: glitchtip.com/documentation/install/
apiVersion: batch/v1
kind: Job
metadata:
  name: glitchtip-migrate
  namespace: error-tracking
spec:
  completions: 1
  backoffLimit: 3
  template:
    spec:
      restartPolicy: Never
      serviceAccountName: glitchtip
      priorityClassName: obs-background
      initContainers:
        - name: wait-for-postgres
          image: postgres:17-alpine
          command: ["sh", "-c", "until pg_isready -h glitchtip-postgres.error-tracking.svc -U glitchtip; do sleep 2; done"]
      containers:
        - name: migrate
          image: glitchtip/glitchtip:v6.1.8
          command: ["./manage.py", "migrate", "--noinput"]
          env:
            # DATABASE_URL + SECRET_KEY + VALKEY_URL="" from glitchtip-secrets
```

### Pattern 4: Superuser Seed Job

```yaml
# manage.py createsuperuser --noinput uses DJANGO_SUPERUSER_EMAIL + DJANGO_SUPERUSER_PASSWORD
# Source: Django docs (standard Django management command)
containers:
  - name: seed
    image: glitchtip/glitchtip:v6.1.8
    command: ["./manage.py", "createsuperuser", "--noinput"]
    env:
      - name: DJANGO_SUPERUSER_EMAIL
        valueFrom:
          secretKeyRef:
            name: glitchtip-secrets
            key: GLITCHTIP_SUPERUSER_EMAIL
      - name: DJANGO_SUPERUSER_PASSWORD
        valueFrom:
          secretKeyRef:
            name: glitchtip-secrets
            key: GLITCHTIP_SUPERUSER_PASSWORD
      # + DATABASE_URL, SECRET_KEY, VALKEY_URL=""
```

After the superuser exists, the seed Job (or a subsequent script step) hits the GlitchTip REST
API to create org + project + retrieve DSN. The API requires an auth token obtained by POSTing
credentials to `/auth/login/` then creating a token via `/api/0/users/{user}/tokens/`.

### Pattern 5: ERR-02 Registration Verification

**What:** Prove registration is closed by checking `GET /api/0/config/` (returns
`"user_registration_enabled": false`) or by POST-ing to `/api/0/auth/registration/` and
confirming 403/disabled response.

```bash
# Via port-forward (autonomous — no public DNS needed)
# Source: [ASSUMED] standard GlitchTip/Sentry-compatible API
curl -s http://localhost:8000/api/0/config/ | grep user_registration_enabled
# Expected: "user_registration_enabled":false
```

### Pattern 6: ERR-03 Forced-Error Test (Autonomous / port-forward)

**What:** POST a synthetic Sentry envelope directly to the ingest endpoint to prove GlitchTip
records it, without needing the public DNS-resolved errors. URL.

```bash
# Source: develop.sentry.dev/sdk/foundations/transport/envelopes/
# DSN format: https://PUBLIC_KEY@glitchtip-host/PROJECT_ID
# Internal test uses port-forward: kubectl port-forward svc/glitchtip-web 8000:8000 -n error-tracking

PROJECT_ID=1   # first project created by seed Job
PUBLIC_KEY="<dsn_public_key>"

# Envelope format: 3 newline-separated JSON lines
ENVELOPE=$(printf '{"event_id":"aabbccdd00112233445566778899aabb","dsn":"http://%s@localhost:8000/%s"}\n{"type":"event","length":73}\n{"message":"Phase 16 forced test error","level":"error"}' "$PUBLIC_KEY" "$PROJECT_ID")

curl -s -X POST \
  "http://localhost:8000/api/${PROJECT_ID}/envelope/" \
  -H "Content-Type: application/x-sentry-envelope" \
  --data-raw "$ENVELOPE"

# Then verify via API (with superuser token):
curl -s -H "Authorization: Bearer $SUPERUSER_TOKEN" \
  "http://localhost:8000/api/0/projects/staging-org/staging-project/issues/?query=Phase+16"
```

### Pattern 7: GlitchTip PostgreSQL StatefulSet (mirrors 10-postgres.yaml)

```yaml
# Mirror of k8s/staging/10-postgres.yaml adapted for error-tracking namespace
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: glitchtip-postgres
  namespace: error-tracking
spec:
  serviceName: glitchtip-postgres
  replicas: 1
  template:
    spec:
      priorityClassName: obs-background   # evictable under pressure
      serviceAccountName: glitchtip-postgres
      automountServiceAccountToken: false
      containers:
        - name: postgres
          image: postgres:17-alpine
          imagePullPolicy: IfNotPresent
          env:
            - name: POSTGRES_DB
              value: glitchtip
            - name: POSTGRES_USER
              value: glitchtip
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: glitchtip-postgres-auth
                  key: POSTGRES_PASSWORD
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 250m
              memory: 256Mi    # [ASSUMED] — verify vs kubectl top after warm-up
          readinessProbe:
            exec:
              command: ["pg_isready", "-U", "glitchtip", "-d", "glitchtip"]
            initialDelaySeconds: 5
            periodSeconds: 10
  volumeClaimTemplates:
    - metadata:
        name: glitchtip-postgres-data
      spec:
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 5Gi    # [ASSUMED] — error tracking only, staging volume; adjust after 30 days
```

### Pattern 8: nginx vhost cutover (operator-gated)

The errors. vhost file already exists at
`config/nginx/sites-available/errors-stats-staging-solid-stats.conf` (Phase 14 placeholder).
Phase 16 must update the HTTPS server block to proxy_pass to GlitchTip's ClusterIP:

```nginx
# Replace the placeholder 503 block with:
upstream glitchtip_obs {
    server UPSTREAM_PLACEHOLDER;   # bootstrap-obs-edge.sh substitutes at runtime
    keepalive 8;
}

server {
    listen 443 ssl http2;
    server_name errors.stats-staging.solid-stats.ru;
    # ... ssl_certificate, HSTS headers (same as grafana vhost) ...

    location / {
        proxy_pass http://glitchtip_obs;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_http_version 1.1;
        proxy_connect_timeout 5s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
```

The `bootstrap-obs-edge.sh` script already handles the UPSTREAM_PLACEHOLDER substitution
(`kubectl get svc glitchtip-web -n error-tracking -o jsonpath=...`) and the cert lineage
already exists from Phase 14. Re-running with `DOMAIN=errors.stats-staging.solid-stats.ru` and
`ADMIN_EMAIL=...` is all that's needed once DNS resolves. [CITED: scripts/bootstrap-obs-edge.sh]

### Anti-Patterns to Avoid

- **Don't mix ENABLE_OPEN_USER_REGISTRATION and ENABLE_USER_REGISTRATION:** GlitchTip has
  renamed this variable across versions. v3/v4 used `ENABLE_OPEN_USER_REGISTRATION`; v5/v6
  use `ENABLE_USER_REGISTRATION`. Use `ENABLE_USER_REGISTRATION=False` for v6.1.8.
  [CITED: glitchtip.com/documentation/install/]

- **Don't use the all-in-one `bin/start-all-in-one.sh` in k8s:** Separate web + worker pods
  allow independent restarts and resource limits. All-in-one is for single-container/Docker
  Compose use only.

- **Don't run the seed Job before migration completes:** The seed Job must either (a) wait via
  initContainer for `showmigrations` to show no unapplied migrations, or (b) be applied in a
  separate CI wave after the migrate Job reaches `Complete` status. Failure mode: createsuperuser
  fails with missing table error.

- **Don't use `TRUSTED_PROXIES` absent behind nginx:** Granian without TRUSTED_PROXIES defaults
  to `*` (all proxies trusted), which is acceptable for single-node staging. Set explicitly to
  avoid surprises. [CITED: glitchtip.com/blog/2026-02-03-glitchtip-6-released/]

- **Don't set DATABASE_URL with `prefer` sslmode:** Same constraint as the postgres-exporter
  DSN in Phase 13 — use `sslmode=disable` for intra-cluster connections with no TLS on the
  GlitchTip postgres. [CITED: scripts/render-obs-secrets.py comment]

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Task queue / async workers | Custom queue | django-vtasks (built into GlitchTip v6) | Already in the image; VALKEY_URL="" routes through it |
| Beat/cron scheduler | Separate CronJob or K8s CronJob | `manage.py runworker --scheduler` | v6 scheduler is in the worker process; a K8s CronJob would duplicate it |
| Superuser creation | Custom script + k8s exec | `manage.py createsuperuser --noinput` + `DJANGO_SUPERUSER_*` | Standard Django; idempotent (skips if user exists) |
| Org/project/DSN creation | UI-only | GlitchTip REST API (Sentry-compatible) | Fully automatable in seed Job script; POST to /api/0/organizations/ etc. |
| TLS termination | In-pod TLS | Host nginx (Phase 14 bootstrap-obs-edge.sh) | Already established pattern; cert already exists |
| Envelope ingest verification | Custom webhook | `curl` POST to /api/PROJECT_ID/envelope/ | Sentry envelope format is well-documented; no SDK needed for the test |

---

## Common Pitfalls

### Pitfall 1: Wrong ENABLE_USER_REGISTRATION variable name
**What goes wrong:** Using `ENABLE_OPEN_USER_REGISTRATION` (old v3/v4 name) on GlitchTip v6
silently does nothing — registration stays open.
**Why it happens:** Multiple blog posts and compose examples still show the old name.
**How to avoid:** Use `ENABLE_USER_REGISTRATION=False` on v6. Verify via ERR-02 check:
`GET /api/0/config/` → `"user_registration_enabled":false`.
**Warning signs:** Registration endpoint returns 2xx instead of 403.

### Pitfall 2: Seed Job runs before migration completes
**What goes wrong:** `createsuperuser` fails with `relation "accounts_user" does not exist`
because Django tables haven't been created yet.
**Why it happens:** Kubernetes applies Jobs concurrently unless explicitly sequenced.
**How to avoid:** The seed Job (93-glitchtip-seed.yaml) must have an initContainer waiting for
migrate Job completion: `kubectl wait --for=condition=complete job/glitchtip-migrate -n error-tracking --timeout=120s`
or check `manage.py showmigrations | grep '\[ \]'` exits non-zero.
**Warning signs:** Seed Job pods fail with CrashLoopBackOff; logs show missing table.

### Pitfall 3: VALKEY_URL not explicitly set to empty string
**What goes wrong:** GlitchTip tries to connect to a non-existent Valkey/Redis and the worker
crashes with `ConnectionRefused`.
**Why it happens:** The default for VALKEY_URL may point to `redis://valkey:6379/0` in the
official compose sample. If the env var is absent (not explicitly set to ""), the default applies.
**How to avoid:** Set `VALKEY_URL: ""` explicitly in every GlitchTip container spec (web,
worker, migrate, seed).
**Warning signs:** Worker pod logs: `redis.exceptions.ConnectionError`.

### Pitfall 4: bin/start.sh entrypoint path or SERVER_ROLE dispatch
**What goes wrong:** The container starts with the wrong mode (e.g., web instead of worker).
**Why it happens:** `SERVER_ROLE` dispatch via `bin/start.sh` is a v6-specific feature. If the
image uses a different entrypoint, the env var is ignored.
**How to avoid:** [ASSUMED] Verify `docker run glitchtip/glitchtip:v6.1.8 cat bin/start.sh`
in an operator bootstrap step. Fallback: use explicit command
`["python", "manage.py", "runworker", "--scheduler"]` for the worker and
`["python", "-m", "granian", "glitchtip.asgi:application", "--port", "8000"]` for web.
**Warning signs:** Worker pod logs show Granian web server starting (not runworker).

### Pitfall 5: validate-obs-manifests.py namespace check fails
**What goes wrong:** The static manifest validator (Phase 13) rejects GlitchTip manifests
because they declare `namespace: error-tracking` instead of `monitoring`.
**Why it happens:** The validator currently enforces `namespace: monitoring` on all resources.
**How to avoid:** Extend `validate-obs-manifests.py` to accept both `monitoring` and
`error-tracking` as valid obs namespaces. [CITED: scripts/validate-obs-manifests.py]
**Warning signs:** CI validate job fails with "namespace must be monitoring".

### Pitfall 6: Port mismatch — v6 changed from 8080 to 8000
**What goes wrong:** nginx proxy_pass targets port 8080 (old v4/v5 default), GlitchTip web
listens on 8000, resulting in connection refused.
**Why it happens:** v6 standardized on port 8000. [CITED: glitchtip.com/blog/2026-02-03-glitchtip-6-released/]
**How to avoid:** Use port 8000 in Service spec and nginx upstream. Set `PORT=8000` in env.
**Warning signs:** 502 Bad Gateway from nginx.

### Pitfall 7: Resource exhaustion — GlitchTip web OOMKilled
**What goes wrong:** Granian + Django OOM-killed because memory limit is too tight.
**Why it happens:** GlitchTip recommends 512 MB for web; with tight limits, the pod gets evicted.
**How to avoid:** Start web at 256Mi limit, monitor with `kubectl top pod`, adjust in the live
validation step. The worker can run at 192Mi. Both are `obs-background` so eviction before
app pods is guaranteed.
**Warning signs:** Pod restarts with OOMKilled exit code.

### Pitfall 8: Sentry envelope auth — DSN public key must match project
**What goes wrong:** Envelope POST returns 403 "Invalid DSN" or "ProjectId mismatch".
**Why it happens:** The DSN public key in the envelope header must match the project's actual
DSN key. Using a placeholder or mismatched key fails silently or with 403.
**How to avoid:** Retrieve the real DSN from the API after org/project creation; extract
`PUBLIC_KEY` and `PROJECT_ID` from the DSN URL programmatically in the test script.
**Warning signs:** `/api/PROJECT_ID/envelope/` returns 403.

---

## GlitchTip v6 Environment Variables Reference

| Variable | Required | Value for This Phase | Source |
|----------|----------|---------------------|--------|
| `SECRET_KEY` | Yes | random 50-char string (from GitHub secret) | [CITED: docs] |
| `DATABASE_URL` | Yes | `postgresql://glitchtip:PWD@glitchtip-postgres.error-tracking.svc:5432/glitchtip?sslmode=disable` | [CITED: docs] |
| `GLITCHTIP_DOMAIN` | Yes | `https://errors.stats-staging.solid-stats.ru` (or localhost for internal) | [CITED: docs] |
| `VALKEY_URL` | Yes (empty) | `""` — postgres-only mode | [CITED: glitchtip.com/blog/2026-02-03-glitchtip-6-released/] |
| `ENABLE_USER_REGISTRATION` | Yes | `"False"` | [CITED: glitchtip.com/documentation/install/] |
| `EMAIL_BACKEND` | No | `django.core.mail.backends.console.EmailBackend` — no SMTP | [ASSUMED] standard Django |
| `DEFAULT_FROM_EMAIL` | Yes | `glitchtip@stats-staging.solid-stats.ru` | [CITED: docs] |
| `TRUSTED_PROXIES` | Yes | `"*"` — behind nginx | [CITED: v6 release notes] |
| `PORT` | No | `"8000"` | [CITED: v6 release notes — changed from 8080] |
| `SERVER_ROLE` | No | `"web"` (default) or `"worker"` | [CITED: v6 release notes] |
| `DJANGO_SUPERUSER_EMAIL` | Seed Job only | from GitHub secret | [ASSUMED: standard Django --noinput] |
| `DJANGO_SUPERUSER_PASSWORD` | Seed Job only | from GitHub secret | [ASSUMED: standard Django --noinput] |
| `GRANIAN_WORKERS` | No | `"1"` — tight resource limit | [CITED: docs] |
| `VTASKS_CONCURRENCY` | No | `"2"` — reduce from default 20 | [CITED: docs — default 20] |
| `DATABASE_POOL_MAX_SIZE` | No | `"5"` — reduce from default 20 | [CITED: docs] |

---

## Resource Sizing (ASSUMED — must verify vs kubectl top)

All pods: `priorityClassName: obs-background`, namespace: `error-tracking`.

| Pod | CPU req | CPU limit | Mem req | Mem limit | Notes |
|-----|---------|-----------|---------|-----------|-------|
| glitchtip-postgres | 100m | 250m | 128Mi | 256Mi | light; no app queries |
| glitchtip-web | 100m | 300m | 192Mi | 384Mi | Granian single-worker |
| glitchtip-worker | 50m | 200m | 128Mi | 256Mi | runworker --scheduler, VTASKS_CONCURRENCY=2 |
| migrate Job | 50m | 200m | 128Mi | 256Mi | one-shot |
| seed Job | 50m | 200m | 128Mi | 256Mi | one-shot |

**Total working set at steady state (postgres + web + worker): ~640Mi requests, ~896Mi limits.**
Node headroom is ~2.6Gi; existing obs stack (monitoring ns) consumes ~1.5Gi working set. Adding
~640Mi requests stays within headroom. [ASSUMED values — Plan 16-06 live-apply step MUST run
`kubectl top pods -n error-tracking` and tune before declaring Phase 16 complete.]

---

## Secret Rendering Extension

`scripts/render-obs-secrets.py` must be extended to emit secrets for the `error-tracking`
namespace. Pattern: add a second `NAMESPACE = "error-tracking"` section or emit multi-document
YAML with both namespaces. New secrets needed:

```python
# New GitHub Secrets required (DEP-04):
# GLITCHTIP_SECRET_KEY         — Django SECRET_KEY (50-char random)
# GLITCHTIP_POSTGRES_PASSWORD  — GlitchTip's own DB password
# GLITCHTIP_SUPERUSER_EMAIL    — initial superuser email
# GLITCHTIP_SUPERUSER_PASSWORD — initial superuser password

# Secrets emitted:
# glitchtip-postgres-auth (error-tracking) → POSTGRES_PASSWORD
# glitchtip-secrets (error-tracking) → SECRET_KEY, DATABASE_URL, GLITCHTIP_SUPERUSER_EMAIL, GLITCHTIP_SUPERUSER_PASSWORD
```

The renderer should add `NAMESPACE = "error-tracking"` emitting to the correct namespace,
following the existing `secret()` helper pattern exactly.

---

## ERR-02 Verification Protocol

**Registration-closed proof** (autonomous — via port-forward):

```bash
# Method A: config endpoint
curl -s http://localhost:8000/api/0/config/ | python3 -c "import sys,json; cfg=json.load(sys.stdin); assert cfg.get('user_registration_enabled') is False, 'registration OPEN'; print('ERR-02 PASS: registration disabled')"

# Method B: attempt registration, expect 4xx
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/api/0/auth/registration/ \
  -H "Content-Type: application/json" \
  -d '{"email":"probe@test.invalid","password1":"TestProbe123!","password2":"TestProbe123!"}')
if [[ "$STATUS" == "403" || "$STATUS" == "400" ]]; then
  echo "ERR-02 PASS: registration endpoint returned $STATUS"
else
  echo "ERR-02 FAIL: expected 403/400, got $STATUS" && exit 1
fi
```

[ASSUMED] — the exact response code (403 vs 400) depends on GlitchTip v6 implementation.
The config endpoint method (Method A) is more reliable.

---

## Autonomous vs Operator-Gated Work

### Autonomous (agent can execute without DNS/operator)

| Task | Mechanism |
|------|-----------|
| Author all manifests (90–93) | Write YAML to k8s/observability/ |
| Extend render-obs-secrets.py | Edit existing script |
| Update validate-obs-manifests.py for error-tracking ns | Edit existing script |
| Update errors. nginx vhost for proxy_pass | Edit config/nginx/sites-available/errors-stats-staging-solid-stats.conf |
| Update bootstrap-obs-edge.sh for glitchtip ClusterIP discovery | Add `glitchtip*` case |
| Write validate-phase-16.sh | New script |
| Write test-glitchtip-ingest.sh (forced-error test via port-forward) | New script |
| Add GitHub Secrets instructions to docs | docs/glitchtip.md |
| Deploy manifests via CI (deploy-observability.yml) | Existing CI path |
| Verify pods Running | kubectl get pods / validate-phase-16.sh |
| ERR-02 check via port-forward | curl to localhost:8000 |
| ERR-03 forced-error test via port-forward | test-glitchtip-ingest.sh |

### Operator-Gated (requires DNS A record resolution for errors. subdomain)

| Task | Trigger |
|------|---------|
| Set GitHub Secrets (4 new secrets) | Once, before first CI deploy |
| Run `bootstrap-obs-edge.sh` with GlitchTip upstream | After DNS resolves |
| Verify `curl -I https://errors.stats-staging.solid-stats.ru/` returns 200 | After certbot |
| Run public-URL smoke test | After operator cutover |

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | bash validate scripts (project convention) + curl |
| Config file | none — standalone bash scripts |
| Quick run command | `bash scripts/validate-phase-16.sh --internal` (port-forward mode) |
| Full suite command | `bash scripts/validate-phase-16.sh` (requires live GlitchTip pod) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ERR-01 | GlitchTip web + worker + postgres pods Running | smoke | `kubectl get pods -n error-tracking` | ❌ Wave 0 |
| ERR-01 | VALKEY_URL="" effective (no Valkey connection attempts) | unit/log | Check worker logs for ConnectionError | ❌ Wave 0 |
| ERR-01 | migrate Job completed successfully | smoke | `kubectl get job glitchtip-migrate -n error-tracking` | ❌ Wave 0 |
| ERR-02 | Registration endpoint returns 403/400 or config shows disabled | integration | `curl /api/0/config/` + validate-phase-16.sh | ❌ Wave 0 |
| ERR-03 | Org + project + DSN exist (API returns project list) | integration | curl with superuser token | ❌ Wave 0 |
| ERR-03 | Forced test error appears in GlitchTip issues | integration | `test-glitchtip-ingest.sh` via port-forward | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `bash scripts/validate-obs-manifests.py` (static YAML gate)
- **Per wave merge:** `bash scripts/validate-phase-16.sh` (full live check)
- **Phase gate:** All 6 rows above pass + forced-error appears in issues list

### Wave 0 Gaps

- [ ] `scripts/validate-phase-16.sh` — covers ERR-01, ERR-02, ERR-03 live checks
- [ ] `scripts/test-glitchtip-ingest.sh` — forced-error ingest test via port-forward

---

## Security Domain

### Applicable ASVS Categories (Level 2)

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | Yes | GlitchTip own auth; ENABLE_USER_REGISTRATION=False; superuser seed via DJANGO_SUPERUSER_* |
| V3 Session Management | Yes | Django sessions via postgres (VALKEY_URL="" routes sessions to DB) |
| V4 Access Control | Yes | Only superuser can administer; org invites disabled by ENABLE_USER_REGISTRATION=False |
| V5 Input Validation | Yes | GlitchTip Django handles; envelope endpoint validates DSN public key |
| V6 Cryptography | Yes | SECRET_KEY from secret; postgres password from secret; never in git |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Open registration → unauthorized orgs/projects | Elevation of Privilege | `ENABLE_USER_REGISTRATION=False` from first boot |
| SECRET_KEY in env var / git | Information Disclosure | Rendered from GitHub secret by render-obs-secrets.py at deploy time |
| GlitchTip postgres accessible cross-namespace | Tampering | Separate `glitchtip-postgres` Service in error-tracking; no cross-namespace route; Phase 17 NetworkPolicy |
| Default ServiceAccount token auto-mount | Elevation of Privilege | `automountServiceAccountToken: false` on all pods; dedicated glitchtip ServiceAccount |
| Public ingest endpoint unauthenticated | Spoofing | DSN public key required per envelope; no sensitive data in ingest path; acceptable for staging |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `./bin/start.sh` + `SERVER_ROLE=worker` dispatches to `manage.py runworker --scheduler` in v6.1.8 | Pattern 2 | Worker starts Granian instead; fix: explicit command in Deployment spec |
| A2 | Resource limits (128-384Mi web, 128-256Mi worker, 128-256Mi postgres) fit within node headroom | Resource Sizing | OOMKill or eviction; fix: tune upward in live-apply step |
| A3 | `ENABLE_USER_REGISTRATION=False` registration endpoint returns 403 (not 400 or 405) | ERR-02 Verification | Test script fails; fix: check `/api/0/config/` endpoint instead |
| A4 | `manage.py createsuperuser --noinput` reads `DJANGO_SUPERUSER_EMAIL` + `DJANGO_SUPERUSER_PASSWORD` in GlitchTip v6 | Pattern 4 | Seed Job fails; fix: use `echo | manage.py createsuperuser` interactively or check GlitchTip's custom user model |
| A5 | GlitchtTip REST API for org/project/DSN creation follows Sentry-compatible path (`/api/0/organizations/`) | ERR-03 seed | API path differs; fix: check GlitchTip API docs at `/api/0/` discovery endpoint |
| A6 | GlitchTip postgres PVC 5Gi sufficient for staging error volume | Resource Sizing | PVC full; fix: resize PVC (manual on k3s local-path) |
| A7 | `GLITCHTIP_DOMAIN` set to errors. public URL is safe even before DNS resolves (used for absolute URL generation only) | Env vars | Links in emails/UI point to unresolvable host; acceptable for staging | 
| A8 | `EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend` suppresses SMTP errors cleanly in v6 | Env vars | Worker/web logs spam with SMTP errors; fix: add `EMAIL_URL=consolemail://` |

---

## Open Questions

1. **Exact `bin/start.sh` content in v6.1.8**
   - What we know: v6 blog post says `SERVER_ROLE` env controls dispatch; `./bin/start.sh` is the entrypoint
   - What's unclear: Whether the script literally dispatches on `SERVER_ROLE` or if the image has a different entrypoint
   - Recommendation: Wave 1 plan includes a one-liner operator bootstrap step: `docker run --rm glitchtip/glitchtip:v6.1.8 cat bin/start.sh` to confirm before authoring Deployment specs

2. **`DJANGO_SUPERUSER_*` support in GlitchTip's custom User model**
   - What we know: Standard Django `createsuperuser --noinput` reads these env vars when the User model has `email` as USERNAME_FIELD
   - What's unclear: GlitchTip may have a custom user model that uses `email` (standard for them) or additional required fields
   - Recommendation: Seed Job includes a fallback: if createsuperuser fails, use a short Python one-liner `manage.py shell -c "from users.models import User; User.objects.create_superuser(...)"` with the same secrets

3. **GlitchTip REST API path for org creation**
   - What we know: GlitchTip is Sentry-compatible; Sentry uses `POST /api/0/organizations/`
   - What's unclear: Whether GlitchTip v6 implements the full Sentry org-creation API or requires UI-only for first org
   - Recommendation: Include both API-based org creation AND a fallback `manage.py` command path in the seed Job

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| k3s / kubectl | All deployment tasks | ✓ | already on staging VPS | — |
| Docker Hub pull (glitchtip/glitchtip:v6.1.8) | Image pull on node | ✓ | public image | — |
| Port-forward (kubectl port-forward) | ERR-02/ERR-03 autonomous tests | ✓ | kubectl built-in | — |
| DNS for errors. subdomain | Public URL cutover | ✗ | not yet resolved | Use port-forward for all internal tests |
| Let's Encrypt cert for errors. | HTTPS cutover | ✓ | Phase 14 cert already issued | — |

**Missing dependencies with no fallback for autonomous work:** None — all ERR-01/02/03 acceptance tests work via port-forward without DNS.

**Operator-gated only:** DNS A record for `errors.stats-staging.solid-stats.ru`. Everything else is autonomous.

---

## Sources

### Primary (HIGH confidence)
- [glitchtip.com/documentation/install/](https://glitchtip.com/documentation/install/) — env vars, VALKEY_URL="", ENABLE_USER_REGISTRATION, migrate command
- [glitchtip.com/blog/2026-02-03-glitchtip-6-released/](https://glitchtip.com/blog/2026-02-03-glitchtip-6-released/) — v6 architecture (granian, SERVER_ROLE, django-vtasks, port 8000, TRUSTED_PROXIES)
- [hub.docker.com/r/glitchtip/glitchtip/tags](https://hub.docker.com/r/glitchtip/glitchtip/tags) — confirmed v6.1.8 is current stable (pushed 2026-06-06)
- [develop.sentry.dev/sdk/foundations/transport/envelopes/](https://develop.sentry.dev/sdk/foundations/transport/envelopes/) — envelope format, POST /api/PROJECT_ID/envelope/
- [scripts/bootstrap-obs-edge.sh](../../../scripts/bootstrap-obs-edge.sh) — confirmed Phase 14 bootstrap handles errors. vhost, UPSTREAM_PLACEHOLDER pattern
- [config/nginx/sites-available/errors-stats-staging-solid-stats.conf](../../../config/nginx/sites-available/errors-stats-staging-solid-stats.conf) — confirmed 503 placeholder, cert already issued
- [k8s/staging/10-postgres.yaml](../../../k8s/staging/10-postgres.yaml) — postgres StatefulSet pattern to mirror
- [scripts/render-obs-secrets.py](../../../scripts/render-obs-secrets.py) — secret renderer pattern to extend
- [k8s/staging/01-obs-rbac.yaml](../../../k8s/staging/01-obs-rbac.yaml) — confirmed error-tracking ns RBAC already exists

### Secondary (MEDIUM confidence)
- [glitchtip.com/blog/2025-11-13-glitchtip-5-2-released/](https://glitchtip.com/blog/2025-11-13-glitchtip-5-2-released/) — VALKEY_URL="" postgres-only mode introduced in 5.2 (confirmed in 6.x)
- [django-vtasks.glitchtip.com/guide/](https://django-vtasks.glitchtip.com/guide/) — `manage.py runworker --scheduler` command

### Tertiary (LOW confidence / ASSUMED)
- bin/start.sh entrypoint + SERVER_ROLE dispatch — inferred from v6 blog post; not verified via codebase
- Resource sizing numbers — community data + official min-req; must verify vs kubectl top
- DJANGO_SUPERUSER_* env vars in seed Job — standard Django pattern; GlitchTip-specific behavior not confirmed

---

## Metadata

**Confidence breakdown:**
- GlitchTip v6 postgres-only mode: HIGH — confirmed from official docs + release blog
- Image tag v6.1.8: HIGH — verified from Docker Hub tags page
- bin/start.sh + SERVER_ROLE dispatch: MEDIUM — from official release blog, not grep'd from image
- Resource sizing: LOW — community data + official minimums; must tune live
- createsuperuser --noinput env vars: MEDIUM — standard Django pattern; GlitchTip model assumed compatible
- Sentry envelope ingest format: HIGH — official Sentry developer docs

**Research date:** 2026-06-14
**Valid until:** 2026-07-14 (GlitchTip releases frequently; re-check if > 4 weeks old)
