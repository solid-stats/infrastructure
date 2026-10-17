# Unified personal/global memory on shared Qdrant

The runtime uses one full MemPalace 3.5.0 process, one embeddinggemma model,
namespace `unified-memory`, its own PVC and ServiceAccounts, and the existing
private Qdrant 1.19.0 service in `solidstats-memory`. The user approved this
process-sharing boundary. SolidStats collections, aliases, local state and
Qdrant credentials remain separate; its client contract is unchanged. The user
explicitly approved reusing the existing S3 credential for backups under
`backups/unified-memory/`; that credential can access both backup scopes.
Prefix separation is not S3 credential isolation. VocalClub is outside this
deployment. Source changes alone do not prove deployment acceptance.

## Inputs and generated resources

Copy `k8s/unified-memory/inputs.example.json` into the operator's private work
area. Keep corpus, credentials, generated Secrets and acceptance evidence
outside Git. Replace the approved probe wing, both documentation-only CIDRs,
physical collection names, PVC size, resource requests/limits and minimum backup
free bytes with reviewed values. The scratch floor is checked on the actual
backup work volume before snapshots; size it for snapshots, metadata archive,
temporary extraction and object readback. The example value is not a capacity
measurement. The source directory is `/data`, including `/data/palace` and
writable tunnel siblings. No bulk embeddings run on the VPS.

The schema is `unified-memory-deployment-input/v1`. Both logical collections
`mempalace_drawers` and `mempalace_closets` are required, each with the exact
keys `logicalName`, `alias`, `physical`, `dimension`, `distance`. Dimension is
384 and distance is `Cosine`. Backend namespace is `Unified`; path
`/data/palace` hashes to `9a994364b7c26031` in deterministic aliases. The Qdrant
URL is fixed to `http://qdrant.solidstats-memory.svc:6333`. The source example
is not deployable until its `REQUIRED` marker is replaced.

Use the inspected full image, explicitly pinned at invocation:

<!-- markdownlint-disable MD013 -->
```sh
python3 scripts/render-unified-memory.py --inputs /root/memory-operator/inputs.json --image ghcr.io/mempalace/mempalace@sha256:d9d75fab4138a22d013a244bb4153fa1938830be3726cf826ffd02aeba73fe8e --output /root/memory-operator/rendered --admin-key-file /root/memory-operator/admin.key --http-token-file /root/memory-operator/http-token --s3-file /root/memory-operator/s3.json
```
<!-- markdownlint-enable MD013 -->

The output directory must be absent. On POSIX it and its files are owner-only.
Private inputs must be owner-only files. The optional three private arguments
must be supplied together; omitting all three renders only `resources.json`.
With all three, `secrets.json` is also written. Nothing prints credential
values. The S3 JSON has exactly `S3_BUCKET`, `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`. The existing signing key is consumed to issue scoped
JWTs; it is never placed in generated resources or rotated.

The runtime gets alias-rw only. The backup gets physical-rw only. Init
validation also gets a separate observer token with read-only access to both
owned physical names and aliases, because Qdrant filters alias metadata unless
both are allowed. The serving container never receives that observer token. Init
checks the exact alias-to-physical mapping, backend marker, embedder identity
and one offline inference. It does not create collections, aliases, markers or
model caches. Provision these through the reviewed import before starting the
Deployment.

The generated List includes restricted namespace, PVC, separate identities,
ConfigMap, one-replica Recreate Deployment, ClusterIP Service, suspended backup
CronJob and default-deny policies. It includes reciprocal Qdrant ingress in the
SolidStats namespace; apply that resource too. DNS uses the existing `k8s-app:
kube-dns` selector. Only measured host-nginx source access and scoped HTTPS
backup egress are allowed. Retain `MEMPALACE_MCP_ALLOW_PEER_WRITER=1` for
MemPalace 3.5's HTTP thread-writer workaround. `/data` remains writable for
sibling tunnel files.

