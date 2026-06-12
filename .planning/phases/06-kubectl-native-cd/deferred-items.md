# Deferred Items — Phase 06 (kubectl-native-cd)

Out-of-scope discoveries logged during execution. NOT fixed (scope boundary: only
issues directly caused by the current task are auto-fixed).

## D-06-01: validate-staging.py manifest_shape fails on 01-ci-rbac.yaml

- **Discovered during:** Plan 06-04, Task 2 (after deleting scripts/deploy-staging.sh)
- **Status:** Pre-existing — present at base HEAD 49084be, introduced by plan 06-01
  (commit 4667fb1 added k8s/staging/01-ci-rbac.yaml).
- **Symptom:** `python3 scripts/validate-staging.py` exits 1 with
  `error: k8s/staging/01-ci-rbac.yaml document missing apiVersion`.
- **Root cause:** 01-ci-rbac.yaml begins with a 4-line operator comment block before
  the first `---`. validate-staging.py's `split_documents()` treats those leading
  comment lines as the first YAML document; `top_value(doc, "apiVersion")` returns
  None for it, tripping the `require(api_version is not None, ...)` assertion in
  `validate_manifest_shape()`.
- **Why deferred:** Not caused by Plan 06-04's changes. Verified failing identically
  at base HEAD before deleting deploy-staging.sh. The Plan 06-04 deviation (removing
  the deploy-staging.sh script-syntax check) is correct and independent — the
  `script syntax` check now passes (`ok: script syntax`).
- **Suggested fix (separate plan):** Make `split_documents()` skip comment-only /
  whitespace-only documents, or strip a leading comment preamble before the first
  `---`. Then re-confirm validate-staging.py exits 0.
