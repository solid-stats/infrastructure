<!-- refreshed: 2026-06-13 -->
# Architecture

**Analysis Date:** 2026-06-13

## System Overview

The Solid Stats Infrastructure repository owns the staging k3s runtime: PostgreSQL and RabbitMQ stateful services, three application workloads (server-2, replay-parser-2, web), scheduled backup and replay-fetch jobs, and the operator-controlled edge cutover lever via host nginx. The data flow runs from raw HTTP ingest → server-2 (API) → RabbitMQ (job queue) → replay-parser-2 (workers) → Timeweb S3 (artifacts), with PostgreSQL holding metadata. Backup exports to S3 daily; restore-drill validates backups in isolation before full-run cutover work.

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│                    GitHub Actions CI (WireGuard Gate)                         │
│                         `.github/workflows/deploy-staging.yml`                │
│   (validate → dry-run → WireGuard tunnel → kubeconfig → kubectl apply)       │
└──────────┬───────────────────────────────────────────────────────────────────┘
           │ applies manifests to k3s API via WireGuard tunnel
           │ (excludes 00-namespace.yaml and 01-ci-rbac.yaml)
           ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                    k3s Cluster (staging VPS)                                  │
│                    solid-stats-staging namespace                              │
├──────────────┬──────────────────┬─────────────────┬───────────────────────────┤
│  PostgreSQL  │   RabbitMQ       │   server-2      │   replay-parser-2         │
│ StatefulSet  │   StatefulSet    │   Deployment    │   Deployment (2 replicas) │
│ 10-postgres  │  20-rabbitmq     │  35-deployment  │   40-replay-parser-2      │
│ (20Gi PVC)   │   (5Gi PVC)      │  (1 replica)    │   (init: wait for dbs)    │
│              │                  │  (init: wait)   │                           │
│              │                  │  ConfigMap      │   extracts & uploads      │
│              │                  │  server-2-config│   replay artifacts to S3  │
└──────────────┴──────────────────┴─────────────────┴───────────────────────────┘
       │                │                │                    │
       │ .5432          │ .5672          │ :3000              │ :8080 (probes)
       ▼                ▼                ▼                    ▼
    [Metadata]      [Job Queue]     [HTTP API]          [Worker Processes]
                                                         (AMQP consumer)
       │
       │ daily 06:00 Moscow via CronJob
       ▼
    postgres-backup Job → pg_dump → S3 backups/postgres/<id>/
    (60-postgres-backup.yaml)
       │ creates manifest.json + list file
       │
       └── Restore Drill (70-restore-drill.yaml, operator-triggered)
           Downloads latest backup → ephemeral pg_restore → sanity checks
           (scratch postgres on emptyDir, isolated from live postgres-0)
           
       └── replays-fetcher CronJob (suspended by default)
           (50-replays-fetcher.yaml) fetches raw replays when enabled

