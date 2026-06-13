# Retrospective: Solid Stats Infrastructure

A living record of what worked, what didn't, and patterns established per milestone.

## Milestone: v2.0 — Production-Ready Infra & kubectl-native CD

**Shipped:** 2026-06-13
**Phases:** 6 (06–11) | **Plans:** 21

### What Was Built

kubectl-native CD over a WireGuard tunnel (namespace-scoped SA-token, SSH/scp removed);
edge nginx/certbot/ufw idempotent adopt-reconcile bootstrap + reversible teardown; an
automated PostgreSQL restore drill in an ephemeral scratch DB; the `web` runtime slot;
30-day S3 retention on `backups/postgres/` (applied live); and a 4-gate reversible
production-cutover mechanism.

### What Worked

- **Live verification caught what offline never could.** Every "offline-verified" path that
  finally met real infrastructure surfaced bugs: CD had **6 latent ones** (process-substitution
  dying under `sudo`, the lazy WireGuard handshake never initiating, no kernel route to the
  tunnel IP, `xargs kubectl apply -f` swallowing files, the kubeconfig storing a CA *path* that
  a trap deleted, the namespace manifest the SA can't apply); the S3 probe surfaced an aws-cli
  `NoneType` crash and the Timeweb `delete-bucket-lifecycle` no-op. None were findable on paper.
- **Operator-gated, reversible, evidence-first.** Consequential steps (RBAC bootstrap, the WG
  peer, prod-bucket retention, the cutover) were each gated on explicit confirmation, made
  reversible where possible, and recorded with fresh evidence before being trusted.
- **User-run `!` scripts** cleanly sidestepped the cloud classifier's shared-infra write guards
  while keeping every mutation transparent and additive.

### What Was Inefficient

- Helper scripts accumulated in `~` and needed explicit cleanup (now a standing preference).
- A repo-local git `user.email` override silently mis-attributed every infra commit until noticed.
- The `milestone.complete` CLI clobbered STATE.md frontmatter with wrong progress numbers (manually fixed).

### Patterns Established

- **First-live-run is a verification phase, not a formality** — budget for bug-fixing when an
  offline-proven path first touches real infrastructure.
- **Empirical-proof-before-destructive-apply** for third-party API parity: raw-HTTP `--debug`
  probe → reversible round-trip → inventory/blast-radius review → gated apply.
- **Mechanism-live-verify without the consequential act** (cutover SELF_TEST + DRY_RUN + live
  edge readiness) when the real action is out of scope.

### Key Lessons

- Don't trust a high-level CLI's exit/stdout for control-flow gates against a non-AWS S3 — read
  the raw `<Code>`/HTTP status. The aws-cli `NoneType`-on-empty-`<Message>` 404 broke both the
  probe heuristic and the apply guard.
- Timeweb S3 lifecycle is **replace-only** (`delete-bucket-lifecycle` is a no-op) — plan
  retention changes as PUTs; there is no "remove".
- Keeping the production cutover out of scope was correct; verifying the *mechanism* (not flipping
  traffic) is the right way to close a milestone whose final act is intentionally deferred.

### Cost Observations

- Sessions: one long interactive operator session (recovered a hung prior v2 session).
- Model: Opus 4.8 (1M context) throughout.

---

## Cross-Milestone Trends

| Milestone | Phases | Shipped | Note |
|-----------|--------|---------|------|
| v1.0 Staging Foundation | 1–5 | 2026-05-10 | Reproducible staging; manual backup + restore-list gate |
| v2.0 Production-Ready Infra & kubectl-native CD | 6–11 | 2026-06-13 | kubectl-native CD live-verified; prod traffic flip deferred by scope |

**Recurring theme:** offline-proven artifacts reliably hide infra-contact bugs; the live
first-run is where they surface. Budget verification time accordingly, and prefer reversible,
operator-gated, evidence-first execution for anything that touches shared/production state.
