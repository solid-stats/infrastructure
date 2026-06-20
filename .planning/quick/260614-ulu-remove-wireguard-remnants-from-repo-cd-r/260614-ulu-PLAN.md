---
phase: quick-260614-ulu
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - scripts/wg-tunnel-up.sh
  - .github/workflows/deploy-staging.yml
  - README.md
  - docs/observability.md
  - docs/operator-bootstrap.md
  - scripts/bootstrap-edge.sh
  - scripts/validate-edge.py
  - scripts/teardown-edge.sh
  - scripts/validate-phase-13.sh
  - scripts/resource-preflight.sh
  - AGENTS.md
  - scripts/validate-stack.sh
  - scripts/validate-phase-12.sh
  - scripts/validate-phase-15.sh
  - scripts/validate-phase-16.sh
  - scripts/restore-drill.sh
  - docs/sa-token-rotation.md
  - docs/staging.md
  - docs/glitchtip.md
  - docs/s3-lifecycle.md
  - docs/backup-restore.md
  - docs/resource-protection.md
  - docs/edge-bootstrap.md
  - docs/wireguard-access.md
  - docs/k3s-api-access.md
autonomous: true
requirements: [WG-DECOMM]

must_haves:
  truths:
    - "scripts/wg-tunnel-up.sh no longer exists in the repo"
    - "The validate CI job no longer requires wg-tunnel-up.sh and still requires ssh-tunnel-up.sh"
    - "No repo source file outside .planning/ references WireGuard, wg0, WG_* secrets, or 51820 except where intentionally documenting their removal"
    - "k3s API 6443 is documented as private (reached only via the SSH local-forward), never exposed externally"
    - "bootstrap-edge.sh applies the edge firewall without requiring a wg0 interface and adds no public 6443 allow rule"
    - "10.8.0.1 cert-SAN handling (operator-bootstrap Step 5, kubeconfig --tls-server-name) is preserved untouched"
    - "Every script comment that named WireGuard as the access prerequisite now names the SSH local-forward / kubectl-reachable equivalent"
    - "The dedicated WG-access doc is rewritten to the SSH-tunnel reality and renamed to docs/k3s-api-access.md, with no in-repo link pointing at the old wireguard-access.md path"
    - "docs/edge-bootstrap.md matches the reworked bootstrap-edge.sh: 6443 documented as private (default-deny, reached via SSH local-forward), no wg0 pre-check or wg0-qualified 6443 rule described"
    - "python3 scripts/validate-staging.py, bash -n on every edited shell script, and a YAML parse of deploy-staging.yml all pass"
  artifacts:
    - path: ".github/workflows/deploy-staging.yml"
      provides: "validate job without the wg-tunnel-up.sh test -f line"
      contains: "test -f scripts/ssh-tunnel-up.sh"
    - path: "scripts/bootstrap-edge.sh"
      provides: "edge firewall bootstrap with no wg0 dependency and no public 6443 rule"
    - path: "scripts/validate-edge.py"
      provides: "bootstrap idempotency validator that no longer asserts the wg0 6443 literal"
    - path: "docs/operator-bootstrap.md"
      provides: "SSH-tunnel CI access section replacing the WireGuard secrets section; Step 5 SAN handling retained"
    - path: "docs/k3s-api-access.md"
      provides: "SSH-local-forward operator access doc (renamed from wireguard-access.md), documenting the forward-only VPS user and kubectl over 127.0.0.1:16443 with --tls-server-name=10.8.0.1"
      contains: "permitopen"
    - path: "docs/edge-bootstrap.md"
      provides: "edge runbook synced with the reworked bootstrap-edge.sh — 6443 documented as private behind the SSH local-forward, no wg0 rule/pre-check"
  key_links:
    - from: ".github/workflows/deploy-staging.yml"
      to: "scripts/ssh-tunnel-up.sh"
      via: "Open SSH tunnel step runs ssh-tunnel-up.sh (already wired — do not change)"
      pattern: "scripts/ssh-tunnel-up.sh"
    - from: "scripts/validate-staging.py"
      to: "scripts/validate-edge.py"
      via: "py_compile of validate-edge.py (syntax only — edge assertions are not run by validate-staging)"
      pattern: "validate-edge.py"
---

<objective>
Remove every WireGuard remnant from the repo locations enumerated in the quick
scope, and align the prose with the SSH-tunnel reality: CD and local kubectl
access now run over an SSH local-forward (`scripts/ssh-tunnel-up.sh` opens
`127.0.0.1:16443 -> k3s API 6443` over TCP). WG is fully decommissioned — WG_*
GitHub secrets deleted, VPS + local `wg0` interfaces torn down. SSH is the ONLY
transport.

Purpose: Stop the repo from advertising a decommissioned, non-existent transport
(misleading runbooks, a CI `test -f` that would fail once the script is deleted,
and a firewall script that refuses to run because `wg0` no longer exists).

Output: wg-tunnel-up.sh deleted; CI validate job, README, observability +
operator-bootstrap docs, AGENTS.md, and the two named preflight/validate scripts
re-pointed to SSH; bootstrap-edge.sh reworked to apply the edge firewall with no
`wg0` dependency and no public 6443 exposure; and the two in-repo validators that
assert the now-removed wg0 firewall literal (validate-edge.py, teardown-edge.sh)
brought back into agreement so the repo stays internally consistent.

NOTE — additions beyond the 9 scoped items (Task 4): the scope brief listed 9
edits. Discovery found that `scripts/validate-edge.py:200` hard-requires the
EXACT literal "ufw allow in on wg0 to any port 6443 proto tcp" inside
bootstrap-edge.sh, and `scripts/teardown-edge.sh:97` deletes that same rule.
Removing the rule (scoped item 7) without updating these two would leave a
checked-in validator that FATALs on the new bootstrap-edge.sh and a teardown that
references a rule that is never created. They are a load-bearing coupling of item
7, not discretionary extras, so they are included here and called out explicitly
for veto.

