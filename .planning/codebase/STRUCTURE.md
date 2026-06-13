# Codebase Structure

**Analysis Date:** 2026-06-13

## Directory Layout

```
infrastructure/
├── .github/
│   └── workflows/
│       └── deploy-staging.yml           # CI/CD: validate → dry-run → deploy to k3s
├── .planning/
│   ├── codebase/                        # GSD-maintained: ARCHITECTURE.md, STRUCTURE.md, etc.
│   └── phases/                          # Planned work phases
├── k8s/
│   └── staging/
│       ├── 00-namespace.yaml            # solid-stats-staging namespace (operator-applied once)
│       ├── 01-ci-rbac.yaml              # ci-deployer ServiceAccount + Role (operator-applied once)
│       ├── 10-postgres.yaml             # PostgreSQL StatefulSet + Service + SA
│       ├── 20-rabbitmq.yaml             # RabbitMQ StatefulSet + Service + SA
│       ├── 30-server-2.yaml             # server-2 ConfigMap + Service
│       ├── 35-server-2-deployment.yaml  # server-2 Deployment + SA (image SHA pinned)
│       ├── 36-web.yaml                  # web ConfigMap + Service
│       ├── 37-web-deployment.yaml       # web Deployment + SA (image SHA pinned)
│       ├── 40-replay-parser-2.yaml      # replay-parser-2 Deployment + SA (image SHA pinned)
│       ├── 50-replays-fetcher.yaml      # replays-fetcher CronJob + SA (suspended)
│       ├── 60-postgres-backup.yaml      # postgres-backup CronJob + SA (daily 06:00)
│       ├── restore-drill/
│       │   └── 70-restore-drill.yaml    # restore-drill Job (operator-triggered, never auto-schedule)
│       └── s3-lifecycle/
│           └── 80-s3-lifecycle-probe-job.yaml  # s3-lifecycle-probe Job (operator-run once)
├── config/
│   ├── nginx/
│   │   └── sites-available/
│   │       └── stats-staging-solid-stats.conf  # nginx vhost: TLS, proxy, cutover lever
│   ├── s3/
│   │   └── (S3 lifecycle config, managed separately)
│   └── systemd/
│       ├── certbot-deploy-hook.sh       # systemd: nginx reload on cert renewal
│       ├── certbot-renew-failure.service # systemd: certbot renewal failure unit
│       └── certbot.service.d/
│           └── (systemd drop-in overrides)
├── docs/
│   ├── staging.md                       # Scope, secrets, deploy model, hardening exceptions
│   ├── backup-restore.md                # Backup schedule, manual trigger, restore drill
│   ├── backup-gate.md                   # Gate status: backup validation evidence
│   ├── cutover.md                       # Pre-flight gates, policy, timing, operator runbook
│   ├── diff-readiness.md                # Diff gate evidence, parser output validation
│   ├── edge-bootstrap.md                # Operator runbook: bootstrap-edge.sh, teardown-edge.sh
│   ├── full-run.md                      # Controlled ingest runbook (v2 work)
│   ├── s3-lifecycle.md                  # S3 lifecycle rules, validation, operator runbook
│   ├── wireguard-access.md              # WireGuard tunnel setup for remote kubectl
│   ├── sa-token-rotation.md             # ci-deployer token rotation procedure
│   └── operator-bootstrap.md            # First-time cluster setup, operator responsibilities
├── gsd-briefs/
│   └── (Strategic planning documents, e.g. observability-plan.md)
├── scripts/
│   ├── wg-tunnel-up.sh                  # CI gate: WireGuard handshake verification
│   ├── kubeconfig-setup.sh              # CI: build kubeconfig from ci-deployer token + CA cert
│   ├── render-staging-secrets.py        # CI: derive Kubernetes Secrets from GitHub env vars
│   ├── validate-staging.py              # CI + local: validate manifests, Secrets, images
│   ├── backup-postgres-now.sh           # Operator: create one-off backup Job, print evidence
│   ├── restore-drill.sh                 # Operator: apply restore-drill Job, wait, print evidence
│   ├── bootstrap-edge.sh                # Operator: adopt-reconcile vhost, certbot, UFW
│   ├── teardown-edge.sh                 # Operator: reverse bootstrap-edge.sh
│   ├── cutover.sh                       # Operator-only: flip nginx upstream + reload, enforce gates
│   ├── start-controlled-full-run.sh     # Trigger full ingest run (v2 feature)
│   ├── apply-s3-lifecycle.sh            # Operator: apply S3 lifecycle config
│   └── validate-s3-lifecycle.py         # Standalone validator for S3 lifecycle rules
├── AGENTS.md                            # Project definition, constraints, conventions, skills
├── CLAUDE.md                            # Reference to AGENTS.md
├── README.md                            # Overview, layout, deploy model, manual backup
├── LICENSE                              # License text
├── skills-lock.json                     # GSD skills lock file
└── .gitignore                           # Exclude local files, logs, secrets

```

