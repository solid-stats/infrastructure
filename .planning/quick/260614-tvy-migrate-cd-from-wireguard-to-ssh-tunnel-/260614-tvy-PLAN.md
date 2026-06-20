---
phase: quick-260614-tvy
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - scripts/ssh-tunnel-up.sh
  - scripts/kubeconfig-setup.sh
  - scripts/validate-staging.py
  - .github/workflows/deploy-staging.yml
  - .github/workflows/deploy-observability.yml
autonomous: true
requirements: []
must_haves:
  truths:
    - "CI reaches the k3s API over an SSH local-forward instead of WireGuard"
    - "ssh-tunnel-up.sh fails closed (exit 1) when the forward is not reachable, and exit 64 when required config is missing"
    - "kubeconfig-setup.sh targets 127.0.0.1:16443 with --tls-server-name=10.8.0.1 by default and keeps multi-context obs behavior intact"
    - "python3 scripts/validate-staging.py passes after the change"
    - "scripts/wg-tunnel-up.sh and WG secrets remain in the repo for future WG restoration"
  artifacts:
    - path: "scripts/ssh-tunnel-up.sh"
      provides: "SSH local-forward gate for CI (mirrors wg-tunnel-up.sh conventions)"
      contains: "ExitOnForwardFailure=yes"
    - path: "scripts/kubeconfig-setup.sh"
      provides: "kubeconfig built against 127.0.0.1:16443 + tls-server-name override"
      contains: "tls-server-name"
    - path: ".github/workflows/deploy-staging.yml"
      provides: "dry-run + deploy jobs using the SSH tunnel transport"
      contains: "ssh-tunnel-up.sh"
    - path: ".github/workflows/deploy-observability.yml"
      provides: "obs deploy job using the SSH tunnel transport"
      contains: "ssh-tunnel-up.sh"
  key_links:
    - from: ".github/workflows/deploy-staging.yml"
      to: "scripts/ssh-tunnel-up.sh"
      via: "Open SSH tunnel step runs bash scripts/ssh-tunnel-up.sh with DEPLOY_SSH_* env"
      pattern: "ssh-tunnel-up\\.sh"
    - from: "scripts/ssh-tunnel-up.sh"
      to: "scripts/kubeconfig-setup.sh"
      via: "tunnel forwards LOCAL_PORT 16443 -> 127.0.0.1:6443; kubeconfig server points at 127.0.0.1:16443"
      pattern: "16443"
---

<objective>
Migrate CD from WireGuard to an SSH local-forward for k3s API access. WireGuard
over UDP is dead on the Timeweb VPS (the hypervisor drops all inbound UDP);
TCP/SSH works. Mirror the already-working local fix: a forward-only `tunnel-ci`
SSH user opens `-L 16443:127.0.0.1:6443`, and kubectl talks to
`https://127.0.0.1:16443` with `--tls-server-name=10.8.0.1` (the k3s CA SAN
includes 10.8.0.1 but not 127.0.0.1).

Purpose: Restore automated CD that has been broken since UDP was confirmed dead.
Output: A new `scripts/ssh-tunnel-up.sh`, an edited `kubeconfig-setup.sh`, both
deploy workflows swapped from WG steps to one SSH-tunnel step, and a validator
that recognizes the new script. WireGuard artifacts (script + secrets) stay for
future restoration.
</objective>

<execution_context>
@.claude/gsd-core/workflows/execute-plan.md
@.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@AGENTS.md
@scripts/wg-tunnel-up.sh
@scripts/kubeconfig-setup.sh
@.github/workflows/deploy-staging.yml
@.github/workflows/deploy-observability.yml
@scripts/validate-staging.py

Verified facts (do NOT re-discover):
- k3s API listens on the VPS at 127.0.0.1:6443; SSH to the VPS works over TCP.
- The k3s CA SAN includes 10.8.0.1 but NOT 127.0.0.1 — kubectl over the SSH
  local-forward MUST use `--tls-server-name=10.8.0.1`. Verified working:
  `kubectl --server=https://127.0.0.1:16443 --tls-server-name=10.8.0.1 get nodes`
  returns the node Ready.