EXTENSION (Tasks 5-7) — full WG sweep: the user has since confirmed WireGuard
must be removed ENTIRELY, so the remnants the first pass flagged as out of scope
are now in scope. Tasks 5-7 sweep the remaining script comments, the doc passing
mentions, the WG-key-rotation procedure, the edge-bootstrap runbook (synced to the
reworked bootstrap-edge.sh), and the dedicated WG-access doc (rewritten to the
SSH-tunnel reality and renamed to docs/k3s-api-access.md). Classification result:
the five remaining scripts (validate-stack.sh, validate-phase-12/15/16.sh,
restore-drill.sh) contain ONLY cosmetic "WireGuard tunnel up" prerequisite
comments — no functional WG assertion; the only functional script-level WG
assertions are validate-edge.py:200 + teardown-edge.sh:97, already owned by Task 4.
After Tasks 1-7 there is NO functional WG reference and no doc describing WG as the
live access path anywhere outside .planning/ (historical planning notes are left).
</objective>

<execution_context>
@.claude/gsd-core/workflows/execute-plan.md
@.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@AGENTS.md
@scripts/ssh-tunnel-up.sh
@scripts/kubeconfig-setup.sh
@scripts/bootstrap-edge.sh
@scripts/validate-edge.py
@scripts/teardown-edge.sh
@.github/workflows/deploy-staging.yml
@docs/operator-bootstrap.md
@docs/observability.md
@README.md

Repo conventions (AGENTS.md): Script Style (`#!/usr/bin/env bash`,
`set -euo pipefail`, explicit required-var checks, exit 64 on missing config),
Manifest Style, Secret Handling (NO secret values in git or docs — hard
constraint). Do NOT modify scripts/ssh-tunnel-up.sh or scripts/kubeconfig-setup.sh.
Do NOT remove 10.8.0.1 cert-SAN handling — it is load-bearing for SSH-tunnel TLS
(kubectl over the forward uses `--tls-server-name=10.8.0.1`).

Ground truth for the new transport (from ssh-tunnel-up.sh / deploy-staging.yml):
- `scripts/ssh-tunnel-up.sh` opens `ssh -fN -L 16443:127.0.0.1:6443` to
  `${DEPLOY_SSH_USER}@${DEPLOY_SSH_HOST}` and fail-closed probes 127.0.0.1:16443.
- Staging-env secrets in use: DEPLOY_SSH_PRIVATE_KEY, DEPLOY_SSH_KNOWN_HOSTS,
  DEPLOY_SSH_HOST, DEPLOY_SSH_USER.
- kubeconfig-setup.sh points kubectl at https://127.0.0.1:16443 with
  --tls-server-name=10.8.0.1 (CA SAN includes 10.8.0.1, not 127.0.0.1).
</context>

<tasks>

<task type="auto">
  <name>Task 1: Delete wg-tunnel-up.sh; de-WireGuard the CI validate job, README, AGENTS.md, and the two preflight/validate-script comments</name>
  <files>scripts/wg-tunnel-up.sh, .github/workflows/deploy-staging.yml, README.md, AGENTS.md, scripts/validate-phase-13.sh, scripts/resource-preflight.sh</files>
  <action>
1. DELETE scripts/wg-tunnel-up.sh entirely with `git rm scripts/wg-tunnel-up.sh` (remove the file, do not blank it).
2. .github/workflows/deploy-staging.yml — in the validate job "Validate manifests and scripts" step, REMOVE the line testing for scripts/wg-tunnel-up.sh (currently line 33). KEEP the adjacent line testing for scripts/ssh-tunnel-up.sh — it already exists and must stay. Touch no other workflow line (SSH tunnel steps are already wired).
3. scripts/validate-staging.py — VERIFY only; discovery confirms it references scripts/ssh-tunnel-up.sh (line 211) and NOT wg-tunnel-up.sh. Make NO edit unless a wg-tunnel-up.sh reference is actually present. (Explicit no-op per scope item 3.)
4. README.md — rewrite the two WireGuard mentions to the SSH tunnel:
   - The Layout bullet that currently describes scripts/wg-tunnel-up.sh as "brings up the CI WireGuard tunnel to the k3s API and gates on a successful handshake before any kubectl" -> replace with a scripts/ssh-tunnel-up.sh bullet: opens an SSH local-forward (127.0.0.1:16443 -> k3s API 6443) over TCP and fail-closed gates on the forwarded port being reachable before any kubectl.
   - The Deploy paragraph sentence "the workflow opens a WireGuard tunnel to the closed k3s API" -> rewrite to "the workflow opens an SSH local-forward to the closed k3s API (scripts/ssh-tunnel-up.sh)". Leave the rest of that paragraph unchanged (kubeconfig from ci-deployer SA token, applies k8s/staging excluding operator-managed manifests, rollout waits).
5. AGENTS.md — update the two references to scripts/wg-tunnel-up.sh (under CI/CD, and under "CI deploy helpers" in Entry Points): change scripts/wg-tunnel-up.sh to scripts/ssh-tunnel-up.sh and adjust WireGuard wording to SSH tunnel / SSH local-forward. Touch no unrelated AGENTS.md content.
6. scripts/validate-phase-13.sh — comment-only: change the header comment that reads "(WireGuard tunnel up from operator workstation or CI):" to the SSH-tunnel equivalent (e.g. "(kubectl reachable — SSH local-forward up from operator workstation or CI, or run on the staging node):"). Executable code unchanged.
7. scripts/resource-preflight.sh — comment-only: change the usage line that reads "(or from operator workstation with WireGuard tunnel up)" and the later note "run from a WireGuard operator workstation" to the SSH-tunnel equivalent (kubectl reachable via the SSH local-forward, or run on the k3s node over SSH). Executable code unchanged.

