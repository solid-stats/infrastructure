# Pitfalls Research

**Domain:** Production-readiness infra for an existing k3s staging cluster (WireGuard-tunnelled kubectl CD from GitHub-hosted runners, Timeweb S3-compatible storage, PostgreSQL restore drills, host-nginx edge, production cutover)
**Researched:** 2026-06-11
**Confidence:** HIGH on k3s SA-token / WireGuard / cutover mechanics (official docs + repo evidence); MEDIUM on Timeweb S3 lifecycle exact feature parity (vendor docs confirm lifecycle exists but not full AWS feature surface).

This file is scoped to the v2.0 milestone: ADDING six features to the system that already exists in this repo. Every pitfall below is tied to concrete facts in the repo: API at `https://10.8.0.1:6443` reachable only over the `wg0` tunnel (`6443` closed at ufw + Timeweb perimeter, `51820/udp` public), current CD is SSH-based in `deploy-staging.sh` / `deploy-staging.yml`, backup CronJob writes `backups/postgres/<id>/...` to `s3.twcstorage.ru` (path-style, region `ru-1`), restore drill restores into `solid_stats_restore_drill` inside the live `postgres-0` pod, edge is host nginx to `https://stats-staging.solid-stats.ru`, `web` runtime not yet wired.

---

## Critical Pitfalls

### Pitfall 1: WireGuard handshake never completes from the ephemeral runner — "another tunnel swallows the UDP handshake"

**What goes wrong:**
The CD job brings up `wg0`, but `kubectl` hangs and dies on `dial tcp 10.8.0.1:6443: i/o timeout`. The tunnel never reaches a handshake. This is the runner-side version of the trap already documented for workstations in `wireguard-access.md`: if any other route/tunnel/NAT captures UDP to `<VPS_PUBLIC_IP>:51820`, the handshake is swallowed and the link never establishes.

**Why it happens:**
- GitHub-hosted runners are NAT'd and ephemeral; their egress source IP changes every run, but WireGuard is stateless/roaming-tolerant so that alone is fine — the failure is usually the runner having no default route for the WG endpoint, a corporate/Actions egress proxy that only passes TCP/443, or `AllowedIPs` set so it tries to route the endpoint IP *through* the tunnel (chicken-and-egg).
- No `PersistentKeepalive` on the runner peer → the first packet must come from the runner, and if there is any stateful NAT in front of the VPS the return path is closed until keepalive opens it.
- MTU: WG default 1420; on some egress paths fragmented UDP is dropped, so the handshake (small) succeeds but the first large `kubectl` TLS flight silently stalls — looks like "connected but every command times out."