┌──────────────────────────────────────────────────────────────────────────────┐
│                    Host Edge (nginx + systemd)                                │
│                    config/nginx/sites-available/stats-staging-solid-stats.conf│
├──────────────────────────────────────────────────────────────────────────────┤
│  TLS termination @ stats-staging.solid-stats.ru (certbot managed)             │
│  HTTP 301 redirect to HTTPS                                                   │
│  HTTPS proxy → upstream server 10.43.94.103:3000 (k3s server-2 ClusterIP)     │
│                                                                                │
│  # CUTOVER: marker — operator changes this line to flip production traffic     │
│             (Phase 11 lever, never CI-automated)                              │
│                                                                                │
│  systemd hook: config/systemd/certbot-deploy-hook.sh (nginx reload)           │
│  UFW rules: allow 443/tcp, 80/tcp (set up by bootstrap-edge.sh)               │
└──────────────────────────────────────────────────────────────────────────────┘
           │
           │ ingress traffic: HTTP ingest requests from external clients
           │
           ▼
        server-2 pod (inside k3s)
        ↓
        RabbitMQ publish jobs (parse.requested)
        ↓
        replay-parser-2 workers consume + write artifacts to S3
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| **PostgreSQL StatefulSet** | Durable metadata store: ingest state, parser jobs, statistics, requests, audit logs | `k8s/staging/10-postgres.yaml` |
| **RabbitMQ StatefulSet** | Job queue broker: server-2 publishes parse jobs; replay-parser-2 consumes | `k8s/staging/20-rabbitmq.yaml` |
| **server-2 Deployment** | HTTP API: ingest endpoint, statistics, admin endpoints; publishes jobs to RabbitMQ | `k8s/staging/30-server-2.yaml`, `35-server-2-deployment.yaml` |
| **server-2-config ConfigMap** | Runtime config for server-2: NODE_ENV, PORT, S3 endpoint, session settings, parser version | `k8s/staging/30-server-2.yaml` |
| **web Deployment** | Frontend serving (UI) — minimal config pointing to server-2 API backend | `k8s/staging/36-web.yaml`, `37-web-deployment.yaml` |
| **replay-parser-2 Deployment** | Worker pool (2 replicas): consumes job queue, parses replays, uploads artifacts to S3 | `k8s/staging/40-replay-parser-2.yaml` |
| **replays-fetcher CronJob** | Fetch raw replays (suspended until gate passes); pulls from source, stores to S3 | `k8s/staging/50-replays-fetcher.yaml` |
| **postgres-backup CronJob** | Daily backup (06:00 Moscow): pg_dump custom format → S3 backups prefix | `k8s/staging/60-postgres-backup.yaml` |
| **restore-drill Job** | Operator-triggered: validate backup; ephemeral pg_restore; sanity checks | `k8s/staging/restore-drill/70-restore-drill.yaml` |
| **s3-lifecycle-probe Job** | Operator-run once: verify Timeweb S3 lifecycle API support for future auto-expire | `k8s/staging/s3-lifecycle/80-s3-lifecycle-probe-job.yaml` |
| **ci-deployer ServiceAccount + RBAC** | Operator-applied once: GitHub Actions uses this to apply staging manifests over WireGuard | `k8s/staging/01-ci-rbac.yaml` |
| **Host nginx vhost** | TLS termination, HTTP redirect, proxy to k3s server-2; cutover lever (operator-edited) | `config/nginx/sites-available/stats-staging-solid-stats.conf` |
| **WireGuard tunnel gate** | CI pre-flight: tunnel handshake verification before `kubectl` runs | `scripts/wg-tunnel-up.sh` |
| **kubeconfig builder** | CI: authenticates as ci-deployer; verifies non-anonymous auth | `scripts/kubeconfig-setup.sh` |
| **Secret renderer** | CI: derives app-specific Secrets from GitHub env vars (DATABASE_URL, AMQP_URL, etc.) | `scripts/render-staging-secrets.py` |
| **Manifest validator** | CI + local: checks expected manifest files, Secret structure, image SHAs, S3 lifecycle rules | `scripts/validate-staging.py` |
| **Manual backup trigger** | Operator tool: creates one-off backup Job, waits for completion, prints manifest | `scripts/backup-postgres-now.sh` |
| **Restore drill runner** | Operator tool: applies restore-drill Job, waits, prints evidence line, cleans up | `scripts/restore-drill.sh` |
| **Edge bootstrap/teardown** | Operator tools: idempotent adopt-reconcile for vhost, certbot, UFW; reversible for cutover test | `scripts/bootstrap-edge.sh`, `scripts/teardown-edge.sh` |
| **Cutover script** | Operator-only: flip nginx upstream line + reload; fail-closed gates (never CI) | `scripts/cutover.sh` |

## Pattern Overview

**Overall:** kubectl-native deployment with fail-closed CI gates, WireGuard access control, explicit ServiceAccounts (no default), and operator-controlled production traffic switch.

**Key Characteristics:**
- **Infrastructure as Code:** All runtime wiring in numbered-prefix YAML manifests; app repos build images; infra repo pins and deploys.
- **Fail-closed CI gates:** WireGuard handshake must complete before any kubectl runs; kubeconfig auth must be non-anonymous; dry-run before apply.
- **Namespace isolation:** single `solid-stats-staging` namespace; 00-namespace.yaml applied once by operator, never re-applied by CI.
- **Operator-controlled cutover:** Production traffic flip via single nginx `server` line edit; never CI-automated; reversible within minutes.
- **Backup before cutover:** PostgreSQL backup CronJob daily; restore-drill validates in isolation; both gates must pass before full-run.
- **Secret hygiene:** GitHub environment secrets → CI Secret renderer → Kubernetes Secrets; no secret values in git or planning docs.
- **Explicit RBAC:** ci-deployer Role grants only needed verbs (apply, patch, create, get, list); no admin or cluster-scoped access.

## Layers