Follow repo Script Style — for the .sh files in this task, comment-only edits; do not alter executable behavior. NO secret values anywhere.
  </action>
  <verify>
    <automated>cd . && test ! -e scripts/wg-tunnel-up.sh && grep -q 'test -f scripts/ssh-tunnel-up.sh' .github/workflows/deploy-staging.yml && ! grep -lq 'wg-tunnel-up.sh' .github/workflows/deploy-staging.yml README.md AGENTS.md && python3 -c "import yaml; yaml.safe_load(open('.github/workflows/deploy-staging.yml')); print('yaml ok')" && bash -n scripts/validate-phase-13.sh && bash -n scripts/resource-preflight.sh && echo PASS</automated>
  </verify>
  <done>scripts/wg-tunnel-up.sh is gone; the validate job tests for ssh-tunnel-up.sh but not wg-tunnel-up.sh; README + AGENTS.md describe the SSH local-forward with no WireGuard wording; both preflight/validate scripts pass bash -n and their WireGuard comments now read SSH; deploy-staging.yml parses as valid YAML.</done>
</task>

<task type="auto">
  <name>Task 2: Re-point observability.md and operator-bootstrap.md to the SSH tunnel; preserve Step 5 cert-SAN handling</name>
  <files>docs/observability.md, docs/operator-bootstrap.md</files>
  <action>
docs/observability.md — replace the two WireGuard references with the SSH-tunnel equivalent:
  - In the deploy-workflow bullet, change "obs-ci-deployer token + WireGuard" to "obs-ci-deployer token + SSH local-forward".
  - In the "One-time operator bootstrap" intro, change "WireGuard up, or SSH to the staging node where kubectl is local." to "Reach kubectl via the SSH local-forward (scripts/ssh-tunnel-up.sh), or SSH to the staging node where kubectl is local."

docs/operator-bootstrap.md:
  - Line ~7 (intro): change "For token and WireGuard key rotation after the initial setup, see docs/sa-token-rotation.md" to "For token and SSH key rotation after the initial setup, see docs/sa-token-rotation.md". (Do not edit sa-token-rotation.md itself — out of scope; see OUT OF SCOPE note.)
  - KEEP Step 5 verbatim (patch k3s API cert SAN to include 10.8.0.1). It is STILL REQUIRED — kubectl over the forward uses --tls-server-name=10.8.0.1. Do not remove or weaken it.
  - REPLACE Step 6 "Configure WireGuard secrets in GitHub" in full (the WG_PRIVATE_KEY/WG_PEER_PUBLIC_KEY/WG_ENDPOINT table, the "add the CI runner peer to the WireGuard interface" [Peer] block, and the "reload WireGuard on the VPS" wg syncconf command) with an SSH-tunnel setup section. New Step 6 content: CI reaches the k3s API via an SSH local-forward (scripts/ssh-tunnel-up.sh) to a forward-only SSH user on the VPS. Document the staging-env secrets now needed in a table — DEPLOY_SSH_PRIVATE_KEY (forward-only SSH private key for the CI runner), DEPLOY_SSH_KNOWN_HOSTS (pinned host key for the VPS, format: `ssh-keyscan -p 22 <host>` output), DEPLOY_SSH_HOST (VPS SSH host), DEPLOY_SSH_USER (the forward-only VPS username) — descriptions only, NO secret values. Document the forward-only VPS user: a dedicated non-login user whose authorized_keys entry is locked with restrict,port-forwarding,permitopen="127.0.0.1:6443",command="/bin/false" so it can ONLY open the local-forward to the k3s API and run no commands. State 6443 is never exposed externally — it is reached only through this forward to 127.0.0.1:6443.
  - Verification section intro currently says "Once all six steps are complete" — keep the step count consistent with the rewritten Step 6 (still six steps); adjust only if your rewrite changes the count.
  - Troubleshooting table: REMOVE the row "WireGuard handshake did not complete / 51820/udp egress blocked". Optionally ADD SSH rows: "Load key ... error in libcrypto" -> DEPLOY_SSH_PRIVATE_KEY secret missing the trailing newline; "Permission denied (publickey)" -> key not authorized on the VPS forward-only user, or wrong DEPLOY_SSH_USER. KEEP the "x509 ... not 10.8.0.1" row (still valid — SAN dependency).

NO secret values anywhere. Follow the existing Markdown table / heading style in the file.
  </action>
  <verify>
    <automated>cd . && ! grep -niq 'wireguard\|wg_private\|wg_peer\|wg_endpoint\|51820\|wg syncconf\|10\.8\.0\.2' docs/observability.md docs/operator-bootstrap.md && grep -q '10.8.0.1' docs/operator-bootstrap.md && grep -q 'tls-san' docs/operator-bootstrap.md && grep -q 'ssh-tunnel-up.sh' docs/operator-bootstrap.md && grep -q 'permitopen' docs/operator-bootstrap.md && echo PASS</automated>
  </verify>
  <done>observability.md and operator-bootstrap.md contain no WireGuard/WG_*/51820/10.8.0.2 references; operator-bootstrap Step 5 (10.8.0.1 tls-san patch) is intact; Step 6 documents the four DEPLOY_SSH_* secrets and the restrict,port-forwarding,permitopen="127.0.0.1:6443",command="/bin/false" forward-only VPS user with no secret values; the WireGuard handshake troubleshooting row is gone.</done>
</task>

<task type="auto">
  <name>Task 3: Rework bootstrap-edge.sh — drop the wg0 pre-check and the wg0 6443 ufw rule; document 6443 as private (no public allow)</name>
  <files>scripts/bootstrap-edge.sh</files>
  <action>
