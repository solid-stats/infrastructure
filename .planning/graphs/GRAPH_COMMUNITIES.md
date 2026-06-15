# Graph Communities — infrastructure

_22 communities, named by member analysis (no LLM API used). Source: `.planning/graphs/graph.json`._

| # | Name | Purpose | Key files |
|---|------|---------|-----------|
| 0 | **Staging Manifest Validation** | Validates staging Kubernetes manifests, secrets, workloads, and image pins against expected structure and configurations. | scripts/validate-staging.py<br>scripts/validate-s3-lifecycle.py |
| 1 | **Observability Manifests Validation** | Static gate ensuring observability manifests have no secret values, correct namespace declarations, and required PriorityClass labels. | scripts/validate-obs-manifests.py |
| 2 | **Observability Edge Bootstrap** | Validates observability edge bootstrap scripts, nginx vhost configurations for Grafana and error tracking, and Phase 14 systemd artifacts. | scripts/validate-obs-edge.py<br>scripts/bootstrap-obs-edge.sh |
| 3 | **Edge Infrastructure Validation** | Offline validator for Phase 7 edge automation artifacts including nginx vhosts, systemd drop-ins, shell scripts, and idempotency markers. | scripts/validate-edge.py<br>scripts/bootstrap-edge.sh |
| 4 | **S3 Lifecycle Configuration** | Validates S3 lifecycle JSON structure and apply-s3-lifecycle.sh script syntax for backup retention policies. | scripts/validate-s3-lifecycle.py<br>scripts/apply-s3-lifecycle.sh |
| 5 | **Error Tracking System Validation** | Phase 16 live assertion harness validating error tracking system health, forced-error ingest, and API connectivity. | scripts/validate-phase-16.sh |
| 6 | **Production Upstream Cutover** | Reversible production upstream switch for stats-staging.solid-stats.ru with rollback capability across 4 gates. | scripts/cutover.sh |
| 7 | **Observability Readiness Assertions** | Phase 13 live assertions covering observability metric and health endpoint validation across the monitoring stack. | scripts/validate-phase-13.sh |
| 8 | **Logging System Assertions** | Phase 15 live assertions validating log ingestion from application workloads into the observability stack. | scripts/validate-phase-15.sh |
| 9 | **Phase 12 Infrastructure Validation** | Assertion harness validating staging infrastructure preparation and resource allocation before workload deployment. | scripts/validate-phase-12.sh |
| 10 | **Kubernetes Cluster Access Setup** | Constructs kubeconfig from ServiceAccount token and CA certificate for kubectl authentication to staging k3s cluster. | scripts/kubeconfig-setup.sh |
| 11 | **SSH Tunnel Precondition Gate** | CI validation gate ensuring SSH local-forward tunnel to staging cluster API is established before kubectl operations. | scripts/ssh-tunnel-up.sh |
| 12 | **Resource Preflight Snapshot** | Re-runnable snapshot of node CPU/memory/disk capacity and existing pod resource allocations for capacity planning. | scripts/resource-preflight.sh |
| 13 | **Restore Drill Execution** | Applies and verifies database restore drill job with evidence collection and cleanup. | scripts/restore-drill.sh |
| 14 | **PostgreSQL Backup Automation** | Operator-triggered PostgreSQL backup script for staging database durability. | scripts/backup-postgres-now.sh |
| 15 | **Full-Run Orchestration** | Controlled end-to-end full-run orchestration for staging statistics validation. | scripts/start-controlled-full-run.sh |
| 16 | **Error Tracking Test Ingest** | Forced-error ingest test for GlitchTip error tracking system validation via port-forward. | scripts/test-glitchtip-ingest.sh |
| 17 | **Edge Teardown and Rollback** | Reverses Phase 7 edge bootstrap by restoring original nginx vhost and removing deploy automation artifacts. | scripts/teardown-edge.sh |
| 18 | **Observability Stack Validation** | Full observability stack validation orchestrator integrating metrics, logs, and error tracking checks. | scripts/validate-stack.sh |
| 19 | **Edge Nginx Configuration** | Idempotent adoption and reconciliation of staging edge nginx infrastructure with security policies. | scripts/bootstrap-edge.sh |
| 20 | **Observability Edge Nginx Setup** | Environment-parameterized observability edge bootstrap wiring public subdomains into host nginx. | scripts/bootstrap-obs-edge.sh |
| 21 | **Staging Secrets Rendering** | Renders staging secrets from GitHub environment variables into Kubernetes Secret YAML for secure deployment. | scripts/render-staging-secrets.py |
