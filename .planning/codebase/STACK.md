# Technology Stack

**Analysis Date:** 2026-06-13

## Languages

**Primary:**
- Bash — `scripts/*.sh` entry points for deploy gate, WireGuard tunnel, kubeconfig setup, backup, restore, edge bootstrap, and cutover
- Python 3 — stdlib only for manifest validation and secret rendering (`scripts/validate-staging.py`, `scripts/render-staging-secrets.py`, `scripts/validate-s3-lifecycle.py`, `scripts/validate-edge.py`)

**No application source code:** This is an infrastructure-only repository; application code lives in separate repositories (solid-stats/server-2, solid-stats/replay-parser-2, solid-stats/replays-fetcher, solid-stats/web).

## Runtime

**Kubernetes Cluster:**
- k3s on the Timeweb staging VPS
- Namespace: `solid-stats-staging` (defined in `k8s/staging/00-namespace.yaml`)
- API access via WireGuard tunnel (10.8.0.1:6443)

**Container Images (pinned by SHA):**
- `postgres:17-alpine` — PostgreSQL 17 in `k8s/staging/10-postgres.yaml` (StatefulSet)
- `rabbitmq:4-management` — RabbitMQ 4 with management plugin in `k8s/staging/20-rabbitmq.yaml` (StatefulSet)
- `busybox:1.37` — Init and utility containers for postgres wait-for and RabbitMQ cookie repair
- GHCR application images (pinned to commit SHAs, never `latest`):
  - `ghcr.io/solid-stats/server-2:3866f6b...` — in `k8s/staging/35-server-2-deployment.yaml`
  - `ghcr.io/solid-stats/replay-parser-2:5e09d33...` — in `k8s/staging/40-replay-parser-2.yaml`
  - `ghcr.io/solid-stats/replays-fetcher:8395fbc...` — in `k8s/staging/50-replays-fetcher.yaml`
  - `ghcr.io/solid-stats/web:...` — in `k8s/staging/37-web-deployment.yaml` (v2.0 added)

**API Groups Used:**
- `apps/v1` — Deployment, StatefulSet
- `batch/v1` — CronJob, Job
- `v1` — Service, ServiceAccount, Secret, ConfigMap, Namespace, PersistentVolumeClaim

## Storage & Persistence

**In-Cluster Databases:**
- PostgreSQL 17 StatefulSet with PVC `postgres-data` (`20Gi` request) in `k8s/staging/10-postgres.yaml`
  - Database: `solid_stats`
  - Port: 5432
  - Health check: `pg_isready` probes
- RabbitMQ 4 StatefulSet with PVC `rabbitmq-data` (`5Gi` request) in `k8s/staging/20-rabbitmq.yaml`
  - AMQP port: 5672
  - Management UI: 15672
  - Health check: `rabbitmq-diagnostics ping` probes
  - Init container repairs `.erlang.cookie` ownership on existing PVC

**External Object Storage:**
- Timeweb S3-compatible storage (`https://s3.twcstorage.ru`, region `ru-1`)
- Path-style access (not virtual-hosted): `aws configure set default.s3.addressing_style path`
- Prefixes managed in this repo:
  - `backups/postgres/` — PostgreSQL backups (with 30-day lifecycle rule in `config/s3/backups-lifecycle.json`)
  - `artifacts/v3` — Replay parser artifacts
  - Raw replay files (from source external to this cluster)
- Lifecycle policy: 30-day retention for backups, abort incomplete multipart after 7 days

## Build & Deployment Tools

**CI/CD:**
- GitHub Actions (`.github/workflows/deploy-staging.yml`)
  - Triggers: PR validation, push to master, workflow_dispatch
  - Jobs: validate (manifest/script checks), dry-run (server-side), deploy (live apply + rollout verify)

**Infrastructure Access:**
- **WireGuard tunnel** (CI → k3s API) — configured in `scripts/wg-tunnel-up.sh`
  - Local IP: 10.8.0.3/32 (CI runner)
  - API server: 10.8.0.1:6443 (k3s on VPS)
  - Secrets from GitHub environment: `WG_PRIVATE_KEY`, `WG_PEER_PUBLIC_KEY`, `WG_ENDPOINT`
  - Handshake timeout: 10 seconds (fail-closed gate)
  - Private key passed via /dev/stdin (never written to disk)

**kubectl Configuration:**
- Built dynamically in CI via `scripts/kubeconfig-setup.sh`
- Uses `ci-deployer` ServiceAccount token (`K8S_TOKEN`) and CA cert (`K8S_CA_CERT`)
- Server-side dry-run validation before live apply
- Verifies kubectl auth whoami returns non-anonymous identity (fail-closed)

**Container Registry:**
- GitHub Container Registry (GHCR)
- Pull secret configured as `ghcr-pull` in `k8s/staging/` (rendered from `GHCR_USERNAME` + `GHCR_TOKEN`)
- `imagePullPolicy: IfNotPresent` for all images (assume local cache after bootstrap)

## Edge/Host Tools