- The GitHub `staging` environment ALREADY has secrets DEPLOY_SSH_PRIVATE_KEY,
  DEPLOY_SSH_KNOWN_HOSTS, DEPLOY_SSH_HOST, DEPLOY_SSH_USER. Do NOT create or
  modify any secret. The repo is PUBLIC, so host/user live in secrets (mirroring
  the existing WG_ENDPOINT-as-secret pattern), never hardcoded in YAML.
- `tunnel-ci` is a forward-only SSH user locked to permitopen=127.0.0.1:6443,
  no shell.
- Old WG secrets (WG_PRIVATE_KEY/WG_PEER_PUBLIC_KEY/WG_ENDPOINT) STAY.

IMPORTANT finding (corrects the task brief): `scripts/validate-staging.py` does
NOT reference `wg-tunnel-up.sh`. Its `validate_scripts()` checks a FIXED list of
bash scripts (backup-postgres-now.sh, restore-drill.sh, apply-s3-lifecycle.sh,
cutover.sh, resource-preflight.sh, validate-phase-12.sh) plus three py_compile
targets — none of them tunnel scripts. The `test -f scripts/wg-tunnel-up.sh`
assertion lives in the `validate` job step of `deploy-staging.yml` (line 33),
not in the Python validator. So: add `scripts/ssh-tunnel-up.sh` to the
validator's bash `-n` syntax loop (so the new script gets CI syntax coverage),
and update the workflow's `test -f` line to also assert the new script. Do NOT
delete the wg-tunnel-up.sh assertion.
</context>

<tasks>

<task type="auto">
  <name>Task 1: Create scripts/ssh-tunnel-up.sh mirroring wg-tunnel-up.sh conventions</name>
  <files>scripts/ssh-tunnel-up.sh</files>
  <action>
Create a NEW executable bash script that opens an SSH local-forward to the k3s
API and fail-closed verifies reachability. Mirror scripts/wg-tunnel-up.sh's
structure, comment style, and gate discipline EXACTLY:

