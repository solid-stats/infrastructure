---
phase: quick-260614-hvq
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - k8s/observability/40-postgres-exporter.yaml
  - k8s/observability/50-grafana.yaml
  - k8s/staging/01-obs-rbac.yaml
  - scripts/validate-obs-manifests.py
autonomous: true
requirements: [OBS-CD-FIX]
must_haves:
  truths:
    - "Deploy observability CD apply step no longer 403s on roles/rolebindings"
    - "No namespaced Role or RoleBinding remains under k8s/observability/"
    - "The two namespaced Role+RoleBinding pairs live in the operator-bootstrap file k8s/staging/01-obs-rbac.yaml"
    - "Validator fails any future re-render that re-introduces namespaced RBAC into k8s/observability/"
  artifacts:
    - path: "k8s/staging/01-obs-rbac.yaml"
      provides: "Operator-applied postgres-exporter + grafana namespaced Role/RoleBinding"
      contains: "kind: Role"
    - path: "scripts/validate-obs-manifests.py"
      provides: "Namespaced + cluster RBAC forbidden in obs dir"
      contains: "_FORBIDDEN_OBS_KINDS"
  key_links:
    - from: "scripts/validate-obs-manifests.py"
      to: "k8s/observability/"
      via: "_check_no_clusterrole scans every doc; _FORBIDDEN_OBS_KINDS now includes Role/RoleBinding"
      pattern: "_FORBIDDEN_OBS_KINDS"
---

<objective>
Fix the red "Deploy observability stack" CD. The "Apply obs manifests (monitoring)" step
does a server-side apply over the whole `k8s/observability/` glob, which PATCHes two empty,
helm-rendered namespaced `Role`+`RoleBinding` pairs (`postgres-exporter`, `grafana`).
`obs-ci-deployer` is namespace-scoped and deliberately holds NO verbs on
`rbac.authorization.k8s.io` roles/rolebindings, so each PATCH returns 403 and the CD goes red.

Mirror the established extraction pattern (cluster RBAC was already moved OUT of obs manifests
INTO `k8s/staging/01-obs-rbac.yaml`): move the namespaced RBAC into the operator-bootstrap file
(excluded from the CI apply glob) and extend the validator so a future helm re-render that
re-introduces namespaced RBAC fails in CI before it can break the deploy.

Purpose: green obs CD without widening the least-privilege deployer Role (CI self-escalation is
the rejected alternative).
Output: 2 obs manifests with the RBAC docs removed, the two pairs added to 01-obs-rbac.yaml, and
validator coverage extended to namespaced RBAC.
</objective>

<execution_context>
@.claude/gsd-core/workflows/execute-plan.md
@.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@AGENTS.md
@k8s/staging/01-obs-rbac.yaml
@k8s/observability/40-postgres-exporter.yaml
@k8s/observability/50-grafana.yaml
@scripts/validate-obs-manifests.py
@.github/workflows/deploy-observability.yml

Established pattern (already in 01-obs-rbac.yaml): cluster RBAC for prometheus,
kube-state-metrics, and grafana was extracted out of the CI-applied obs manifests into
this operator-bootstrap file, each with a header comment of the form:
"... runtime RBAC — operator-applied, NOT from CI. Extracted from <file> (Phase N helm render)
because obs-ci-deployer is namespace-scoped and cannot create ClusterRole. Applied once by
operator alongside the rest of this file." Match that comment style for the namespaced pairs,
and preserve the original `# Source: <chart>/templates/...` helm-source comments + labels.

The two RBAC pairs to move:
- postgres-exporter: Role (NO `rules:` key at all) + RoleBinding — from 40-postgres-exporter.yaml
  (helm chart prometheus-postgres-exporter-8.0.0), namespace monitoring.
- grafana: Role (`rules: []`) + RoleBinding — from 50-grafana.yaml
  (helm chart grafana-10.5.15), namespace monitoring.
Both Roles grant nothing; the RoleBindings bind the workload SA to an empty Role — moving both
pairs is functionally inert (the workloads need no namespaced permissions).

The CI apply glob (deploy-observability.yml "Apply obs manifests (monitoring)" step) is
`find k8s/observability -maxdepth 1 -name '*.yaml' ... | xargs kubectl apply --server-side`.
`k8s/staging/01-obs-rbac.yaml` is outside `k8s/observability/` and is never in any CI glob
(operator-applied once), so docs added there are safe from CD.
</context>

<tasks>

<task type="auto">
  <name>Task 1: Remove the two empty namespaced Role+RoleBinding pairs from obs manifests</name>
  <files>k8s/observability/40-postgres-exporter.yaml, k8s/observability/50-grafana.yaml</files>
  <action>