**CI/CD Layer (GitHub Actions):**
- Purpose: Validate, dry-run, deploy staging manifests; gate on WireGuard handshake and authenticated kubeconfig.
- Location: `.github/workflows/deploy-staging.yml`, `scripts/wg-tunnel-up.sh`, `scripts/kubeconfig-setup.sh`, `scripts/render-staging-secrets.py`, `scripts/validate-staging.py`
- Contains: Workflow definition, shell gates, Python validators, secret derivation.
- Depends on: GitHub environment secrets (WG keys, K8S token/cert, app credentials), repository checkout.
- Used by: Master pushes trigger deploy; PRs run validate + dry-run.

**Infrastructure Manifest Layer (k8s/staging/):**
- Purpose: Declare all Kubernetes resources and their runtime parameters.
- Location: `k8s/staging/*.yaml` (numeric prefix ordering), `k8s/staging/restore-drill/`, `k8s/staging/s3-lifecycle/`
- Contains: Namespace, RBAC, StatefulSets (postgres, rabbitmq), Deployments (server-2, replay-parser-2, web), CronJobs (backup, fetcher), Services, ConfigMaps, ServiceAccounts, SecurityContexts, probes, resource limits.
- Depends on: Secrets created by CI (rendered from GitHub env vars).
- Used by: `kubectl apply` in CI/CD; operator restore-drill and probe scripts.

**Operational Script Layer (scripts/):**
- Purpose: Tunnel setup, kubeconfig building, secret rendering, validation, backup/restore, edge bootstrap, cutover.
- Location: `scripts/*.sh`, `scripts/*.py`
- Contains: Bash gates (WireGuard, kubeconfig), Python validators (manifests, S3 lifecycle), secret renderers, manual backup triggers, drill runners.
- Depends on: kubectl, aws-cli, pg_dump, pg_restore, nginx, certbot (for edge ops).
- Used by: GitHub Actions workflow steps, operator runbooks.

**Host Edge Layer (config/):**
- Purpose: TLS termination, HTTP proxy, certificate lifecycle, firewall, systemd hooks.
- Location: `config/nginx/sites-available/`, `config/systemd/`
- Contains: nginx vhost config (cutover lever), certbot deploy hook, systemd service drop-ins, UFW rules (bootstrap script).
- Depends on: certbot, nginx, UFW, systemd.
- Used by: Operator bootstrap-edge.sh; traffic ingress to k3s.

## Data Flow

### Primary Request Path (HTTP Ingest → Server-2 → RabbitMQ → Parser Workers → S3)

1. **Client HTTP request** → Host nginx (TLS termination) `config/nginx/sites-available/stats-staging-solid-stats.conf` line marked `# CUTOVER:`
2. **nginx proxy pass** → k3s `server-2` Service ClusterIP:3000 (upstream target)
3. **server-2 Deployment pod** (`k8s/staging/35-server-2-deployment.yaml` line 50, image SHA pinned)
   - Receives ingest request
   - Writes to `postgres:5432` (connected via env var DATABASE_URL from Secret)
   - Publishes job to `rabbitmq:5672` (RABBITMQ_URL)
   - Response returned to client
4. **replay-parser-2 Deployment pods** (2 replicas, `k8s/staging/40-replay-parser-2.yaml`)
   - Consume from RabbitMQ queue `server2.parse.requested`
   - Fetch replay artifact from S3 (`S3_ENDPOINT=https://s3.twcstorage.ru`)
   - Parse and upload parsed artifacts to S3 prefix `artifacts/v3/`
   - Publish result to exchange `solid_stats.parser` routing key `parse.completed`
5. **server-2 processes result** (subscribes to completion events)
6. **Final statistics** stored in PostgreSQL (`postgres` Service, 5432)

### Backup & Restore Flow (Scheduled + On-Demand)

1. **postgres-backup CronJob** (daily 06:00 Moscow, `k8s/staging/60-postgres-backup.yaml`)
   - Runs in k3s pod
   - Connects to `postgres:5432` (POSTGRES_HOST env var + Secret POSTGRES_PASSWORD)
   - `pg_dump --format=custom` → `/tmp/solid_stats.dump`
   - `pg_restore --list` → `/tmp/solid_stats.dump.list`
   - Uploads to S3:
     - `s3://<bucket>/backups/postgres/<backup-id>/solid_stats.dump`
     - `s3://<bucket>/backups/postgres/<backup-id>/solid_stats.dump.list`
     - `s3://<bucket>/backups/postgres/<backup-id>/manifest.json` (metadata)

