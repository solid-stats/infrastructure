# Phase 21: Restore, Cutover & Recovery - Pattern Map

**Mapped:** 2026-08-20  
**Files analyzed:** 9 planned files  
**Analogs found:** 9 / 9

## File Classification

<!-- markdownlint-disable MD013 -->

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
| --- | --- | --- | --- | --- |
| `k8s/memory/30-network-policy.yaml` | config | request-response | `k8s/memory/30-network-policy.yaml` | exact |
| `scripts/validate-memory-manifests.py` | utility | transform | `scripts/validate-memory-manifests.py` | exact |
| `tests/test-memory-runtime-contract.py` | test | request-response | `tests/test-memory-runtime-contract.py` | exact |
| `tests/test-memory-cutover-contract.py` | test | transform | `tests/test-solidstats-memory-policy.py` | role-match |
| `scripts/validate-phase-21.py` | utility | transform | `scripts/verify-solidstats-memory-parity.py` | role-match |
| `scripts/restore-solidstats-memory.py` | service | request-response | `scripts/verify-solidstats-memory-parity.py` | data-flow-match |
| `scripts/probe-solidstats-memory.py` | utility | request-response | `k8s/memory/50-monitoring.yaml` | data-flow-match |
| `scripts/cutover-solidstats-memory.sh` | utility | event-driven | `scripts/cutover.sh` | role-match |
| `docs/solidstats-memory.md` | config | event-driven | `docs/solidstats-memory.md` | exact |

`k8s/memory/restore-drill/` is optional. If selected, classify its manifest as a `config` file with `batch` flow and copy the existing `k8s/staging/restore-drill/70-restore-drill.yaml`/`scripts/restore-drill.sh` Job-plus-wrapper pattern; do not add it to the CI workload list.

<!-- markdownlint-enable MD013 -->

## Pattern Assignments

<!-- markdownlint-disable MD013 -->

### `k8s/memory/30-network-policy.yaml` (config, request-response)

**Analog:** the existing same-namespace, least-privilege policy pairs in this file.

**Manifest pattern** ([`k8s/memory/30-network-policy.yaml`](/home/afgan0r/Projects/SolidGames/infrastructure/k8s/memory/30-network-policy.yaml:13)):

```yaml
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: solidstats-memory-backup
  policyTypes: [Egress]
  egress:
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: qdrant
      ports:
        - protocol: TCP
          port: 6333
```

Add the equivalent MemPalace-selected `Egress` to Qdrant TCP/6333. Keep the existing Qdrant-selected `Ingress` policy name and add no broad namespace, CIDR, or extra port. The default-deny policy remains authoritative.

### `scripts/validate-memory-manifests.py` (utility, transform)

**Analog:** its exact-string, fail-closed contracts.

**Imports and error pattern** ([`scripts/validate-memory-manifests.py`](/home/afgan0r/Projects/SolidGames/infrastructure/scripts/validate-memory-manifests.py:1)):

```python
class ValidationError(Exception):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)
```

**Network contract pattern** ([`scripts/validate-memory-manifests.py`](/home/afgan0r/Projects/SolidGames/infrastructure/scripts/validate-memory-manifests.py:110)):

```python
policies = {key for key in docs if key.startswith("NetworkPolicy/")}
require(required <= policies, f"network policies missing: {sorted(required - policies)}")
...
require(
    observer_egress.split("spec:\n", 1)[-1].strip()
    == expected_observer_egress.split("spec:\n", 1)[-1].strip(),
    "observer egress must retain only its DNS, MemPalace TCP 8765, and Qdrant TCP 6333 paths",
)
```

Extend `require_network_contract()` with an exact expected MemPalace egress shape and a failure message that rejects drift/broadened access. Preserve source-vs-rendered placeholder branching and the single `main()` error boundary.

### `tests/test-memory-runtime-contract.py` (test, request-response)

**Analog:** `MemoryObserverContractTests`, which parses checked-in YAML and asserts both halves of a reciprocal policy.

**Test pattern** ([`tests/test-memory-runtime-contract.py`](/home/afgan0r/Projects/SolidGames/infrastructure/tests/test-memory-runtime-contract.py:366)):

```python
documents = yaml.safe_load_all((ROOT / "k8s/memory/30-network-policy.yaml").read_text())
return {
    document["metadata"]["name"]: document
    for document in documents
    if document and document["kind"] == "NetworkPolicy"
}
```

```python
expected_tuple = {
    "to": [{"podSelector": {"matchLabels": {"app.kubernetes.io/name": "mempalace"}}}],
    "ports": [{"protocol": "TCP", "port": 8765}],
}
self.assertIn(expected_tuple, egress["egress"])
```

