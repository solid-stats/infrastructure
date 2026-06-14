# Observability Stack — Operator Runbook (v3.0)

The staging metrics stack: **Prometheus + Grafana + kube-state-metrics + node-exporter +
postgres-exporter + RabbitMQ native metrics**, deployed into the `monitoring` namespace
(created in Phase 12) via a render-then-apply pipeline independent of the runtime CD.

- Manifests: `k8s/observability/*.yaml` (rendered with `helm template`; git is the source of
  truth — no in-cluster helm, no operator/CRDs).
- Values (helm inputs, not applied): `k8s/observability/values/`.
- Dashboards (vendored JSON → ConfigMaps): `k8s/observability/dashboards/`, shipped by
  `60-grafana-dashboards.yaml`.
- Deploy workflow: `.github/workflows/deploy-observability.yml` (own concurrency group
  `infrastructure-obs-deploy`, `obs-ci-deployer` token + SSH local-forward, independent of runtime CD).
- Validation: `scripts/validate-phase-13.sh` (live), `scripts/validate-obs-manifests.py` (static).

All obs workloads carry `priorityClassName: obs-background` so the scheduler evicts them
before the app under node memory pressure (the node has ~2.5Gi headroom; see
`docs/resource-protection.md`).

## Resource footprint (measured, live)

| Pod | Memory (live) | CPU (live) |
|-----|---------------|------------|
| grafana | ~206Mi | ~5m |
| prometheus-server | ~47Mi (grows with TSDB) | ~4m |
| kube-state-metrics | ~16Mi | ~1m |
| node-exporter | ~10Mi | ~1m |
| postgres-exporter | ~8Mi | ~1m |

Total ~290Mi — comfortably under the rendered requests/limits and the node headroom.

## One-time operator bootstrap

These steps touch live cluster state and the GitHub secret store; run once before (or as part of)
the first observability deploy. Reach kubectl via the SSH local-forward (scripts/ssh-tunnel-up.sh), or SSH to the staging node where `kubectl` is local.

### 1. Prometheus RBAC (operator-applied; obs-ci-deployer cannot create cluster RBAC)

```
kubectl apply -f k8s/staging/01-obs-rbac.yaml
kubectl get clusterrole prometheus-monitoring        # exists, read-only get/list/watch
kubectl -n monitoring get sa prometheus              # exists
kubectl auth can-i create clusterroles --as=system:serviceaccount:monitoring:obs-ci-deployer  # -> no
```

### 2. postgres monitoring role (non-superuser)

Create the `solid_monitor` login role with `pg_monitor` (built-in, non-superuser) on the live DB,
choosing a strong password (the same value goes into `PG_MONITOR_PASSWORD` below):

```
kubectl -n solid-stats-staging exec -i postgres-0 -- sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' <<'SQL'
DO $do$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='solid_monitor')
  THEN CREATE ROLE solid_monitor LOGIN PASSWORD '<PG_MONITOR_PASSWORD>';
  ELSE ALTER ROLE solid_monitor LOGIN PASSWORD '<PG_MONITOR_PASSWORD>'; END IF;
END $do$;
GRANT pg_monitor TO solid_monitor;
SQL
```

Confirm `rolsuper = false` for `solid_monitor`. The exporter DSN uses `sslmode=disable`: the
lib/pq driver rejects `prefer`, and the staging postgres serves no TLS, so `require` would fail
the handshake. The connection is intra-cluster pod-to-pod and is isolated by NetworkPolicy in
Phase 17; enforce TLS later (verify-full + mounted CA) once postgres serves TLS.

### 3. Render + apply the obs Secrets

`scripts/render-obs-secrets.py` reads `GRAFANA_ADMIN_PASSWORD` + `PG_MONITOR_PASSWORD` from the
environment and emits `grafana-secrets` (`admin-user`/`admin-password`) and
`postgres-monitor-secret` (`dsn`). No secret values are ever written to git.

```
GRAFANA_ADMIN_PASSWORD=<...> PG_MONITOR_PASSWORD=<...> \
  python3 scripts/render-obs-secrets.py | kubectl apply -n monitoring -f -
```

### 4. GitHub environment secrets (for the CI deploy path)

Add three secrets to the `staging` GitHub environment so `deploy-observability.yml` can render
the same Secrets in CI:

- `K8S_OBS_TOKEN` — the `obs-ci-deployer` token: `kubectl -n monitoring get secret obs-ci-deployer-token -o jsonpath='{.data.token}' | base64 -d`
- `GRAFANA_ADMIN_PASSWORD` — same value used in step 3
- `PG_MONITOR_PASSWORD` — same value used in steps 2 and 3

```
gh secret set K8S_OBS_TOKEN --env staging
gh secret set GRAFANA_ADMIN_PASSWORD --env staging
gh secret set PG_MONITOR_PASSWORD --env staging
```

### 5. Storage preflight

`kubectl get storageclass` shows `local-path (default)`; the node has enough free disk for the
Prometheus (5–8Gi) + Grafana (2Gi) PVCs (`ssh root@<node> df -h /`).

## Deploy

CI: push to the obs deploy path or dispatch `deploy-observability.yml`. Manual (operator):

```
kubectl apply --server-side --force-conflicts -n monitoring -f k8s/observability/<file>.yaml
```

Use `--server-side` for the dashboards — the node-exporter/rabbitmq JSONs exceed the 256KB
client-side last-applied-configuration annotation limit.

## Verify

```
bash scripts/validate-phase-13.sh          # MET-01..06 (set GRAFANA_ADMIN_PASSWORD for MET-05/06)
```

Manual panel check: `kubectl -n monitoring port-forward svc/grafana 3000:80`, open
`http://localhost:3000` (admin / `GRAFANA_ADMIN_PASSWORD`), confirm the node-exporter, PostgreSQL,
RabbitMQ, and kube-state dashboards render non-zero data. No public ingress/TLS yet — that is
Phase 14.

## Recovery notes

- Grafana `CreateContainerConfigError`: `grafana-secrets` must carry **both** `admin-user` and
  `admin-password`.
- Grafana `failed to create admin user: no such column: uid`: a partially-migrated SQLite DB from
  a prior crash — scale Grafana to 0, delete `grafana.db` on its PVC, scale back to 1.
