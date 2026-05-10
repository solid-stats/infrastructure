# Phase 1: Staging Deploy Baseline - Context

**Gathered:** 2026-05-10
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 1 delivers a safe, infrastructure-owned staging deploy baseline for the
resources already represented in this repository: namespace, PostgreSQL,
RabbitMQ, `server-2`, `replay-parser-2`, suspended `replays-fetcher`, and
`postgres-backup`. It does not remove legacy app repository deploy workflows,
does not bring host nginx/certificate/firewall automation under management, and
does not add production or `web` runtime wiring.

</domain>

<decisions>
## Implementation Decisions

### Deploy Boundary and Resource Ownership
- Infra owns every listed staging runtime resource already in `k8s/staging`:
  namespace, PostgreSQL, RabbitMQ, `server-2`, `replay-parser-2`, suspended
  `replays-fetcher`, and `postgres-backup`.
- App CD overlap should be documented and validated around in Phase 1; do not
  disable app repository workflows until the Phase 3 ownership handoff.
- Host nginx, certificates, firewall automation, production cutover, and `web`
  runtime wiring stay outside Phase 1 and must be documented as v1 exceptions.
- Deploy success means repo-local/CI validation plus live `kubectl apply` and
  rollout checks for PostgreSQL, RabbitMQ, `server-2`, and
  `replay-parser-2`; CronJobs should be visible after deploy but not force-run
  in this phase.

### Kubernetes Hardening Scope
- Workloads should avoid the default ServiceAccount by using explicit
  ServiceAccounts where manifests need them.
- Add pod and container security contexts where current images allow them;
  document deliberate exceptions instead of forcing changes that risk runtime
  breakage.
- CI should detect missing resource requests, resource limits, and readiness or
  liveness probe decisions where applicable.
- Add NetworkPolicies if the current k3s CNI enforces them; otherwise document
  the CNI exception and follow-up path.

### Validation and Secret Rendering
- Add deterministic repo-local checks: YAML parsing, Python compilation, Bash
  syntax, rendered-secret output shape, manifest safety checks, and optional
  `kubectl` dry-run when available.
- Fix or validate GHCR pull secret rendering so `.dockerconfigjson` contains
  usable auth data without logging secret values.
- Prefer standard library checks and `kubectl` if present; do not introduce a
  package manager solely for Phase 1 validation.
- Secret validation should check structure and required keys while keeping
  secret values out of logs, docs, and committed files.

### Operator Documentation and Verification Evidence
- Keep operator docs concise: deploy command, required secrets, expected
  resources, rollout verification, and known v1 exceptions.
- Phase completion should include current local validation output plus live
  staging deploy/rollout output when credentials are available; if live access
  is unavailable, verification must state the gap explicitly.
- Deferred resources should be documented, not represented by placeholder
  manifests.
- Surface operator safety warnings in `docs/staging.md` and README near deploy
  instructions, especially app-CD overlap and suspended fetcher behavior.

### the agent's Discretion
All implementation details not fixed above are at the agent's discretion, as
long as they preserve the staging-first scope, secret-handling constraints, and
Kubernetes hardening baseline.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- Staging manifests already exist under `k8s/staging/` with numeric apply
  ordering.
- `scripts/render-staging-secrets.py` renders runtime and GHCR secrets from
  environment variables using only the Python standard library.
- `scripts/deploy-staging.sh` applies rendered secrets and manifests over SSH
  and waits for StatefulSet/Deployment rollout state.
- `scripts/backup-postgres-now.sh` creates a one-off Job from the deployed
  backup CronJob and prints logs.
- Existing runbooks live in `README.md`, `docs/staging.md`, and
  `docs/backup-restore.md`.

### Established Patterns
- Manifests are plain YAML, one staging environment per directory, with
  explicit namespaces and standard Kubernetes app labels.
- App image tags are pinned to explicit SHAs with `imagePullPolicy:
  IfNotPresent`.
- Bash scripts use `set -euo pipefail` and explicit required environment
  checks.
- Python scripts use a `required()` helper and exit code 64 for missing
  configuration.
- Documentation is written as concise operational runbooks rather than long
  implementation narratives.

### Integration Points
- GitHub Actions workflow `.github/workflows/deploy-staging.yml` currently owns
  validation and staging deployment entrypoints.
- Deploy verification currently waits for `statefulset/postgres`,
  `statefulset/rabbitmq`, `deployment/server-2`, and
  `deployment/replay-parser-2`.
- The Kubernetes safety baseline comes from the project-local
  `kubernetes-specialist` skill: explicit ServiceAccounts, resource limits,
  probes, security contexts, NetworkPolicies or documented exceptions, and
  no secret values in git.

</code_context>

<specifics>
## Specific Ideas

Use the existing plain-manifest and standard-library style. Prioritize
validation and documentation improvements that make the current infra-owned
deploy path safer without broadening Phase 1 into app CD migration, backup gate
execution, full-run operations, diffing, production, `web`, or edge automation.

</specifics>

<deferred>
## Deferred Ideas

- Phase 3 handles legacy app repository deploy handoff.
- Phase 2 handles manual backup, S3 upload, and restore-list validation.
- Phase 4 handles controlled manual ingest/full-run operations.
- Phase 5 handles old-vs-new statistics diff readiness.
- v2 handles production cutover, host edge automation, automated restore drill,
  S3 lifecycle policy enforcement, and `web` runtime wiring.

</deferred>