## Directory Purposes

**`.github/workflows/`:**
- Purpose: GitHub Actions CI/CD automation.
- Contains: Single `deploy-staging.yml` workflow.
- Key files: `.github/workflows/deploy-staging.yml` (validate → dry-run → deploy jobs).

**`.planning/`:**
- Purpose: GSD-maintained planning and analysis documents.
- Contains: `codebase/` (ARCHITECTURE.md, STRUCTURE.md, CONVENTIONS.md, TESTING.md, STACK.md, INTEGRATIONS.md, CONCERNS.md) and `phases/` (executed and upcoming work phases).
- Key files: Not committed; generated by `/gsd-map-codebase` and `/gsd-plan-phase`.

**`k8s/staging/`:**
- Purpose: Kubernetes manifests for the staging cluster.
- Contains: Numbered-prefix manifests (`00-` through `80-`), subdirectories for operator-only resources.
- Apply order: Numeric prefix order (00 → 01 → 10 → 20 → ... → 80).
- Key files:
  - `00-namespace.yaml` — Namespace (operator-applied once, never re-applied by CI).
  - `01-ci-rbac.yaml` — RBAC (operator-applied once, defines ci-deployer identity).
  - `10-postgres.yaml` — PostgreSQL StatefulSet, Service, SA, 20Gi PVC.
  - `20-rabbitmq.yaml` — RabbitMQ StatefulSet, Service, SA, 5Gi PVC.
  - `30-server-2.yaml` — server-2 ConfigMap, Service.
  - `35-server-2-deployment.yaml` — server-2 Deployment, SA (image SHA pinned).
  - `36-web.yaml` — web ConfigMap, Service.
  - `37-web-deployment.yaml` — web Deployment, SA (image SHA pinned).
  - `40-replay-parser-2.yaml` — replay-parser-2 Deployment, SA (2 replicas, image SHA pinned).
  - `50-replays-fetcher.yaml` — replays-fetcher CronJob, SA (suspended by default).
  - `60-postgres-backup.yaml` — postgres-backup CronJob, SA (daily 06:00 Moscow).
  - `restore-drill/70-restore-drill.yaml` — restore-drill Job (operator-triggered).
  - `s3-lifecycle/80-s3-lifecycle-probe-job.yaml` — s3-lifecycle-probe Job (operator-run).

**`config/nginx/`:**
- Purpose: Host-level nginx configuration.
- Contains: nginx vhost configuration for `stats-staging.solid-stats.ru`.
- Key files: `config/nginx/sites-available/stats-staging-solid-stats.conf` (TLS termination, HTTP proxy, `# CUTOVER:` lever at line 9).

**`config/systemd/`:**
- Purpose: Host-level systemd configuration and hooks.
- Contains: certbot deploy hook, systemd service drop-ins.
- Key files:
  - `config/systemd/certbot-deploy-hook.sh` — Executed after cert renewal; reloads nginx.
  - `config/systemd/certbot-renew-failure.service` — Alert unit if renewal fails.

