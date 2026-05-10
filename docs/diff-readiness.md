# Diff and Cutover Readiness

This document defines the old-vs-new statistics comparison contract. It is a
review gate only; it does not approve production traffic cutover.

## Comparison inputs

- Old statistics export or query result from the current trusted source.
- New statistics export or query result produced after the controlled full run.
- Allowlist file for known acceptable differences.
- Metadata: source timestamps, full-run Job name, backup id, and operator.

## Execution path

1. Confirm `docs/backup-gate.md` has a verified backup.
2. Confirm the controlled full run has completed and its Job/log evidence is
   recorded.
3. Export old and new statistics into deterministic files.
4. Run the comparison tool from the app or operator workspace.
5. Store the diff output with the full-run evidence.

## Output shape

Diff output must include:

- `strict_failures`: differences that block review.
- `allowlisted_known_differences`: differences accepted by the allowlist.
- `summary`: counts by category and data source.
- `inputs`: old/new input identifiers and timestamps.
- `decision`: `review_required`, never `approved_for_cutover`.

## Strict failures

Strict failures include missing players, missing matches, changed aggregate
totals outside tolerance, parser errors, failed exports, or any unexplained
difference not present in the allowlist.

## Allowlisted known differences

Allowlisted known differences must include:

- stable identifier
- reason
- expected old value or range
- expected new value or range
- expiration or review date

## Production cutover remains blocked

Production cutover remains blocked until a human reviews the diff output and a
separate v2 production cutover plan is approved. A clean diff is evidence for
review; it is not automatic approval to switch traffic.