## Deployment preparation and live acceptance

The main operator owns each live command and the exact import/cutover sequence.
The following commands are explicit operations, not evidence that they ran:

<!-- markdownlint-disable MD013 -->
```sh
kubectl apply -f k8s/unified-memory/00-namespace.yaml
kubectl apply --dry-run=server -f /root/memory-operator/rendered/resources.json
kubectl apply -f /root/memory-operator/rendered/secrets.json
kubectl apply -f /root/memory-operator/rendered/resources.json
kubectl -n unified-memory rollout status deployment/mempalace --timeout=180s
kubectl -n unified-memory exec deployment/mempalace -- python3 /opt/unified-memory/bootstrap-unified-memory.py probe --bindings /opt/unified-memory/bindings.json
```
<!-- markdownlint-enable MD013 -->

Create namespace before the namespace-scoped Secrets; split/apply the namespace
from `k8s/unified-memory/00-namespace.yaml` first. Stage/import PVC state before
allowing the Deployment to start; an empty PVC intentionally fails init. Apply
through the main operator's explicit Kubernetes context. The rendered manifest
contains no import or nginx command. Preserve the existing personal route until
fresh acceptance passes, then switch only the personal upstream with nginx
config test, reload and exact rollback prestate retained by the main operator.

Acceptance requires current collection/count/content/vector and local-state
parity, full personal MCP tools including KG and tunnels, ordinary capture/read/
recall/delete with exact cleanup, offline embedding/cache, no cross-palace
access, namespace policy tests, restart/reboot recovery and resource
observations. Freeze ordinary writes for the final source snapshot and import.
After writes reopen, source rollback requires current writes to be preserved; do
not restore an old source snapshot over new writes. RAM uncertainty was
accepted; no former numeric seven-day gate applies.

## Shared host coordinator

Install the reviewed source as root-owned, non-writable-by-others files:

<!-- markdownlint-disable MD013 -->
```sh
sudo install -d -m700 /etc/shared-memory /var/lib/shared-memory-coordinator
sudo install -m755 scripts/operate-shared-memory.py /usr/local/sbin/operate-shared-memory
sudo install -d -m755 /usr/local/libexec
sudo install -m644 scripts/unified_memory_recovery.py /usr/local/libexec/unified_memory_recovery.py
sudo install -m600 /root/memory-operator/coordinator.json /etc/shared-memory/coordinator.json
sudo install -m600 /root/memory-operator/protected.json /etc/shared-memory/protected.json
sudo install -m600 /root/memory-operator/admin.key /etc/shared-memory/qdrant-operator.key
```
<!-- markdownlint-enable MD013 -->

Start from `config/shared-memory/coordinator.example.json`. Supply the exact
Kubernetes context, canonical root-owned nonsymlink kubectl/Python paths, fixed
restore modules, and template digests. Parent directories must be root-owned and
not group/world writable. An ordinary symlinked `/usr/bin/python3` is rejected;
use its verified canonical executable path. A kubectl shim may be a reviewed
root-owned executable calling the existing k3s kubectl command. Never weaken
these trust checks to accommodate an untrusted executable.

Both CronJobs must remain suspended and `Forbid`. Disable any old direct backup
launcher before enabling the two host timers; preserve the existing failure
guard. The coordinator never unsuspends a CronJob. Its SS Job name and
controller owner reference stay compatible with the existing guard. Its SS Job
template, package and capture/read-back completion oracles are preserved.

<!-- markdownlint-disable MD013 -->
```sh
sudo /usr/local/sbin/operate-shared-memory --config /etc/shared-memory/coordinator.json preflight
sudo /usr/local/sbin/operate-shared-memory --config /etc/shared-memory/coordinator.json template-digest --scope solidstats
sudo /usr/local/sbin/operate-shared-memory --config /etc/shared-memory/coordinator.json template-digest --scope unified
```
<!-- markdownlint-enable MD013 -->