**`docs/`:**
- Purpose: Human-readable operational documentation.
- Contains: Runbooks, gate status, architecture notes, operator procedures.
- Key files:
  - `docs/staging.md` — Scope, required GitHub secrets, deploy model, handoff matrix.
  - `docs/backup-restore.md` — Backup schedule, manual trigger, restore drill.
  - `docs/backup-gate.md` — Status tracker for backup validation gate.
  - `docs/cutover.md` — Pre-flight gates, policy, operator runbook.
  - `docs/diff-readiness.md` — Diff gate evidence (new vs. legacy parser).
  - `docs/edge-bootstrap.md` — bootstrap-edge.sh / teardown-edge.sh runbook.
  - `docs/s3-lifecycle.md` — S3 lifecycle rules, validation, configuration.

**`gsd-briefs/`:**
- Purpose: Strategic planning documents (not operational runbooks).
- Contains: Long-term roadmap briefs, e.g., observability-plan.md.
- Key files: None currently in scope; referenced in README.

**`scripts/`:**
- Purpose: Operational and CI automation scripts.
- Contains: Bash scripts for tunneling, kubeconfig setup, backup, restore, edge bootstrap, cutover; Python validators and secret renderers.
- Key files:
  - **CI scripts (called by GitHub Actions):**
    - `scripts/wg-tunnel-up.sh` — Establishes WireGuard tunnel, waits for handshake, probes API.
    - `scripts/kubeconfig-setup.sh` — Builds kubeconfig from ci-deployer token + CA cert.
    - `scripts/render-staging-secrets.py` — Derives Kubernetes Secrets from GitHub env vars.
    - `scripts/validate-staging.py` — Validates manifests, Secrets, images, S3 lifecycle rules.
  - **Operator scripts (called manually):**
    - `scripts/backup-postgres-now.sh` — Creates one-off backup Job, waits, prints evidence.
    - `scripts/restore-drill.sh` — Applies restore-drill Job, waits, prints evidence.
    - `scripts/bootstrap-edge.sh` — Idempotent adopt-reconcile for vhost, certbot, UFW.
    - `scripts/teardown-edge.sh` — Reverses bootstrap-edge.sh.
    - `scripts/cutover.sh` — Flips nginx upstream (operator-only, enforces gates).
    - `scripts/apply-s3-lifecycle.sh` — Applies S3 lifecycle configuration.
    - `scripts/validate-s3-lifecycle.py` — Validates S3 lifecycle rules.

## Key File Locations

**Entry Points:**

| Purpose | File | Invoked By |
|---------|------|-----------|
| **CI/CD workflow** | `.github/workflows/deploy-staging.yml` | GitHub Actions (push to master / workflow_dispatch) |
| **Local validation** | `scripts/validate-staging.py` | Developer (pre-PR) or CI `validate` job |
| **Manual backup** | `scripts/backup-postgres-now.sh` | Operator (kubectl access required) |
| **Restore drill** | `scripts/restore-drill.sh` | Operator (kubectl access required) |
| **Edge bootstrap** | `scripts/bootstrap-edge.sh` | Operator (VPS root access required) |
| **Edge teardown** | `scripts/teardown-edge.sh` | Operator (VPS root access required) |
| **Production cutover** | `scripts/cutover.sh` | Operator (VPS root access required) |
| **Project overview** | `README.md` | Human reference |
| **Staging operations** | `docs/staging.md` | Operator reference |
| **Backup/restore runbook** | `docs/backup-restore.md` | Operator reference |
| **Cutover runbook** | `docs/cutover.md` | Operator reference |

**Configuration:**

| Purpose | File |
|---------|------|
| **Namespace definition** | `k8s/staging/00-namespace.yaml` |
| **CI RBAC** | `k8s/staging/01-ci-rbac.yaml` |
| **server-2 runtime config** | `k8s/staging/30-server-2.yaml` (ConfigMap) |
| **web runtime config** | `k8s/staging/36-web.yaml` (ConfigMap) |
| **nginx vhost + cutover lever** | `config/nginx/sites-available/stats-staging-solid-stats.conf` |
| **certbot hook** | `config/systemd/certbot-deploy-hook.sh` |

**Core Logic:**

