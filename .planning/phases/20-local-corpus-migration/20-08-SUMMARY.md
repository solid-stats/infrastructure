---
phase: 20-local-corpus-migration
plan: 08
subsystem: migration-governance
tags: [mempalace, qdrant, migration, approval, provenance]
requires:
  - phase: 20-04
    provides: sanitized immutable-source inventory proof
provides:
  - approved inventory-bound mapping contract
  - fail-closed routing and preservation rules for Plan 20-05
affects: [20-05, 20-06, MIG-02]
actuals:
  tokens: 3668
  tasks: 1
  commits: 3
tech-stack:
  added: []
  patterns:
    - canonical JSON SHA-256 approval binding
    - public-rule-only migration governance artifacts
key-files:
  created:
    - .planning/phases/20-local-corpus-migration/20-MAPPING-CONTRACT.json
    - .planning/phases/20-local-corpus-migration/20-08-SUMMARY.md
  modified:
    - .planning/STATE.md
    - .planning/ROADMAP.md
key-decisions:
  - Exact source timestamp fields are preserved without precedence, normalization, or synthesis.
  - Canonical repository wings route only to their corresponding public archive wings.
  - The source metadata dictionary is nested under _solidstats_migration for exact parity.
requirements-completed: []
coverage:
  - id: D1
    description: Approved mapping contract is complete, inventory-bound, and privacy-scoped.
    verification:
      - kind: other
        ref: Plan 20-08 contract and strengthened JSON/privacy validation commands
        status: pass
    human_judgment: false
duration: 20 min
completed: 2026-08-20
status: complete
---

# Phase 20 Plan 08: Approved Mapping Contract Summary

The approved contract preserves source evidence exactly while routing eligible
repository records into immutable public archive wings for the later local
transform.

## Performance

- **Duration:** 20 min
- **Completed:** 2026-08-20T07:44:18Z
- **Tasks:** 1/1
- **Files modified:** 4

## Accomplishments

- Recorded the complete approved routing, timestamp, legacy-label, exclusion,
  and preservation decisions in the required contract shape.
- Bound the contract to the exact current source-inventory file bytes and to
  the explicit `approve-complete-contract` approval token.
- Kept the contract limited to public rules and labels; it contains no corpus
  records, source identifiers, documents, metadata values, vectors, private
  paths, environment values, or credentials.

## Approval Binding

`approval_digest` is SHA-256 over the UTF-8 canonical JSON representation of
the contract with `approval_digest` omitted. Object keys are recursively sorted,
array order is retained, and compact JSON separators are used. The resulting
payload binds the approval token, approval time, inventory-file digest, and all
normalized decision rules.

## Task Commits

1. **Task 1: Approve the exact inventory-bound mapping contract** — `9d8b54e`
   (`docs`)
2. **Task 1 correction: bind the approval token in the digest** — `649fdfc`
   (`fix`)

## Files Created/Modified

- `.planning/phases/20-local-corpus-migration/20-MAPPING-CONTRACT.json` —
  approved public mapping and preservation rules.
- `.planning/phases/20-local-corpus-migration/20-08-SUMMARY.md` — plan
  closeout, validation evidence, and downstream boundary.
- `.planning/STATE.md` — advances the current plan to 20-05.
- `.planning/ROADMAP.md` — records Plan 20-08 as complete.

## Decisions Made

- Preserve `content_date`, `filed_at`, and `source_mtime` exactly as found;
  missing or invalid candidates never discard a record.
- Route the five registry-backed platform wings to their matching `*-archive`
  wings and route the shared `SolidStats` wing to `SolidStats-archive`.
- Exclude agent and other-wing records from target import without deleting their
  immutable snapshot or private evidence.
- Preserve legacy rooms unchanged and fail closed on unexpected or unbound
  archive labels.
- Preserve exact original metadata inside `_solidstats_migration.source_metadata`
  while operational metadata changes only the archive-routing wing; fail closed
  on a reserved-key collision.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Bound the explicit approval token into the digest**

- **Found during:** Task 1
- **Issue:** The first digest payload did not include the exact approval token.
- **Fix:** Added the token to the existing preservation representation and
  recomputed the canonical approval digest.
- **Files modified:** `20-MAPPING-CONTRACT.json`
- **Verification:** The strengthened contract check recomputed the digest and
  required the token.
- **Committed in:** `649fdfc`

**Total deviations:** 1 auto-fixed (Rule 2 - Missing Critical)

## Issues Encountered

None after the approval-token binding correction.

## Known Stubs

None.

## Next Phase Readiness

Plan 20-05 is next and may consume this approved, current inventory-bound
contract. MIG-02 transform, import, field parity, vector parity, recall parity,
deployment, cutover, and external mutation remain unclaimed.

## Self-Check: PASSED

- The approved contract and summary exist at their required phase paths.
- Task commits `9d8b54e` and `649fdfc` exist in the repository history.
- The contract, JSON/privacy checks, Markdown lint, and diff check passed.