**How to avoid:**
- On the runner peer config: `PersistentKeepalive = 25`, and `AllowedIPs = 10.8.0.1/32` ONLY (split tunnel — never `0.0.0.0/0`, which would blackhole the runner's own GitHub callbacks and the WG endpoint route).
- Confirm the endpoint IP is reached directly: the route to `<VPS_PUBLIC_IP>` must be the runner's normal default route, not `wg0`.
- After `wg-quick up`, gate on an explicit handshake check before any `kubectl`: poll `wg show wg0 latest-handshakes` until non-zero (or `ping -c1 -W5 10.8.0.1`), fail fast with the WG state dumped to logs. Do not let `kubectl` be the thing that "discovers" the tunnel is down.
- Lower `MTU = 1380` on the runner `[Interface]` if large responses stall while small ones work.
- Egress: 51820/udp outbound must be allowed by whatever network the runner sits on. Self-hosted runners behind a TCP-only proxy cannot do raw WG — that pushes you to `wireguard-go` over a different path or a self-hosted runner on a network that permits UDP.

**Warning signs:**
`wg show` shows `latest handshake: (none)` / `transfer: 0 B received`; `kubectl` errors are `i/o timeout` not `connection refused` (refused would mean you reached something); small commands work but `kubectl logs`/`apply` of big manifests hang.

**Phase to address:** kubectl-native CD phase (WireGuard-in-CI). Make the handshake gate part of the very first iteration.

---

### Pitfall 2: k3s ≥1.24 ServiceAccount has no auto-generated token Secret — the CI token is empty or absent

**What goes wrong:**
You create the deploy ServiceAccount, then try to read its token from `secrets/<sa>-token` (the pre-1.24 way) to paste into a GitHub secret. On k3s (modern, ≥1.24) that Secret does not exist, so the kubeconfig has an empty token and CD authenticates as `system:anonymous` → every `kubectl` returns `Forbidden`.

**Why it happens:**
Kubernetes 1.24 turned on `LegacyServiceAccountTokenNoAutoGeneration` (GA in 1.26): the API server no longer auto-creates a long-lived Secret for each SA. k3s tracks upstream, so a cluster provisioned recently behaves this way. People copy old StackOverflow snippets that assume the Secret exists.

**How to avoid:**
Pick one deliberately:
- **Long-lived (matches the milestone's "long-lived SA token in CI secrets")**: create the Secret explicitly — `kind: Secret`, `type: kubernetes.io/service-account-token`, annotation `kubernetes.io/service-account.name: <sa>`; the controller then populates `.data.token`. Store that in the `staging` GitHub environment. Document it as a long-lived credential that must be rotated.
- **Short-lived (preferred security-wise)**: don't store a token at all — but a GitHub-hosted runner can't `kubectl create token <sa> --duration=...` without already being authenticated, so for this topology a long-lived bound-Secret token is the pragmatic choice. Just make rotation a first-class runbook step (see Pitfall 6).
- Either way, build the kubeconfig in-job from the token + the cluster CA, and assert identity before deploying: `kubectl auth whoami` (or `auth can-i`) must NOT be anonymous.

**Warning signs:**
`error: You must be logged in to the server (Unauthorized)` or `Forbidden`; `kubectl auth whoami` shows `system:anonymous`; the SA's `secrets:` list is empty in `kubectl get sa <sa> -o yaml`.

**Phase to address:** kubectl-native CD phase (ServiceAccount + RBAC setup), before the WireGuard glue is trusted.

---

### Pitfall 3: TLS SAN / CA mismatch when the runner hits `10.8.0.1` instead of `127.0.0.1`

**What goes wrong:**
CD connects through the tunnel and gets `x509: certificate is valid for 127.0.0.1, 10.43.0.1, kubernetes.default..., not 10.8.0.1`, or the workaround `--insecure-skip-tls-verify` gets committed into CI (which silently disables MITM protection on the one path that crosses the public internet's UDP).

**Why it happens:**
The k3s serving cert only includes SANs it was told about. `wireguard-access.md` already requires adding `10.8.0.1` to `tls-san` in `/etc/rancher/k3s/config.yaml` and restarting k3s — but that is documented as a workstation step and is easy to assume "already done." If the cert was regenerated, rotated, or the node IP/hostname changed, `10.8.0.1` can drop out of the SAN list. Separately, the kubeconfig's embedded CA may not match after a k3s data-dir reset.

**How to avoid:**
- Treat `10.8.0.1 ∈ tls-san` as a verified precondition of the CD phase, not an assumption: `openssl s_client -connect 10.8.0.1:6443 </dev/null 2>/dev/null | openssl x509 -noout -text | grep -A1 'Subject Alternative Name'` must list it.
- In CI, point `server:` at `https://10.8.0.1:6443` and supply the real cluster CA (`certificate-authority-data`). Never `--insecure-skip-tls-verify` in CD.
- If you must hit it by a name, add that name to `tls-san` too and use it consistently.

**Warning signs:**
`x509: certificate is valid for ... not 10.8.0.1`; someone proposing `--insecure-skip-tls-verify` in a PR; cert errors that appear only after a k3s restart/upgrade.

**Phase to address:** kubectl-native CD phase. Bundle with Pitfall 1/2 as the "can CI reach + trust + auth to the API" gate.

---

### Pitfall 4: Deploy RBAC too broad (cluster-admin) or too narrow (can't `rollout status`)

**What goes wrong:**
- Too broad: the long-lived CI token is bound to `cluster-admin` or a `ClusterRoleBinding`. A leaked token (Pitfall 6) then owns the whole cluster, not just one namespace.
- Too narrow: a hand-written namespace Role grants `apps/deployments` and `core/pods` but the deploy script (`deploy-staging.sh`, lines 30-36) also does `rollout status statefulset/...`, `get service`, `get cronjob`, creates the namespace, and `kubectl apply`s Secrets/ConfigMaps/ServiceAccounts. Missing verbs → `Forbidden` mid-deploy, often after some resources already applied (partial deploy).

**Why it happens:**
`kubectl rollout status` reads Deployments/StatefulSets AND watches their Pods/ReplicaSets; `apply` needs `get/patch/create` on every kind in `k8s/staging/*.yaml` (Namespace, Secret, ConfigMap, Service, Deployment, StatefulSet, CronJob, ServiceAccount). It's hard to enumerate by hand, so people either over-grant or under-grant.

**How to avoid:**
- Namespace-scoped `Role` + `RoleBinding` in `solid-stats-staging` only (never ClusterRoleBinding for the deploy identity). Namespace creation should be done once by an admin out-of-band, NOT by the CI identity, so CD doesn't need cluster-level `namespaces: create` — this also removes the `kubectl create namespace` privilege from `deploy-staging.sh` for the kubectl-native path.
- Derive the verb/resource list from the manifests, then verify with `kubectl auth can-i --list --as=system:serviceaccount:solid-stats-staging:<sa> -n solid-stats-staging` and dry-run the full apply as the SA in a pre-merge check.
- Include `get/list/watch` on `deployments`, `statefulsets`, `replicasets`, `pods` (for rollout status), plus `apply` verbs (`get/list/create/patch/update`) on `services`, `configmaps`, `secrets`, `cronjobs`, `serviceaccounts`. No `delete` unless a prune step truly needs it.

**Warning signs:**
`Forbidden` on `pods`/`replicasets` only during `rollout status` while `apply` worked; partial deploys; `auth can-i --list` showing `*/*` (too broad).

**Phase to address:** kubectl-native CD phase (RBAC). Verification = `auth can-i --list` snapshot + SA-impersonated dry-run committed as the phase's evidence.

---

### Pitfall 5: SSH/legacy path left open after cutover to kubectl-native CD

**What goes wrong:**
After CD switches to WireGuard+kubectl, the old SSH machinery stays live: `CD_SSH_PRIVATE_KEY/HOST/PORT/USER` secrets remain in the `staging` environment, the deploy host trusts the runner key, port 22 stays broadly open, and `deploy-staging.sh` still SSHes. Now there are two deploy paths and a standing remote-shell credential — exactly what the milestone wanted removed (PROJECT.md: "SSH/scp removed").

**Why it happens:**
"It still works, leave it" — the SSH path is load-bearing until the kubectl path is proven, so removal gets deferred and then forgotten. The script and workflow both still reference SSH env vars.

**How to avoid:**
- Make SSH removal an explicit, gated step of the CD phase, not a someday: rewrite `deploy-staging.sh` to use `kubectl` against the kubeconfig (drop the `ssh "${ssh_args[@]}"` wrappers and the `scp` of rendered secrets — apply directly), and delete the `Install SSH key`/`Trust deploy host` steps from `deploy-staging.yml`.
- Remove `CD_SSH_*` from the `staging` GitHub environment once the kubectl path has shipped at least one successful deploy.
- Note: rendered secrets currently travel via `scp` to `/tmp` then `kubectl apply` on the host — the kubectl-native path must `kubectl apply -f -` the rendered secrets over the tunnel (TLS) instead, and never write them to a file on the runner without `trap rm`.
- Audit ufw: confirm no new `6443` exposure crept in and SSH is restricted (key-only, ideally source-limited), since SSH is no longer the deploy mechanism.

**Warning signs:**
`CD_SSH_*` still present after CD migration; both old and new deploy jobs runnable; `deploy-staging.sh` still contains `ssh`/`scp`; rendered secret YAML written to the runner filesystem.

**Phase to address:** kubectl-native CD phase (final hardening step) — block phase completion on SSH removal + secret cleanup.

---

### Pitfall 6: Long-lived SA token rotation / leak risk

**What goes wrong:**
The long-lived bound-Secret token sits in a GitHub environment secret indefinitely. It is a namespace-admin-equivalent credential reachable from any workflow that can select the `staging` environment, printed into kubeconfig in-job (risk of log echo), and never rotated. A fork-PR, a compromised action, or an over-permissive `environment` gate leaks it.

**Why it happens:**
Long-lived tokens don't expire, so nothing forces rotation. The "it works" credential becomes permanent. Pull-request triggers can run workflows; if the deploy job (or a careless `echo`) runs on `pull_request`, the secret is exposed to untrusted code.

**How to avoid:**
- Keep the deploy job behind `environment: staging` with required reviewers, and ensure it does NOT run on `pull_request` (current workflow already guards deploy with `if: github.event_name != 'pull_request'` — preserve that).
- Mask the token: never `echo` it; build kubeconfig with `kubectl config set-credentials --token=... ` from an env var, rely on GitHub's automatic secret masking, and disable command tracing (`set +x`) around credential handling.
- Define a rotation runbook: delete + recreate the token Secret, update the GitHub secret, verify with `auth whoami`. Pair rotation with WG peer key rotation. Document an owner and cadence.
- Bound blast radius via Pitfall 4 (namespace Role, not cluster-admin) so a leak is contained to `solid-stats-staging`.

**Warning signs:**
Token age unknown / never rotated; token usable from `pull_request` runs; `set -x` around credential steps; the same token reused across more than the deploy workflow.

**Phase to address:** kubectl-native CD phase (token lifecycle + rotation runbook), revisited at Production cutover (production gets its own scoped token, never the staging one).

---

### Pitfall 7: TLS renewal / host-nginx breaks during production cutover

**What goes wrong:**
Edge automation (host nginx + cert renewal) is added at the same time traffic is cut from legacy to the new runtime. A certbot/acme renewal hook reloads nginx mid-cutover, or the new server block for the new upstream has a config error, and `nginx -s reload` fails or serves the wrong upstream → the public `https://stats-staging.solid-stats.ru` (and later production host) drops or serves stale/legacy.

**Why it happens:**
Host nginx is currently undocumented operational state (staging.md: host nginx/cert automation is explicitly *not owned* yet). Introducing automation (reload hooks, firewall rules) and re-pointing the upstream simultaneously means two unproven changes interact. ACME HTTP-01 renewal also needs port 80 reachable; a firewall change in the same phase can break the challenge and silently let certs lapse weeks later.

**How to avoid:**
- Separate edge automation from cutover: land host nginx + cert renewal + firewall as their own phase, prove a renewal dry-run (`certbot renew --dry-run`) and `nginx -t` gating every reload, BEFORE re-pointing any traffic.
- Make the upstream switch a single reversible change (one `proxy_pass` / upstream block) with `nginx -t` then `reload`, and keep the legacy upstream config one comment away for instant rollback.
- Verify ACME challenge path stays open after firewall automation: leave 80/443 inbound, confirm renewal succeeds end-to-end, set a cert-expiry alert so a broken renewal is caught in days not at expiry.
- Don't let cert renewal hooks blind-reload a config that hasn't passed `nginx -t`.

**Warning signs:**
`nginx -t` not run before reload in the renewal hook; cutover PR also changes firewall/cert config; no cert-expiry monitoring; HTTP-01 renewal after a firewall change never re-tested.

**Phase to address:** Edge automation phase (nginx/TLS/firewall) FIRST and standalone; Production cutover phase consumes a proven edge and only flips the upstream.

---

### Pitfall 8: Timeweb S3 lifecycle rules silently differ from AWS or are partially unsupported

**What goes wrong:**
You write an AWS-style `put-bucket-lifecycle-configuration` JSON (transitions to storage classes, `AbortIncompleteMultipartUpload`, tag/prefix `Filter` blocks, `NoncurrentVersionExpiration`) and either the call is accepted but only partially honored, or it errors on the unsupported field — so backups under `backups/postgres/` are believed to be auto-expiring when they are not (unbounded S3 growth / cost), or replay/artifact prefixes get expired more aggressively than intended.

**Why it happens:**
Timeweb's S3 is S3-*compatible*, not S3. Vendor docs confirm lifecycle and versioning ARE supported, but the exact AWS feature surface (transitions/storage classes don't exist the same way, `Filter` vs legacy `Prefix` schema, multipart-abort rules, per-prefix granularity) is not guaranteed. The backup job already uses `addressing_style path` and `--endpoint-url` precisely because the API isn't drop-in AWS — lifecycle is the next compatibility cliff. There are multiple distinct prefixes that must coexist (`backups/postgres/`, raw replays, parser artifacts, future reports), each wanting different retention.

**How to avoid:**
- Treat lifecycle support as something to *prove on Timeweb*, not assume: apply a rule, then read it back (`get-bucket-lifecycle-configuration`) and confirm the stored rule matches what you sent; then verify actual expiry on a throwaway test object dated in the past (or wait one cycle) before trusting it for real retention.
- Use the simplest portable construct: prefix-scoped `Expiration { Days }` only. Avoid transitions/storage-class moves and tag filters unless Timeweb explicitly supports them.
- Decide retention per prefix explicitly (backups vs replays vs artifacts) — never one bucket-wide rule that could expire backups you meant to keep.
- If versioning is enabled, also set `NoncurrentVersionExpiration` or non-current copies accumulate forever; if Timeweb ignores it, fall back to not versioning the backup prefix.
- Prefer configuring via Timeweb's own panel/API if the S3 lifecycle endpoint proves flaky, and document which mechanism is authoritative.

**Warning signs:**
`get-bucket-lifecycle-configuration` returns nothing or a rule different from what you put; `MalformedXML`/`NotImplemented`/`InvalidRequest` on apply; S3 usage keeps growing past the intended retention window; old `backups/postgres/<id>/` objects still present long after expiry days.

**Phase to address:** S3 lifecycle phase. Verification = put-then-get round-trip + an observed expiry on a test object, captured as evidence (PROJECT.md requires S3 object checks for completion).

---

### Pitfall 9: Restore drill corrupts the live DB / PVC due to weak isolation

**What goes wrong:**
The drill is meant to restore into `solid_stats_restore_drill` inside the live `postgres-0` pod (backup-restore.md). But `pg_restore --clean --if-exists` pointed at the wrong `--dbname`, a missing `--dbname` (defaults to the connection DB), or a copy-paste that targets `solid_stats` instead of the drill DB will DROP/overwrite live staging data. Restoring inside the production pod also competes for the same PVC disk/IO and can fill `postgres-data` (20Gi) — a large dump + restored DB can exhaust the volume and crash live PostgreSQL.

**Why it happens:**
The drill runs in the same pod and same PostgreSQL instance as live data (only a separate database name isolates it). `--clean --if-exists` is destructive by design; one wrong flag/name turns a drill into a wipe. Disk pressure from a second full DB on the same PVC is easy to overlook. Automating the drill (the milestone goal) removes the human who would have noticed the wrong target.

**How to avoid:**
- For an *automated* drill, do NOT restore into the live `postgres-0`/`postgres-data` PVC. Spin up an ephemeral, throwaway PostgreSQL Pod/Job with its own emptyDir or short-lived PVC in the same namespace, restore there, smoke-check, tear down. This makes corruption of live data structurally impossible.
- Hard-guard the target: assert the connection DB name == drill DB and `!= solid_stats` before running `pg_restore`; never run `--clean` against a connection whose default DB is live.
- Size/disk guard: ensure the scratch volume has headroom for dump + restored DB; never let the restore share the live 20Gi PVC.
- Keep the manual runbook's explicit `--dbname=solid_stats_restore_drill` and `dropdb` cleanup, but in automation prefer full instance isolation over same-instance separate-DB.
- Run the drill against a downloaded dump copy, not by reading/writing live tables.

**Warning signs:**
Drill restore connects to `solid_stats`; `pg_restore` without an explicit drill `--dbname`; live row counts change after a drill; `postgres-data` usage spikes during drills; drill and live share the same PVC.

**Phase to address:** Automated restore drill phase. Verification = drill runs with live DB checksums/row counts unchanged before/after; scratch isolation demonstrated.

---

### Pitfall 10: `web` runtime collides with manifest apply ordering and edge routing

**What goes wrong:**
Adding `web` manifests to `k8s/staging/` breaks deploys because (a) the repo relies on numeric filename-prefix ordering (`00-`, `10-`...`60-`) and `deploy-staging.sh` concatenates `k8s/staging/*.yaml` with `awk` then `kubectl apply -f -` as one stream — a `web` file numbered to land before its namespace/secret/configmap dependencies fails apply; (b) `deploy-staging.sh`'s `rollout status` list is hard-coded (postgres, rabbitmq, server-2, replay-parser-2) so a new `web` Deployment is deployed but never verified — green CD, broken `web`; (c) edge routing: host nginx now must route `web` vs `server-2` (API) on the same host, and a path/host collision sends API traffic to `web` or vice-versa.

**Why it happens:**
The apply model is "glob + concatenate + apply once," which is order- and dependency-sensitive, and the verification list is static. `web` is the first genuinely new workload added under the new ownership model, so the ordering/verification/edge assumptions baked for the existing four services get exercised for the first time.

**How to avoid:**
- Number `web` manifests after their dependencies (config/secret/namespace) and before nothing they don't depend on; keep one-Kind-per-concern files consistent with existing prefixes.
- Update the rollout-status verification in `deploy-staging.sh`/docs to include the `web` Deployment, or make verification derive from labels (`app.kubernetes.io/part-of: solid-stats`) rather than a hard-coded list, so new workloads are automatically gated.
- Define `web` Service + edge routing explicitly: decide host/path split (`server-2` API vs `web` UI) and validate the nginx upstream map before cutover (ties into Pitfall 7).
- Give `web` the same guardrails as existing workloads per the kubernetes-specialist skill and PROJECT.md: explicit ServiceAccount (not default), `automountServiceAccountToken: false` unless needed, resource requests/limits, probes, pinned image SHA (not `latest`), security context.

**Warning signs:**
`kubectl apply -f -` errors on `web` resources referencing a not-yet-applied namespace/secret; CD goes green but `web` pods are `CrashLoopBackOff`/`Pending` (not in rollout-status list); nginx serves `web` for API routes; `web` using the default ServiceAccount.

**Phase to address:** `web` runtime wiring phase; edge interaction validated jointly with the Edge automation phase.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| `--insecure-skip-tls-verify` in CD to dodge the SAN issue | CD connects immediately | Disables MITM protection on the one hop crossing public internet (the WG endpoint); becomes permanent | Never — fix `tls-san` (Pitfall 3) |
| Bind the CI token to `cluster-admin` | No RBAC enumeration work | Leaked token owns the whole cluster; violates least-privilege baseline | Never for the deploy identity |
| Keep SSH deploy path "just in case" after kubectl CD ships | Easy rollback | Two deploy paths + standing remote-shell credential; the thing the milestone removed | Only until first successful kubectl deploy, then delete |
| Restore drill into the live `postgres-0` (separate DB only) | Reuses running PostgreSQL, simplest manual path | One wrong `--dbname`/`--clean` wipes live data; PVC disk pressure | OK for a careful *manual* drill; never for the *automated* drill |
| One bucket-wide S3 lifecycle rule | One rule to manage | Can expire backups you meant to keep; can't differentiate prefixes | Never — backups vs replays vs artifacts need different retention |
| Hard-coded rollout-status service list | Simple, explicit | New workloads (web) deploy unverified; green CD hides broken pods | Acceptable short-term if a TODO + manual check exists; better to derive from labels |
| Long-lived SA token with no rotation runbook | Works forever, no plumbing | Permanent namespace-admin credential, no rotation, leak is silent | Only with a documented rotation owner + cadence |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| WireGuard from GitHub-hosted runner | No keepalive / `AllowedIPs=0.0.0.0/0` / no handshake gate before kubectl | `PersistentKeepalive=25`, `AllowedIPs=10.8.0.1/32`, poll `wg show ... latest-handshakes` before any kubectl |
| k3s API auth from CI | Reading a non-existent auto SA token Secret (≥1.24) | Explicitly create `kubernetes.io/service-account-token` Secret; assert `auth whoami != anonymous` |
| k3s serving cert | Hitting `10.8.0.1` not in `tls-san` | Add `10.8.0.1` to `/etc/rancher/k3s/config.yaml` `tls-san`, restart k3s, verify SAN via `openssl s_client` |
| Timeweb S3 lifecycle | Assuming AWS feature parity (transitions, tag filters, multipart-abort) | Put-then-get round-trip + observed expiry on a test object; prefix `Expiration{Days}` only |
| Timeweb S3 addressing | Virtual-hosted-style / wrong region | Keep path-style (`addressing_style path`) + `--endpoint-url https://s3.twcstorage.ru`, region `ru-1`, as backup job already does |
| pg_restore drill | `--clean`/wrong `--dbname` against live DB | Automated drill into an ephemeral throwaway PostgreSQL instance, not live `postgres-0`/PVC |
| Host nginx + ACME during cutover | Blind `nginx -s reload`; firewall change breaks HTTP-01 | `nginx -t` gate every reload; `certbot renew --dry-run`; keep 80/443 open; cert-expiry alert |
| `web` into glob-apply pipeline | Misnumbered file / missing from rollout-status list | Order by dependency; gate rollout by `part-of` label, not hard-coded names |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| WG MTU too high for runner egress | Small kubectl commands work, `apply`/`logs` of large payloads stall | Set runner `MTU=1380`; gate on handshake not on first big command | Whenever a large manifest stream or log is fetched over the tunnel |
| Backups never expire (lifecycle silently no-op) | S3 usage climbs; tariff can't be downgraded (Timeweb limitation) | Verify lifecycle actually deletes; alert on bucket size | Weeks/months in — slow cost bleed |
| Restore drill on live PVC | `postgres-data` (20Gi) fills; live PostgreSQL crashes on disk pressure | Drill in ephemeral instance with its own volume | When dump+restored DB approaches PVC free space |
| Concatenated single `kubectl apply` stream | One bad doc fails the whole apply / partial state | Keep manifests valid + ordered; consider server-side apply or per-file apply if web adds complexity | As manifest count/dependencies grow with `web` |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| `6443` opened to public/perimeter during CD work | k3s API exposed to the internet | Keep `6443` closed at ufw + Timeweb; allow only on `wg0` (`ufw allow in on wg0 to any port 6443`) |
| Long-lived SA token reusable from `pull_request` runs | Untrusted fork code exfiltrates a namespace-admin token | `environment: staging` gate; deploy job not on `pull_request`; mask token, no `set -x` around it |
| Token bound cluster-wide | Leak = full-cluster compromise | Namespace `Role`/`RoleBinding` only; namespace created out-of-band by admin |
| Rendered secrets written to runner filesystem / scp'd | Secret material on disk / in transit beyond TLS | `kubectl apply -f -` rendered secrets over the tunnel; `trap rm` any temp file; never log |
| SSH key + port 22 left broadly open post-cutover | Standing remote-shell attack surface after SSH is no longer needed | Remove `CD_SSH_*`, restrict/lock down SSH after kubectl CD ships |
| Default ServiceAccount / token automount on `web` | Pod can call API with ambient creds | Explicit SA, `automountServiceAccountToken: false` unless required (matches existing workloads) |

## "Looks Done But Isn't" Checklist

- [ ] **WireGuard CD:** handshake gate present — verify `wg show wg0 latest-handshakes` is non-zero BEFORE the first `kubectl`, not that kubectl "eventually worked once."
- [ ] **SA token:** verify `kubectl auth whoami` is the deploy SA (not `system:anonymous`) and the token Secret actually has `.data.token`.
- [ ] **RBAC:** verify `auth can-i --list` covers `rollout status` (pods/replicasets get/list/watch) AND every Kind in `k8s/staging/*.yaml` — run a full SA-impersonated dry-run.
- [ ] **SSH removal:** verify `CD_SSH_*` secrets deleted and `deploy-staging.sh`/workflow contain no `ssh`/`scp` after CD migration.
- [ ] **TLS SAN:** verify `10.8.0.1` is in the live serving cert SANs and CD uses the real CA (no `--insecure-skip-tls-verify`).
- [ ] **S3 lifecycle:** verify with `get-bucket-lifecycle-configuration` round-trip AND an observed expiry on a test object — not just "the put succeeded."
- [ ] **Restore drill:** verify live DB row counts/checksums unchanged before/after, and that the drill uses an isolated instance/volume.
- [ ] **Edge/TLS:** verify `certbot renew --dry-run` passes, every reload is `nginx -t`-gated, and a cert-expiry alert exists; HTTP-01 still works after firewall automation.
- [ ] **Cutover:** verify instant rollback (legacy upstream one edit away) and that the upstream actually points where intended (`curl` the public host).
- [ ] **web runtime:** verify `web` Deployment is in the rollout-status gate, manifests apply in dependency order, edge routes API vs UI correctly, and it has SA/limits/probes/pinned SHA.

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| WG handshake fails in CI | LOW | Dump `wg show`; fix keepalive/AllowedIPs/MTU/endpoint route; re-run; tunnel is stateless so no cleanup |
| Anonymous/empty SA token | LOW | Create the `service-account-token` Secret; refresh GitHub secret; `auth whoami` |
| TLS SAN mismatch | LOW-MED | Add `10.8.0.1` to `tls-san`, `systemctl restart k3s`; re-verify SAN; NEVER skip-verify |
| Partial deploy from too-narrow RBAC | MED | Add missing verbs; re-apply (apply is idempotent); reconcile partially-applied state |
| Leaked long-lived token | MED-HIGH | Delete token Secret (invalidates it), recreate, rotate GitHub secret, audit access logs; namespace-scope limits blast radius |
| Lifecycle silently not expiring | LOW-MED | Reconfigure via panel/API; manual cleanup of overdue objects; add bucket-size alert |
| Drill wiped live DB | HIGH | Restore from latest `backups/postgres/` dump into live DB; the very backup the drill validates is the recovery — but downtime + possible data loss since last backup |
| Cutover/edge broke public host | LOW (if reversible) | Revert the single upstream edit, `nginx -t && nginx -s reload`; legacy stays one edit away |
| web breaks apply ordering | LOW | Renumber manifest; re-run idempotent apply; add to rollout-status gate |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| 1. WG handshake swallowed | kubectl-native CD | `wg show` handshake gate non-zero before kubectl; CD green from a runner |
| 2. k3s ≥1.24 no auto SA token | kubectl-native CD | Token Secret has `.data.token`; `auth whoami` == deploy SA |
| 3. TLS SAN / CA mismatch | kubectl-native CD | `openssl s_client` SANs include `10.8.0.1`; no skip-verify in CD |
| 4. RBAC too broad/narrow | kubectl-native CD | `auth can-i --list` snapshot + SA-impersonated full dry-run |
| 5. SSH path left open | kubectl-native CD (final gate) | `CD_SSH_*` removed; no `ssh`/`scp` in scripts/workflow |
| 6. Token rotation/leak | kubectl-native CD; revisit at Cutover | Rotation runbook exists; deploy not on `pull_request`; token masked |
| 7. TLS renewal breaks edge | Edge automation (standalone, before cutover) | `certbot renew --dry-run` ok; `nginx -t`-gated reloads; expiry alert |
| 8. S3 lifecycle differs on Timeweb | S3 lifecycle | put-then-get round-trip + observed test-object expiry |
| 9. Drill corrupts live DB/PVC | Automated restore drill | Live row counts unchanged; isolated instance/volume |
| 10. web ordering/routing collision | web runtime wiring (+ Edge for routing) | web in rollout gate; dependency-ordered apply; correct edge route |
| Production cutover interactions (7+10) | Production cutover | Reversible single-edit upstream switch; public host curl; instant rollback proven |

## Sources

- [Managing Service Accounts — Kubernetes (1.24 no auto-token, `LegacyServiceAccountTokenNoAutoGeneration`, manual `service-account-token` Secret)](https://kubernetes.io/docs/reference/access-authn-authz/service-accounts-admin/) — HIGH
- [Service Accounts — Kubernetes (bound/projected tokens, `kubectl create token`)](https://kubernetes.io/docs/concepts/security/service-accounts/) — HIGH
- [k3s token docs](https://docs.k3s.io/cli/token) — MEDIUM (k3s tracks upstream SA behavior)
- [Timeweb S3 bucket management — lifecycle + versioning supported, endpoint `s3.twcstorage.ru`, path & virtual-hosted addressing, AWS SigV2/V4, Swift API](https://timeweb.cloud/docs/s3-storage/manage-storage/manage-buckets) — MEDIUM (confirms lifecycle exists; full AWS feature parity not guaranteed)
- [AWS PutBucketLifecycleConfiguration reference (the AWS feature surface Timeweb may not fully match)](https://docs.aws.amazon.com/AmazonS3/latest/API/API_PutBucketLifecycleConfiguration.html) — HIGH
- Repo evidence: `docs/wireguard-access.md` (UDP-swallowed-by-another-tunnel trap, `tls-san`, split-tunnel `AllowedIPs`), `scripts/deploy-staging.sh` (SSH/scp model, hard-coded rollout-status list, glob-concatenate apply), `.github/workflows/deploy-staging.yml` (`CD_SSH_*` secrets, `pull_request` guard on deploy), `k8s/staging/60-postgres-backup.yaml` (path-style S3, `s3.twcstorage.ru`, region `ru-1`, `backups/postgres/` prefix), `docs/backup-restore.md` (drill restores into `solid_stats_restore_drill` inside live `postgres-0`), `k8s/staging/30-server-2.yaml` (`PUBLIC_BASE_URL` host, path-style S3 env), `.planning/PROJECT.md` (v2.0 goals, SSH removal, 20Gi PVC, suspended fetcher) — HIGH

---
*Pitfalls research for: production-readiness infra additions to an existing k3s/WireGuard/Timeweb-S3/GitHub-hosted-runner system*
*Researched: 2026-06-11*
