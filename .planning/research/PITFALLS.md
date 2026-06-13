# Pitfalls Research

**Domain:** Kubernetes observability stack on constrained single-node k3s
**Researched:** 2026-06-13
**Confidence:** HIGH (memory/eviction/storage mechanics), MEDIUM (k3s swap behavior, GlitchTip Helm specifics)

---

## Top 3 Deployment-Sinking Risks

The three pitfalls most likely to take down this specific deployment, in order:

1. **OOM eviction of postgres/server-2** — no swap means OOM is instant kill, not a slowdown; without PriorityClass the scheduler has no basis to protect app pods over obs pods.
2. **Loki or Prometheus PVC undersized + local-path can't expand** — one redeploy with data loss to fix; gets worse as Loki fills disk and crashes the whole node.
3. **GlitchTip first-run sequence wrong** — migration Job must complete before web/worker start; open registration + default superuser = exposed error tracker.

---

## Critical Pitfalls

### Pitfall 1: OOM Kill Hits Postgres or server-2, Not the Observability Stack

**What goes wrong:**
The node is already at ~77% memory (~6.2 GB used of 8 GB) before the obs stack lands. No swap means the kernel OOM killer fires without warning — no graceful eviction, no chance to rebalance. Without explicit PriorityClass assignments, Kubernetes does not know that postgres is more important than Prometheus. When memory pressure peaks (typically during Prometheus WAL compaction or Loki ingestion spikes), the scheduler will evict or the OOM killer will shoot whatever pod has the worst oom_score_adj ratio — which may be postgres (Burstable QoS if requests < limits) before it kills obs pods.

**Why it bites here specifically:**
- No swap = OOM is an instant hard kill, not a slowdown the scheduler can react to.
- ~1.7 GB headroom before adding obs stack; Prometheus alone needs 300–500 MB; Loki another 200–400 MB; GlitchTip (web + worker + beat + Redis) another 400–600 MB. Total new demand ~1–1.5 GB — exceeds headroom without trimming.
- Obs pods start at BestEffort or Burstable QoS by default if limits are not set correctly, which means the eviction order is unpredictable.
- A Burstable postgres pod (requests < limits) and a Burstable Prometheus pod compete on the ratio of `(usage - request) / request`; Prometheus WAL compaction can spike usage well above its request, triggering eviction of the wrong pod first.

**How to avoid:**
- Create two PriorityClasses before deploying any obs workload:
  ```yaml
  # app-critical: postgres, rabbitmq, server-2, replay-parser-2
  apiVersion: scheduling.k8s.io/v1
  kind: PriorityClass
  metadata:
    name: app-critical
  value: 1000
  globalDefault: false
  preemptionPolicy: PreemptLowerPriority
  ---
  # obs-background: all obs pods
  apiVersion: scheduling.k8s.io/v1
  kind: PriorityClass
  metadata:
    name: obs-background
  value: 100
  globalDefault: false
  preemptionPolicy: Never   # obs pods cannot preempt each other OR app pods
  ```
- Set `priorityClassName: app-critical` on postgres, rabbitmq, server-2, replay-parser-2.
- Set `priorityClassName: obs-background` on ALL obs pods (Prometheus, Grafana, Loki, Alloy, kube-state-metrics, node-exporter, GlitchTip and its postgres/Redis).
- Make app pods Guaranteed QoS: set `requests == limits` for memory on postgres and server-2. Guaranteed pods are evicted last and have the most favorable OOM score.
- Size obs pod memory limits conservatively and enforce them (limits = hard ceiling). Set requests at ~60–70% of limits so the scheduler sees accurate demand.
- Add host swap (2–4 GB) as a host-level buffer BEFORE deploying the obs stack. Even if pods cannot use swap directly (see Pitfall 2), the host kernel uses swap for other host-level processes, freeing RAM for pods. Enable via `fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile` + fstab. Do not rely on pods consuming swap.

**Warning signs:**
- `kubectl describe node` shows `MemoryPressure=True` or eviction events.
- `dmesg | grep -i "oom"` shows postgres or server-2 in OOM log lines.
- Pod restarts on postgres or server-2 without an application crash.

**Phase to address:** Phase 0 / Pre-deployment preflight — PriorityClass creation and app pod annotation MUST land before any obs workload is deployed. Swap MUST be added to the host before Phase 1.

---

### Pitfall 2: Swap Is Host-Level Relief Only — Pods Do Not Use It Transparently

**What goes wrong:**
Operators add swap to the host expecting it to automatically protect pods from OOM. In practice, Kubernetes pods do NOT benefit from host swap by default and may not even with explicit configuration on the k3s version in use.