In the "=== 7. ufw firewall rules ===" block (currently lines ~142-165):
  - REMOVE the wg0 existence pre-check (`if ip link show wg0 ...`) AND the `ufw allow in on wg0 to any port 6443 proto tcp ... 'k3s API via WireGuard only'` rule AND its `else ... FATAL: wg0 not found ...` branch. With WG decommissioned there is no wg0 interface, so this block would always hit the FATAL and refuse to apply the firewall.
  - Do NOT add any external/public 6443 allow rule (a bare `ufw allow 6443` would expose the k3s API publicly — forbidden).
  - ADD a clear comment in place of the removed block explaining: 6443 is intentionally NOT exposed externally — the k3s API is reached only via the SSH local-forward to 127.0.0.1:6443 (scripts/ssh-tunnel-up.sh), so the ufw `default deny incoming` policy keeps it private. No 6443 ufw rule is needed or wanted.
  - PRESERVE every other ufw rule and behavior: `ufw default deny incoming`, `ufw default allow outgoing`, the 22/tcp SSH rule, 80/tcp, 443/tcp, the `ufw --force enable` gate, and `ufw status verbose`. The SKIP_UFW guard stays.
  - Also update the closing operator-verification echo "4. ufw status verbose (confirm split-tunnel rules)" wording if it implies a wg0/split-tunnel 6443 rule — change "split-tunnel rules" to "edge rules (22/80/443; 6443 intentionally absent — reached via SSH local-forward)".

Follow repo Script Style — keep `set -euo pipefail`, the FATAL-on-failure pattern for the remaining ufw calls, and idempotency. Do not touch any block other than section 7 and the section-7-related closing echo. NO secret values.
  </action>
  <verify>
    <automated>cd . && bash -n scripts/bootstrap-edge.sh && ! grep -q 'wg0' scripts/bootstrap-edge.sh && ! grep -Eq 'ufw allow [^2489]*6443' scripts/bootstrap-edge.sh && grep -q 'ufw allow 22/tcp' scripts/bootstrap-edge.sh && grep -q 'ufw allow 80/tcp' scripts/bootstrap-edge.sh && grep -q 'ufw allow 443/tcp' scripts/bootstrap-edge.sh && grep -q 'ufw default deny incoming' scripts/bootstrap-edge.sh && echo PASS</automated>
  </verify>
  <done>bootstrap-edge.sh passes bash -n; no `wg0` reference and no 6443 ufw allow rule remain; the 22/80/443 rules, default-deny-incoming, --force enable gate, and SKIP_UFW guard are intact; a comment documents that 6443 stays private behind the SSH local-forward.</done>
</task>

<task type="auto">
  <name>Task 4: Realign the two in-repo validators that assert the removed wg0 firewall literal (coupling of Task 3 — flagged beyond the 9 scoped items)</name>
  <files>scripts/validate-edge.py, scripts/teardown-edge.sh</files>
  <action>
These two edits are NOT in the brief's 9 items but are a hard coupling of Task 3 — without them the repo is internally inconsistent (a checked-in validator FATALs on the new bootstrap-edge.sh; a teardown deletes a rule that is never created). If the developer vetoes, Task 3 must be reverted too, since the two cannot diverge.

scripts/validate-edge.py (validate_bootstrap_script, lines ~195-204):
  - REMOVE the `require("ufw allow in on wg0 to any port 6443 proto tcp" in content, ...)` assertion and its multi-line message (the D-7 wg0 literal check). This literal is no longer present in bootstrap-edge.sh by design.
  - ADD a negative assertion that 6443 is NOT publicly exposed: require that no bare public 6443 allow rule exists — i.e. `require("ufw allow in on wg0" not in content and not re.search(r"ufw allow (in )?6443", content), "...")` with a message explaining 6443 must stay private (reached only via the SSH local-forward; ufw default-deny keeps it closed; no `ufw allow 6443` and no wg0 rule). KEEP the existing `ufw allow 80` / `ufw allow 443` / `nginx -t` / lineage assertions unchanged. The `re` module is already imported (used at line ~190).
  - Adjust the surrounding "D-7" comment to reflect the new invariant (6443 private behind SSH local-forward; no interface-qualified wg0 rule).

scripts/teardown-edge.sh (line ~97 and the closing echo ~103):
  - The `delete_rule "6443/tcp on wg0" allow in on wg0 to any port 6443 proto tcp` call now targets a rule that bootstrap never creates. Because `delete_rule` already skips cleanly when the rule is absent (it greps `ufw status` first), removing it is safe and removes the dead WireGuard reference. REMOVE that `delete_rule` line.
  - Update the closing echo "Removed: ... ufw 80/443/6443-wg0" to "Removed: ... ufw 80/443" (drop the 6443-wg0 token). Update the comment at line ~84 that references "the 6443/wg0 rule still active" only if it now reads as stale — keep the delete_rule helper's general explanation but drop the wg0-specific example if it misleads.
  - PRESERVE the 22/tcp-preservation comments, the `ufw disable` prohibition, and the 80/443 delete_rule calls.

Follow repo Script Style / Python style already in those files. NO secret values.
  </action>
  <verify>
    <automated>cd . && python3 -m py_compile scripts/validate-edge.py && bash -n scripts/teardown-edge.sh && ! grep -q 'wg0' scripts/validate-edge.py scripts/teardown-edge.sh && grep -q 'ufw allow 80' scripts/validate-edge.py && grep -q 'ufw allow 443' scripts/validate-edge.py && echo PASS</automated>
  </verify>
  <done>validate-edge.py compiles and no longer asserts the wg0 6443 literal (instead asserts 6443 is not publicly exposed), keeping its 80/443/nginx-t/lineage checks; teardown-edge.sh passes bash -n and no longer references the wg0 6443 rule; neither file contains `wg0`.</done>
</task>

