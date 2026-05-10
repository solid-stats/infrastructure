# Phase 1: Staging Deploy Baseline - Research

## Research Question

What needs to be true to plan a safe staging deploy baseline for the current
plain-manifest k3s infrastructure repository?

## Current Runtime Surface

The repository already represents the Phase 1 resource set:

- `k8s/staging/00-namespace.yaml` creates `solid-stats-staging`.
- `k8s/staging/10-postgres.yaml` defines PostgreSQL Service and StatefulSet.
- `k8s/staging/20-rabbitmq.yaml` defines RabbitMQ Service and StatefulSet.
- `k8s/staging/30-server-2.yaml` defines the `server-2` ConfigMap and Service.
- `k8s/staging/35-server-2-deployment.yaml` defines the `server-2`
  Deployment.
- `k8s/staging/40-replay-parser-2.yaml` defines the `replay-parser-2`
  Deployment.
- `k8s/staging/50-replays-fetcher.yaml` defines the suspended
  `replays-fetcher` CronJob.
- `k8s/staging/60-postgres-backup.yaml` defines the `postgres-backup`
  CronJob.

The deploy entrypoint is `scripts/deploy-staging.sh`. It renders secrets,
applies manifests over SSH, waits for PostgreSQL, RabbitMQ, `server-2`, and
`replay-parser-2` rollout state, then lists the two CronJobs.

## Implementation Findings

### Kubernetes Safety

The app Deployments and PostgreSQL/RabbitMQ StatefulSets currently do not set
explicit `serviceAccountName`, so they use the default ServiceAccount. The
backup CronJob sets `automountServiceAccountToken: false` but still relies on
the implicit default ServiceAccount. The fetcher CronJob also uses the implicit
default ServiceAccount.

`server-2`, `replay-parser-2`, `replays-fetcher`, and `postgres-backup` have
resource requests and limits. PostgreSQL and RabbitMQ define probes but do not
define resource requests or limits. Security contexts are absent across the
main workload set.

NetworkPolicy resources are absent. Before adding restrictive policies, the
implementation should determine whether the staging k3s CNI enforces
NetworkPolicy. If the CNI is unknown, Phase 1 can add a documented exception
and CI check for either NetworkPolicy presence or exception documentation.

### Validation

The GitHub Actions `validate` job currently verifies file presence and lists
manifest files. It does not parse YAML, compile Python, check Bash syntax,
validate secret output shape, detect default ServiceAccount usage, detect
missing resources/probes/security contexts, or run `kubectl --dry-run`.

Because the repository intentionally has no package manager, Phase 1 validation
should use the available standard library and shell tooling:

- `python3 -m py_compile scripts/render-staging-secrets.py`
- `bash -n scripts/deploy-staging.sh scripts/backup-postgres-now.sh`
- a standard-library Python validator for multi-document YAML shape, manifest
  safety assertions, and rendered-secret structural assertions
- optional `kubectl apply --dry-run=client -f -` when `kubectl` is installed

### Secret Rendering

`scripts/render-staging-secrets.py` already emits a Docker config containing
`username`, `password`, and base64 `auth`. It should be protected by a validation
test that proves required Secret documents exist and the Docker config is
parseable without printing actual secret values.

The validator can run the renderer with deterministic dummy environment values,
parse the YAML documents, decode `.dockerconfigjson`, and assert required keys:

- `ghcr-pull` type is `kubernetes.io/dockerconfigjson`.
- `.dockerconfigjson` has `auths.ghcr.io.username`, `password`, and `auth`.
- Runtime Secret names exist for PostgreSQL, RabbitMQ, `server-2`,
  `replay-parser-2`, and `replays-fetcher`.

### Operator Documentation

`README.md` and `docs/staging.md` already explain the repository purpose, owned
resources, deploy model, and suspended fetcher. Phase 1 should extend these
docs with:

- explicit validation command
- expected deploy verification resources
- app-CD overlap warning
- host edge and `web` as documented v1 exceptions
- Kubernetes hardening exception notes, especially NetworkPolicy/CNI status if
  not enforceable in the current cluster

## Validation Architecture

Phase 1 should add a repo-local validation command or script that can run in CI
and locally before deploy. The validation should fail on:

- broken Python syntax in `scripts/render-staging-secrets.py`
- broken Bash syntax in deploy/backup scripts
- missing expected staging manifest files
- Kubernetes documents without `apiVersion` or `kind`
- workload pod specs that rely on the default ServiceAccount without an
  explicit exception
- containers missing resource requests or limits
- long-running app containers missing readiness/liveness probes
- absence of both NetworkPolicy resources and documented NetworkPolicy/CNI
  exception
- rendered secrets missing expected names, types, keys, or parseable GHCR Docker
  auth structure

The validation should avoid logging secret values by using dummy test inputs and
checking only document structure and required keys.

## Planning Recommendations

Plan the phase as four execution slices:

1. Add a validation entrypoint and CI wiring before deployment.
2. Harden manifests with explicit ServiceAccounts, resource/security decisions,
   and NetworkPolicy or exception documentation.
3. Strengthen secret rendering validation around GHCR pull credentials and
   runtime Secret shape.
4. Update operator runbooks so Phase 1 boundaries, deploy verification, and
   deliberate exceptions are visible outside planning docs.

The executor should keep the repository's plain-manifest, standard-library, and
concise-runbook style. It should not add Helm, Kustomize, a package manager, or
production/edge automation in Phase 1.

## Risks

- Restrictive security contexts may break vendor images if user/group or
  filesystem assumptions are wrong; document exceptions where the image contract
  is uncertain.
- NetworkPolicy manifests may be ineffective on the current k3s CNI; validation
  should accept a documented exception until the CNI is verified.
- Live rollout verification requires staging SSH access and secrets. If those
  are unavailable during execution, verification must report the missing live
  evidence explicitly instead of claiming full deploy proof.

## Research Complete

This research is sufficient to plan Phase 1.
