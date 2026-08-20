# Phase 21: Restore, Cutover & Recovery - Research

<!-- markdownlint-disable MD013 -->

**Researched:** 2026-08-20
**Domain:** Provenance-bound Qdrant restore, Kubernetes recovery, MCP cutover
**Confidence:** MEDIUM

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Restore and Provenance

- Recompute every Phase 20 handoff, source, mapping, bundle, and parity digest
  before reading retained private artifacts or creating a restore target.
- Restore into an isolated collection and namespace first. No restore command
  may target a live or existing collection.
- Preserve the approved reused-vector and strict cross-engine ANN equivalence
  contracts; exact field, identifier, metadata, timestamp, and vector parity
  remain zero-tolerance gates.

#### Cutover and Recovery

- Keep Qdrant private. Only token-authenticated MemPalace HTTPS is public at
  `/solidstats/mcp`.
- Treat cutover as an operator-owned, reversible state change. Preflight,
  backup, restore proof, negative-auth checks, smoke probes, and a tested
  rollback command must pass before the switch.
- Prove both process restart and VPS reboot recovery before accepting cutover.
  Recovery evidence must cover the public MCP endpoint and the private Qdrant
  collection.
- Register only the `solidstats_memory` client after the live service passes;
  remove or disable the legacy SolidStats client only after rollback evidence
  is sealed.

### the agent's Discretion

- The agent may choose the exact script boundaries, evidence schemas, probe
  ordering, and Kubernetes resource layout while preserving the requirements
  and operator gates above.
- The project knowledge graph is stale and could not be rebuilt because the
  `graphify` CLI is unavailable. Planning must treat current repository files,
  Phase 20 artifacts, and live probes as primary evidence.

### Deferred Ideas (OUT OF SCOPE)

Archive shard extraction, candidate deduplication, and curator-owned promotion
remain Phase 22 work.
</user_constraints>

<phase_requirements>

## Phase Requirements

| ID | Description | Research Support |
| --- | --- | --- |
| ISO-01 | The MCP client is named `solidstats_memory`; no legacy `mempalace` alias remains after cutover. | Two-stage client registration/removal gate and machine-local rollback evidence. |
| ISO-03 | Qdrant remains private; only MemPalace is exposed at public HTTPS `/solidstats/mcp` through host nginx. | Service, NetworkPolicy, nginx, and negative reachability gates. |
| OPS-02 | Backups combine a Qdrant collection snapshot, MemPalace metadata archive, manifest, and checksums under the accepted prefix. | Snapshot creation, checksum, object-store inventory, and restore-drill sequence. |
| OPS-03 | Restore is proven in isolation before cutover and never targets the active collection. | Absent-target proof, physical restore collection, alias gate, and rollback design. |
| OPS-05 | Cutover proves auth rejection, MCP schema, scoped recall, semantic-miss fallback, archive labeling, capture shape, read-after-write, restart recovery, and reboot recovery. | One executable probe matrix run before cutover, after cutover, after restart, and after reboot. |

</phase_requirements>

## Summary

Phase 21 should be planned as a fail-closed state machine, not as a sequence of
operator notes. Phase 20 supplies a passing digest-bound handoff for 19,534
imported records, 21 approved exclusions, zero exact-parity failures, and a
strict ANN-equivalence result. Phase 21 must recompute those bindings before it
opens any private artifact, and it must produce only aggregate, value-free
evidence. [VERIFIED: .planning/phases/20-local-corpus-migration/20-06-SUMMARY.md]