<task type="auto">
  <name>Task 5: Sweep the remaining script comments — reword the cosmetic "WireGuard tunnel up" prerequisites to the SSH-local-forward / kubectl-reachable equivalent</name>
  <files>scripts/validate-stack.sh, scripts/validate-phase-12.sh, scripts/validate-phase-15.sh, scripts/validate-phase-16.sh, scripts/restore-drill.sh</files>
  <action>
CLASSIFICATION (from discovery — all five are COSMETIC, none assert WG state):
each hit is a prose prerequisite ("WireGuard tunnel up", "WireGuard tunnel must be
up") telling the operator how kubectl reaches the cluster. None greps for a wg ufw
rule, checks a handshake / 51820, or requires a wg0 interface to be present. So
these are comment/echo-string reword only — executable code is UNCHANGED. (The
only functional script-level WG assertions live in validate-edge.py +
teardown-edge.sh, already handled in Task 4 — do NOT touch those here.)

1. scripts/validate-stack.sh — line ~84, inside the cluster-reachability preflight
   FATAL echo. The hint string currently reads "Ensure the WireGuard tunnel is up
   and KUBECONFIG points at the staging cluster." Reword to the SSH reality, e.g.
   "Ensure the SSH local-forward to the k3s API is up (scripts/ssh-tunnel-up.sh, or
   an operator `ssh -L 16443:127.0.0.1:6443`) and KUBECONFIG points at the staging
   cluster." This is a >&2 echo string only — the `kubectl cluster-info` probe
   above it is the actual gate and stays exactly as-is.
2. scripts/validate-phase-12.sh — header comment line ~10-11 "Requires: kubectl
   configured and pointing at solid-stats-staging cluster (WireGuard tunnel up from
   operator workstation or CI)." Reword the parenthetical to "(kubectl reachable —
   SSH local-forward up from operator workstation or CI, or run on the staging node
   over SSH)."
3. scripts/validate-phase-15.sh — header comment line ~7-8 "Run after all Phase 15
   obs manifests have been applied to the cluster (WireGuard tunnel up from operator
   workstation or CI):" Reword the parenthetical to the same SSH-local-forward
   equivalent as above.
4. scripts/validate-phase-16.sh — header comment line ~7-8 "Run after all Phase 16
   manifests have been applied (WireGuard tunnel up or kubectl configured against
   staging cluster):" Reword to "(kubectl configured against staging cluster — via
   the SSH local-forward, or on the staging node):" (drop the WireGuard clause).
5. scripts/restore-drill.sh — header comment line ~6 "Requires: kubectl in PATH,
   WireGuard tunnel up (if running against remote cluster)." Reword the parenthetical
   to "kubectl in PATH and reachable (SSH local-forward up if running against the
   remote cluster)."

Follow repo Script Style (`#!/usr/bin/env bash`, `set -euo pipefail` are already
present — do not alter). Comment/echo-string edits ONLY; do not change any
assertion, flag, or executable line. NO secret values.
  </action>
  <verify>
    <automated>cd . && for f in scripts/validate-stack.sh scripts/validate-phase-12.sh scripts/validate-phase-15.sh scripts/validate-phase-16.sh scripts/restore-drill.sh; do bash -n "$f" || exit 1; done && ! grep -niE 'wireguard|wg0|wg-tunnel-up|51820' scripts/validate-stack.sh scripts/validate-phase-12.sh scripts/validate-phase-15.sh scripts/validate-phase-16.sh scripts/restore-drill.sh && grep -q 'ssh-tunnel-up.sh\|local-forward' scripts/validate-stack.sh && echo PASS</automated>
  </verify>
  <done>All five scripts pass `bash -n`; none contains WireGuard/wg0/wg-tunnel-up/51820; each prerequisite comment/echo now names the SSH local-forward (or kubectl-reachable) equivalent; no executable line changed.</done>
</task>

<task type="auto">
  <name>Task 6: Sweep doc passing-mentions to the SSH tunnel; de-WG sa-token-rotation.md (drop the WG key-rotation procedure)</name>
  <files>docs/staging.md, docs/glitchtip.md, docs/s3-lifecycle.md, docs/backup-restore.md, docs/resource-protection.md, docs/sa-token-rotation.md</files>
  <action>
PASSING MENTIONS — reword WireGuard -> SSH local-forward (k3s API reached via the
SSH local-forward; operator runs kubectl over the tunnel or on the node). NO secret
values; preserve each file's existing heading/table style.

1. docs/staging.md:
   - Line ~5-6 intro: "For remote `kubectl` access from a workstation over WireGuard
     (instead of running kubectl on the VPS over SSH), see [WireGuard Access](./wireguard-access.md)."
     -> rewrite to point at the renamed doc and the SSH-forward method, e.g. "For
     remote `kubectl` access from a workstation via the SSH local-forward (instead of
     running kubectl on the VPS directly), see [k3s API Access](./k3s-api-access.md)."
     (Task 7 creates k3s-api-access.md and deletes wireguard-access.md — this link must
     point at the new path so no link dangles.)
   - Lines ~66-68 "Required GitHub Secrets" list: REMOVE the three WG_* bullets
     (`WG_PRIVATE_KEY`, `WG_PEER_PUBLIC_KEY`, `WG_ENDPOINT`) and REPLACE with the
     four DEPLOY_SSH_* secrets the SSH tunnel needs — `DEPLOY_SSH_PRIVATE_KEY`
     (forward-only CI SSH private key), `DEPLOY_SSH_KNOWN_HOSTS` (pinned VPS host key),
     `DEPLOY_SSH_HOST` (VPS SSH host), `DEPLOY_SSH_USER` (forward-only VPS user).
     Descriptions only, NO values. Keep `K8S_TOKEN`, `K8S_CA_CERT`, and the rest.
   - Line ~133 "the infrastructure workflow deploys over the WireGuard tunnel."
     -> "the infrastructure workflow deploys over the SSH local-forward."
   - Lines ~139-141 "The deploy job brings up a WireGuard tunnel to the closed k3s API
     (`scripts/wg-tunnel-up.sh`), builds a kubeconfig..." -> "The deploy job opens an
     SSH local-forward to the closed k3s API (`scripts/ssh-tunnel-up.sh`), builds a
     kubeconfig..." Leave the kubeconfig-setup.sh / exclude-01-ci-rbac.yaml clause intact.