**nginx:**
- Reverse proxy on VPS host (`config/nginx/sites-available/stats-staging-solid-stats.conf`)
- TLS termination for `stats-staging.solid-stats.ru`
- Upstream to k3s `server-2` ClusterIP (`10.43.94.103:3000`)
- HTTP → HTTPS redirect; ACME challenge webroot at `/var/www/html`
- Managed/bootstrapped by `scripts/bootstrap-edge.sh` (operator-run, not CI)
- Cutover lever at `# CUTOVER:` marker for Phase 11 production switch

**certbot:**
- Let's Encrypt certificate renewal
- Webroot flow on `/var/www/html`
- Configured/bootstrapped by `scripts/bootstrap-edge.sh`
- Admin email: from `ADMIN_EMAIL` env var during bootstrap

**ufw (firewall):**
- Managed by `scripts/bootstrap-edge.sh` for port rules on VPS host
- Optional: `SKIP_UFW=1` to skip during bootstrap
- Rules for TCP 80, 443 (nginx) and internal k3s access

**aws-cli:**
- Used in `postgres-backup` CronJob container for S3 operations
- Installed at job runtime: `apk add --no-cache aws-cli`
- S3 addressing style: path (set via `aws configure set default.s3.addressing_style path`)
- Also used in restore drill and S3 lifecycle validation scripts

**ssh:**
- Used by restore/backup scripts for pod log retrieval and edge operations
- VPS access for manual operations (certificate renewal, firewall rules)

## Configuration Management

**Static Configuration:**
- Kubernetes manifests: `k8s/staging/*.yaml` (numeric prefixes for apply order)
- nginx vhost config: `config/nginx/sites-available/stats-staging-solid-stats.conf`
- S3 lifecycle rules: `config/s3/backups-lifecycle.json` (JSON format)

**Secrets Rendering:**
- `scripts/render-staging-secrets.py` — Python 3 script that reads GitHub environment secrets and outputs Kubernetes Secrets YAML
  - Input: `GHCR_USERNAME`, `GHCR_TOKEN`, `POSTGRES_PASSWORD`, `RABBITMQ_PASSWORD`, `S3_*`, `REPLAYS_FETCHER_*`, `SERVER2_*`
  - Output: 6 Kubernetes Secrets + server-2-config ConfigMap
  - Exit code 64 on missing required vars
  - Uses only stdlib: json, os, sys, base64, urllib.parse

**Validation Scripts (CI + Local):**
- `scripts/validate-staging.py` — Checks expected manifests exist, secrets structure, workloads config, app image SHAs
- `scripts/validate-s3-lifecycle.py` — Validates S3 lifecycle rules (Days >= 30 floor, AbortIncompleteMultipartUpload)
- `scripts/validate-edge.py` — Validates edge bootstrap state (nginx, certbot, ufw)
- Run locally: `python3 scripts/validate-staging.py`

## No Package Manager

This repository owns no application source code. No `package.json`, `requirements.txt`, `Cargo.toml`, `go.mod`, or `pyproject.toml` exist. Scripts use only bash stdlib and Python 3 stdlib (`json`, `os`, `sys`, `pathlib`, `subprocess`, `tempfile`, `base64`, `urllib.parse`, `importlib`, `py_compile`, `shutil`).

## Runtime Wiring

**In-Cluster Service Discovery:**
- `postgres` Service (ClusterIP, port 5432)
- `rabbitmq` Service (ClusterIP, AMQP 5672 + management 15672)
- `server-2` Service (ClusterIP, port 3000)
- `web` Service (ClusterIP, port 3001) — added in v2.0
- No default ServiceAccounts used; all workloads specify explicit `serviceAccountName`
- Service discovery via DNS within namespace (e.g., `postgres.solid-stats-staging.svc.cluster.local`)

**Readiness & Liveness Probes:**
- PostgreSQL: `pg_isready` exec probes
- RabbitMQ: `rabbitmq-diagnostics ping` exec probes
- server-2: HTTP GET `/ready` (readiness), `/live` (liveness) on port 3000
- replay-parser-2: HTTP GET `/readyz` (readiness), `/livez` (liveness) on port 8080
- web: HTTP GET (if applicable)

**Resource Requests & Limits:**
- PostgreSQL: 250m CPU / 512Mi memory request; 1 CPU / 2Gi limit
- RabbitMQ: 250m CPU / 512Mi memory request; 1 CPU / 2Gi limit
- server-2: 100m CPU / 256Mi memory request; 1 CPU / 1Gi limit
- replay-parser-2: 100m CPU / 256Mi memory request; 1 CPU / 1Gi limit
- replays-fetcher: 100m CPU / 256Mi memory request; 1 CPU / 1Gi limit

**Security Context:**
- server-2, replay-parser-2, replays-fetcher: `allowPrivilegeEscalation: false`, `capabilities: drop: [ALL]`
- PostgreSQL, RabbitMQ: Vendor images with exceptions documented in `docs/staging.md`

---

*Stack analysis: 2026-06-13*