The safest physical design is: import or stage the approved bundle into a
non-active collection; create and upload a Qdrant snapshot plus MemPalace
metadata/checksums; restore that snapshot into a second absent collection;
verify the restored physical collection; then switch the MemPalace-expected
logical collection name through an atomic Qdrant alias. Qdrant documents that
alias actions are atomic and that collection snapshots do not contain aliases,
so alias state must be backed up and restored separately. [CITED:
https://qdrant.tech/documentation/manage-data/collections/] [CITED:
https://qdrant.tech/documentation/snapshots/]

There is one blocker-quality repository defect to close before any live work:
the namespace has a default-deny policy, and the checked-in manifests allow
ingress to Qdrant from MemPalace but do not allow MemPalace egress to TCP/6333.
Kubernetes requires both the source egress and destination ingress policies to
permit a connection. [VERIFIED: k8s/memory/30-network-policy.yaml:1-61 —
verbatim: `policyTypes: [Ingress, Egress]`, `name:
allow-mempalace-to-qdrant`, `policyTypes: [Ingress]`, `port: 6333`] [CITED:
https://kubernetes.io/docs/concepts/services-networking/network-policies/]

**Primary recommendation:** implement one tested Phase 21 control plane with
explicit `preflight -> stage -> snapshot -> isolated-restore -> verify ->
alias-cutover -> public-probe -> client-register -> restart-probe ->
reboot-probe -> seal` transitions and a rollback action available from every
mutating state.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
| --- | --- | --- | --- |
| Provenance and private-artifact validation | Operator workstation | Object storage | Private retained inputs remain local until their digests pass. |
| Snapshot creation and isolated recovery | Database / Storage | Kubernetes operator job | Qdrant owns snapshot and collection state; Kubernetes owns bounded execution and credentials. |
| Logical collection switch | Database / Storage | API / Backend | Qdrant alias is the reversible data-plane lever; MemPalace consumes the logical name. |
| Public `/solidstats/mcp` switch | Host nginx | MemPalace Service | nginx owns the only public route; MemPalace remains a private ClusterIP. |
| MCP behavior verification | API / Backend | Client | A real MCP initialize/tools/call flow is required, not only HTTP health. |
| Client registration | Machine-local Codex config | Public MCP | This is external state, not a repository or Kubernetes resource. |
| Restart and reboot recovery | Kubernetes / host OS | Storage | Workloads must return with the same PVC data, alias, and public route. |

## Project Constraints (from AGENTS.md)

- Work only in the `solidstats-memory` staging boundary; production remains out
  of scope. [VERIFIED: AGENTS.md:240-259]
- Infrastructure owns Kubernetes manifests, runtime wiring, deployment scripts,
  runbooks, and staging CI/CD; it must not own application source or images.
  [VERIFIED: AGENTS.md:225-237]
- Never store or print secrets, connection strings, corpus values, raw replay
  bytes, or unpublished artifacts. [VERIFIED: AGENTS.md:61-69]
- Use immutable image digests, non-default ServiceAccounts, security contexts,
  resource requests/limits, and explicit network isolation. [VERIFIED:
  AGENTS.md:248-259]
- Repository artifacts are English; every edited Markdown file must pass
  `markdownlint-cli2 --fix`. [VERIFIED: AGENTS.md:94-105]
- Batch remote operations; do not execute an interactive drip-feed of SSH and
  kubectl commands. [VERIFIED: filtered parent handoff and durable project
  instruction]
- Do not perform an operator cutover merely because CI deploy succeeds. The
  cutover and reboot are separately authorized, externally visible state
  changes. [VERIFIED: .planning/phases/21-restore-cutover-recovery/21-CONTEXT.md]

## Existing Implementation Seams

### Runtime contract

The checked-in runtime already defines the exact namespace and services:
verbatim `namespace: solidstats-memory`, Qdrant `type: ClusterIP`, Qdrant ports
`6333` and `6334`, and MemPalace port `8765`. [VERIFIED:
k8s/memory/10-qdrant.yaml:12-30] [VERIFIED:
k8s/memory/20-mempalace.yaml:25-40]

Qdrant is a one-replica StatefulSet with verbatim retention values
`whenDeleted: Retain` and `whenScaled: Retain`; MemPalace is a one-replica
Deployment with verbatim `strategy: type: Recreate`. [VERIFIED:
k8s/memory/10-qdrant.yaml:32-66] [VERIFIED:
k8s/memory/20-mempalace.yaml:42-76]

The Qdrant image is already immutable and version-matched to Phase 20:
verbatim
`ghcr.io/qdrant/qdrant/qdrant:v1.19.0-unprivileged@sha256:18a245d16eb663d4f6ad054123371243248d8256a8067f352cd6e88d512fee0b`.
[VERIFIED: k8s/memory/10-qdrant.yaml:64-67]

The current MemPalace runtime exposes verbatim `MEMPALACE_BACKEND: qdrant`,
`MEMPALACE_QDRANT_URL: http://qdrant:6333`,
`MEMPALACE_QDRANT_NAMESPACE: SolidStats`, and `/data/palace`. [VERIFIED:
k8s/memory/20-mempalace.yaml:80-98]

### Backup contract

The existing backup CronJob is deliberately inert: verbatim `suspend: true`.
It creates a collection snapshot, downloads it, archives `palace`, writes
`SHA256SUMS` and `manifest.json`, and uploads to verbatim
`backups/solidstats-memory/`. [VERIFIED: k8s/memory/40-backup.yaml:11-78]

Plan Phase 21 work around a one-shot Job derived from the CronJob template.
Do not unsuspend the recurring schedule until the first object-store backup has
been downloaded, checksum-verified, restored, and validated. The recurring
CronJob should remain the steady-state mechanism only after the drill passes.

### Public edge

The nginx template maps the exact public location verbatim `location =
/solidstats/mcp` to internal verbatim `proxy_pass
http://solidstats_memory_mcp/mcp`, forwards `Authorization`, disables buffering,
and returns `404` for every other path. [VERIFIED:
config/nginx/sites-available/solidstats-memory-mcp.conf.template:34-54]

The template is not an installed site and still contains operator evidence
markers. [VERIFIED: docs/solidstats-memory.md:70-81]

### Deploy workflow

The memory workflow validates offline, proves the exact CI identity before
mutation, performs server-side dry-run, applies secrets and workloads, and waits
for Qdrant, MemPalace, and observer rollouts. [VERIFIED:
.github/workflows/deploy-memory.yml:21-105]

Its exact identity is verbatim
`system:serviceaccount:solidstats-memory:memory-ci-deployer`, and it explicitly
denies namespace, RBAC, staging, and monitoring mutations. [VERIFIED:
.github/workflows/deploy-memory.yml:61-73]

The workflow must remain a deploy path, not become the cutover orchestrator.
Host nginx changes, machine-local MCP registration, process restart, and VPS
reboot require an operator batch outside CI.

## Critical Gaps Before Live Work

1. **MemPalace egress is blocked.** Add an exact same-namespace egress rule from
   `app.kubernetes.io/name: mempalace` to Qdrant TCP/6333, and extend both the
   validator and tests to require the reciprocal pair. [VERIFIED:
   k8s/memory/30-network-policy.yaml:36-61] [CITED:
   https://kubernetes.io/docs/concepts/services-networking/network-policies/]
2. **No Phase 21 state machine exists.** Current scripts validate manifests and
   Phase 20 parity, but none owns absent-target proof, snapshot restore, alias
   state, MCP schema/calls, client registration, restart, reboot, or rollback.
   [VERIFIED: `ast-index explore`, 2026-08-20]
3. **The restore target cannot be a name-only convention.** Before recovery,
   query both collections and aliases and require the physical restore name to
   be absent. The Qdrant recovery API can overwrite data; the project guard is
   what enforces the stronger no-existing-target decision. [CITED:
   https://api.qdrant.tech/master/api-reference/snapshots/recover-from-snapshot]
4. **Alias compatibility with the pinned MemPalace image needs a live preflight.**
   Qdrant aliases are query-compatible and atomically switchable, but Phase 21
   must prove the exact MemPalace build opens and uses the expected alias before
   accepting this design. [CITED:
   https://qdrant.tech/documentation/manage-data/collections/]
5. **Snapshot capacity must be measured.** Qdrant states restore can require
   approximately twice the collection disk while the snapshot and restored
   collection coexist. Measure free PVC/node disk before upload or recovery.
   [CITED: https://qdrant.tech/documentation/migration-recovery-options/]
6. **The full Phase 20 test command is not currently green on local Python
   3.14.4.** On 2026-08-20 it produced 9 errors and 1 failure in inventory tests,
   while the 25 runtime-contract tests and 7 policy tests passed. Wave 0 must
   either repair the brittle mocked-clock tests or define and prove a supported
   Python runtime before the provenance gate is trusted. [VERIFIED: local test
   execution, 2026-08-20]

## Standard Stack

No external package installation is needed. Use the repository's Python 3
standard-library pattern for validation/evidence, Bash only for thin operator
orchestration, `kubectl` for cluster state, Qdrant HTTP APIs for snapshot and
alias actions, nginx for the public route, and the installed `codex mcp` CLI for
machine-local registration. [VERIFIED: AGENTS.md:288-299] [VERIFIED: local CLI
availability audit, 2026-08-20]

| Tool | Verified local version | Purpose |
| --- | --- | --- |
| Python | `3.14.4` | Evidence schemas, checksum validation, privacy-safe reports, tests |
| kubectl | `v1.36.3` | Dry-run, apply, rollout, restart, pod/PVC/alias-adjacent probes |
| Docker | `29.7.2` | Exact-image offline and local recovery gates when needed |
| nginx | `1.28.3` | Offline config validation and host edge reload |
| Codex MCP CLI | current installed binary | Add/get/remove the machine-local client |

The locally verified registration syntax is verbatim `codex mcp add <NAME>
--url <URL> --bearer-token-env-var <ENV_VAR>`. Never place the bearer value in
the command, repository, evidence, or shell history. [VERIFIED: local `codex
mcp add --help`, 2026-08-20]

## Architecture Patterns

### System Architecture Diagram

```text
retained Phase 20 inputs
        |
        v
digest/provenance gate --fail--> STOP (no private read, no target)
        |
        v
physical candidate collection -> Qdrant snapshot + metadata archive -> S3 checksums
        |                                                        |
        |                                                        v
        |                                absent physical restore collection
        |                                                        |
        +---------------- exact parity / MCP compatibility <-----+
                                                                 |
operator checkpoint ---------------------------------------------+
        |
        v
atomic logical alias -> MemPalace -> ClusterIP -> host nginx `/solidstats/mcp`
        |                                           |
        |                                           v
        |                                  real MCP/auth probes
        v
machine-local `solidstats_memory` registration
        |
        v
process restart -> same probes -> VPS reboot -> same probes -> seal evidence
        |
        +---- any failure ----> alias/nginx/client/runtime rollback
```

### Pattern 1: Immutable evidence envelope

Every action consumes a manifest containing schema version, run ID, input
digests, target names, pre-state digests, action result, aggregate counts, and
timestamps. The next action verifies the prior manifest's digest. Evidence must
never include token values, corpus values, private filesystem paths, documents,
vectors, identifiers, or metadata values. [VERIFIED:
.planning/phases/20-local-corpus-migration/20-PHASE21-HANDOFF.json]

### Pattern 2: Physical collection plus logical alias

Use a unique physical collection for each restore attempt and reserve the
MemPalace-derived name as a logical alias. Record the alias pre-state before
mutation. Create or switch it only after restored parity passes. Rollback is an
atomic alias action back to the recorded prior physical collection, or alias
removal if no prior alias existed. Qdrant documents atomic multi-action alias
updates. [CITED: https://qdrant.tech/documentation/manage-data/collections/]

### Pattern 3: One batched operator run with explicit checkpoints

Create one operator script that executes remote preflight and mutations in
coarse, restartable stages. Each stage writes a local value-free evidence file
and exits before the next irreversible boundary unless the preceding gate is
green. Re-running a completed stage must verify and reuse its exact run ID, not
silently create another collection or overwrite a backup.

### Pattern 4: Probe behavior, not only health

The MCP probe must initialize a real Streamable HTTP session, list tools and
their schemas, and call the required recall/capture tools. MCP Streamable HTTP
uses one endpoint for POST and GET, requires JSON-RPC POSTs with the correct
Accept types, and may require a session header after initialization. [CITED:
https://modelcontextprotocol.io/specification/2025-06-18/basic/transports]

### Recommended Project Structure

```text
scripts/
├── validate-phase-21.py          # offline schema, privacy, and transition validator
├── restore-solidstats-memory.py  # provenance, absent-target, upload/recover/alias logic
├── probe-solidstats-memory.py    # auth + MCP behavior matrix
└── cutover-solidstats-memory.sh  # thin operator stage orchestrator and rollback
tests/
└── test-memory-cutover-contract.py
k8s/memory/
├── 30-network-policy.yaml        # reciprocal MemPalace/Qdrant flow
└── restore-drill/                # operator-only Job template if selected; excluded from CD
docs/
└── solidstats-memory.md           # exact operator sequence and evidence locations
```

Names are recommended, not locked. Prefer fewer scripts if one Python control
plane can keep transitions and rollback in one place.

## Exact Verification Matrix

| Gate | Required evidence | Failure behavior |
| --- | --- | --- |
| Provenance | Recomputed digests equal handoff, source proof, mapping, transform, bundle files, parity report; exact image/version match | Exit before reading bundle content or contacting Qdrant |
| Target absence | `GET /collections`, `GET /aliases`, and target-specific lookup all prove the generated physical name is unused | Generate no replacement name automatically; stop for review |
| Capacity | PVC capacity/usage, node allocatable/free disk, snapshot size, projected 2x restore headroom | Stop before upload/recovery |
| Restore | Recovery returns success with `priority=snapshot`; collection reaches green; point count and vector config match | Do not create/switch alias; preserve failed collection for diagnosis |
| Exact parity | Field, ID, metadata, timestamp, vector zero failures; exclusion count matches; ANN rule remains the approved Phase 20 rule | No cutover |
| Backup | Snapshot object, metadata archive, manifest, checksum file exist under one run prefix; downloaded hashes match | Keep recurring CronJob suspended |
| Private boundary | Qdrant is not NodePort/LoadBalancer/public; outside-namespace and public probes cannot reach 6333/6334 | No nginx installation |
| Auth | Missing token and invalid token are rejected; valid token succeeds; response bodies do not echo credentials | No client registration |
| MCP schema | Real initialize, tools/list, required tool schema snapshot, and one non-mutating call pass | Roll back public edge if already switched |
| Recall | Scoped active recall returns expected aggregate behavior; semantic miss falls back to drawer listing/fetch | No acceptance |
| Archive | Archive result is labeled untrusted/historical and no automatic mining/promotion occurs | No acceptance |
| Capture | Deduplicate, create one synthetic durable test conclusion, verify shape, read it back, then remove it by exact ID if the API supports safe cleanup | No acceptance; never leave ambiguous test data |
| Restart | Record pod UIDs/restarts/PVC/alias; restart MemPalace then Qdrant one at a time; wait; rerun full public/private probe | Roll back or restore service before continuing |
| Reboot | Record host boot ID/time and pre-state; reboot once; wait for SSH/k3s/workloads; rerun full public/private probe and backup | Phase remains incomplete |
| Client | `codex mcp get solidstats_memory` shows exact URL/token-env binding; live MCP call passes; legacy remains until rollback proof sealed | Remove new client and restore previous config |

## Cutover and Rollback State Model

1. **PREPARED:** all offline tests and provenance digests pass; no external
   mutation.
2. **STAGED:** physical candidate exists; no alias, nginx, or client change.
3. **RESTORE_PROVEN:** object-store backup has been restored to another absent
   physical collection and verified.
4. **PRIVATE_LIVE:** the new runtime is healthy privately; the old VPS runtime
   is stopped so both long-running stacks do not coexist. [VERIFIED:
   docs/solidstats-memory.md:5-13]
5. **DATA_SWITCHED:** logical alias points to the verified restored collection.
6. **PUBLIC_LIVE:** nginx config is installed, `nginx -t` passed, reload passed,
   negative auth and MCP probes passed.
7. **CLIENT_ADDED:** only the new `solidstats_memory` registration is added; the
   legacy entry remains available but disabled/unselected until rollback proof.
8. **RECOVERY_PROVEN:** restart and reboot matrices pass.
9. **SEALED:** rollback was exercised, evidence was sealed, and only then the
   legacy alias is removed or disabled.

Rollback must restore, in reverse order, machine-local client configuration,
nginx site bytes/symlink state, Qdrant alias pre-state, workload state, and the
legacy service. Never delete a candidate or prior collection during rollback;
deletion is a later exact-ID cleanup decision.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
| --- | --- | --- | --- |
| Collection backup | Raw PVC copy while Qdrant is running | Qdrant collection snapshot API | Snapshot contains collection data/config/index state. |
| Live collection switch | Rename/copy points in place | Qdrant atomic alias update | Provides a reversible logical pointer. |
| MCP protocol probe | Ad hoc curl-only JSON checks | Real MCP client/session plus targeted HTTP negative-auth probes | Exercises initialization, schemas, sessions, and calls. |
| Secret transport | CLI argument or evidence field containing token | Environment variable and Kubernetes Secret | Avoids history/log leakage. |
| Recovery evidence | Screenshots or operator prose | Machine-readable value-free manifest plus exact commands/results | Re-runnable and checker-verifiable. |
| Remote execution | Many interactive SSH calls | One staged script with reconnect and timeouts | Reduces partial, unrecorded state. |

## Common Pitfalls

### One-sided NetworkPolicy

**What goes wrong:** Qdrant readiness passes, but MemPalace cannot connect.

**Why:** destination ingress is allowed while source egress remains denied.

**Avoidance:** exact reciprocal policies and a live same-pod connection probe
before rollout acceptance. [CITED:
https://kubernetes.io/docs/concepts/services-networking/network-policies/]

### Treating API recovery as inherently non-destructive

**What goes wrong:** a typo targets an existing collection and recovery
overwrites data.

**Avoidance:** independently prove absence across collections and aliases, bind
the name to the run manifest, and refuse `force` behavior. Qdrant's API reference
explicitly says recovery can overwrite current node data. [CITED:
https://api.qdrant.tech/master/api-reference/snapshots/recover-from-snapshot]

### Using the default snapshot priority

**What goes wrong:** restoring a new collection with replica priority can prefer
the empty current state.

**Avoidance:** specify verbatim `priority=snapshot` and verify post-restore
count/config. [CITED: https://qdrant.tech/documentation/snapshots/]

### Forgetting alias state is outside the snapshot

**What goes wrong:** data survives restart/recovery but MemPalace's logical name
does not resolve after a disaster restore.

**Avoidance:** record, back up, restore, and probe alias state separately.
[CITED: https://qdrant.tech/documentation/snapshots/]

### Declaring recovery after rollout health only

**What goes wrong:** pods are Ready while alias, MCP schema, auth, or data access
is broken.

**Avoidance:** run the same full behavior matrix after initial cutover, process
restart, and host reboot.

### Reboot without a bounded reconnection plan

**What goes wrong:** the operator loses the session and cannot distinguish a
normal reboot from k3s/storage failure.

**Avoidance:** capture boot ID and pre-state, issue one authorized reboot, poll
SSH with a deadline, then wait separately for node Ready, PVC Bound, StatefulSet
Ready, Deployment Available, nginx active, and MCP behavior.

### Removing the legacy client too early

**What goes wrong:** public rollback succeeds but the operator has no usable
client registration.

**Avoidance:** add the new client only after live validation; keep the legacy
entry until rollback evidence is sealed; remove by exact configured name only.

### Capturing sensitive probe output

**What goes wrong:** token headers, corpus text, IDs, private paths, or payloads
land in CI logs or planning evidence.

**Avoidance:** probes emit only status, schema hashes, aggregate counts, boolean
checks, and sanitized failure codes; raw response bodies stay in restrictive
temporary storage and are deleted after digesting.

## Validation Architecture

### Test Framework

| Property | Value |
| --- | --- |
| Framework | Python `unittest` with PyYAML already available to the existing suite |
| Config file | none |
| Quick run command | `timeout 30s python3 -m unittest tests/test-memory-cutover-contract.py` |
| Full suite command | `timeout 90s python3 -m unittest tests/test-memory-runtime-contract.py tests/test-solidstats-memory-policy.py tests/test-solidstats-memory-migration.py tests/test-memory-cutover-contract.py` |

### Phase Requirements -> Test Map

| Req ID | Behavior | Test type | Automated command | File exists? |
| --- | --- | --- | --- | --- |
| ISO-01 | Exact new client name and legacy-removal ordering | contract | quick run command | No - Wave 0 |
| ISO-03 | Only nginx/MemPalace public; reciprocal private Qdrant path | manifest contract | quick run command plus source validators | Partial - extend existing tests |
| OPS-02 | Backup manifest/checksum/object prefix and one-shot run | unit + live integration | quick run; operator backup stage | Partial - current static contract only |
| OPS-03 | Absent target, isolated recovery, no force/overwrite | unit + live integration | quick run; operator restore stage | No - Wave 0 |
| OPS-05 | Auth/schema/recall/capture/restart/reboot matrix | unit + live acceptance | quick run; operator probe stages | No - Wave 0 |

### Sampling Rate

- **Per task commit:** quick Phase 21 contract suite plus relevant existing
  validator.
- **Per wave merge:** full suite with a supported Python runtime.
- **Phase gate:** offline suite green, then one complete live restore/cutover/
  rollback/restart/reboot evidence chain green.

### Wave 0 Gaps

- [ ] Repair or pin the Python runtime for the currently failing Phase 20
  inventory tests before reusing them as provenance evidence.
- [ ] Add `tests/test-memory-cutover-contract.py` covering transitions,
  idempotency, privacy, absent-target rejection, alias rollback, and probe schema.
- [ ] Extend `tests/test-memory-runtime-contract.py` and
  `scripts/validate-memory-manifests.py` for reciprocal MemPalace egress.
- [ ] Add synthetic Qdrant HTTP fixtures for create/download/upload/recover,
  alias pre-state/switch/rollback, and failure injection.
- [ ] Add a no-secret/no-private-path recursive validator for all Phase 21
  evidence outputs.

## Security Domain

### Applicable ASVS Categories

| ASVS category | Applies | Standard control |
| --- | --- | --- |
| V2 Authentication | yes | Token required on public MCP; missing/invalid/valid matrix; token never logged |
| V3 Session Management | yes | Real MCP initialization and session propagation/expiry behavior |
| V4 Access Control | yes | Namespace-scoped CI identity, private Qdrant, least-privilege NetworkPolicies |
| V5 Input Validation | yes | Strict schemas for target names, URLs, CIDRs, digests, run IDs, and evidence |
| V6 Cryptography | yes | TLS at nginx; SHA-256 for artifact integrity; no custom crypto |
| V8 Data Protection | yes | Value-free evidence, restrictive temporary files, no private paths or corpus output |
| V13 API and Web Service | yes | MCP protocol/schema validation, status handling, Origin/auth checks |

### Threat Model

| Threat | STRIDE | Mitigation |
| --- | --- | --- |
| Restore targets active collection | Tampering | Absent-target proof across collection and alias APIs; no force option |
| Handoff/bundle drift | Tampering | Recompute entire digest chain before private read and before mutation |
| Token/corpus leakage in evidence | Information disclosure | Environment/Secret inputs, redacted structured output, recursive privacy validator |
| Public Qdrant exposure | Information disclosure | ClusterIP only, default deny, negative reachability probe |
| DNS rebinding or untrusted Origin to MCP | Spoofing | Verify MemPalace Origin validation behavior and nginx host routing; MCP recommends Origin validation [CITED: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports] |
| Alias changed by concurrent operator | Tampering | Compare-and-switch using recorded alias pre-state and immediate read-back |
| Partial cutover after SSH loss | Denial of service | Idempotent staged manifests, local evidence journal, rollback from each state |
| Reboot returns pods but not data path | Denial of service | Full private/public behavior matrix after node Ready and workload Ready |

## Suggested Plan Decomposition

### Plan 21-01 - Offline control plane and blocker closure

Add the transition/evidence schemas, synthetic tests, privacy validator, supported
Python runtime gate, and reciprocal MemPalace-to-Qdrant egress. Keep all live
actions impossible in this plan.

### Plan 21-02 - Backup and isolated restore tooling

Implement provenance recomputation, unique physical names, absent-target guard,
candidate import, one-shot snapshot/metadata backup, checksum verification,
isolated snapshot recovery with `priority=snapshot`, restored parity, and alias
compatibility probe. Leave alias/public/client unchanged.

### Plan 21-03 - Reversible private and public cutover

Batch preflight, legacy-stack stop, alias switch, nginx install/backup/test/
reload, negative-auth and real MCP behavior probes, automatic rollback, and
`solidstats_memory` registration. Do not remove the legacy client.

### Plan 21-04 - Recovery and final seal

Prove MemPalace restart, Qdrant restart, one complete backup cycle, VPS reboot,
full post-recovery behavior, and an exercised rollback/forward cycle. Seal only
aggregate evidence, then remove or disable the legacy client by exact name.

## Open Questions

1. **What exact MemPalace-derived collection name should become the logical
   alias?** The Phase 20 public handoff intentionally exposes only the derivation
   digest, not the private value. Resolve it inside the operator run after all
   digests pass; never copy it into RESEARCH/PLAN files.
2. **Does the pinned MemPalace build treat a Qdrant alias exactly like its
   derived collection?** Qdrant supports it, but the exact image must be tested
   before the alias design is locked into live cutover.
3. **What is the consistency boundary of `/data/palace` metadata backup?** If
   MemPalace mutates it during capture, the recurring backup must quiesce writes
   or use a product-supported consistent export. The initial pre-client backup
   is naturally write-quiescent; do not generalize that to steady state without
   a live/source check.
4. **Which legacy client name is present machine-locally?** Discover with a
   redacted `codex mcp list`; never assume the exact name or remove a broad
   pattern.

## Environment Availability

| Dependency | Required by | Available | Version | Fallback |
| --- | --- | --- | --- | --- |
| Python | validators/tests | yes | 3.14.4 | Pin supported runtime if Wave 0 tests remain broken |
| kubectl | cluster operations | yes | 1.36.3 | none |
| Docker | exact-image/local gates | yes | 29.7.2 | cluster-only exact image gate |
| nginx | config validation | yes | 1.28.3 | validate on target host |
| Codex MCP CLI | client cutover | yes | installed | direct machine-local config only with explicit safe writer |
| Live k3s/VPS/S3 | restore/reboot evidence | not probed in research | unknown | operator-gated execution plan |

**Missing dependencies with no fallback:** live cluster, object-store, and reboot
availability are intentionally deferred to operator-gated execution.

## Sources

### Primary repository evidence (HIGH confidence)

- `21-CONTEXT.md`, `REQUIREMENTS.md`, `STATE.md`, `ROADMAP.md`
- Phase 20 summaries, handoff, parity report, and verification
- `k8s/memory/*.yaml`, `deploy-memory.yml`, nginx template, validators, tests,
  and `docs/solidstats-memory.md`

### Official external sources (MEDIUM confidence per research seam)

- [Kubernetes Network Policies](https://kubernetes.io/docs/concepts/services-networking/network-policies/)
- [Kubernetes StatefulSets](https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/)
- [Qdrant snapshots](https://qdrant.tech/documentation/snapshots/)
- [Qdrant migration and recovery](https://qdrant.tech/documentation/migration-recovery-options/)
- [Qdrant collection aliases](https://qdrant.tech/documentation/manage-data/collections/)
- [Qdrant recover API](https://api.qdrant.tech/master/api-reference/snapshots/recover-from-snapshot)
- [MCP Streamable HTTP transport](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)
- [MCP authorization](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization)

## Assumptions Log

| # | Claim | Section | Risk if wrong |
| --- | --- | --- | --- |
| A1 | [ASSUMED] The pinned MemPalace image can use a Qdrant alias as its derived collection. | Architecture | Requires a different reversible data switch if false. |
| A2 | [ASSUMED] `/data/palace` can be archived consistently while no captures are occurring. | Open Questions | Metadata backup may be inconsistent and OPS-02 would fail. |
| A3 | [ASSUMED] A one-shot in-cluster restore Job is preferable to workstation port-forward upload. | Suggested plans | Operator tooling and network-policy layout may differ. |

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH - all tools and runtime assets already exist locally.
- Architecture: MEDIUM - Qdrant recovery/alias behavior is official, but exact
  MemPalace alias compatibility requires a live gate.
- Pitfalls: HIGH - primary repository inspection plus official Kubernetes,
  Qdrant, and MCP documentation.
- Live environment: LOW - no cluster, S3, public endpoint, or reboot mutation was
  authorized or performed during research.

**Research date:** 2026-08-20
**Valid until:** 2026-09-19, unless Qdrant/MemPalace images or MCP client change.

## RESEARCH COMPLETE

Phase 21 is ready for planning after the planner treats the reciprocal
NetworkPolicy fix and the Phase 20 test-runtime repair as Wave 0 gates. No live
state was mutated during research.

<!-- markdownlint-enable MD013 -->
