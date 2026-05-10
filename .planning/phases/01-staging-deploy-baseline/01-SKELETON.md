# Phase 01 - Walking Skeleton

## Skeleton Purpose

The thinnest end-to-end infrastructure slice is:

1. Render staging secrets from environment variables.
2. Validate the repository-local staging manifest set and rendered secret shape.
3. Apply the manifests through the existing deploy script.
4. Verify live rollout state for PostgreSQL, RabbitMQ, `server-2`, and
   `replay-parser-2`.
5. Keep recurring replay fetching suspended until later phases.

## Backbone Decisions

- Runtime model: plain Kubernetes YAML under `k8s/staging/`.
- Deployment model: GitHub Actions invokes `scripts/deploy-staging.sh`, which
  runs remote `kubectl` over SSH.
- Secret model: GitHub environment secrets are rendered into Kubernetes Secrets
  at deploy time; no secret values are committed.
- Validation model: standard-library `scripts/validate-staging.py` runs locally
  and in CI before deploy.
- Safety model: explicit workload ServiceAccounts, security contexts and
  resources where supported, and NetworkPolicy or documented CNI exception.

## Skeleton Verification

- `python3 scripts/validate-staging.py` passes.
- `scripts/deploy-staging.sh` can apply staging manifests when staging SSH and
  secret environment variables are available.
- Deploy output includes successful rollout status for the two StatefulSets and
  two Deployments.
