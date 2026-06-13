# Milestones

## v2.0 Production-Ready Infra & kubectl-native CD (Shipped: 2026-06-13)

**Phases completed:** 6 phases (06–11), 21 plans. In-scope work 100% complete; the
live production traffic flip (Phase 11) is deferred by scope per AGENTS.md (v2 targets
staging only).

**Key accomplishments:**

- **Phase 06 — kubectl-native CD (LIVE-VERIFIED).** SSH/scp deploy replaced by a
  WireGuard tunnel brought up in CI + a namespace-scoped `ci-deployer` ServiceAccount
  applying directly against the closed k3s API (`deploy-staging.yml`: PR validate+dry-run
  / master deploy split, single-deploy concurrency lock; `01-ci-rbac.yaml`; fail-closed
  WG handshake gate + SA-token kubeconfig builder; quarterly SA-token+WG rotation runbook).
  Proven end-to-end on real GitHub runners (PR #1 dry-run + master deploy green); **6 latent
  bugs found & fixed** (WG key via /dev/stdin under sudo, lazy-handshake init, kernel route
  to the tunnel IP, per-file `-f` for apply, kubeconfig `--embed-certs`, exclude 00-namespace).
- **Phase 07 — Edge automation (LIVE-VERIFIED).** Idempotent adopt-reconcile nginx/certbot/ufw
  bootstrap (verbatim vhost mirror with the `# CUTOVER` lever; certbot OnFailure drop-in;
  ufw split-tunnel 6443-on-wg0) + reversible teardown; `validate-edge.py`. All 6 VPS UAT
  checks passed; 2 live bugs fixed.
- **Phase 08 — Automated restore drill (LIVE-VERIFIED).** Ephemeral scratch-DB restore drill
  (`70-restore-drill.yaml`) with a CI guard blocking drill manifests from the CD path; drill
  PASSED on the cluster (26 tables / 303 267 rows to a scratch DB; postgres-0 untouched).
- **Phase 09 — `web` runtime wiring.** 0-replica `web` slot wired into the runtime + CD path.
- **Phase 10 — S3 lifecycle & retention (APPLIED LIVE).** 30-day retention on
  `backups/postgres/` + abort-incomplete-multipart 7d (`apply-s3-lifecycle.sh`,
  `backups-lifecycle.json`, 30-day floor enforced in CI). S3-03 empirically proven on live
  Timeweb S3 (GET/PUT/x-amz-expiration via a reversible round-trip); retention applied after
  a backup-inventory review (6 oldest of 37 backups async-expire). **Finding:** Timeweb
  `delete-bucket-lifecycle` is a no-op — a config is replace-only.
- **Phase 11 — Production cutover (mechanism LIVE-VERIFIED).** 4-gate reversible nginx
  upstream switch (`cutover.sh`: backup + green-diff coverage gates, byte-restore rollback,
  smoke-check auto-rollback, DRY_RUN) + `docs/cutover.md` + offline CI gate. Mechanism
  verified live (SELF_TEST rollback, DRY_RUN gates both ways + preview, live edge cutover-ready);
  the live production traffic flip is deferred by scope.

**Known deferred items (v2.x):** see STATE.md "Deferred Items" — Phase 6 doc-drift cleanup,
Phase 10 clean-bucket aws-cli guard fix, S3-04, CD-10, DRILL-05, CUT-05, and the Phase 11
live production flip (deferred by scope).

---