- Shebang `#!/usr/bin/env bash` then `set -euo pipefail`.
- A header comment block in the same boxed style as wg-tunnel-up.sh: name the
  script, describe that it opens a background SSH local-forward and fail-closed
  verifies TCP reachability of the forwarded port, note that it exits 64 on
  missing required config and exits 1 if the forward is not reachable (the
  fail-closed gate analogous to wg's handshake-timeout gate), and a Usage line
  showing the DEPLOY_SSH_* env vars (NEVER include any secret value).

- Optional vars with defaults using the `: "${VAR:=default}"` idiom:
  `LOCAL_PORT=16443`, `REMOTE_API_HOST=127.0.0.1`, `REMOTE_API_PORT=6443`,
  and a small `REACHABILITY_TIMEOUT_SECS=10` for the probe.

- Required vars (exit 64 if missing) using the same `if [[ -z "${VAR:-}" ]]`
  blocks with `>&2` FATAL messages as wg-tunnel-up.sh: DEPLOY_SSH_PRIVATE_KEY,
  DEPLOY_SSH_KNOWN_HOSTS, DEPLOY_SSH_HOST, DEPLOY_SSH_USER.

- Print an opening banner line in wg's style, e.g. `=== SSH Tunnel Pre-flight Gate ===`.

- Key/known_hosts handling (mirror wg's "never on disk longer than needed"
  discipline as closely as ssh allows): create a chmod-600 temp identity file
  and a temp known_hosts file via `mktemp`, register a single
  `trap 'rm -f "$key_file" "$known_hosts_file"' EXIT` BEFORE writing them, then
  `printf '%s' "$DEPLOY_SSH_PRIVATE_KEY" > "$key_file"` and
  `chmod 600 "$key_file"`, and `printf '%s' "$DEPLOY_SSH_KNOWN_HOSTS" > "$known_hosts_file"`.
  NEVER echo/print the key or known_hosts contents. ssh needs an identity file
  on disk, so a 600 temp file removed on EXIT is the correct analogue to wg's
  stdin discipline — note this in a comment.

- Open the forward in the background with these EXACT options (pin the host key
  via the temp known_hosts; NEVER use StrictHostKeyChecking=no or accept-new):
  `ssh -fN -L "${LOCAL_PORT}:${REMOTE_API_HOST}:${REMOTE_API_PORT}"`
  `-i "$key_file"`
  `-o BatchMode=yes`
  `-o IdentitiesOnly=yes`
  `-o ExitOnForwardFailure=yes`
  `-o ServerAliveInterval=30`
  `-o ServerAliveCountMax=3`
  `-o ConnectTimeout=10`
  `-o StrictHostKeyChecking=yes`
  `-o UserKnownHostsFile="$known_hosts_file"`
  `"${DEPLOY_SSH_USER}@${DEPLOY_SSH_HOST}"`
  Print a progress line before opening it (do not print the host/user secret
  values verbatim beyond what is needed for an operator log — a generic
  "Opening SSH local-forward 127.0.0.1:${LOCAL_PORT} -> k3s API" line is fine).

- FAIL-CLOSED TCP reachability probe of 127.0.0.1:${LOCAL_PORT} analogous to
  wg's section 6: a short poll loop using `timeout` + bash `/dev/tcp` (e.g.
  `timeout 1 bash -c "echo > /dev/tcp/127.0.0.1/${LOCAL_PORT}"`), retrying until
  REACHABILITY_TIMEOUT_SECS elapses (use a `date +%s` start/elapsed pattern like
  wg's handshake loop). If never reachable, print a clear `FATAL:` message to
  `>&2` and `exit 1`. A short poll (not a single shot) is correct because
  `ssh -fN` backgrounds before the listener is necessarily bound.

- Final success line in wg's style:
  `SSH tunnel ready — k3s API reachable at 127.0.0.1:${LOCAL_PORT}`.

Do NOT place fenced code blocks in the file beyond normal script content. Keep
section comments (`# --- N. ... ---`) matching wg-tunnel-up.sh's numbering style.
After writing, make it executable.
  </action>
  <verify>
    <automated>cd . && bash -n scripts/ssh-tunnel-up.sh && grep -q 'ExitOnForwardFailure=yes' scripts/ssh-tunnel-up.sh && grep -q 'StrictHostKeyChecking=yes' scripts/ssh-tunnel-up.sh && grep -q 'exit 64' scripts/ssh-tunnel-up.sh && grep -q '16443' scripts/ssh-tunnel-up.sh && test -x scripts/ssh-tunnel-up.sh && ! grep -Eq 'StrictHostKeyChecking[= ](no|accept-new)' scripts/ssh-tunnel-up.sh && echo TUNNEL_OK</automated>
  </verify>
  <done>
scripts/ssh-tunnel-up.sh exists, is executable, passes `bash -n`, opens an
`ssh -fN -L 16443:127.0.0.1:6443` forward with the exact hardened option set,
pins the host key (no StrictHostKeyChecking=no/accept-new), exits 64 on any
missing DEPLOY_SSH_* var, fail-closed exits 1 when the forward is unreachable,
and never prints secret values. The verify command prints TUNNEL_OK.
  </done>
</task>

<task type="auto">
  <name>Task 2: Point kubeconfig-setup.sh at 127.0.0.1:16443 with --tls-server-name override</name>
  <files>scripts/kubeconfig-setup.sh</files>
  <action>
Edit scripts/kubeconfig-setup.sh with TWO scoped changes; leave every other
behavior (credentials, context, use-context, the `whoami` fail-closed check, the
no-`--insecure-skip-tls-verify` guarantee, and all the K8S_* context vars the obs
workflow overrides) byte-for-byte intact:

1. Change the default API server. The line
   `: "${K8S_API_SERVER:=https://10.8.0.1:6443}"` becomes
   `: "${K8S_API_SERVER:=https://127.0.0.1:16443}"`. Also update the header
   comment block that currently says it targets the k3s API over the WireGuard
   tunnel (https://10.8.0.1:6443) so it describes the SSH local-forward
   (https://127.0.0.1:16443 with a tls-server-name override) — keep the comment
   style and the "Never uses --insecure-skip-tls-verify" sentence.

2. Add a new optional var with the OTHER defaults block:
   `: "${K8S_TLS_SERVER_NAME:=10.8.0.1}"` (place it among the existing
   `: "${K8S_*:=...}"` defaults). Pass it to the cluster config by adding
   `--tls-server-name="$K8S_TLS_SERVER_NAME"` as an additional flag on the
   existing `kubectl config set-cluster` invocation (the same command that has
   `--certificate-authority`, `--embed-certs=true`, `--server`, `--kubeconfig`).
   This is required because the k3s CA SAN includes 10.8.0.1 but not 127.0.0.1,
   so TLS verification of the forwarded 127.0.0.1 endpoint must use the
   10.8.0.1 server name. Add a one-line comment explaining that.

Do NOT touch the credentials/context/use-context blocks or the auth verify.
  </action>
  <verify>
    <automated>cd . && bash -n scripts/kubeconfig-setup.sh && grep -q 'K8S_API_SERVER:=https://127.0.0.1:16443' scripts/kubeconfig-setup.sh && grep -q 'K8S_TLS_SERVER_NAME:=10.8.0.1' scripts/kubeconfig-setup.sh && grep -q 'tls-server-name="\$K8S_TLS_SERVER_NAME"' scripts/kubeconfig-setup.sh && grep -q 'system:anonymous' scripts/kubeconfig-setup.sh && ! grep -q 'insecure-skip-tls-verify' scripts/kubeconfig-setup.sh && echo KUBECONFIG_OK</automated>
  </verify>
  <done>
The default server is https://127.0.0.1:16443, K8S_TLS_SERVER_NAME defaults to
10.8.0.1 and is passed as --tls-server-name to set-cluster, the anonymous-auth
fail-closed check and the absence of --insecure-skip-tls-verify are preserved,
the script passes `bash -n`, and the verify command prints KUBECONFIG_OK. The
obs workflow's multi-context overrides still work because only the cluster
server/tls-server-name changed (context/user/token logic untouched).
  </done>
</task>

<task type="auto">
  <name>Task 3: Swap WG steps to one SSH-tunnel step in both workflows + update validators</name>
  <files>.github/workflows/deploy-staging.yml, .github/workflows/deploy-observability.yml, scripts/validate-staging.py</files>
  <action>
Three coordinated edits. Keep all surrounding step ordering and structure
identical — only the transport step and the validator references change.

A) .github/workflows/deploy-staging.yml — in BOTH the `dry-run` job and the
`deploy` job, replace the two consecutive steps "Install WireGuard tools" and
"Bring up WireGuard tunnel" (including its WG_PRIVATE_KEY/WG_PEER_PUBLIC_KEY/
WG_ENDPOINT/WG_LOCAL_IP env and the `run: bash scripts/wg-tunnel-up.sh`) with a
SINGLE step:

  - name: Open SSH tunnel
    env:
      DEPLOY_SSH_PRIVATE_KEY: ${{ secrets.DEPLOY_SSH_PRIVATE_KEY }}
      DEPLOY_SSH_KNOWN_HOSTS: ${{ secrets.DEPLOY_SSH_KNOWN_HOSTS }}
      DEPLOY_SSH_HOST: ${{ secrets.DEPLOY_SSH_HOST }}
      DEPLOY_SSH_USER: ${{ secrets.DEPLOY_SSH_USER }}
    run: bash scripts/ssh-tunnel-up.sh

Leave the "Setup kubeconfig" step and everything after it unchanged in both
jobs. The apt install of wireguard-tools and the WG_LOCAL_IP env disappear with
the removed steps (do not leave a dangling apt step).

Also update the `validate` job step "Validate manifests and scripts": the line
`test -f scripts/wg-tunnel-up.sh` must STAY (wg script is retained), and ADD a
new line `test -f scripts/ssh-tunnel-up.sh` right after it.

B) .github/workflows/deploy-observability.yml — in its `deploy` job, perform the
SAME two-steps-to-one swap (replace "Install WireGuard tools" + "Bring up
WireGuard tunnel" with the single "Open SSH tunnel" step shown above, same env
mapping, `run: bash scripts/ssh-tunnel-up.sh`). All steps after it (the two
"Setup kubeconfig (...)" context builds, secret split/apply, manifest applies,
rollout verifies) stay byte-for-byte unchanged. Remove the wireguard-tools apt
step and WG_LOCAL_IP env with the removed WG step.

C) scripts/validate-staging.py — in `validate_scripts()`, add
`"scripts/ssh-tunnel-up.sh"` to the list of scripts run through `bash -n` (the
list currently ending with `scripts/validate-phase-12.sh`). This gives the new
script CI syntax coverage. Do NOT remove anything. (Note: this validator does
NOT and never did reference wg-tunnel-up.sh, so no WG removal is needed here.)

