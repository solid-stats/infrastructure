<!-- markdownlint-disable MD013 -->

# Phase 20: Local Corpus Migration - Pattern Map

**Mapped:** 2026-08-20
**Files analyzed:** 7
**Analogs found:** 4 / 7

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
| --- | --- | --- | --- | --- |
| scripts/inventory-solidstats-memory.py | utility | file-I/O, transform | scripts/validate-solidstats-memory-policy.py | partial-match |
| scripts/build-solidstats-memory-bundle.py | utility | file-I/O, transform | scripts/render-memory-manifests.py | partial-match |
| scripts/verify-solidstats-memory-parity.py | utility | transform, request-response | No close analogue | none |
| tests/test-solidstats-memory-migration.py | test | transform | tests/test-solidstats-memory-policy.py | role-match |
| config/solidstats-memory/migration-policy.json | config | transform | existing file | exact |
| scripts/validate-solidstats-memory-policy.py | utility | file-I/O, transform | existing file | exact |
| tests/test-solidstats-memory-policy.py | test | transform | existing file | exact |

## Pattern Assignments

### scripts/inventory-solidstats-memory.py (utility, file-I/O and transform)

**Analog:** scripts/validate-solidstats-memory-policy.py

Use stdlib-only pure helpers, Path inputs, deterministic JSON, and a caller-owned CLI. Reject incomplete snapshots, unsafe paths, symlinks, duplicate IDs, and non-lossless metadata before emitting an artifact. Never print documents, metadata values, or secrets.

**Imports and root pattern** (scripts/validate-solidstats-memory-policy.py lines 4-11):

~~~python
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
~~~

**Streaming checksum pattern** (scripts/validate-solidstats-memory-policy.py lines 83-88):

~~~python
def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
~~~

Use exit 64 only for missing required configuration; validation failures return 1.

### scripts/build-solidstats-memory-bundle.py (utility, file-I/O and transform)

**Analog:** scripts/render-memory-manifests.py

Create a new output directory only, never append to a prior target. Process records deterministically, bind every artifact to checksums, and use the pinned v3.5.0 mapping oracle instead of independently recreating UUIDv5, payload, or collection naming.

**Exclusive-output pattern** (scripts/render-memory-manifests.py lines 27-34):

~~~python
if args.output_dir.exists():
    raise ValueError(f"output directory already exists: {args.output_dir}")
args.output_dir.mkdir()
for name in sorted(EXPECTED):
    shutil.copyfile(source_files[name], args.output_dir / name)
~~~

**CLI error boundary** (scripts/render-memory-manifests.py lines 37-42): catch ValueError, print the safe diagnostic to stderr, then exit 64.

### scripts/verify-solidstats-memory-parity.py (utility, transform and request-response)

**Analog:** No close end-to-end analogue.

Follow the existing validator error-accumulation model for deterministic local checks. Add an operator-gated Qdrant adapter only after proving a new empty, loopback-bound local collection. Compare source IDs, mempalace_id, source-derived UUIDv5 IDs, document hashes, canonical metadata hashes, source timestamps, vector evidence, and ordered recall fixtures. Exclude Qdrant ingestion updated_at from source equality.

**Error accumulation pattern** (scripts/validate-solidstats-memory-policy.py lines 91-138):

~~~python
errors: list[str] = []
for item in files:
    if not isinstance(item, dict):
        errors.append("every bundle file entry must be an object")
        continue
~~~

### tests/test-solidstats-memory-migration.py (test, transform)

**Analog:** tests/test-solidstats-memory-policy.py

Use unittest, load scripts through importlib.util, and make all bundles in TemporaryDirectory. Fixtures remain synthetic and non-secret; test pure inventory, mapping, and parity helpers independently of the operator-gated target.

**Module-loading pattern** (tests/test-solidstats-memory-policy.py lines 13-18):

~~~python
MODULE_PATH = ROOT / "scripts" / "validate-solidstats-memory-policy.py"
SPEC = importlib.util.spec_from_file_location("memory_policy_validator", MODULE_PATH)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)
~~~

**Temp-bundle assertion pattern** (tests/test-solidstats-memory-policy.py lines 49-70): build one malformed fixture, call the pure validator, and assert its exact expected error list. For subprocess boundaries, copy synthetic_environment and a ten-second timeout from tests/test-memory-runtime-contract.py lines 29-46. Never substitute the VPS.

### config/solidstats-memory/migration-policy.json (config, transform)

**Analog:** the existing committed migration policy.

Extend the single policy contract rather than creating a second schema. Keep literal fail-closed invariants, including migration_mode and legacy_writes_frozen (migration-policy.json lines 23-25). Add declarative bundle-schema names and attestations; never include source data, credentials, or credential-bearing URLs.

### scripts/validate-solidstats-memory-policy.py (utility, file-I/O and transform)

**Analog:** existing implementation.

Extend validate_policy and validate_bundle rather than adding a second validator. Preserve pure helpers returning list[str], exact type checks, lowercase SHA-256 enforcement, and safe-relative-path checks.

**Policy invariant loop** (scripts/validate-solidstats-memory-policy.py lines 58-80):

~~~python
for key, expected in required_values.items():
    if policy.get(key) != expected:
        errors.append(f"{key}: expected {expected!r}, got {policy.get(key)!r}")
~~~

**Bundle containment and digest pattern** (scripts/validate-solidstats-memory-policy.py lines 118-137): reject absolute and parent paths, require lowercase 64-character SHA-256 values, then compare the streamed digest. Extend this with resolved-under-root and symlink-escape checks.

### tests/test-solidstats-memory-policy.py (test, transform)

**Analog:** existing implementation.

Add one focused regression test per new policy or manifest invariant. Preserve exact malformed-fixture errors and use VALIDATOR.sha256 for valid digests (tests/test-solidstats-memory-policy.py lines 93-143).

## Shared Patterns

### Fail-closed validation

**Sources:** scripts/validate-solidstats-memory-policy.py lines 48-138; scripts/validate-memory-manifests.py lines 33-42.

Use ValueError for unreadable JSON and ValidationError plus require() for contract violations. Gather comparable file-entry errors, but abort before a target write when provenance or vector compatibility is absent.

### Determinism and artifact safety

**Sources:** scripts/render-memory-manifests.py lines 27-34; scripts/validate-solidstats-memory-policy.py lines 83-88.

Sort directory-derived work, create new output paths only, stream SHA-256, and retain only non-secret counts and hashes. Treat documents and metadata as untrusted data, never commands or diagnostics.

### Tests and isolation

**Source:** tests/test-memory-runtime-contract.py lines 29-46.

Use explicit synthetic environments, temporary directories, subprocess timeouts, and no ambient credentials. The isolated-Qdrant test is conditional integration work, never a reason to use the VPS or a shared collection.

## No Analog Found

| File | Role | Data Flow | Reason |
| --- | --- | --- | --- |
| scripts/verify-solidstats-memory-parity.py | utility | transform, request-response | No field/vector/recall parity tool exists. |
| scripts/inventory-solidstats-memory.py | utility | file-I/O, transform | No immutable Chroma snapshot inventory tool exists. |
| scripts/build-solidstats-memory-bundle.py | utility | file-I/O, transform | Existing renderer copies repository manifests, not a frozen corpus through the pinned oracle. |

## Metadata

**Analog search scope:** scripts/, tests/, config/solidstats-memory/
**Files scanned:** 12
**Pattern extraction date:** 2026-08-20

<!-- markdownlint-enable MD013 -->