2. docs/glitchtip.md:
   - Line ~41 "`WG_PRIVATE_KEY`, `WG_PEER_PUBLIC_KEY`, `WG_ENDPOINT` — set during
     Phase 13/14." -> replace with the DEPLOY_SSH_* secrets (or, if the sentence is
     only cross-referencing CI access, reword to "the `DEPLOY_SSH_*` tunnel secrets —
     see docs/operator-bootstrap.md"). NO values.
   - Lines ~88, ~143 "(WireGuard tunnel up)" / "(WireGuard tunnel up to staging VPS)"
     -> "(kubectl reachable via the SSH local-forward)" / "(SSH local-forward to the
     staging VPS up)".
3. docs/s3-lifecycle.md:
   - Line ~81 "WireGuard tunnel to the staging cluster is up (`wg show` confirms the
     interface is active)." -> "SSH local-forward to the staging cluster is up
     (`kubectl cluster-info` confirms the API is reachable)."
   - Line ~140 "same cluster access as Section 3 (WireGuard up, KUBECONFIG set)."
     -> "same cluster access as Section 3 (SSH local-forward up, KUBECONFIG set)."
4. docs/backup-restore.md:
   - Line ~60 "From a machine with `kubectl` access to the cluster (WireGuard tunnel
     must be up):" -> "...(SSH local-forward to the k3s API must be up):".
5. docs/resource-protection.md:
   - Line ~31 "...requires kubectl access via WireGuard):" -> "...requires kubectl
     access via the SSH local-forward):".
6. docs/sa-token-rotation.md — this is more than a passing mention (whole Step 2
   rotates the WG key pair), and a doc describing WG as the live mechanism violates
   the hard constraint. De-WG it fully:
   - Title line ~1 "# ServiceAccount Token and WireGuard Key Rotation" -> "# ServiceAccount
     Token and CI SSH Key Rotation".
   - Intro lines ~3-7: replace "the WireGuard key pair used by GitHub Actions to reach
     the k3s API" with "the forward-only CI SSH key used by GitHub Actions to reach the
     k3s API over the SSH local-forward".
   - Overview Scope row ~19: change "WireGuard key pair (`WG_PRIVATE_KEY` +
     `WG_PEER_PUBLIC_KEY`)" to "CI SSH key (`DEPLOY_SSH_PRIVATE_KEY`, plus the matching
     public key on the VPS forward-only user)".
   - Step 2 (lines ~62-113) "Rotate the WireGuard Key Pair": REPLACE the whole step
     with "Rotate the CI SSH Key" — generate a new SSH keypair for the forward-only CI
     user (`ssh-keygen -t ed25519 -N '' -f <file>` — describe, do not embed a key);
     update the `DEPLOY_SSH_PRIVATE_KEY` GitHub secret (and refresh `DEPLOY_SSH_KNOWN_HOSTS`
     only if the host key changed); on the VPS, replace the public key in the
     forward-only user's `~/.ssh/authorized_keys` line (keeping the
     `restrict,port-forwarding,permitopen="127.0.0.1:6443",command="/bin/false"`
     options prefix); verify by triggering a CI deploy and confirming the SSH
     local-forward opens and `kubectl auth whoami` is non-anonymous. Remove every
     `wg genkey` / `wg pubkey` / `wg syncconf` / `wg-quick@wg0` / `wg show ... latest-handshakes`
     command and the `/etc/wireguard/wg0.conf` reference. NO secret values.
   - Overview Scope and "same window" rules: keep the ordering rule (update GitHub
     secrets before the VPS side) — it still applies to the SSH key.
   - Troubleshooting table ~133-135: replace the two WG rows ("WireGuard handshake did
     not complete", "`WG_PEER_PUBLIC_KEY` rejected") with SSH equivalents ("SSH
     local-forward fails to open / Permission denied (publickey)" -> new key not yet in
     the VPS forward-only user's authorized_keys, or `DEPLOY_SSH_PRIVATE_KEY` missing its
     trailing newline; "ExitOnForwardFailure / port 6443 refused" -> permitopen does not
     match 127.0.0.1:6443). In the "Rotation fails mid-window" row change `WG_PRIVATE_KEY`
     to `DEPLOY_SSH_PRIVATE_KEY`.
   - Related Documents ~139-140: change "WireGuard setup" to "SSH-tunnel setup".

After this task, none of these six docs may contain WireGuard/WG_*/51820/wg0/
wg-quick/wg syncconf/wireguard-access. NO secret values anywhere.
  </action>
  <verify>
    <automated>cd . && ! grep -niE 'wireguard|wg_private|wg_peer|wg_endpoint|wg0|wg-quick|wg syncconf|51820|wireguard-access' docs/staging.md docs/glitchtip.md docs/s3-lifecycle.md docs/backup-restore.md docs/resource-protection.md docs/sa-token-rotation.md && grep -q 'DEPLOY_SSH_PRIVATE_KEY' docs/staging.md && grep -q 'k3s-api-access.md' docs/staging.md && grep -q 'permitopen' docs/sa-token-rotation.md && echo PASS</automated>
  </verify>
  <done>The six docs contain no WireGuard/WG_*/wg0/51820/wireguard-access references; staging.md lists the four DEPLOY_SSH_* secrets and links to ./k3s-api-access.md; sa-token-rotation.md's title and Step 2 document CI SSH-key rotation against the forward-only VPS user with no WG commands; all passing-mention prerequisites read SSH local-forward. No secret values.</done>
</task>