Add an analogous `mempalace -> qdrant` assertion plus mutation subtests that reject wildcard selectors, namespace/CIDR expansion, wrong labels, ports, and policy direction.

### `tests/test-memory-cutover-contract.py` (test, transform)

**Analog:** [`tests/test-solidstats-memory-policy.py`](/home/afgan0r/Projects/SolidGames/infrastructure/tests/test-solidstats-memory-policy.py:1) and the isolated JSON contract helpers in [`scripts/verify-solidstats-memory-parity.py`](/home/afgan0r/Projects/SolidGames/infrastructure/scripts/verify-solidstats-memory-parity.py:436).

**Contract style**:

```python
with self.assertRaises(ParityFailure):
    write_phase21_handoff(output, malformed_payload)
```

Use synthetic Qdrant HTTP fixtures only. Cover absent physical target checks, state-transition ordering/idempotency, alias pre-state/rollback, secret/private-value rejection, and the status/schema-only probe report. No live endpoint, credentials, corpus payloads, or actual client registration belongs in this test.

### `scripts/validate-phase-21.py` (utility, transform)

**Analog:** [`scripts/verify-solidstats-memory-parity.py`](/home/afgan0r/Projects/SolidGames/infrastructure/scripts/verify-solidstats-memory-parity.py:84).

**Safe file and digest pattern**:

```python
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
```

```python
if candidate.is_absolute() or ".." in candidate.parts:
    raise ParityFailure(f"{label} provenance is unsafe")
```

Implement schema-version allowlists, recursive value-free evidence validation, and recomputed handoff/bundle/parity digests before any private read or live request. Return nonzero through a dedicated exception; emit aggregate booleans/counts and digests only.

### `scripts/restore-solidstats-memory.py` (service, request-response)

**Analog:** Phase 20 provenance plus evidence-hand-off writer in [`scripts/verify-solidstats-memory-parity.py`](/home/afgan0r/Projects/SolidGames/infrastructure/scripts/verify-solidstats-memory-parity.py:143).

**Gate-before-access pattern**:

```python
proof = _regular_file(inventory_proof, "source inventory proof")
contract_path = _regular_file(mapping_contract, "mapping contract")
manifest = _load_json(transform_manifest, "transform manifest")
...
if proof_digest != expected_proof or contract_digest != expected_contract:
    raise ParityFailure("transform provenance digest mismatch")
```

**Evidence allowlist pattern** ([`scripts/verify-solidstats-memory-parity.py`](/home/afgan0r/Projects/SolidGames/infrastructure/scripts/verify-solidstats-memory-parity.py:457)):

```python
allowed = {"handoff_schema", "source_inventory_sha256", "mapping_contract_sha256", ...}
if set(payload) != allowed or payload.get("handoff_schema") != "solidstats-memory-phase21-handoff/v1":
    raise ParityFailure("handoff schema is invalid")
```

Use one Python control plane with explicit `preflight`, `stage`, `snapshot`, `isolated-restore`, `verify`, `alias-cutover`, and `rollback` commands. Bind each stage to the same run ID and prior evidence digest. Query collections and aliases before recovery; if the generated physical target already exists, stop rather than choose another target or use force. Use `priority=snapshot` and write no alias/client/nginx change before parity and compatibility gates pass.

### `scripts/probe-solidstats-memory.py` (utility, request-response)

**Analog:** bounded HTTP parsing in [`k8s/memory/50-monitoring.yaml`](/home/afgan0r/Projects/SolidGames/infrastructure/k8s/memory/50-monitoring.yaml:53).

**Probe parsing pattern**:

```python
snapshot_ok, snapshot_body, _ = probe_http(
    "http://qdrant:6333/collections/" + collection + "/snapshots", headers
)
snapshot = latest_snapshot_timestamp(snapshot_body) if snapshot_ok else None
```

Keep raw public/private responses in restrictive temporary storage only long enough to derive status, schema hashes, and aggregate counters. The committed evidence must include negative-auth outcomes, MCP initialize/tools/call outcomes, scoped recall/miss fallback, archive label, capture/read-back, and private Qdrant boundary checks—never headers, token values, identifiers, vectors, documents, or paths.

### `scripts/cutover-solidstats-memory.sh` (utility, event-driven)

**Analog:** [`scripts/cutover.sh`](/home/afgan0r/Projects/SolidGames/infrastructure/scripts/cutover.sh:1).

**Required-input pattern**:

```bash
required() {
  local var="$1"
  if [[ -z "${!var:-}" ]]; then
    echo "FATAL: ${var} is required but not set" >&2
    exit 64
  fi
}
```

**Single rollback pattern** ([`scripts/cutover.sh`](/home/afgan0r/Projects/SolidGames/infrastructure/scripts/cutover.sh:84)):