| Purpose | File | Scope |
|---------|------|-------|
| **PostgreSQL database** | `k8s/staging/10-postgres.yaml` | StatefulSet, Service, SA |
| **RabbitMQ broker** | `k8s/staging/20-rabbitmq.yaml` | StatefulSet, Service, SA |
| **server-2 API** | `k8s/staging/35-server-2-deployment.yaml` | Deployment, SA (image SHA pinned) |
| **web frontend** | `k8s/staging/37-web-deployment.yaml` | Deployment, SA (image SHA pinned) |
| **replay-parser-2 workers** | `k8s/staging/40-replay-parser-2.yaml` | Deployment (2 replicas), SA, image SHA pinned |
| **replay fetcher (suspended)** | `k8s/staging/50-replays-fetcher.yaml` | CronJob, SA (suspended: true) |
| **postgres-backup (daily)** | `k8s/staging/60-postgres-backup.yaml` | CronJob, SA (06:00 Moscow) |

**Testing & Validation:**

| Purpose | File |
|---------|------|
| **Manifest validator** | `scripts/validate-staging.py` |
| **S3 lifecycle validator** | `scripts/validate-s3-lifecycle.py` |
| **Secret renderer** | `scripts/render-staging-secrets.py` |

## Naming Conventions

**Files:**

| Pattern | Purpose | Examples |
|---------|---------|----------|
| `\d{2}-.*\.yaml` | Kubernetes manifest with apply order | `00-namespace.yaml`, `10-postgres.yaml`, `60-postgres-backup.yaml` |
| `[a-z-]+-[a-z]+-[a-z]+\.sh` | Bash script (kebab-case) | `wg-tunnel-up.sh`, `backup-postgres-now.sh` |
| `[a-z-]+\.py` | Python script (kebab-case) | `render-staging-secrets.py`, `validate-staging.py` |
| `[A-Z][A-Z]+\.md` | Documentation (UPPERCASE) | `README.md`, `AGENTS.md`, `CLAUDE.md` |
| `[a-z-]+\.md` (in `docs/`) | Runbook or reference (lowercase) | `staging.md`, `backup-restore.md`, `cutover.md` |

**Directories:**

| Pattern | Purpose | Examples |
|---------|---------|----------|
| `k8s/<env>/` | Kubernetes environment | `k8s/staging/` |
| `k8s/<env>/<subdir>/` | Operator-only or special resources | `k8s/staging/restore-drill/`, `k8s/staging/s3-lifecycle/` |
| `config/<system>/` | Host-level configuration | `config/nginx/`, `config/systemd/` |
| `docs/` | Human documentation | `docs/`, `docs/staging.md` |
| `scripts/` | Automation scripts | `scripts/`, `scripts/wg-tunnel-up.sh` |

**Kubernetes Resources:**

| Type | Naming | Examples |
|------|--------|----------|
| **Namespace** | Kebab-case, environment-scoped | `solid-stats-staging` |
| **Deployment/StatefulSet** | Kebab-case | `server-2`, `replay-parser-2`, `postgres`, `rabbitmq` |
| **Service** | Same as workload name | `postgres`, `server-2`, `rabbitmq` |
| **ConfigMap** | Kebab-case with `-config` suffix | `server-2-config`, `web-config` |
| **Secret** | Kebab-case with purpose suffix | `postgres-auth`, `server-2-runtime`, `ghcr-pull` |
| **ServiceAccount** | Same as workload (or purpose) | `postgres`, `server-2`, `ci-deployer` |
| **CronJob** | Kebab-case with purpose | `postgres-backup`, `replays-fetcher` |
| **Job** | Kebab-case with operation | `restore-drill`, `s3-lifecycle-probe` |
| **Labels** | `app.kubernetes.io/name`, `app.kubernetes.io/part-of` | `app.kubernetes.io/name: server-2`, `app.kubernetes.io/part-of: solid-stats` |

## Where to Add New Code