Copy each returned SHA256 into the corresponding trusted registry entry after
reviewing that exact live `spec.jobTemplate`. The hash uses compact sorted-key
JSON, not raw YAML or the entire CronJob. Every run compares it again before
mutating a writer. Drift fails closed.

<!-- markdownlint-disable MD013 -->
```sh
sudo /usr/local/sbin/operate-shared-memory --config /etc/shared-memory/coordinator.json backup --scope solidstats
sudo /usr/local/sbin/operate-shared-memory --config /etc/shared-memory/coordinator.json backup --scope unified
sudo install -m644 config/shared-memory/shared-memory-backup@.service /etc/systemd/system/shared-memory-backup@.service
sudo install -m644 config/shared-memory/solidstats-memory-backup.timer /etc/systemd/system/solidstats-memory-backup.timer
sudo install -m644 config/shared-memory/unified-memory-backup.timer /etc/systemd/system/unified-memory-backup.timer
sudo systemctl daemon-reload
sudo systemctl enable --now solidstats-memory-backup.timer unified-memory-backup.timer
```
<!-- markdownlint-enable MD013 -->

Enable timers only after both manual runs and recovery acceptance. Times are
05:00 and 06:30 Europe/Moscow. Persistent boot catch-up waits at most 3900
seconds for the shared lock before failing visibly, so concurrent timer
activation queues behind the first operation. The service has a bounded
15000-second outer timeout; an interrupted run remains fenced. Nonzero systemd
results and the private journal are visible failure evidence; no external alert
delivery is claimed. The single host lock covers writer quiescence, Job
completion, upload/readback and writer restoration. Unified is restored to its
exact original replica count and must pass create/read/delete after resume. SS
retains its existing in-Job quiescence and oracles. Durable intent is fsynced
before mutations. Unknown active Jobs, active Job-owned/backup Pods, foreign PVC
consumers, changed Job UID or incomplete journal fence both schedules.

A failure may have left the writer stopped or temporary probe data. Inspect the
private `operation.json`, Kubernetes Jobs and Pods, and the existing guard
before reconciliation. Do not delete the journal or lock file, manufacture PASS
logs, or start a second backup manually. If a timed-out historical controller
may still have external work, prove that work stopped before reconciliation.
Reconciliation is a deliberate operator action, not automatic acceptance of a
failed package:

<!-- markdownlint-disable MD013 -->
```sh
sudo /usr/local/sbin/operate-shared-memory --config /etc/shared-memory/coordinator.json reconcile --run-id EXACT_RECORDED_RUN_ID
```
<!-- markdownlint-enable MD013 -->

## Complete recovery packages and isolated restore

Unified uses `unified-memory-recovery/v1`, separate from SS's unchanged
four-file schema. Each point contains two native snapshots, local-state tar,
manifest with collection/vector/point fingerprints and SQLite integrity/table
counts, and `COMPLETE.json` bound to the manifest digest. Archive paths and
member types are checked before extraction, with limits of 100000 unique members
and 16 GiB expanded regular-file bytes, and a capacity check on the actual
extraction filesystem. This schema accepts uncompressed tar only. Safe internal
model-cache symlinks are supported; escaping links are rejected. Hashes, full
point payload/vector fingerprints and local state are rechecked before a
recovery point is complete.

Each created transient Qdrant snapshot is deleted by its exact returned name
after download, including failed downloads. A process/node crash may bypass
cleanup; inspect and reconcile its exact transient snapshots before reopening a
failed run.

