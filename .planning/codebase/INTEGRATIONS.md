# External Integrations

**Analysis Date:** 2026-06-13

## APIs & External Services

**GitHub Container Registry (GHCR):**
- Image source for all application workloads
- Files: `k8s/staging/35-server-2-deployment.yaml`, `k8s/staging/40-replay-parser-2.yaml`, `k8s/staging/50-replays-fetcher.yaml`, `k8s/staging/37-web-deployment.yaml`
- Pull secret: `ghcr-pull` (kubernetes.io/dockerconfigjson type)
- Auth via GitHub environment secrets: `GHCR_USERNAME`, `GHCR_TOKEN`
- Credentials rendered by: `scripts/render-staging-secrets.py` (lines 57–68)
- `imagePullPolicy: IfNotPresent` to use cached images after bootstrap

**GitHub Actions:**
- CI/CD orchestration in `.github/workflows/deploy-staging.yml`
- Triggers: pull_request, push to master, workflow_dispatch
- Concurrency: `infrastructure-staging-deploy` group with `cancel-in-progress: false`
- Jobs: validate, dry-run, deploy (sequential, with dependencies)
- Environment: `staging` (GitHub environment with protected secrets)
- Environment secrets:
  - **WireGuard:** `WG_PRIVATE_KEY`, `WG_PEER_PUBLIC_KEY`, `WG_ENDPOINT`
  - **Kubernetes:** `K8S_TOKEN`, `K8S_CA_CERT`
  - **Container Registry:** `GHCR_USERNAME`, `GHCR_TOKEN`
  - **Databases:** `POSTGRES_PASSWORD`, `RABBITMQ_PASSWORD`
  - **S3:** `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`
  - **Replays Source:** `REPLAYS_FETCHER_REPLAY_SOURCE_URL`, `REPLAYS_FETCHER_REPLAY_SOURCE_TRANSPORT`, `REPLAYS_FETCHER_REPLAY_SOURCE_SSH_HOST`, `REPLAYS_FETCHER_REPLAY_SOURCE_SSH_COMMAND` (optional)
  - **App Bootstrap:** `SERVER2_BOOTSTRAP_ADMIN_STEAM_ID` (optional)

## Data Storage

**External S3-Compatible Storage (Timeweb):**
- Provider: Timeweb object storage
- Endpoint: `https://s3.twcstorage.ru`
- Region: `ru-1`
- Bucket: stored in `S3_BUCKET` environment secret
- Credentials: `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` (rendered into workload secrets by `scripts/render-staging-secrets.py`, lines 41–43)
- Access style: path-style (not virtual-hosted); `aws configure set default.s3.addressing_style path`
- Key prefixes:
  - `backups/postgres/` — PostgreSQL database backups (daily at 06:00 UTC+3 via CronJob)
  - `artifacts/v3` — Replay parser analysis artifacts (in `k8s/staging/40-replay-parser-2.yaml`)
  - Raw replay files — from external source (configured via `REPLAYS_FETCHER_REPLAY_SOURCE_*`)

**S3 Lifecycle Policy:**
- File: `config/s3/backups-lifecycle.json`
- Applied by: `scripts/apply-s3-lifecycle.sh` (operator-run tool)
- Rules:
  - Expire `backups/postgres/` after 30 days
  - Abort incomplete multipart uploads after 7 days
- Validation: `scripts/validate-s3-lifecycle.py` enforces minimum 30-day retention for compliance

**In-Cluster PostgreSQL:**
- Service: `postgres` (ClusterIP, port 5432)
- Database: `solid_stats`
- User: `solid` (password from `POSTGRES_PASSWORD` secret key)
- Password secret: `postgres-auth` (Opaque type, defined in `scripts/render-staging-secrets.py`, lines 39–40)
- StatefulSet: `postgres` in `k8s/staging/10-postgres.yaml`
- Client: standard postgres protocol, `pg_dump` / `pg_restore` for backups
- Connection string: `postgres://solid:<password>@postgres:5432/solid_stats` (rendered by `scripts/render-staging-secrets.py`, line 70)
- Consumers: `server-2`, `replays-fetcher`, `postgres-backup` (CronJob)
- Data directory: `/var/lib/postgresql/data` (mounted from `postgres-data` PVC)

