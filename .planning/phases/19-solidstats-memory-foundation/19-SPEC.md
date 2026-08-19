# Phase 19: SolidStats Memory Foundation - Specification

## Goal

The repository contains a complete, validation-ready isolated deployment
boundary for SolidStats MemPalace backed by private Qdrant, without performing
any live mutation.

## Deliverables

1. `k8s/memory/` namespace/bootstrap, workload, service, storage, NetworkPolicy,
   backup, and monitoring manifests.
2. A dedicated secret renderer, manifest validator, deploy workflow, and
   operator bootstrap/runbook.
3. A committed room/wing migration policy and offline bundle/checksum validator.
4. Explicit blockers for immutable MemPalace image, host-source NetworkPolicy,
   resource sizing, metrics names, and cross-backend transform.

## Acceptance Criteria

- All manifests parse and select only namespace `solidstats-memory` except
  documented cluster-scoped bootstrap resources.
- Qdrant has no public ingress and no NodePort/LoadBalancer Service.
- MemPalace is configured for HTTP MCP on port 8765 and Qdrant backend only.
- Secrets are references/placeholders rendered at deploy time; no value is
  committed.
- Every pod has an explicit non-default ServiceAccount, disabled token
  automount, probes, resources, and hardened security context.
- PVCs are separate and backup/restore cannot target the active collection.
- CI credentials cannot modify staging or observability namespaces.
- Offline validation runs without cluster access, credentials, or network.

## Non-Goals

- Building or publishing the MemPalace application image.
- Running the real Chroma-to-Qdrant transform or choosing vector reuse versus
  re-embedding before its mapping and embedding evidence are source-verified.
- Deploying to k3s, changing nginx/DNS, rotating credentials, stopping the old
  stack, migrating real data, or changing machine-local MCP registration.
- Importing semantic tunnels, KG data, diary data, or unscoped legacy content.

## Failure Policy

Unknown runtime values fail closed. They remain explicit placeholders rejected
by validators and documented as operator gates; they are never replaced with
guessed image tags, CIDRs, metric names, collection names, or credentials.