2. **Manual backup trigger** (`scripts/backup-postgres-now.sh`)
   - Operator runs from workstation with kubectl access (WireGuard tunnel up)
   - Creates one-off Job from cronjob/postgres-backup
   - Waits for completion, prints `backup_id=` and `dump_object=`
   - Operator updates `docs/backup-gate.md` with result

3. **Restore drill** (operator-triggered, `scripts/restore-drill.sh`)
   - Applies `k8s/staging/restore-drill/70-restore-drill.yaml` (never auto-scheduled)
   - Job pod:
     - Fetches latest S3 backup via aws-cli (read-only credentials)
     - Runs ephemeral PostgreSQL (`postgres:17-alpine` on emptyDir, UID 70)
     - `pg_restore` → sanity checks (table count ≥ 5, rows > 0, no errors)
     - Prints `DRILL_RESULT=PASS` or `FAIL` + evidence line
   - Script extracts evidence, prints to stdout, deletes Job

### State Management

- **Configuration state:** ConfigMaps (`server-2-config`, `web-config`) store non-secret runtime parameters; changed via Git PR + CI deploy.
- **Secrets state:** Kubernetes Secrets (postgres-auth, rabbitmq-auth, app runtime Secrets) rendered by CI from GitHub environment variables; never stored in git.
- **Persistent data:** PostgreSQL PVC (`postgres-data`, 20Gi) and RabbitMQ PVC (`rabbitmq-data`, 5Gi) survive pod restarts; backed up daily to S3.
- **Backup artifacts:** S3 under `backups/postgres/` prefix; latest accessed by restore-drill for validation.
- **Parsed artifacts:** S3 under `artifacts/v3/` prefix; written by replay-parser-2 workers.

## Key Abstractions

**ServiceAccount + RBAC:**
- Purpose: Explicit security identity for each workload (postgres, rabbitmq, server-2, replay-parser-2, ci-deployer, restore-drill, etc.); prevents accidental use of default ServiceAccount.
- Examples: `k8s/staging/10-postgres.yaml` (postgres SA, automountServiceAccountToken: false), `k8s/staging/01-ci-rbac.yaml` (ci-deployer Role with scoped verbs).
- Pattern: Named SA per workload; explicit Role/RoleBinding; `automountServiceAccountToken: false` unless workload needs in-cluster API access.

**Secret Derivation:**
- Purpose: Map GitHub environment secrets → Kubernetes Secrets with app-specific keys (DATABASE_URL, AMQP_URL, S3 credentials).
- Examples: `scripts/render-staging-secrets.py` constructs `server-2-runtime` (DATABASE_URL, RABBITMQ_URL, S3_BUCKET, etc.) from POSTGRES_PASSWORD, RABBITMQ_PASSWORD, S3_ACCESS_KEY_ID, etc.
- Pattern: Single source of truth (GitHub env vars); derived Secrets injected via `envFrom.secretRef` in pod specs.

**WireGuard Access Control:**
- Purpose: Seal k3s API behind a closed tunnel; CI must prove handshake before kubectl allowed.
- Examples: `scripts/wg-tunnel-up.sh` (establishes tunnel, waits for handshake, probes API port), `.github/workflows/deploy-staging.yml` (runs tunnel-up before kubeconfig-setup).
- Pattern: Fail-closed gate; timeout on handshake; TCP probe as final verification.

**Operator-Controlled Cutover:**
- Purpose: Single-lever traffic flip via nginx upstream edit; never CI-automated; reversible.
- Examples: `config/nginx/sites-available/stats-staging-solid-stats.conf` line 9 marked `# CUTOVER:`, `scripts/cutover.sh` (operator-only, enforces backup + diff gates).
- Pattern: Config file with marker comment; bash script validates gates before proceeding; dry-run mode available for rehearsal.

## Entry Points

**Automated (CI-triggered):**
- **`.github/workflows/deploy-staging.yml`:** Runs on push to master or workflow_dispatch; validates, dry-runs, applies staging manifests.
  - Triggers: `validate` job (checks expected files, runs Python validator), `dry-run` job (server-side --dry-run via kubectl), `deploy` job (live apply to k3s).
  - Uses: WireGuard tunnel, kubeconfig, Secret renderer, manifest apply.