**Why it bites here specifically:**
- The k3s default ships with `fail-swap-on=false` typically disabled, meaning it may refuse to start if swap exists unless configured.
- NodeSwap feature gate: graduated to Beta in Kubernetes 1.28, default behavior in 1.32 is `NoSwap` — workloads cannot use swap even when the node has it, unless `swapBehavior: LimitedSwap` is explicitly configured. Only `LimitedSwap` is available (UnlimitedSwap was removed in 1.32).
- NodeSwap requires cgroup v2. k3s on Ubuntu 22.04+ typically uses cgroup v2, but confirm: `stat -f /sys/fs/cgroup` should show `tmpfs`; `cat /sys/fs/cgroup/cgroup.controllers` should exist.
- There is a confirmed k3s bug (issue #12677) where pods ignore swap even when NodeSwap is enabled and fail-swap-on=false is set. The issue is marked Done but may depend on the exact k3s patch version.
- Even if NodeSwap is working: only Burstable pods can use swap; Guaranteed pods (requests == limits) never use swap by design.

**How to avoid:**
- Treat swap as host-process relief only — it frees physical RAM that host daemons (containerd, kubelet, sshd, fish) would otherwise consume, indirectly giving pods more room.
- To use swap with k3s kubelet add to `/etc/rancher/k3s/config.yaml`:
  ```yaml
  kubelet-arg:
    - "fail-swap-on=false"
    - "feature-gates=NodeSwap=true"
  ```
  And in kubelet config: `memorySwap.swapBehavior: LimitedSwap`
  Restart k3s service after changes.
- Do NOT design memory budgets assuming pods will use swap. Budget as if no swap exists for pods.
- Verify cgroup v2 BEFORE enabling NodeSwap: `ls /sys/fs/cgroup/memory.swap.max` — if this file exists, cgroup v2 is active.

**Warning signs:**
- k3s fails to start after adding swap without `fail-swap-on=false`.
- `/proc/swaps` shows swap active but `kubectl top pods` shows no swap usage even under pressure.

**Phase to address:** Phase 0 preflight — verify cgroup version, add swap to host, configure kubelet flag if desired, document that pod-level swap is NOT guaranteed.

---

### Pitfall 3: Prometheus Cardinality Explosion — TSDB Memory Grows Without Bound

**What goes wrong:**
Prometheus memory usage grows linearly with the number of active time series. On a busy node, cAdvisor alone generates thousands of series per container (CPU/memory/network per container per CPU per namespace). kube-state-metrics adds more. With a short scrape interval and no metric-relabeling drops, Prometheus easily hits 500 MB–1 GB RAM for a small but label-rich cluster, then OOMKills.

**Why it bites here specifically:**
- This node runs postgres, rabbitmq, server-2, replay-parser-2, replays-fetcher, AND all obs pods — relatively high container density for a single small node.
- Default scrape interval in kube-prometheus-stack Helm chart is 30s; default retention is 15 days. Both inflate TSDB memory.
- cAdvisor scraping is enabled by default for all containers, all CPU cores, all network interfaces.
- Setting only `--storage.tsdb.retention.time` does NOT cap memory — retention caps on-disk blocks but the head block (last 2h) stays in RAM regardless of retention.
- `--storage.tsdb.retention.size` does cap disk but can be violated during compaction (upstream issue #11112 — compaction can temporarily exceed the size limit, risking a full disk).
- WAL is always in memory until compaction — WAL memory cannot be directly limited.

**How to avoid:**
- Set scrape interval to 60s for non-critical targets (kube-state, node-exporter); 30s only for app targets (postgres-exporter, rabbitmq-exporter).
- Drop high-cardinality useless metrics via `metric_relabel_configs`. Examples to drop on a small cluster:
  - `container_tasks_state` (per-task container metrics, rarely needed)
  - `container_cpu_usage_seconds_total` with `cpu=~"cpu.*"` label variants beyond `"total"`
  - All `go_*` runtime metrics from exporters you don't monitor
  - `apiserver_request_duration_seconds_bucket` histogram (dozens of buckets × endpoints)
- Set retention to 7 days (matches Loki target): `--storage.tsdb.retention.time=7d`
- Set size retention: `--storage.tsdb.retention.size=5GB` (leave buffer below PVC size)
- Enable WAL compression: `--storage.tsdb.wal-compression`
- Set memory limit on Prometheus pod at 400 MB; set request at 250 MB. If it OOMKills, the limit was too tight — increase to 512 MB before adjusting series count.
- Run `prometheus_tsdb_head_series` metric after 1 hour; if above 50,000 series, drop more via relabeling before retention issues accumulate.

**Warning signs:**
- `prometheus_tsdb_head_series > 50000` in Prometheus self-metrics.
- Prometheus pod repeatedly OOMKilled (check `kubectl describe pod prometheus-xxx`).
- `prometheus_tsdb_compactions_failed_total` incrementing (disk or memory pressure during compaction).

**Phase to address:** Phase 1 (metrics stack) — set these values in Helm values before first apply. Do NOT use defaults then tune later; the head block fills RAM within hours.

---

### Pitfall 4: Loki Fills the 31 GB Disk — local-path PVC Cannot Expand

**What goes wrong:**
Loki without retention_enabled=true accumulates chunks indefinitely. With conservative 7-day retention, a busy logging cluster on a 4-node setup would stay small, but a single node with all workloads generating logs + Loki ingesting its own logs creates a feedback loop. The compactor must be running and correctly configured or chunks are never deleted. If the PVC runs out and `local-path` does not support `allowVolumeExpansion`, the only fix is delete PVC + redeploy (data loss) or add a new PV manually.

**Why it bites here specifically:**
- k3s default `local-path` StorageClass sets `allowVolumeExpansion: false` — confirmed from the constraint in the milestone brief.
- 31 GB free disk is shared between: Loki PVC, Prometheus PVC, GlitchTip postgres PVC, GlitchTip Redis PVC, container image layers (Loki image ~400 MB, Prometheus ~200 MB, GlitchTip ~1 GB with deps), containerd image store, Alloy WAL buffer.
- Loki local storage: chunk files + BoltDB/TSDB index. At 7-day retention with moderate log volume (~5 MB/s ingest), this can reach 3–5 GB. Without compaction, it never shrinks.
- Loki does NOT delete data based on free disk space — it only deletes based on retention configuration. A full disk crashes the pod; it does not back off gracefully.

**How to avoid:**
- Size PVC generously upfront: 10 GB for Loki (covers 7-day retention × 2 for WAL + compactor working dir). Do NOT set 5 GB and plan to expand.
- Enable retention and compaction in Loki config:
  ```yaml
  compactor:
    working_directory: /loki/compactor
    shared_store: filesystem
    retention_enabled: true
    retention_delete_delay: 2h
    retention_delete_worker_count: 150
  limits_config:
    retention_period: 168h   # 7 days
  ```
- Set `chunk_retain_period` > 0 (30m default) so compactor can safely delete.
- Set index period to 24h — required for boltdb-shipper retention.
- Monitor disk usage via node-exporter + alert before 80% full (even without external alerts, make the Grafana panel prominent).
- For Prometheus: 7 GB PVC (5 GB retention + WAL headroom). Use `--storage.tsdb.retention.size=5GB` so Prometheus self-manages.
- For GlitchTip postgres: 3 GB PVC (error tracking data only, not app data).

**Warning signs:**
- `node_filesystem_avail_bytes` for the Loki volume dropping.
- Loki pod CrashLoopBackOff with `no space left on device` in logs.
- Compactor not running — check `loki_compactor_runs_total` stays 0 after startup.

**Phase to address:** Phase 2 (log stack) — set PVC sizes and compaction config before first apply. Check `kubectl describe storageclass local-path` to confirm expansion is disabled before sizing.

---

### Pitfall 5: CPU Saturation Stalls App Workloads

**What goes wrong:**
The node is at ~93% CPU before the obs stack lands. Prometheus scraping, rule evaluation, and WAL compaction are CPU-intensive bursts. Loki ingestion (regex parsing, chunk writing) adds steady CPU. kube-state-metrics and node-exporter add steady low-level CPU polling. The result is CPU throttling on all pods — postgres query latency increases, server-2 request timeouts, RabbitMQ ack delays.

**Why it bites here specifically:**
- 93% CPU baseline leaves ~0.3 vCPU of slack on 4 vCPU. Prometheus WAL compaction alone can spike to 1 full vCPU for several seconds.
- CronJobs (replays-fetcher, postgres-backup) run at scheduled times — if they overlap with a Prometheus compaction, the spike can saturate all 4 cores.
- k3s node has no autoscaler fallback.

**How to avoid:**
- Set CPU *requests* low (scheduler signal) but CPU *limits* tight on obs pods:
  - Prometheus: request 100m, limit 500m
  - Loki: request 100m, limit 300m
  - Grafana: request 50m, limit 200m
  - kube-state-metrics: request 50m, limit 150m
  - node-exporter: request 25m, limit 100m
  - Alloy: request 50m, limit 200m
  - GlitchTip web/worker: request 50m, limit 200m each
- Increase scrape intervals: 60s for infrastructure targets; 120s for kube-state.
- Disable recording rules initially — evaluate whether rule-eval CPU is worth it vs. query-time computation for this scale.
- Disable Prometheus federation and remote-write if not needed (prevents extra CPU on push).
- Check `node_cpu_seconds_total{mode="idle"}` after obs deployment — target >15% idle at steady state.

**Warning signs:**
- `rate(node_cpu_seconds_total{mode="idle"}[5m]) < 0.05` (less than 5% idle).
- Pod CPU throttling: `container_cpu_throttled_seconds_total` rising for postgres or server-2.
- PostgreSQL query latency increasing (server-2 response times).

**Phase to address:** Phase 1 (metrics stack) — set CPU limits in Helm values from day one. Revisit after 24h of live data.

---

### Pitfall 6: GlitchTip First-Run Sequence Failure

**What goes wrong:**
Multiple failure modes on first deploy:
1. Web/worker pods start before the Django migration Job completes — Django crashes with `relation "x" does not exist`.
2. Superuser not created before ENABLE_USER_REGISTRATION=False is set — nobody can log in and there is no in-cluster way to create a user without exec.
3. Celery worker and beat are separate containers/pods by default — if beat does not start, scheduled cleanup tasks (error aggregation, retention) never run, memory grows.
4. Redis (or Valkey) persistence: if Redis AOF/RDB is not configured, a Redis pod restart loses the Celery task queue, dropping unprocessed error events.

**Why it bites here specifically:**
- k3s does not have a managed Helm hook retry mechanism; the migration Job must succeed before web pods become ready.
- GlitchTip 5.x supports running without Redis/Valkey (PostgreSQL as Celery broker), which simplifies the stack but requires `VALKEY_URL=""` to be explicitly set; forgetting this means GlitchTip tries to connect to a Redis that may not exist.
- GlitchTip uses ENABLE_USER_REGISTRATION to lock registration, but this flag must be set AFTER superuser creation — or lock before creating, then create via `kubectl exec`.

**How to avoid:**
- Use Helm `helm.sh/hook: pre-install,pre-upgrade` on the migration Job; set `helm.sh/hook-delete-policy: before-hook-creation` to clean old Job pods.
- Set `initContainers` on web/worker that wait for migration completion (or use the Helm hook ordering — Job must succeed before Deployment rollout).
- Sequence on first deploy:
  1. Deploy GlitchTip with ENABLE_USER_REGISTRATION=True.
  2. Confirm migration Job completed (`kubectl wait --for=condition=complete job/glitchtip-migrate`).
  3. Create superuser: `kubectl exec deploy/glitchtip-web -- python manage.py createsuperuser --noinput --username admin --email <email>` with DJANGO_SUPERUSER_PASSWORD env var.
  4. Set ENABLE_USER_REGISTRATION=False and redeploy.
- For Redis: set `appendonly yes` in Redis config. Or use GlitchTip 5.2+ with PostgreSQL backend (set `VALKEY_URL=""`) to eliminate Redis entirely and reduce memory by ~50–100 MB.
- Set memory limits on GlitchTip Redis at 128 MB with `maxmemory 100mb` and `maxmemory-policy allkeys-lru`.
- For celery beat: confirm it is running as a separate process or pod and that its schedule persists — if beat crashes without persistent storage, tasks stop running silently.

**Warning signs:**
- GlitchTip web pod CrashLoopBackOff on first deploy — check for Django migration errors.
- `kubectl logs job/glitchtip-migrate` showing `no such table` or `relation does not exist` errors.
- No Celery tasks processing — check worker logs for connection errors to Redis/Valkey/Postgres.
- Registration locked but no admin user — exec into web pod and run `createsuperuser`.

**Phase to address:** Phase 3 (error tracking) — deployment order is: GlitchTip postgres → migration Job → web → worker → beat. Validate migration success before marking phase complete.

---

### Pitfall 7: Alloy DaemonSet Log Permission and Path Gotchas Under k3s/containerd

**What goes wrong:**
Alloy DaemonSet mounts `/var/log/pods` from the host. Under k3s with containerd, log paths are symlinked: `/var/log/pods/<namespace>_<pod>_<uid>/<container>/` with actual logs under `/var/lib/rancher/k3s/agent/containerd/` or similar. Alloy may follow symlinks correctly but needs host-level read permissions. Running Alloy without a privileged security context or without mounting the correct host paths results in empty log streams with no error — Alloy silently collects nothing.

Additionally, Alloy should NOT collect its own logs in a recursive loop (Alloy logs → Loki → Alloy tries to scrape Loki → Loki logs → loop).

**Why it bites here specifically:**
- k3s uses its own containerd data directory (`/var/lib/rancher/k3s/`), not the standard Docker/containerd path. Log symlinks under `/var/log/pods` point into this directory.
- Community forum reports (Grafana Labs, issue confirmed) of `permission denied` when mounting `/var/log/pods` without the right securityContext.
- A DaemonSet on a single node is still a DaemonSet — one pod runs, but if misconfigured it produces no logs and no error.

**How to avoid:**
- Mount both `/var/log/pods` and `/var/log/containers` as hostPath volumes.
- Add volume mount for `/var/lib/rancher/k3s` (read-only) so Alloy can follow symlinks.
- Run Alloy container with `runAsUser: 0` (root) or with `supplementalGroups` that has read access to containerd log files.
- Add label-based exclusion to prevent Alloy from collecting its own logs:
  ```
  # In Alloy config: drop logs from monitoring namespace itself
  drop_block {
    source = "namespace"
    value  = "monitoring"
  }
  ```
  Or filter GlitchTip/Loki/Prometheus namespaces from Alloy's own log collection if chatty.
- Validate with: `kubectl exec -it alloy-xxx -- /bin/sh -c "ls /var/log/pods"` — should see actual pod directories, not empty.
- Check Alloy self-metrics: `alloy_logs_entries_total` should be > 0 within 60s of deploy.

**Warning signs:**
- Alloy pod running but `alloy_logs_entries_total` stays 0.
- `permission denied` in Alloy pod logs.
- Loki shows no log streams in Grafana Explore.

**Phase to address:** Phase 2 (log stack) — validate log collection before closing phase. Required success criterion: logs from `solid-stats-staging` namespace visible in Grafana Explore.

---

### Pitfall 8: NetworkPolicy Default-Deny Applied Before Scrape Paths Are Allowed — Silent Breakage

**What goes wrong:**
Applying a `default-deny` NetworkPolicy to the `solid-stats-staging` namespace (or any app namespace) before creating the allow rules for Prometheus scraping silently breaks all metric collection. Prometheus shows targets as DOWN but the pods themselves continue running. This is especially insidious because the pods appear healthy — the breakage is invisible until someone looks at Prometheus targets or Grafana dashboards show gaps.

**Why it bites here specifically:**
- The plan calls for NetworkPolicy after CNI enforcement is proven — but if someone applies default-deny prematurely or in the wrong order, there is no alarm.
- Prometheus scrapes cross-namespace: it lives in `monitoring` namespace and scrapes targets in `solid-stats-staging`, `glitchtip`, and `kube-system`. Each requires an explicit cross-namespace allow rule.
- k3s uses Flannel CNI by default, which supports NetworkPolicy via `network-policy` controller (enabled with `--flannel-backend=vxlan` + `--kube-proxy-arg=...` — verify: `kubectl get pods -n kube-system | grep flannel`). If NetworkPolicy is not actually enforced by the CNI, applying policies is a no-op (false security).

**How to avoid:**
- Verify CNI supports NetworkPolicy before creating any policy: deploy a test pod in `monitoring`, try to curl a pod in `solid-stats-staging`, then apply a deny policy, verify the curl fails.
- Create allow rules BEFORE applying default-deny:
  ```yaml
  # In solid-stats-staging: allow ingress from monitoring namespace on exporter ports
  apiVersion: networking.k8s.io/v1
  kind: NetworkPolicy
  metadata:
    name: allow-prometheus-scrape
    namespace: solid-stats-staging
  spec:
    podSelector: {}
    policyTypes: [Ingress]
    ingress:
      - from:
          - namespaceSelector:
              matchLabels:
                kubernetes.io/metadata.name: monitoring
        ports:
          - protocol: TCP
            port: 9187  # postgres-exporter
          - protocol: TCP
            port: 9419  # rabbitmq-exporter
  ```
- Apply and validate scraping succeeds BEFORE adding default-deny.
- Keep NetworkPolicy as last step in each namespace after full scrape/datasource validation.

**Warning signs:**
- Prometheus target page shows `connection refused` or `context deadline exceeded` for previously-healthy targets after a network policy change.
- Grafana datasource test fails after obs namespace changes.
- `kubectl exec -n monitoring -- curl http://postgres-exporter.solid-stats-staging:9187/metrics` times out.

**Phase to address:** Phase 4 (network isolation) — must come AFTER Phase 1–3 scraping is fully validated. The plan already states this; it must be a hard ordering constraint in the roadmap.

---

### Pitfall 9: certbot Let's Encrypt Rate Limits and DNS Race

**What goes wrong:**
Requesting two new subdomain certificates (`grafana.stats-staging.solid-stats.ru` and `errors.stats-staging.solid-stats.ru`) in rapid succession, especially after failed attempts, risks hitting Let's Encrypt rate limits (50 certificates per registered domain per week, 5 failed validation attempts per domain per hour).

**Why it bites here specifically:**
- Both subdomains are new — first time issuing certs for them.
- The v2.0 certbot work already proved that `certbot renew` hangs on auth certs (see memory: `certbot full-renew hangs on auth cert`). A botched first attempt consuming a rate-limit slot before DNS is ready is a known risk on this host.
- If DNS `A` records for the new subdomains are not yet propagated when certbot runs HTTP-01 validation, the attempt fails and counts against the hourly limit.

**How to avoid:**
- Add DNS A records and wait for propagation (check with `dig +short grafana.stats-staging.solid-stats.ru @8.8.8.8`) BEFORE running certbot.
- Use `certbot --dry-run` first to confirm the HTTP-01 challenge path works through host nginx.
- If the nginx vhost for the new subdomains is not yet configured, the HTTP-01 challenge at `/.well-known/acme-challenge/` will 404. Configure nginx vhost (even with a temporary `return 200`) BEFORE certbot.
- Issue both certs in a single `certbot certonly --cert-name` command with multiple `-d` flags if both subdomains share the same cert, reducing rate limit exposure.
- Use Let's Encrypt staging (`--test-cert`) to validate the setup before the real issue.

**Warning signs:**
- certbot error: `too many certificates already issued for registered domain solid-stats.ru`.
- `dig` returns NXDOMAIN for new subdomains.
- nginx returns 404 on `/.well-known/acme-challenge/test`.

**Phase to address:** Phase 3 (public edge) — DNS must be verified before certbot is run. Dry-run first, then production cert issue.

---

### Pitfall 10: postgres-exporter / rabbitmq-exporter Add Connection Load to Already-Loaded Postgres

**What goes wrong:**
postgres-exporter opens a persistent connection to PostgreSQL and runs queries on every scrape (default every 30s). postgres-exporter v0.14.0 had a confirmed connection-leak bug (patched in v0.15.0) that exhausted `max_connections`. On an already-loaded postgres with existing app connections (server-2, replay-parser-2), even a non-leaking exporter adds a monitored connection that counts against `max_connections` (default 100 in Postgres).

**Why it bites here specifically:**
- The app postgres (in `solid-stats-staging`) is the same postgres handling server-2 and replay-parser-2 business data. GlitchTip gets its own postgres, but the exporter monitors the app postgres.
- Default `max_connections=100` shared between app connections + replication slots + exporter = tight budget.
- rabbitmq-exporter uses the management API (HTTP), not AMQP, so it does not consume RabbitMQ connections, but it does add HTTP polling load to the management plugin.

**How to avoid:**
- Pin postgres-exporter to v0.15.0+ (avoid the v0.14.0 connection leak).
- Create a dedicated read-only Postgres user for the exporter with minimal grants:
  ```sql
  CREATE USER exporter WITH PASSWORD 'xxx' CONNECTION LIMIT 2;
  GRANT pg_monitor TO exporter;
  ```
  The `pg_monitor` role (Postgres 10+) provides all metrics access without superuser.
- Set exporter scrape interval to 60s (not 30s) to halve connection-hold duration.
- Monitor `pg_stat_activity` connection count; alert if > 80% of `max_connections`.
- For rabbitmq-exporter: use the official `kbudde/rabbitmq-exporter` or Prometheus native rabbitmq plugin. Configure it with the rabbitmq management user (already exists). Scrape interval 60s.
- Optionally front postgres with PgBouncer (transaction-mode pooler) before adding the exporter if connection budget is tight — but this is a separate phase item.

**Warning signs:**
- `FATAL: sorry, too many clients already` in server-2 or replay-parser-2 logs.
- postgres-exporter pod in CrashLoopBackOff with `pq: too many connections`.
- `pg_stat_activity` count near `max_connections`.

**Phase to address:** Phase 1 / exporter sub-phase — create the read-only exporter user as part of the pre-deploy runbook; do not use superuser credentials.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Skip PriorityClass, rely on QoS only | Simpler initial deploy | Unpredictable eviction; obs pod may outlive postgres during pressure | Never — set PriorityClass before first obs deploy |
| Use default Helm values (scrape_interval=30s, retention=15d) | Zero config | Prometheus OOMKills within days; TSDB fills disk | Never for this constrained node |
| Use a single PVC of "probably enough" size for Loki | One less decision | PVC cannot expand; redeploy = data loss | Never — right-size upfront |
| Deploy GlitchTip with ENABLE_USER_REGISTRATION=True permanently | Skip superuser race | Any user who reaches the URL can create an account and see all error events | Never in staging; close registration within Phase 3 |
| Prometheus superuser credentials for postgres-exporter | Simpler setup | Connection leak bug risk; exporter has write access; violates least privilege | Never |
| Apply NetworkPolicy default-deny first, add allows later | "Secure first" feel | Silent scraping breakage; hours of debugging | Never — validate scraping, THEN add deny |
| Skip swap configuration entirely | Less risk of kubelet startup issues | First OOM under obs stack load kills something critical | Acceptable ONLY if obs memory budget is confirmed safely within headroom |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Prometheus → postgres-exporter | Use superuser DSN, v0.14.0 image | Use `pg_monitor` role, pin to v0.15.0+ |
| Alloy → k3s containerd logs | Only mount `/var/log/pods`, miss symlink targets | Also mount `/var/lib/rancher/k3s` read-only; run as root |
| Loki compactor | Leave `retention_enabled: false` (default) | Explicitly set `retention_enabled: true` + retention period |
| GlitchTip → its own Postgres | Race between web pod and migration Job | Use Helm pre-install hook; `kubectl wait --for=condition=complete` |
| certbot → new subdomains | Run before DNS propagates | Verify DNS resolution + configure nginx vhost first |
| NetworkPolicy → cross-namespace scraping | Apply default-deny before allow rules | Create allow rules first, validate, then apply deny |
| Prometheus → kube-state-metrics | Default scrape includes all API object labels (huge cardinality) | Use `metricLabelsAllowlist` to restrict label exposure |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| High-cardinality labels in kube-state-metrics | Prometheus memory > 500 MB within 6h | `metricLabelsAllowlist` + `metric_relabel_configs` drops | Immediately on first scrape cycle if not pre-configured |
| Loki ingesting all namespaces including monitoring itself | Loki disk fills 2x faster, compaction can't keep up | Filter out `monitoring` and `glitchtip` namespaces from Alloy config | After ~3 days without compaction keeping up |
| GlitchTip Celery beat missing (single container oversight) | Error aggregation stops; retention cleanup never runs | Confirm celery-beat is a separate process/container in the Helm chart | Silently, within first deploy; symptoms days later |
| redis without maxmemory set | Redis grows unbounded, OOMKills | Set `maxmemory 100mb` + `maxmemory-policy allkeys-lru` | Within hours if error volume spikes |
| Prometheus default 15-day retention on 5 GB PVC | Disk full at day 8-9 (compaction overhead) | Set retention to 7d + size-based retention with 20% buffer | Around day 8 for moderate series count |

---

## "Looks Done But Isn't" Checklist

- [ ] **Swap enabled:** `/proc/swaps` is non-empty AND `free -h` shows swap — not just `swapon` run but not persistent in `/etc/fstab`.
- [ ] **PriorityClass on app pods:** `kubectl get pod -n solid-stats-staging -o jsonpath='{.items[*].spec.priorityClassName}'` — must show `app-critical`, not empty.
- [ ] **Loki retention running:** `loki_compactor_runs_total > 0` after first compaction interval (~1h); check chunks directory is shrinking after 7d.
- [ ] **GlitchTip registration closed:** `curl -s https://errors.stats-staging.solid-stats.ru/api/0/auth/register/ | grep -i "registration"` — should show registration disabled.
- [ ] **Prometheus scraping all expected targets:** Prometheus `/targets` page — ALL targets GREEN; no DOWN state with `connection refused`.
- [ ] **NetworkPolicy validated:** After applying default-deny, verify Prometheus targets still healthy (they should be — allow rules were applied first).
- [ ] **Alloy collecting logs:** `alloy_logs_entries_total > 0`; Grafana Explore → Loki → `{namespace="solid-stats-staging"}` returns recent logs.
- [ ] **postgres-exporter using non-superuser:** `SELECT usename, usesuper FROM pg_user WHERE usename='exporter'` — usesuper must be false.
- [ ] **certbot certs valid for both subdomains:** `curl -vI https://grafana.stats-staging.solid-stats.ru` — TLS handshake succeeds, cert not expired, SAN matches.
- [ ] **GlitchTip receives a test error:** SDK integration sends a test exception; it appears in GlitchTip issues list within 60s.

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| OOM killed postgres | HIGH | `kubectl rollout restart statefulset/postgres`; verify WAL consistency; check data integrity; was the PVC intact? |
| Prometheus OOMKilled | LOW | Increase memory limit; reduce scrape interval; add metric drops; restart pod (TSDB on PVC, data intact) |
| Loki PVC full, local-path can't expand | HIGH | Scale Loki to 0; manually delete old chunk files from host (`/var/lib/rancher/k3s/storage/<pvc>/loki/chunks/`); restart; OR create new PVC + redeploy (data loss) |
| GlitchTip registration open | MEDIUM | Immediately set `ENABLE_USER_REGISTRATION=False` and roll; audit who registered in Django admin |
| NetworkPolicy broke scraping | LOW | `kubectl delete networkpolicy default-deny -n <namespace>`; fix allow rules; reapply deny |
| certbot rate-limited | MEDIUM | Wait up to 1 week; use staging cert temporarily; or use DNS-01 challenge to bypass HTTP-01 issues |
| postgres-exporter connection leak (v0.14.0) | LOW | Pin to v0.15.0+; restart exporter pod; run `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename='exporter'` to clear leaked connections |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| OOM / no swap / PriorityClass | Phase 0: Preflight + host swap + PriorityClass | `kubectl describe node` — no MemoryPressure; app pods have `app-critical` priority |
| Swap behavior in k3s | Phase 0: Preflight verification | `free -h` shows swap; document whether pods can use it |
| Prometheus cardinality / memory | Phase 1: Metrics stack (Helm values) | `prometheus_tsdb_head_series < 50000`; no OOMKill in 24h |
| CPU saturation | Phase 1: Metrics stack (interval + limits) | `node_cpu_seconds_total{mode="idle"}` > 15% at steady state |
| Loki disk fill / no expansion | Phase 2: Log stack (PVC sizing + compaction) | Compactor running; retention visible after 7d; disk usage stable |
| Alloy log collection | Phase 2: Log stack | `alloy_logs_entries_total > 0`; staging namespace logs in Grafana |
| GlitchTip first-run sequence | Phase 3: Error tracking | Migration job complete before web; registration closed; test error received |
| NetworkPolicy order | Phase 4: Network isolation | Applied after Phase 1–3 validation; all targets still GREEN post-apply |
| certbot DNS race | Phase 3: Public edge | DNS resolves; dry-run passes; prod cert issued and valid |
| postgres-exporter connection load | Phase 1 exporter sub-phase | Exporter user is non-superuser; `pg_stat_activity` count within budget |

---

## Sources

- Kubernetes node-pressure eviction docs: https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/
- K8s swap support blog (1.28 Beta): https://kubernetes.io/blog/2023/08/24/swap-linux-beta/
- K8s swap 1.32 improvements: https://www.kubernetes.io/blog/2025/03/25/swap-linux-improvements/
- k3s NodeSwap pods-ignore-swap issue #12677: https://github.com/k3s-io/k3s/issues/12677
- Prometheus storage docs: https://prometheus.io/docs/prometheus/latest/storage/
- Prometheus cardinality in practice: https://medium.com/@dotdc/prometheus-performance-and-cardinality-in-practice-74d5d9cd6230
- Prometheus tsdb.retention.size compaction overflow issue #11112: https://github.com/prometheus/prometheus/issues/11112
- Loki retention docs: https://grafana.com/docs/loki/latest/operations/storage/retention/
- Loki boltdb-shipper docs: https://grafana.com/docs/loki/latest/operations/storage/boltdb-shipper/
- Grafana Alloy permission denied hostPath issue: https://community.grafana.com/t/permission-denied-accessing-var-log-pods-in-grafana-alloy-with-hostpath-volumes-on-kubernetes/157594
- GlitchTip install docs: https://glitchtip.com/documentation/install/
- GlitchTip 5.2 (Valkey-optional): https://glitchtip.com/blog/2025-11-13-glitchtip-5-2-released/
- postgres-exporter v0.14.0 connection leak: https://gitlab.com/gitlab-org/omnibus-gitlab/-/issues/8292
- Let's Encrypt rate limits: https://letsencrypt.org/docs/rate-limits/
- kube-prometheus-stack NetworkPolicy discussion: https://github.com/prometheus-operator/kube-prometheus/discussions/2044

---
*Pitfalls research for: Kubernetes observability stack on constrained single-node k3s (v3.0 milestone)*
*Researched: 2026-06-13*