**New Kubernetes Workload (Deployment/StatefulSet/CronJob):**
1. Create manifest file: `k8s/staging/<NN>-<name>.yaml` (increment `<NN>` numeric prefix to maintain apply order).
2. Include: ServiceAccount, Role (if needed), RoleBinding (if needed), Service (if exposed), and workload spec.
3. Use consistent labels: `app.kubernetes.io/name: <name>`, `app.kubernetes.io/part-of: solid-stats`.
4. Set `automountServiceAccountToken: false` unless workload needs Kubernetes API access.
5. Pin image SHAs (never `latest`) for application images.
6. Add resource requests/limits and liveness/readiness probes.
7. Update `scripts/validate-staging.py` to include new workload in `EXPECTED_WORKLOADS` dict and validate relevant Secrets.
8. Update `.github/workflows/deploy-staging.yml` deploy job `kubectl rollout status` command if workload is long-running (Deployment/StatefulSet).
9. Document in `docs/staging.md` under "Owned here" or "Not owned here".

**New Secret:**
1. Add to `scripts/render-staging-secrets.py` as a derived Kubernetes Secret.
2. Define required GitHub environment variable(s) in the script.
3. Update `scripts/validate-staging.py` `EXPECTED_SECRETS` dict with secret name, type, and required keys.
4. Document required env var in `docs/staging.md` "Required GitHub Secrets" section.
5. Ensure Secret is injected into pods via `envFrom.secretRef` or `valueFrom.secretKeyRef`.

**New Operator Script:**
1. Create file: `scripts/<action>-<noun>.sh` or `scripts/<action>-<noun>.py` (kebab-case).
2. Add shebang: `#!/usr/bin/env bash` or `#!/usr/bin/env python3`.
3. Add `set -euo pipefail` (bash) or equivalent error handling.
4. Document usage, required env vars, and output format in comments at the top.
5. Implement `required()` helper for mandatory env vars; exit code 64 if missing.
6. Validate gates/preconditions; fail early with clear error messages.
7. Test locally before committing (if it modifies the edge, test on staging VPS).

**New Documentation:**
1. Create file: `docs/<topic>.md` (lowercase, descriptive name).
2. Include: purpose, prerequisites, step-by-step instructions, expected output, troubleshooting.
3. Reference related entry points (scripts, manifests, GitHub Actions jobs).
4. Link from `README.md` or `docs/staging.md` as appropriate.
5. If it's a gate or validation status, create a `docs/<gate-name>-gate.md` file (see `docs/backup-gate.md`, `docs/diff-readiness.md`).

**New Validation Rule:**
1. Add check to `scripts/validate-staging.py` (for staging manifests) or `scripts/validate-s3-lifecycle.py` (for S3 rules).
2. If rule should fail the CI `validate` job, use `raise ValidationError(msg)`.
3. If rule should warn but not fail, use `print(f"WARNING: {msg}")`.
4. Document the rule in `docs/staging.md` or relevant runbook.
5. Test: `python3 scripts/validate-staging.py` should pass locally before committing.

**New Host Configuration (nginx, certbot, UFW, systemd):**
1. Add config file to `config/systemd/` or `config/nginx/`.
2. Implement idempotent installation in `scripts/bootstrap-edge.sh`.
3. Implement idempotent cleanup in `scripts/teardown-edge.sh`.
4. Document the change in `docs/edge-bootstrap.md`.
5. Test on staging VPS: run bootstrap, verify config is correct; run teardown, verify cleanup is complete; run bootstrap again, verify idempotent.

## Special Directories

**`k8s/staging/restore-drill/`:**
- Purpose: Operator-triggered restore validation (never auto-scheduled).
- Generated: No (manifests are hand-crafted).
- Committed: Yes (manifests checked into git).
- Trigger: `scripts/restore-drill.sh` applies the Job manually.
- Rationale: Lives in subdirectory so CI's `find k8s/staging -maxdepth 1` glob never matches it; operator explicitly triggers via script or manual `kubectl apply`.

