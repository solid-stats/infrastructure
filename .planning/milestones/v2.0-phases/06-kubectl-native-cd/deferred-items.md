# Deferred Items — Phase 06 (kubectl-native-cd)

Out-of-scope discoveries logged during execution. NOT fixed (scope boundary: only
issues directly caused by the current task are auto-fixed).

## D-06-01: validate-staging.py manifest_shape fails on 01-ci-rbac.yaml — RESOLVED

- **Discovered during:** Plan 06-04, Task 2 (after deleting scripts/deploy-staging.sh)
- **Status:** RESOLVED during phase-6 closure (orchestrator regression fix). The CI
  validate job runs `python3 scripts/validate-staging.py`, so a hard failure here broke
  the whole CD pipeline — fixed rather than deferred.
- **Symptom (original):** `python3 scripts/validate-staging.py` exited 1 with
  `error: k8s/staging/01-ci-rbac.yaml document missing apiVersion`.
- **Root cause:** 01-ci-rbac.yaml begins with a 4-line operator comment block before
  the first `---`. validate-staging.py's `split_documents()` treated those leading
  comment lines as the first YAML document; `top_value(doc, "apiVersion")` returned
  None for it, tripping the `require(api_version is not None, ...)` assertion in
  `validate_manifest_shape()`. Originally introduced by plan 06-01 (commit 4667fb1).
- **Fix:** Added a `_has_yaml_content()` helper so `split_documents()` only counts a
  block as a document when it has a non-comment, non-blank line. Comment-only/whitespace
  preambles are skipped (standard null-document behaviour); real documents are unaffected.
- **Also fixed (related hang):** The local `kubectl apply --dry-run=client` call had no
  timeout, so once manifest_shape passed it would block forever against an unreachable
  cluster (VPN black-holing packets gives no fast "connection refused"). Added a 15s
  timeout; a `TimeoutExpired` is now treated as "cluster unreachable" (warn + skip),
  matching the CI validate job which has no kubectl on PATH. `validate-staging.py` now
  exits 0 both locally and in CI.