In k8s/observability/40-postgres-exporter.yaml, delete the two YAML documents for the
postgres-exporter namespaced RBAC: the `# Source: prometheus-postgres-exporter/templates/role.yaml`
Role document and the following `# Source: prometheus-postgres-exporter/templates/rolebinding.yaml`
RoleBinding document. Remove them cleanly including the `---` separators so the file flows
ServiceAccount → Service (no orphaned `---` and no leading/trailing blank-document). Keep the
ServiceAccount, Service, and Deployment exactly as-is.

In k8s/observability/50-grafana.yaml, delete the two YAML documents for the grafana namespaced
RBAC: the `# Source: grafana/templates/role.yaml` Role document (the one with `rules: []`) and the
following `# Source: grafana/templates/rolebinding.yaml` RoleBinding document. Remove the `---`
separators cleanly so the file flows PersistentVolumeClaim → Service. Keep every other document
(ServiceAccount, ConfigMaps, PVC, Service, Deployment) untouched.

Do NOT alter `serviceAccountName:` in either Deployment, the SAs, or any labels — only the four
RBAC documents (two per file) are removed. These Roles grant nothing and the RoleBindings bind to
empty Roles, so removal from the CD path is functionally inert; the same definitions are re-added
to the operator-bootstrap file in Task 2.
  </action>
  <verify>
    <automated>test "$(grep -rE '^kind: (Role|RoleBinding)$' k8s/observability/ | wc -l)" -eq 0 && grep -q 'kind: Deployment' k8s/observability/40-postgres-exporter.yaml && grep -q 'kind: Deployment' k8s/observability/50-grafana.yaml && echo OK</automated>
  </verify>
  <done>
No `kind: Role` or `kind: RoleBinding` document remains anywhere under k8s/observability/.
Both files still contain their Deployment (and all other non-RBAC docs); no orphaned `---`
separators; serviceAccountName references unchanged.
  </done>
</task>

<task type="auto">
  <name>Task 2: Add the two namespaced Role+RoleBinding pairs to the operator-bootstrap RBAC file</name>
  <files>k8s/staging/01-obs-rbac.yaml</files>
  <action>
Append two operator-applied RBAC blocks to the end of k8s/staging/01-obs-rbac.yaml (after the
existing grafana ClusterRoleBinding, line ~399), each preceded by a `---` separator and a
header comment matching the file's existing extraction-comment style (compare the
"Grafana runtime RBAC — operator-applied, NOT from CI. Extracted from 50-grafana.yaml ... because
obs-ci-deployer is namespace-scoped and cannot create ClusterRole. Applied once by operator..."
banner already in the file). Tailor each banner to say the deployer cannot manage NAMESPACED RBAC
(roles/rolebindings) — not cluster RBAC — since these are namespaced.