Uploads use `backups/unified-memory/` only, stream data with bounded memory,
redownload each member for digest verification and publish COMPLETE last. A
point without that final verified marker is unusable. After a successful
publication, retention preserves every complete point within the last 30 days
and also the latest 30 complete points. It downloads and verifies each expired
complete package before deleting only that exact point under the unified prefix.
COMPLETE is deleted first; removal is confirmed by inventory readback. Recent
and incomplete points are retained. It never changes SS retention or bucket
lifecycle rules. A failed verification performs no deletion of that point.
Before publishing or pruning, the uploader requires a successful
unversioned-bucket response. Enabled, Suspended or unavailable versioning status
fails closed because ordinary DeleteObject cannot prove old-version purge.
Verify actual provider versioning/list/delete semantics and scoped credentials
before live acceptance.

Download every member of one complete prefix into an absent owner-only package
directory through the operator's existing object-store route. Then:

<!-- markdownlint-disable MD013 -->
```sh
python3 scripts/unified_memory_recovery.py verify --package /root/memory-operator/downloaded-point
sudo /usr/local/sbin/operate-shared-memory --config /etc/shared-memory/coordinator.json restore --package /root/memory-operator/downloaded-point --targets /root/memory-operator/restore-targets.json --state-output /root/memory-operator/isolated-state
```
<!-- markdownlint-enable MD013 -->

`restore-targets.json` maps every package physical source name to a distinct
new, absent physical target. The state output must be absent with an existing
trusted parent and sufficient disk space. `protected.json` is a JSON string
array covering **all current SS physical collections and aliases**, including
inactive recovery collections; collect it fresh. Before each restore mutation
the tool also rejects every currently occupied collection, alias and alias
target, source names and protected identities. Use the registry's operator key
only over its verified localhost Qdrant port-forward; never expose that forward
publicly. Maintain the forward separately for the bounded command and stop it
afterward.

Restore verifies all snapshots and local SQLite/state before reporting success.
It never changes or deletes aliases, existing collections, or active PVC state.
The restored metadata retains its target-bound markers: an isolated drill is not
an alias cutover or a ready-to-serve alternate palace. Any later marker/alias
transition needs the separately reviewed import/cutover procedure.

## Existing SolidStats recovery compatibility

The original `scripts/restore-solidstats-memory.py` is unchanged and remains
bound to its sealed Phase 20/21 handoff. That historical controller expects its
historical corpus count; it does not establish parity for today's active corpus.
Its registered wrapper executes all four existing stages under the shared lock:

<!-- markdownlint-disable MD013 -->
```sh
sudo /usr/local/sbin/operate-shared-memory --config /etc/shared-memory/coordinator.json solidstats-recovery --request /root/memory-operator/solidstats-recovery-request.json
```
<!-- markdownlint-enable MD013 -->

The private request schema is `shared-solidstats-recovery-request/v1`, with
`runId`, `handoff`, `evidenceDir`, and `environment` (existing
`SOLIDSTATS_MEMORY_*` string inputs only). The environment must include the
existing `SOLIDSTATS_MEMORY_OPERATOR` and `SOLIDSTATS_MEMORY_PRIVATE_RUN_ROOT`.
Use a new exact run ID; all paths and adapter/interpreter modules must satisfy
root trust checks. Stage diagnostics are retained owner-only beside the
operation journal. The original controller's preflight, backup, isolated-restore
and verify-restore checks are not bypassed. Do not claim a fresh SS
recurring-package restore drill from the historical Phase 21 evidence. The
existing live deployment uses offline init, so its historical online count check
is not evidence of a restart failure.

## Offline verification

Run with Python and PyYAML already available in the operator environment:

```sh
python3 -B tests/test-unified-memory.py
python3 -B tests/test-shared-memory-coordinator.py
python3 scripts/validate-memory-manifests.py --allow-operator-placeholders
python3 scripts/validate-memory-nginx.py --allow-operator-placeholders
```

For real local Qdrant proof set `UNIFIED_QDRANT_BINARY` to the verified local
1.19.0 binary before running the unified suite. A missing binary explicitly
skips those two cases; a skip is not authorization or snapshot proof. Tests use
only synthetic local data and no production credentials or network services.