Confirm both YAML files remain syntactically valid and the python validator
passes.
  </action>
  <verify>
    <automated>cd . && python3 -c "import yaml,sys; [yaml.safe_load(open(f)) for f in ['.github/workflows/deploy-staging.yml','.github/workflows/deploy-observability.yml']]; print('YAML_OK')" && test "$(grep -c 'Open SSH tunnel' .github/workflows/deploy-staging.yml)" -eq 2 && grep -q 'Open SSH tunnel' .github/workflows/deploy-observability.yml && ! grep -q 'wg-tunnel-up.sh' .github/workflows/deploy-staging.yml && grep -q 'test -f scripts/ssh-tunnel-up.sh' .github/workflows/deploy-staging.yml && grep -q 'test -f scripts/wg-tunnel-up.sh' .github/workflows/deploy-staging.yml && ! grep -q 'wireguard-tools' .github/workflows/deploy-staging.yml && ! grep -q 'wireguard-tools' .github/workflows/deploy-observability.yml && grep -q 'ssh-tunnel-up.sh' scripts/validate-staging.py && python3 scripts/validate-staging.py && echo WORKFLOWS_OK</automated>
  </verify>
  <done>
Both workflows use a single "Open SSH tunnel" step (twice in deploy-staging.yml:
dry-run + deploy; once in deploy-observability.yml's deploy job) with the
DEPLOY_SSH_* env mapping and `bash scripts/ssh-tunnel-up.sh`; no WG steps,
WG_LOCAL_IP env, or wireguard-tools apt installs remain in either workflow; the
`validate` job asserts both `scripts/ssh-tunnel-up.sh` AND `scripts/wg-tunnel-up.sh`
exist; validate-staging.py bash-checks ssh-tunnel-up.sh and still passes; both
YAML files parse. The verify command prints YAML_OK ... WORKFLOWS_OK.
  </done>
</task>

</tasks>

<verification>
- `bash -n` passes for scripts/ssh-tunnel-up.sh and scripts/kubeconfig-setup.sh.
- `python3 scripts/validate-staging.py` exits 0 (it now bash-checks the new script).
- Both workflow YAMLs parse via `yaml.safe_load`.
- `scripts/wg-tunnel-up.sh` and the WG_* secrets remain (no deletions).
- No secret values appear in any committed file.
</verification>

<success_criteria>
- CD transport is SSH local-forward (16443 -> 127.0.0.1:6443), not WireGuard.
- kubeconfig targets 127.0.0.1:16443 with --tls-server-name=10.8.0.1 by default.
- Multi-context obs deploy behavior is unchanged.
- Validation gate `python3 scripts/validate-staging.py` passes; YAML valid.
- WireGuard script + secrets retained for future restoration.
</success_criteria>

<output>
Create `.planning/quick/260614-tvy-migrate-cd-from-wireguard-to-ssh-tunnel-/260614-tvy-SUMMARY.md` when done.
</output>