Block A — postgres-exporter namespaced RBAC, copied verbatim from the documents removed in Task 1
(preserve the `# Source: prometheus-postgres-exporter/templates/role.yaml` and
`# Source: prometheus-postgres-exporter/templates/rolebinding.yaml` source comments, the
helm.sh/chart and app.kubernetes.io labels, name `postgres-exporter`, namespace `monitoring`, the
Role with no rules, and the RoleBinding's roleRef + subjects). Precede with a banner like:
"postgres-exporter namespaced RBAC — operator-applied, NOT from CI. Extracted from
40-postgres-exporter.yaml helm render because obs-ci-deployer is namespace-scoped and cannot
create/patch namespaced roles/rolebindings. These bind the workload SA to an empty Role (grant
nothing); kept for helm re-render fidelity. Applied once by operator alongside the rest of this file."

Block B — grafana namespaced RBAC, copied verbatim from the documents removed in Task 1 (preserve
`# Source: grafana/templates/role.yaml` and `# Source: grafana/templates/rolebinding.yaml`, the
grafana-10.5.15 labels, name `grafana`, namespace `monitoring`, the Role with `rules: []`, and the
RoleBinding roleRef + subjects). Precede with an analogous banner naming 50-grafana.yaml as the source.

Keep all four documents in namespace `monitoring`. Do NOT touch the obs-ci-deployer Role anywhere
in this file — the deployer Role must not gain roles/rolebindings verbs (rejected CI-self-escalation
alternative).
  </action>
  <verify>
    <automated>test "$(grep -cE '^kind: (Role|RoleBinding)$' k8s/staging/01-obs-rbac.yaml)" -ge 4 && grep -q 'name: postgres-exporter' k8s/staging/01-obs-rbac.yaml && grep -Eq 'roles|rolebindings' k8s/staging/01-obs-rbac.yaml && echo OK</automated>
  </verify>
  <done>
01-obs-rbac.yaml now contains the postgres-exporter Role+RoleBinding and grafana Role+RoleBinding
(namespace monitoring), each with a source comment + operator-applied banner. The obs-ci-deployer
Role is unchanged (no roles/rolebindings verbs added). `python3 -c "import yaml,sys; list(yaml.safe_load_all(open('k8s/staging/01-obs-rbac.yaml')))"` parses without error if PyYAML is available
(optional — skip if not installed; the file is human-reviewed YAML).
  </done>
</task>

<task type="auto">
  <name>Task 3: Extend the validator to forbid namespaced RBAC in the obs directory</name>
  <files>scripts/validate-obs-manifests.py</files>
  <action>
In scripts/validate-obs-manifests.py, add `"Role"` and `"RoleBinding"` to the `_FORBIDDEN_OBS_KINDS`
set (currently `{"ClusterRole", "ClusterRoleBinding"}`). Update the comment above the set so it
reads as covering both cluster-scoped AND namespaced RBAC kinds, and explains namespaced RBAC must
live in k8s/staging/01-obs-rbac.yaml operator-bootstrap because obs-ci-deployer holds no
roles/rolebindings verbs (it 403s on apply).

Update the `_check_no_clusterrole` docstring and its emitted error message so the wording covers
namespaced RBAC too — currently it says "cluster RBAC" / "cluster-scoped resources". Generalize to
e.g. "RBAC kind (cluster-scoped or namespaced)" and the message to "must not appear in the
CI-applied k8s/observability/ directory — move it to a k8s/staging/ operator-bootstrap file
(obs-ci-deployer cannot create/patch RBAC)". Keep the function name as-is or rename consistently;
do not break the call in `validate()`.

Do not change any other check (secret values, namespace, priority class, render errors). The set
membership drives all behavior; the docstring/comment/message are wording only.
  </action>
  <verify>
    <automated>cd . && python3 -c "import re; s=open('scripts/validate-obs-manifests.py').read(); assert re.search(r'_FORBIDDEN_OBS_KINDS\s*=\s*\{[^}]*\"Role\"[^}]*\"RoleBinding\"', s) or re.search(r'_FORBIDDEN_OBS_KINDS\s*=\s*\{[^}]*\"RoleBinding\"[^}]*\"Role\"', s), 'Role/RoleBinding not in set'; print('SET OK')" && python3 scripts/validate-obs-manifests.py</automated>
  </verify>
  <done>
`_FORBIDDEN_OBS_KINDS` contains ClusterRole, ClusterRoleBinding, Role, RoleBinding. The docstring
and error message reference namespaced RBAC. `python3 scripts/validate-obs-manifests.py` exits 0
(PASSED) against the now-RBAC-free k8s/observability/ tree, and would fail if a Role/RoleBinding
reappeared there.
  </done>
</task>

</tasks>

<verification>
Run from repo root:

1. `python3 scripts/validate-obs-manifests.py` → exits 0, prints "obs manifest validation PASSED".
2. `grep -rE '^kind: (Role|RoleBinding)$' k8s/observability/` → no matches (RBAC fully removed from obs dir).
3. `grep -cE '^kind: (Role|RoleBinding)$' k8s/staging/01-obs-rbac.yaml` → ≥ 4 (both pairs present).
4. `grep -n 'obs-ci-deployer' k8s/staging/01-obs-rbac.yaml` → the obs-ci-deployer Role rules block
   is byte-identical to before (no roles/rolebindings apiGroup added).
5. Bonus (only if kubectl present locally; cluster is remote over WG — do NOT require live access):
   `kubectl apply --dry-run=client -f k8s/observability/40-postgres-exporter.yaml`
   and `... 50-grafana.yaml` and `... k8s/staging/01-obs-rbac.yaml` all parse client-side.
</verification>

<success_criteria>
- Obs CD "Apply obs manifests (monitoring)" step will no longer PATCH roles/rolebindings → no 403.
- No namespaced or cluster RBAC remains under k8s/observability/; validator now blocks both.
- Both namespaced Role+RoleBinding pairs live in the operator-applied k8s/staging/01-obs-rbac.yaml
  with source comments + operator banners; functionally inert (empty Roles).
- obs-ci-deployer Role NOT widened (no CI self-escalation).
- All edited artifacts in English.
</success_criteria>

<output>
Create `.planning/quick/260614-hvq-fix-obs-cd-move-empty-namespaced-role-ro/260614-hvq-SUMMARY.md` when done.
</output>