<task type="auto">
  <name>Task 7: Sync docs/edge-bootstrap.md with the reworked bootstrap-edge.sh; rewrite docs/wireguard-access.md to the SSH-tunnel reality and rename it to docs/k3s-api-access.md</name>
  <files>docs/edge-bootstrap.md, docs/wireguard-access.md, docs/k3s-api-access.md</files>
  <action>
Depends on Task 3 (bootstrap-edge.sh reworked: no wg0 pre-check, no wg0 6443 rule,
6443 private behind the SSH local-forward). This task brings the edge runbook into
agreement and replaces the dedicated WG-access doc. NO secret values; preserve each
file's heading/table style and all non-WG content.

PART A — docs/edge-bootstrap.md (sync to the reworked script):
  - Line ~17 "Applies ufw split-tunnel firewall rules (80/443 public, 6443 via
    WireGuard only)." -> "Applies ufw firewall rules (22/80/443 public; 6443 is NOT
    exposed externally — reached only via the SSH local-forward to 127.0.0.1:6443)."
  - Line ~26 Prerequisites bullet "WireGuard `wg0` interface up on the VPS (from
    Phase 6 ...)." -> REMOVE it. There is no wg0 prerequisite anymore. (Keep the
    SSH-access and ports-80/443 prerequisites.)
  - Lines ~68-69 "Applies ufw rules: `22/tcp`, `80/tcp`, `443/tcp` public; `6443/tcp`
    on `wg0` only (exits with `FATAL` if the `wg0` interface is absent ...)." ->
    "Applies ufw rules: `22/tcp`, `80/tcp`, `443/tcp` public. It adds NO 6443 rule —
    the k3s API stays private behind the `default deny incoming` policy and is reached
    only via the SSH local-forward (`scripts/ssh-tunnel-up.sh` -> 127.0.0.1:6443)."
  - Step 3d (lines ~111-125) "Firewall split-tunnel rules": retitle to "Firewall edge
    rules"; in the expected-rules list REMOVE the "`6443/tcp on wg0 ALLOW Anywhere`
    (k3s API — WireGuard only)" bullet and the following "The `6443` rule **must**
    include `on wg0` ..." paragraph; REPLACE with a note that 6443 is intentionally
    absent from `ufw status` (private, reached via the SSH local-forward; default-deny
    keeps it closed). Keep the 22/80/443 bullets.
  - Line ~199 teardown "ufw rules for `80/tcp`, `443/tcp`, and `6443/tcp on wg0`." ->
    "ufw rules for `80/tcp` and `443/tcp`." (matches the Task-4 teardown-edge.sh edit
    that drops the 6443/wg0 delete_rule). Line ~211 verify comment "80/443/6443 rules
    absent; 22 present" -> "80/443 rules absent; 22 present".
  - Troubleshooting table: REMOVE the "`ufw rule 6443 without 'on wg0'`" row (~224)
    and the "`FATAL: wg0 not found`" row (~226). Optionally ADD a row noting that if
    `ufw status` shows ANY `6443` allow rule it must be removed (`ufw delete allow
    6443/tcp`) because 6443 must stay private behind the SSH local-forward.
  - Line ~228 "See also: ... (Phase 6 WireGuard + RBAC bootstrap)." -> "(Phase 6 RBAC
    + SSH-tunnel bootstrap)".
  - Confirm the doc contains NO remaining wg0 / WireGuard / split-tunnel-6443 text.

PART B — rewrite + rename the dedicated WG-access doc:
  - CREATE docs/k3s-api-access.md documenting the CURRENT access method (no WG):
    * Title "# k3s API Access via SSH Local-Forward".
    * State 6443 is not exposed publicly (closed at ufw `default deny incoming` and the
      Timeweb perimeter); the API is reached only through an SSH local-forward to
      127.0.0.1:6443 on the VPS.
    * CI path: `scripts/ssh-tunnel-up.sh` opens `ssh -fN -L 16443:127.0.0.1:6443` to the
      forward-only VPS user and fail-closed probes 127.0.0.1:16443; kubeconfig built by
      `scripts/kubeconfig-setup.sh` points kubectl at https://127.0.0.1:16443 with
      `--tls-server-name=10.8.0.1` (the k3s CA SAN includes 10.8.0.1, not 127.0.0.1 —
      this SAN handling is load-bearing and must not be removed).
    * Operator path: a systemd-managed (or foreground) `ssh -L 16443:127.0.0.1:6443
      <forward-only-user>@<VPS_HOST>`, then `kubectl --server=https://127.0.0.1:16443
      --tls-server-name=10.8.0.1 ...` (describe a unit or a `ssh -fN` invocation; no
      secret values).
    * Forward-only VPS user: a dedicated non-login user whose authorized_keys entry is
      locked with the options prefix
      `restrict,port-forwarding,permitopen="127.0.0.1:6443",command="/bin/false"` so the
      key can ONLY open the local-forward to the k3s API and run no commands. Show the
      authorized_keys line SHAPE with a `<PUBLIC_KEY>` placeholder — never a real key.
    * Notes: TLS is always verified (no insecure-skip); cert SAN dependency on 10.8.0.1;
      the Happ/other-VPN bypass note (route VPS-host traffic outside any always-on VPN so
      SSH is not swallowed) — adapt the old WireGuard note to SSH.
  - DELETE docs/wireguard-access.md (use `git rm docs/wireguard-access.md`, or
    `git mv docs/wireguard-access.md docs/k3s-api-access.md` then overwrite the content —
    either way the old path must no longer exist).
  - GREP the repo for any remaining link to the old path and repoint it:
    `grep -rn 'wireguard-access' --include='*.md' . | grep -v '\.planning/'`. The known
    one is docs/staging.md (repointed in Task 6); fix any other non-.planning hit to
    ./k3s-api-access.md.