**In-Cluster RabbitMQ:**
- Service: `rabbitmq` (ClusterIP, AMQP 5672, management 15672)
- User: `solid` (password from `RABBITMQ_PASSWORD` secret key)
- Password secret: `rabbitmq-auth` (Opaque type)
- StatefulSet: `rabbitmq` in `k8s/staging/20-rabbitmq.yaml`
- AMQP URL: `amqp://solid:<password>@rabbitmq:5672` (rendered by `scripts/render-staging-secrets.py`, line 71)
- Data directory: `/var/lib/rabbitmq` (mounted from `rabbitmq-data` PVC)
- Message contracts (in `k8s/staging/40-replay-parser-2.yaml`, env vars):
  - Job queue: `server2.parse.requested`
  - Result exchange: `solid_stats.parser`
  - Completed routing key: `parse.completed`
  - Failed routing key: `parse.failed`
- Consumers: `server-2` (producer), `replay-parser-2` (consumer)

## Kubernetes & Control Plane

**k3s API Server (via WireGuard):**
- Endpoint: 10.8.0.1:6443 (on-cluster IP, routable via WireGuard VPN only)
- Access: CI runners establish WireGuard tunnel, then kubectl over TLS
- Auth: `ci-deployer` ServiceAccount with token + kubeconfig
- Kubeconfig build: `scripts/kubeconfig-setup.sh`
  - Token: from environment secret `K8S_TOKEN`
  - CA cert: from environment secret `K8S_CA_CERT` (PEM format, embedded in kubeconfig)
  - Cluster: `k3s-staging`, User: `ci-deployer`, Context: `ci-k3s-staging`
  - Verification: `kubectl auth whoami` must return non-anonymous identity (fail-closed)
- RBAC: `k8s/staging/01-ci-rbac.yaml` defines `ci-deployer` Role and RoleBinding (cluster-operator-managed, not applied by CI)
- Namespace: `solid-stats-staging` (applied in `k8s/staging/00-namespace.yaml`)

**WireGuard Tunnel (CI → VPS):**
- Setup: `scripts/wg-tunnel-up.sh` brings up tunnel in CI runners before any kubectl
- Interface: `wg0` (configurable default)
- Local IP (CI side): 10.8.0.3/32 (configurable)
- Allowed IPs: 10.8.0.1/32 (k3s API only)
- Peer public key: from `WG_PEER_PUBLIC_KEY` environment secret
- Private key: from `WG_PRIVATE_KEY` (passed via /dev/stdin, never written to disk)
- Endpoint: from `WG_ENDPOINT` environment secret (format: HOST:PORT)
- Persistent keepalive: 25 seconds
- Handshake timeout: 10 seconds (exit 1 if handshake incomplete; fail-closed gate)
- TCP reachability check: verify 10.8.0.1:6443 reachable before kubectl

**Manifest Apply Strategy:**
- Dry-run first (PR): `kubectl apply --dry-run=server` for validation
- Live apply (master): `kubectl apply -f <file>` for each manifest
- Exclude operator-managed: skip `00-namespace.yaml`, `01-ci-rbac.yaml` (cluster operator bootstraps these)
- Restore drill: skip depth-1 apply; `k8s/staging/restore-drill/70-restore-drill.yaml` applied manually via `scripts/restore-drill.sh`
- S3 lifecycle: skip depth-1 apply; `config/s3/backups-lifecycle.json` applied manually via `scripts/apply-s3-lifecycle.sh`

## Replay Source (External)

**Replays Fetcher Source Configuration:**
- URL: from `REPLAYS_FETCHER_REPLAY_SOURCE_URL` environment secret
- Transport: `direct` (default) or `ssh` (configurable via `REPLAYS_FETCHER_REPLAY_SOURCE_TRANSPORT`)
- SSH options (if transport=ssh):
  - Host: `REPLAYS_FETCHER_REPLAY_SOURCE_SSH_HOST` (required if ssh)
  - Command: `REPLAYS_FETCHER_REPLAY_SOURCE_SSH_COMMAND` (optional)
- Rendered into `replays-fetcher-runtime` secret by: `scripts/render-staging-secrets.py` (lines 45–51, 73–79)
- Constraints: `suspend: true` in `k8s/staging/50-replays-fetcher.yaml` — fetcher never runs until:
  1. Manual backup gate verification (docs/backup-gate.md)
  2. Manual restore drill execution (scripts/restore-drill.sh)
  3. Schedule enabled by operator

## HTTP Reverse Proxy (nginx)

