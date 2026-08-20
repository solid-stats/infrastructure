---
status: resolved
trigger: >-
  The real source inventory rejected record 2064 after the source-boundary
  repair with a value-free invalid-record digest.
created: 2026-08-20
updated: 2026-08-20
---

# Debug Session: Real Corpus Secret Lexeme Gap

## Symptoms

- Expected: source admission preserves valid legacy metadata verbatim while
  emitting only value-free aggregate evidence.
- Actual: records 1 through 2063 passed; record 2064 failed with the digest
  for the fixed `invalid` category.

## Evidence

- The failure digest is the canonical SHA-256 for `{"kind":"invalid"}`.
  [`_validated_record`](../../scripts/inventory-solidstats-memory.py) emits
  that category only after a document, metadata, vector, or combined-record
  validation failure.
- The main-owned value-free probe reported
  `record=2064 category=metadata_secret_value detail=secret:lexical_only`.
- The probe checked assignment, bearer, URI-userinfo, JWT, and AWS-key
  credential syntax and found none. This is not evidence that the metadata
  value contains no secret by every possible definition.
- Source ID, mapping, oracle protocol, and the removed target timestamp,
  wing, and room eligibility checks were not the failing branch.

## Root Cause

`lossless_metadata()` calls `_reject_secret_shape()` before canonical JSON
losslessness. `_reject_secret_shape()` recursively applies the secret regex to
every metadata string, so ordinary prose containing the lexical term `secret`
is rejected as `metadata_secret_value` before preservation or value-free
evidence generation.

This contradicts the Plan 20-07 source boundary: metadata must be preserved
without invention, while source diagnostics never emit metadata values. The
plan intentionally retains secret-shaped key rejection, bounds, losslessness,
and all protocol safety gates; the defect is the value-text heuristic at source
admission, not removal of those safeguards.

## Impact

- The inventory cannot complete the frozen corpus, blocking the later explicit
  mapping decision and transform plans.
- The failed run produces no accepted partial inventory because the wrapper
  discards incomplete output.
- No corpus value, ID, document, vector, credential, or private path is
  recorded in this report.

## Minimal Safe Fix Direction

Create a new gap plan. In source admission only, replace recursive
metadata-value lexical matching with a metadata-key-only secret-shape guard.
Allow ordinary metadata prose to pass unchanged when it has no recognized
credential syntax.

Retain all of the following unchanged: rejection of secret-shaped metadata
keys; recursive sidecar and freeze-attestation secret checks; private output
permissions; value-free diagnostics; repository evidence privacy rejection;
metadata/document/vector/record bounds; lossless canonicalization; ID,
snapshot, oracle, and protocol validation.

## Required Regression Coverage

1. A synthetic ordinary-prose metadata value containing the lexical term
   `secret` is accepted and retains exact metadata object, canonical bytes,
   key set, and digest.
2. A synthetic secret-shaped metadata key remains rejected with a value-free
   record diagnostic.
3. Existing credential-shaped sidecar, freeze-attestation, metadata-key,
   bounds, losslessness, ID, vector, snapshot-drift, oracle, and protocol
   regression tests stay green.
4. The new test must use only synthetic values and assert that summary evidence
   contains no metadata values, identifiers, documents, vectors, or paths.

## Resolution

- root_cause: recursive lexical scanning of metadata values treats ordinary
  prose as a secret before source metadata is preserved.
- fix: not applied; implementation belongs in a new gap plan.
- verification: value-free main-owned probe isolated record 2064 to
  `metadata_secret_value` with `secret:lexical_only`; the listed recognized
  credential syntaxes did not match.
- files_changed: .planning/debug/real-corpus-secret-lexeme-gap.md