NO secret values (no private keys, no real public keys, no endpoints/IPs beyond the
already-public 10.8.0.1 SAN literal and 127.0.0.1 loopback). Follow repo Markdown style.
  </action>
  <verify>
    <automated>cd . && test ! -e docs/wireguard-access.md && test -e docs/k3s-api-access.md && ! grep -niE 'wireguard|wg0|51820|wg-quick' docs/edge-bootstrap.md docs/k3s-api-access.md && grep -q 'permitopen="127.0.0.1:6443"' docs/k3s-api-access.md && grep -q '10.8.0.1' docs/k3s-api-access.md && ! grep -rn 'wireguard-access' --include='*.md' docs/ README.md && ! grep -q 'wg0' docs/edge-bootstrap.md && echo PASS</automated>
  </verify>
  <done>docs/wireguard-access.md no longer exists; docs/k3s-api-access.md documents the SSH-local-forward CI + operator paths, the forward-only VPS user (restrict,port-forwarding,permitopen="127.0.0.1:6443",command="/bin/false"), and the 10.8.0.1 SAN dependency, with no secret values and no WG text; docs/edge-bootstrap.md describes 6443 as private behind the SSH local-forward with no wg0 pre-check/rule and matches the reworked bootstrap-edge.sh + teardown-edge.sh; no non-.planning Markdown link points at wireguard-access.md.</done>
</task>

</tasks>

<verification>
Phase-level (run after all seven tasks):

```
cd .
python3 scripts/validate-staging.py           # full structure validator (py_compiles validate-edge.py, bash -n's listed scripts incl. ssh-tunnel-up.sh)
bash -n scripts/bootstrap-edge.sh             # firewall script syntax
# bash -n every edited shell script:
for f in scripts/validate-stack.sh scripts/validate-phase-12.sh scripts/validate-phase-15.sh scripts/validate-phase-16.sh scripts/restore-drill.sh scripts/validate-phase-13.sh scripts/resource-preflight.sh scripts/teardown-edge.sh; do bash -n "$f"; done
python3 -m py_compile scripts/validate-edge.py                                            # python syntax
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/deploy-staging.yml'))"    # workflow YAML parse
# WHOLE-REPO WG sweep — only intentional/historical hits (ideally none functional) may remain, and .planning/ is excluded:
grep -rniE 'wireguard|wg-tunnel-up|wg0' --include='*.sh' --include='*.py' --include='*.yml' --include='*.md' . | grep -v '\.planning/'
# The renamed doc replaced the old one:
test ! -e docs/wireguard-access.md && test -e docs/k3s-api-access.md
! grep -rn 'wireguard-access' --include='*.md' --include='*.sh' --include='*.py' --include='*.yml' . | grep -v '\.planning/'
# Load-bearing preservations still present:
grep -q '10.8.0.1' docs/operator-bootstrap.md && grep -q 'tls-san' docs/operator-bootstrap.md   # cert SAN handling kept
grep -q '10.8.0.1' docs/k3s-api-access.md                                                       # SAN dependency documented in renamed doc
git status --short scripts/wg-tunnel-up.sh docs/wireguard-access.md                             # both deletions staged
```

All non-grep commands must succeed. The whole-repo WG sweep must return only
intentional/historical hits outside `.planning/` (target: zero functional refs);
the `wireguard-access` link grep must find nothing.
</verification>

<success_criteria>
- scripts/wg-tunnel-up.sh deleted (git rm).
- validate job no longer requires wg-tunnel-up.sh; still requires ssh-tunnel-up.sh.
- README, AGENTS.md, observability.md, operator-bootstrap.md, validate-phase-13.sh, resource-preflight.sh describe the SSH local-forward — zero WireGuard wording.
- operator-bootstrap.md Step 5 (10.8.0.1 cert SAN) intact; Step 6 documents the four DEPLOY_SSH_* secrets + the forward-only `restrict,port-forwarding,permitopen="127.0.0.1:6443",command="/bin/false"` VPS user, no secret values.
- bootstrap-edge.sh applies the edge firewall with no wg0 dependency and no public 6443 rule; 6443 documented as private behind the SSH forward.
- validate-edge.py and teardown-edge.sh no longer assert/reference the wg0 6443 rule and stay consistent with the new bootstrap-edge.sh.
- python3 scripts/validate-staging.py, bash -n scripts/bootstrap-edge.sh, and the deploy-staging.yml YAML parse all pass.
- scripts/ssh-tunnel-up.sh and scripts/kubeconfig-setup.sh untouched.
- (Tasks 5-7) The five remaining scripts (validate-stack.sh, validate-phase-12/15/16.sh, restore-drill.sh) pass bash -n with their WG prerequisite comments reworded to SSH; no executable line changed.
- (Tasks 5-7) docs/staging.md, glitchtip.md, s3-lifecycle.md, backup-restore.md, resource-protection.md, sa-token-rotation.md carry no WireGuard/WG_*/wg0/51820/wireguard-access references; sa-token-rotation.md documents CI SSH-key rotation; staging.md lists the four DEPLOY_SSH_* secrets.
- (Tasks 5-7) docs/edge-bootstrap.md matches the reworked bootstrap-edge.sh + teardown-edge.sh (6443 private, no wg0 rule/pre-check); docs/wireguard-access.md is deleted and replaced by docs/k3s-api-access.md (SSH-forward access doc), with no in-repo link to the old path.
- After Tasks 1-7, the whole-repo WG sweep (`grep -rniE 'wireguard|wg-tunnel-up|wg0' --include='*.sh' --include='*.py' --include='*.yml' --include='*.md' . | grep -v '.planning/'`) returns no functional reference and no doc describing WG as the live access path; historical .planning/** references are intentionally left.
</success_criteria>

<output>
Create `.planning/quick/260614-ulu-remove-wireguard-remnants-from-repo-cd-r/260614-ulu-SUMMARY.md` when done.
</output>