```bash
rollback() {
  cp "${BAK_VHOST}" "${VHOST_CONF}"
  if ! ${NGINX_T_CMD} 2>&1; then
    echo "FATAL: nginx -t failed after rollback restore" >&2
    exit 1
  fi
  ${NGINX_RELOAD_CMD}
}
```

Keep Bash thin: resolve the repository root, require non-secret control inputs, call the Python stage/probe tools in a batched remote sequence, and preserve pre-state before mutation. One real rollback path must restore client state, nginx bytes/symlink state, alias state, and workload/legacy state in reverse order. Test that same path offline with injected commands; CI must not invoke cutover, host nginx mutations, registration, restart, or reboot.

### `docs/solidstats-memory.md` (config, event-driven)

**Analog:** its existing ordered migration and explicit safety boundary ([`docs/solidstats-memory.md`](/home/afgan0r/Projects/SolidGames/infrastructure/docs/solidstats-memory.md:101)).

```markdown
9. Create a Qdrant snapshot and MemPalace metadata archive with manifest and checksums.
10. Stop the old VPS stack before starting the new long-running stack.
11. Deploy, restore in isolation, validate, cut over `/solidstats/mcp`, and then register only the `solidstats_memory` MCP client.
```

Replace this high-level tail with the exact operator state sequence, per-stage aggregate evidence paths, required authorization checkpoints, rollback command, restart/reboot matrix, and the delayed legacy-removal rule. Retain the explicit no-secret/private-artifact guidance and keep Phase 22 archive distillation out of scope.

<!-- markdownlint-enable MD013 -->

## Shared Patterns

<!-- markdownlint-disable MD013 -->

### Fail-Closed Provenance and Privacy

**Sources:** [`scripts/verify-solidstats-memory-parity.py`](/home/afgan0r/Projects/SolidGames/infrastructure/scripts/verify-solidstats-memory-parity.py:143), [`scripts/verify-solidstats-memory-parity.py`](/home/afgan0r/Projects/SolidGames/infrastructure/scripts/verify-solidstats-memory-parity.py:457)

Apply to every new Python tool and evidence report: validate an exact schema/allowlist, reject unsafe paths, recompute SHA-256 before private access, and print only approved aggregate fields.

### Kubernetes Network Isolation

**Sources:** [`k8s/memory/30-network-policy.yaml`](/home/afgan0r/Projects/SolidGames/infrastructure/k8s/memory/30-network-policy.yaml:1), [`scripts/validate-memory-manifests.py`](/home/afgan0r/Projects/SolidGames/infrastructure/scripts/validate-memory-manifests.py:110)

Apply to the reciprocal MemPalace/Qdrant change: retain default deny, select exact pods, permit only TCP/6333, and assert the full policy shape in both validator and test.

### Reversible Operator Mutations

**Sources:** [`scripts/cutover.sh`](/home/afgan0r/Projects/SolidGames/infrastructure/scripts/cutover.sh:84), [`scripts/restore-drill.sh`](/home/afgan0r/Projects/SolidGames/infrastructure/scripts/restore-drill.sh:1)

Apply to all live stages: required-input exit `64`, bounded waits, explicit success marker, one actual rollback function, and cleanup only after success. No live operation is a CI deployment step.

### Backup Package Shape

**Source:** [`k8s/memory/40-backup.yaml`](/home/afgan0r/Projects/SolidGames/infrastructure/k8s/memory/40-backup.yaml:49)

The one-shot backup should derive from the suspended CronJob: Qdrant snapshot download, `/metadata/palace` archive, `SHA256SUMS`, and a minimal manifest uploaded under one run prefix. Keep `suspend: true` until the isolated drill is verified.

<!-- markdownlint-enable MD013 -->

## No Analog Found

<!-- markdownlint-disable MD013 -->

| File | Role | Data Flow | Reason |
| --- | --- | --- | --- |
| `scripts/restore-solidstats-memory.py` | service | request-response | No existing tool performs Qdrant snapshot recovery, absent-target proof, alias switching, and stage-bound rollback; compose it from the Phase 20 provenance and existing operator-control patterns. |
| `scripts/probe-solidstats-memory.py` | utility | request-response | Existing probes monitor Qdrant readiness only; Phase 21 needs a real MCP initialize/tools/call matrix plus negative authentication checks. |

<!-- markdownlint-enable MD013 -->

## Metadata

**Analog search scope:** `k8s/memory/`, `scripts/`, `tests/`, `docs/`,
`.github/workflows/`, and Phase 20 artifacts  
**Files scanned:** 20  
**Pattern extraction date:** 2026-08-20
