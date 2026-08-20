---
status: resolved
trigger: >-
  Exact-image inventory completes record processing but fails the end snapshot
  digest check when the v3.5.0 Chroma reader opens the writable working copy.
created: 2026-08-20
updated: 2026-08-20
---

# Debug Session: Real Corpus Oracle Scratch Gap

## Symptoms

- Expected behavior: the exact-image inventory reads the immutable snapshot,
  emits its private inventory, and confirms equal start and end snapshot
  digests.
- Actual behavior: record processing completes, then the inventory fails with
  `snapshot digest changed`; incomplete output is discarded.
- Reproduction: mount the authoritative snapshot read-only, make a writable
  working copy, and run the full exact v3.5.0 inventory against that copy.

## Evidence

- The inventory calculates its start digest from `snapshot_dir`, resolves the
  Chroma `palace_root` beneath that same directory, and calculates its end
  digest from the same root.
- `_oracle_rows()` passes that `palace_root` as `--palace-path` to the
  generated v3.5.0 reader.
- `_oracle_program()` opens `--palace-path` with
  `chromadb.PersistentClient`, then reads its collection through the exact
  reader protocol.
- The pinned v3.5.0 Chroma backend treats palace open as potentially mutable:
  its pre-open flow includes SQLite repairs, marker writes, and HNSW quarantine
  renames before creating a persistent client.
- The generated reader uses the raw client path rather than that backend
  pre-open flow, so the exact internal ChromaDB write site is outside the
  pinned source contract inspected here. The observed drift nevertheless proves
  that a stateful reader received a path within the digest target.

## Root Cause

The writable Chroma working copy was used both as the snapshot digest target
and as the persistent storage path supplied to the exact oracle. This aliases
the digest gate with a stateful reader's service area: any read-time Chroma
maintenance changes the tree being measured and causes a self-induced digest
failure.

The failure requires both conditions: the oracle must receive a writable
palace path and that path must be inside the digest target. It is not evidence
that the authoritative source changed.

## Why the Authoritative Source Remained Unchanged

The authoritative source was mounted read-only and was never supplied to the
oracle. The failed digest applied to its writable copy instead. Consequently,
the gate correctly observed a change to the copy but could not distinguish
oracle-owned maintenance from an external source writer.

## Minimal Fix

Keep the authoritative snapshot as the only `snapshot_dir` and digest target.
After validating the snapshot contract, create a private
`tempfile.TemporaryDirectory` scratch area and use `shutil.copytree` to copy
only the validated `palace_root` into it. Validate the copied tree before use.
Pass that scratch palace path, rather than the authoritative `palace_root`, to
`_oracle_rows()` and therefore to `_oracle_program()`.

The scratch directory must be created under a caller-controlled writable
temporary mount, use the existing no-symlink checks, and be removed after the
oracle iterator has been closed. The parent keeps all sidecar validation,
bounded oracle protocol checks, network isolation, private-output permissions,
and the final authoritative snapshot digest comparison unchanged.

## Rejected Alternatives

- Hash the writable working copy after the oracle: rejected because it hides
  the drift condition the gate is supposed to detect.
- Give the oracle the read-only authoritative palace: rejected because the
  exact Chroma reader needs writable persistent storage in this environment.
- Replace `PersistentClient` with a different reader: rejected because it
  changes the pinned v3.5.0 oracle semantics.
- Copy the entire snapshot for the oracle: safe but unnecessary; the oracle
  needs only `palace_root`, while the parent already validates sidecars.
- Use hard links or shared storage for the scratch palace: rejected because
  writes could still affect authoritative digest inputs.

## Required Observable Synthetic Regressions

1. A synthetic subprocess oracle writes a marker under the `--palace-path` it
   receives. Inventory succeeds, the authoritative snapshot digest remains
   unchanged, the marker is absent from the authoritative tree, and no scratch
   directory remains after cleanup. Run this for full inventory and check-only
   protocol paths.
2. A separate synthetic writer changes the authoritative snapshot during full
   inventory. The inventory must fail with `snapshot digest changed` and remove
   incomplete output. This proves the final digest still detects real source
   drift after oracle isolation.

These tests must drive the real subprocess and filesystem paths rather than
mocking the digest helper or asserting only argument wiring.

## Exact-Image Rerun Shape

Run with networking disabled. Mount the authoritative snapshot read-only at
`/snapshot`, a writable tmpfs at `/tmp` for the oracle scratch, and a separate
host-private writable mount at `/private` for final inventory output. Pass
`/snapshot` as `--snapshot-dir` and place `--output-dir` below `/private`.

Do not pre-copy the authoritative snapshot into the work area. The production
CLI creates and cleans its own scratch copy of `palace_root` under `/tmp`; final
private output remains outside tmpfs.

## Resolution

- root_cause: a writable oracle palace was nested inside the tree protected by
  the snapshot start/end digest gate.
- fix: implementation pending; isolate the oracle with a temporary copy of
  `palace_root` while digesting the authoritative read-only snapshot.
- verification: static call-graph tracing, pinned v3.5.0 source inspection,
  and value-free exact-image failure evidence agree on the path alias.
- files_changed: `.planning/debug/real-corpus-oracle-scratch-gap.md`