**Edge Proxy on VPS Host:**
- Config: `config/nginx/sites-available/stats-staging-solid-stats.conf`
- Domain: `stats-staging.solid-stats.ru`
- HTTP listener: port 80 (ACME challenge + redirect to HTTPS)
- HTTPS listener: port 443 (TLS termination, HTTP/2)
- Upstream pool: `solid_stats_staging_server2` → k3s `server-2` ClusterIP 10.43.94.103:3000
- Cutover lever: line marked `# CUTOVER:` switches upstream for Phase 11 production traffic
- Managed by: `scripts/bootstrap-edge.sh` (operator-run on VPS, not CI)
- Validation gate: `nginx -t` before reload (fail-closed)

**Let's Encrypt / certbot Integration:**
- HTTPS certificates: `/etc/letsencrypt/live/stats-staging.solid-stats.ru/`
- Certificate paths in nginx:
  - `ssl_certificate`: fullchain.pem
  - `ssl_certificate_key`: privkey.pem
  - `ssl_dhparam`: ssl-dhparams.pem (letsencrypt options)
- ACME webroot: `/var/www/html/.well-known/acme-challenge/`
- Renewal: certbot automatic renewal (installed by `scripts/bootstrap-edge.sh`)
- Admin email: from `ADMIN_EMAIL` environment variable during bootstrap
- Nginx includes letsencrypt options: `/etc/letsencrypt/options-ssl-nginx.conf`

## System Utilities

**Host SSH Access:**
- Operator SSH to VPS root for manual operations (not used by CI)
- WireGuard tunnel replaces direct kubectl-over-SSH for CI
- Used for: certificate renewal, firewall rules, emergency access

**host ufw (Firewall):**
- Managed by `scripts/bootstrap-edge.sh` (operator-run bootstrap)
- Rules for TCP 80, 443 (nginx) and k3s internal access
- Configurable: `SKIP_UFW=1` environment variable to skip during bootstrap

**aws-cli:**
- Used in `postgres-backup` CronJob container for S3 operations
  - File: `k8s/staging/60-postgres-backup.yaml` (installs `aws-cli` via apk, lines 46–90)
  - Commands: `aws s3 cp` for upload
- Used in restore drill for S3 backup download
  - File: `k8s/staging/restore-drill/70-restore-drill.yaml`
- Used in operator scripts for S3 lifecycle and backup validation
  - Files: `scripts/apply-s3-lifecycle.sh`, `scripts/validate-s3-lifecycle.py`

## Deployment Secrets Model

**GitHub Environment Secrets (Input):**
All secrets stored in GitHub `staging` environment. No secrets in git.

**Kubernetes Secrets (Output):**
`scripts/render-staging-secrets.py` transforms GitHub secrets into 6 Kubernetes Secrets + 1 ConfigMap:
1. `ghcr-pull` — docker config for GHCR image pulls (kubernetes.io/dockerconfigjson)
2. `postgres-auth` — PostgreSQL password (Opaque)
3. `rabbitmq-auth` — RabbitMQ password (Opaque)
4. `server-2-runtime` — DATABASE_URL, RABBITMQ_URL, S3 credentials (Opaque)
5. `replay-parser-2-runtime` — AMQP URL, S3 credentials (Opaque)
6. `replays-fetcher-runtime` — DATABASE_URL, replay source config, S3 credentials (Opaque)
7. `server-2-config` — ConfigMap with app environment variables

All secrets created with `stringData` (automatic base64 encoding by kubectl) and applied BEFORE workload manifests (CI workflow order).

## Validation Integrations

**CI Validation in .github/workflows/deploy-staging.yml:**
1. **validate job:** `python3 scripts/validate-staging.py`
   - Checks: manifest files exist, script runnable, secret structure, workload format, app image SHAs (no `latest`)
2. **dry-run job:** `kubectl apply --dry-run=server` for each manifest
   - Server-side validation without state changes
   - Requires WireGuard tunnel + kubeconfig up
3. **deploy job:** `kubectl apply -f <file>` for each manifest
   - Applies on master push only
   - Verify rollouts: `kubectl rollout status` for postgres, rabbitmq, server-2, replay-parser-2, web (all timeout 300s)
   - Verify services/CronJobs: `kubectl get` output

**Local Validation (operator-run):**
```bash
python3 scripts/validate-staging.py
```
Must pass before opening PR.

**Restore Drill (operator-gated):**
```bash
K8S_NAMESPACE=solid-stats-staging bash scripts/restore-drill.sh
```
Required before production cutover (Phase 11).

**Edge Bootstrap (operator-run):**
```bash
ADMIN_EMAIL=ops@example.com scripts/bootstrap-edge.sh
```
Idempotent; safe to re-run. Installs nginx vhost, certbot, ufw rules.

---

*Integration audit: 2026-06-13*