**`k8s/staging/s3-lifecycle/`:**
- Purpose: Operator-run once to probe S3 lifecycle API support.
- Generated: No (manifests are hand-crafted).
- Committed: Yes (manifests checked into git).
- Trigger: Operator runs `kubectl apply -f k8s/staging/s3-lifecycle/80-s3-lifecycle-probe-job.yaml` manually.
- Rationale: Same as restore-drill — prevents auto-scheduling; operator runs probe once and archives output.

**`.planning/`:**
- Purpose: GSD-maintained planning and analysis documents.
- Generated: Yes (by `/gsd-map-codebase`, `/gsd-plan-phase`, `/gsd-execute-phase`).
- Committed: No (`.planning/` is in `.gitignore` or excluded from VCS).
- Contents: ARCHITECTURE.md, STRUCTURE.md, CONVENTIONS.md, TESTING.md, phase plans, summaries.

**`gsd-briefs/`:**
- Purpose: Strategic planning briefs not tied to execution phases.
- Generated: No (hand-authored by humans or high-level agents).
- Committed: Yes (strategic direction for the project).
- Examples: observability-plan.md, roadmap.md.

## Apply Order (Manifest Numeric Prefixes)

Manifests are applied in numeric order (`00` → `01` → `10` → `20` → ... → `80`):

| Prefix | Purpose | Files |
|--------|---------|-------|
| `00` | Namespace (cluster-scoped, operator-applied once) | `00-namespace.yaml` |
| `01` | RBAC (operator-applied once, defines ci-deployer) | `01-ci-rbac.yaml` |
| `10` | Stateful persistence layer (PostgreSQL) | `10-postgres.yaml` |
| `20` | Message broker (RabbitMQ) | `20-rabbitmq.yaml` |
| `30` | Application config (server-2 ConfigMap) | `30-server-2.yaml` |
| `35` | Application deployment (server-2 Deployment) | `35-server-2-deployment.yaml` |
| `36` | Application config (web ConfigMap) | `36-web.yaml` |
| `37` | Application deployment (web Deployment) | `37-web-deployment.yaml` |
| `40` | Worker deployment (replay-parser-2) | `40-replay-parser-2.yaml` |
| `50` | Scheduled job (replays-fetcher, suspended) | `50-replays-fetcher.yaml` |
| `60` | Scheduled job (postgres-backup, daily) | `60-postgres-backup.yaml` |
| `70+` | Operator-only (restore-drill, s3-lifecycle) | `restore-drill/70-*`, `s3-lifecycle/80-*` |

**Rationale:** Resources that others depend on are applied first (namespace, RBAC, databases, brokers, config); then deployments; then CronJobs. Operator-only manifests at depth > 1 are never auto-applied by CI.

## GSD Integration

**GSD-Maintained Files** (auto-generated, checked into git):
- `.planning/codebase/ARCHITECTURE.md` — Regenerated by `/gsd-map-codebase --focus arch`.
- `.planning/codebase/STRUCTURE.md` — Regenerated by `/gsd-map-codebase --focus arch`.
- `.planning/codebase/CONVENTIONS.md` — Regenerated by `/gsd-map-codebase --focus quality`.
- `.planning/codebase/TESTING.md` — Regenerated by `/gsd-map-codebase --focus quality`.
- `.planning/codebase/STACK.md` — Regenerated by `/gsd-map-codebase --focus tech`.
- `.planning/codebase/INTEGRATIONS.md` — Regenerated by `/gsd-map-codebase --focus tech`.
- `.planning/codebase/CONCERNS.md` — Regenerated by `/gsd-map-codebase --focus concerns`.
- `.planning/phases/*/` — Phase plans, summaries, and context (generated by `/gsd-plan-phase`, `/gsd-execute-phase`).

**Developer Workflow:**
1. Use `/gsd-quick` for small fixes (doc updates, bug fixes).
2. Use `/gsd-debug` for investigation and root-cause analysis.
3. Use `/gsd-plan-phase` to create a phase plan from a brief.
4. Use `/gsd-execute-phase` to implement a phase (reads codebase docs, applies conventions).
5. Use `/gsd-map-codebase --focus <focus>` to regenerate codebase analysis docs when significant changes are made.

---

*Structure analysis: 2026-06-13*