**Manual Operator-Run:**
- **`scripts/backup-postgres-now.sh`:** Creates one-off backup Job, waits, prints evidence.
  - Requires: `K8S_NAMESPACE` env var, kubectl access (WireGuard tunnel must be up).
  - Outputs: backup_id, dump_object, dump_size_bytes to stdout; operator records in `docs/backup-gate.md`.

- **`scripts/restore-drill.sh`:** Applies restore-drill Job, waits, prints evidence, cleans up.
  - Requires: `K8S_NAMESPACE` env var, kubectl access.
  - Outputs: DRILL_RESULT=PASS/FAIL, table count, row count, duration; gates full-run work.

- **`scripts/bootstrap-edge.sh`:** Idempotent adopt-reconcile for host nginx, certbot, UFW, systemd hooks.
  - Requires: root/sudo, `ADMIN_EMAIL` (Let's Encrypt), optional `SKIP_UFW=1`.
  - Outputs: vhost installed, certbot configured, UFW rules set, `.bak` backup created.

- **`scripts/teardown-edge.sh`:** Reverse bootstrap-edge: restore `.bak` vhost, remove certbot rules, remove UFW rules.
  - Requires: root/sudo.
  - Outputs: original vhost restored; safe to re-bootstrap.

- **`scripts/cutover.sh`:** Flip production traffic (nginx upstream line edit + reload).
  - Requires: root/sudo on edge VPS, `NEW_UPSTREAM` env var (k3s ClusterIP:port).
  - Gates: Enforces backup age < 24h, diff-readiness gate (strict_failures: 0) in `docs/diff-readiness.md`.
  - Outputs: nginx reloaded; traffic now to new runtime; reversible via re-run.

**Documentation Gateways:**
- **`README.md`:** Overview, deploy model, validation command.
- **`docs/staging.md`:** Scope, hardening exceptions, required GitHub secrets, handoff matrix, deploy/verify.
- **`docs/backup-restore.md`:** Backup schedule, manual trigger, validate backup object, restore drill runbook.
- **`docs/cutover.md`:** Pre-flight gates (backup, diff, edge reversibility, smoke), policy, timing.
- **`docs/edge-bootstrap.md`:** Host nginx, certbot, UFW, operator runbook for bootstrap/teardown.
- **`AGENTS.md`:** Project constraints, conventions, architecture summary, skills.

## Architectural Constraints

- **Threading:** k3s workloads are multi-threaded (Node.js server-2, replay-parser-2; Python postgres-backup, validate scripts). RabbitMQ and PostgreSQL handle multiple concurrent connections per manifest. No documented global state or singleton pattern; each pod is stateless except for mounted volumes (postgres-data, rabbitmq-data).
- **Global state:** Persistent state lives in PostgreSQL and RabbitMQ; no shared singletons in application code (owned by app repos). S3 is external; backup manifests are append-only.
- **Circular imports:** Not applicable (Kubernetes manifests are declarative, scripts are procedural bash/python).
- **ServiceAccount access:** Only ci-deployer (for GitHub Actions), restore-drill (for backup validation), and postgres-backup (for backup export) need in-cluster credentials. postgres, rabbitmq, server-2, replay-parser-2 have SA tokens disabled (`automountServiceAccountToken: false`) since they do not need Kubernetes API access.
- **Network isolation:** Phase 1 documents NetworkPolicy as an explicit exception (`docs/staging.md`); no NetworkPolicy manifests yet. All pods in same namespace can reach each other by DNS (k3s default CNI).
- **Image versions:** Application images (server-2, replay-parser-2, replays-fetcher, web) pinned to immutable SHAs in Deployment specs, never `latest`. Infra-owned images (postgres:17-alpine, rabbitmq:4-management, busybox:1.37, aws-cli in restore-drill) pinned to release tags.
- **Storage:** PostgreSQL and RabbitMQ each have a single 1-replica StatefulSet with PVC; no multi-zone replication in v1. Backup exports to Timeweb S3 daily; no S3 auto-expire yet (s3-lifecycle probe is experimental).
- **Secrets:** GitHub environment secrets (WG keys, K8S token, app credentials) are rendered into Kubernetes Secrets by CI and stored only in live cluster; never committed to git. ci-deployer ServiceAccount token is generated by cluster control-plane and stored as a Secret (not in git).
- **Operator gates:** Production traffic cutover requires operator approval and manual script execution; CI never runs cutover. Full-run work blocked until backup gate and diff gate pass.

## Anti-Patterns

### Applying 00-namespace.yaml and 01-ci-rbac.yaml from CI

**What happens:** If CI's kubectl apply includes namespace and RBAC manifests on every deploy, it risks overwriting operator-managed RBAC or re-creating the namespace unexpectedly.
**Why it's wrong:** 00-namespace.yaml is applied once at cluster setup and never re-applied; 01-ci-rbac.yaml is operator-bootstrapped once and must not be overwritten by CI (it defines the ci-deployer identity CI uses). Reapplying them wastes compute and risks race conditions.
**Do this instead:** CI's apply glob excludes both files: `.github/workflows/deploy-staging.yml` line 72 uses `! -name '00-namespace.yaml' ! -name '01-ci-rbac.yaml'`. The `scripts/validate-staging.py` checks that both files exist but warns if they are placed at depth > 1 (restore-drill and s3-lifecycle subdirectories are correct; any new operator-only manifests should follow the same pattern).

### Using default ServiceAccount or automounting tokens unnecessarily

**What happens:** Pods inherit the default ServiceAccount; if a pod doesn't need Kubernetes API access, it still gets the control-plane token injected and can be exploited to access the API.
**Why it's wrong:** Least-privilege principle — unnecessary API access increases attack surface.
**Do this instead:** Every pod spec sets `serviceAccountName: <explicit-name>` (e.g., `serviceAccountName: postgres`) and `automountServiceAccountToken: false` unless the workload genuinely needs cluster API (e.g., ci-deployer does; postgres does not). All manifests follow this (`k8s/staging/10-postgres.yaml` line 46 + 47, `k8s/staging/35-server-2-deployment.yaml` line 29 + 30).

### Storing secrets in git or planning documents

**What happens:** API keys, credentials, database passwords end up in version control or planning artifacts; anyone with repo access gets production secrets.
**Why it's wrong:** Violates `docs/staging.md` constraint: "Secrets come from GitHub environment secrets and live Kubernetes Secrets — no secret values belong in git or planning docs."
**Do this instead:** All secrets originate from GitHub environment variables (WG_PRIVATE_KEY, K8S_TOKEN, POSTGRES_PASSWORD, S3_ACCESS_KEY_ID, etc.). CI's `scripts/render-staging-secrets.py` derives Kubernetes Secrets and applies them; values exist only in live cluster. Planning docs reference secret names, never values. All scripts check for missing required env vars and exit 64 (configuration error) if unmet.

### Applying restore-drill or s3-lifecycle manifests automatically

**What happens:** If CI's kubectl apply glob matches restore-drill/70-restore-drill.yaml or s3-lifecycle/80-s3-lifecycle-probe-job.yaml, Jobs run every deploy, consuming time and resources unnecessarily and validating old backups during regular deploy.
**Why it's wrong:** These manifests are operator-triggered exceptions; they should never auto-schedule. The flow is: operator decides to run drill → applies manifest manually → monitors Job.
**Do this instead:** Both manifests live in subdirectories (`k8s/staging/restore-drill/`, `k8s/staging/s3-lifecycle/`). CI's apply glob uses `find k8s/staging -maxdepth 1 -name '*.yaml'` (stops at depth 1). `scripts/validate-staging.py` enforces this by checking for `yaml` files at depth > 1 and warning/failing if found in the main directory.

### Automating production traffic cutover in CI

**What happens:** A CI job flips the nginx upstream line or uses a LoadBalancer to move traffic; the cutover is not reversible within minutes if issues arise.
**Why it's wrong:** `docs/cutover.md` policy: "The live traffic flip is OPERATOR-gated. `scripts/cutover.sh` is never invoked from CI or automation; it is an operator tool only." CI-driven cutover is not auditable or human-reviewable.
**Do this instead:** `scripts/cutover.sh` is a standalone operator tool. It enforces gates programmatically (backup age, diff gate) and fails closed if gates are unmet; operator reads output, reviews diff evidence, and runs the script manually. The flip is reversible (line edit + nginx reload); if issues arise, operator runs cutover.sh again with the old upstream address.

### Treating new parser output as equal to legacy (value-equality gates)

**What happens:** Diff readiness gate checks if new parser statistics equal legacy statistics; any deviation blocks cutover.
**Why it's wrong:** `legacy-vs-new-parser-non-identical` (memory note): The new parser (`server-2` / `replay-parser-2`) is a deliberate rewrite; computed stat VALUES diverge from legacy BY DESIGN. A strict equality gate is incorrect.
**Do this instead:** `docs/diff-readiness.md` and `docs/cutover.md` define the gate as coverage/integrity, not equality. The gate checks for missing players, missing matches, parser errors, and aggregate totals OUTSIDE declared tolerance. Intended value differences are allowlisted and human-reviewed. The gate passes if `strict_failures: 0` (no missing/broken data) and the operator has reviewed the full diff output.

## Error Handling

**Strategy:** Fail-closed CI gates + explicit operator validation before cutover.

**Patterns:**
- **CI validation failures:** `scripts/validate-staging.py` checks manifest structure, Secret keys, image SHAs, S3 lifecycle rules. If any check fails, exit 1; workflow stops.
- **WireGuard handshake timeout:** `scripts/wg-tunnel-up.sh` waits up to 10s for handshake; if timeout, exit 1; no kubectl runs.
- **kubeconfig auth failure:** `scripts/kubeconfig-setup.sh` runs `kubectl auth whoami`; if result is `system:anonymous`, exit 1; deployment stops.
- **kubectl dry-run failure:** `.github/workflows/deploy-staging.yml` runs `--dry-run=server` before live apply; if dry-run fails, `deploy` job is blocked by `needs: [dry-run]`.
- **Backup Job failure:** `scripts/backup-postgres-now.sh` polls `kubectl wait --for=condition=complete`; if Job fails or timeout, script exits 1; operator reviews logs and retries.
- **Restore drill failure:** If `DRILL_RESULT=FAIL` (table count < 5, rows = 0, errors), `scripts/restore-drill.sh` exits 1; operator reviews logs, fixes backup or data, and re-runs.
- **Cutover gates enforcement:** `scripts/cutover.sh` checks backup age and diff-readiness gate before proceeding; if unmet, exit 1; operator updates gates and retries.
- **Live pod failures:** Liveness/readiness probes detect hung processes; failed pods are evicted and restarted by k3s. StatefulSet postgres is single-replica; if pod fails, manual intervention required.

## Cross-Cutting Concerns

**Logging:** 
- Kubernetes pod logs accessed via `kubectl logs` (queried in backup-postgres-now.sh, restore-drill.sh, cutover.sh).
- server-2 and replay-parser-2 log to stdout/stderr (captured by container runtime); log level set by ConfigMap/env var (LOG_LEVEL: info for server-2).
- Backup and restore jobs log shell output (set -x) to pod logs; evidence lines parsed by operator scripts.

**Validation:**
- **Manifest structure:** `scripts/validate-staging.py` parses YAML, checks required resource types, Secret keys, Deployment image SHAs, CronJob schedule syntax.
- **Image SHAs:** All app images pinned to SHA in Deployment specs; validator checks that `latest` tag is never used.
- **Secret source of truth:** `scripts/render-staging-secrets.py` validates that all required GitHub env vars are present; missing vars cause exit 1.
- **Dry-run gate:** CI runs `kubectl apply --dry-run=server` to catch manifest errors before live apply.
- **Backup validation:** Operator downloads backup object, runs `pg_restore --list` to verify dump format; operator records result in `docs/backup-gate.md`.
- **Restore drill:** Validates table count, row count, error absence; produces `DRILL_RESULT=PASS/FAIL` evidence line.

**Authentication & Authorization:**
- **WireGuard tunnel:** CI proves identity via WireGuard private key (secret stored in GitHub); VPS WireGuard endpoint verifies peer public key before allowing traffic.
- **Kubernetes authentication:** ci-deployer ServiceAccount uses token-based auth (token from Secret, generated by cluster control-plane); `kubectl auth whoami` confirms non-anonymous identity.
- **Kubernetes authorization:** ci-deployer Role is namespace-scoped; grants only verbs needed to apply/patch Deployments, StatefulSets, CronJobs, Services, ConfigMaps, Secrets, ServiceAccounts (no admin, no cluster-scoped).
- **Operator authentication:** Operator has shell access to edge VPS (SSH key or bastion); runs scripts as root/sudo for nginx/certbot/UFW operations.
- **S3 credentials:** App-specific read/write credentials (S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY) passed via Kubernetes Secrets; restore-drill uses read-only credentials.

---

*Architecture analysis: 2026-06-13*
