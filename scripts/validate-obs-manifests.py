#!/usr/bin/env python3
# scripts/validate-obs-manifests.py
# Static gate for Phase 13 observability manifests (DEP-04).
# Checks every *.yaml under k8s/observability/ (recursively) for:
#   1. No secret values — Secret documents must have empty/absent stringData/data
#   2. Namespace — every namespaced resource declares namespace: monitoring
#   3. PriorityClass — every pod-bearing spec has priorityClassName: obs-background
#
# Runs in CI validate job and per-commit (no cluster access needed).
# Exits 0 on success; exits 1 with a clear message on any violation.
#
# T-13-03 discipline: forbidden token strings are stored as variables, not echoed
# in head comments, to keep the gate self-consistent.

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OBS_DIR = ROOT / "k8s" / "observability"
PROMETHEUS_VALUES = OBS_DIR / "values" / "prometheus-values.yaml"
PROMETHEUS_MANIFEST = OBS_DIR / "10-prometheus.yaml"
MEMORY_BACKUP_MANIFEST = ROOT / "k8s" / "memory" / "40-backup.yaml"

# Forbidden-token patterns (T-13-03: stored as variables, not comments).
# These fire when a Secret document has a non-empty stringData/data value.
_FORBIDDEN_CREDENTIAL_KEYS = re.compile(
    r"^\s+(admin-password|dsn|password|token|secret|key)\s*:\s*\S",
    re.IGNORECASE,
)
# Long base64 blob heuristic: a key whose value is ≥20 chars of base64 chars.
_FORBIDDEN_BASE64_BLOB = re.compile(
    r"^\s+\S+:\s*([A-Za-z0-9+/=]{20,})\s*$"
)

# Pod-bearing resource kinds.
_POD_BEARING_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"}

# Cluster-scoped resource kinds that legitimately have no namespace.
_CLUSTER_SCOPED_KINDS = {
    "Namespace", "ClusterRole", "ClusterRoleBinding",
    "PriorityClass", "StorageClass", "PersistentVolume",
    "CustomResourceDefinition",
}

# RBAC kinds forbidden in the CI-applied obs directory — both cluster-scoped
# (ClusterRole/ClusterRoleBinding, T-15-07) AND namespaced (Role/RoleBinding).
# All RBAC must live in k8s/staging/ operator-bootstrap files only.
# obs-ci-deployer holds no roles/rolebindings verbs, so it 403s when CI tries to
# create/patch namespaced RBAC — just as it cannot create cluster-scoped RBAC.
_FORBIDDEN_OBS_KINDS = {"ClusterRole", "ClusterRoleBinding", "Role", "RoleBinding"}


def _split_documents(text: str) -> list[str]:
    """Split multi-document YAML on '---' separators."""
    docs = []
    current: list[str] = []
    for line in text.splitlines():
        if line.strip() == "---":
            joined = "\n".join(current).strip()
            if joined:
                docs.append(joined)
            current = []
        else:
            current.append(line)
    joined = "\n".join(current).strip()
    if joined:
        docs.append(joined)
    return docs


# Signatures of a CLI/render error that leaked into a manifest file. `helm template`
# writes errors to stderr, but a careless `> file 2>&1` (or a transient chart-download
# timeout) can splice an error message into the rendered YAML, corrupting it without a
# parse-time failure that the stdlib (no PyYAML) splitter would notice. Catch them by signature.
_RENDER_ERROR_PATTERNS = [
    re.compile(r"^\s*Error:\s", re.MULTILINE),
    re.compile(r"context deadline exceeded"),
    re.compile(r"Client\.Timeout"),
    re.compile(r"^\s*panic:\s", re.MULTILINE),
    re.compile(r"failed to (download|pull|fetch|render)"),
]


def _check_render_errors(text: str, path: Path) -> list[str]:
    """Fail if a manifest file contains CLI/render error text spliced into the YAML."""
    errors = []
    for pat in _RENDER_ERROR_PATTERNS:
        m = pat.search(text)
        if m:
            snippet = text[m.start():m.start() + 80].replace("\n", " ")
            errors.append(f"{path}: render-error signature in manifest ({snippet!r}) — re-render needed")
            break
    return errors


def _top_value(doc: str, key: str) -> str | None:
    prefix = f"{key}:"
    for line in doc.splitlines():
        if line.startswith(prefix) and (len(line) == len(prefix) or line[len(prefix)] in (" ", "\t")):
            return line.split(":", 1)[1].strip()
    return None


def _metadata_name(doc: str) -> str | None:
    """Return the top-level metadata.name from a YAML document split as text."""
    in_metadata = False
    for line in doc.splitlines():
        if line == "metadata:":
            in_metadata = True
            continue
        if in_metadata:
            if line and not line.startswith(" "):
                return None
            if line.startswith("  name:"):
                return line.split(":", 1)[1].strip()
    return None


def _memory_backup_cronjob_name() -> str:
    """Extract the sole namespaced memory backup CronJob from its source manifest."""
    cronjobs = [
        _metadata_name(doc)
        for doc in _split_documents(MEMORY_BACKUP_MANIFEST.read_text())
        if _top_value(doc, "kind") == "CronJob"
        and "namespace: solidstats-memory" in doc
    ]
    if len(cronjobs) != 1 or cronjobs[0] is None:
        raise ValueError(
            "k8s/memory/40-backup.yaml must define exactly one "
            "solidstats-memory CronJob"
        )
    return cronjobs[0]


def _snapshot_alert_expression(text: str) -> str | None:
    match = re.search(
        r"- alert: SolidStatsMemorySnapshotMissingOrStale\s*\n\s+expr:\s*(.*?)\n\s+for:",
        text,
        re.DOTALL,
    )
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else None


def _literal_data_blocks(document: str, header: str) -> dict[str, str]:
    """Return literal scalar blocks directly below a two-space YAML mapping."""
    lines = document.splitlines()
    try:
        start = next(index for index, line in enumerate(lines) if line == header)
    except StopIteration:
        return {}

    blocks: dict[str, str] = {}
    current_key: str | None = None
    current_lines: list[str] = []
    for line in lines[start + 1:]:
        if line and not line.startswith("  "):
            break
        key_match = re.match(r"^  ([^:]+): \|$", line)
        if key_match:
            if current_key is not None:
                blocks[current_key] = "\n".join(current_lines) + "\n"
            current_key = key_match.group(1)
            current_lines = []
        elif current_key is not None:
            if line.startswith("    "):
                current_lines.append(line[4:])
            elif not line:
                current_lines.append("")
    if current_key is not None:
        blocks[current_key] = "\n".join(current_lines) + "\n"
    return blocks


def _prometheus_server_data_blocks(manifest_text: str) -> dict[str, str]:
    """Extract only ConfigMap/prometheus-server data literal blocks."""
    documents = [
        document
        for document in _split_documents(manifest_text)
        if _top_value(document, "kind") == "ConfigMap"
        and _metadata_name(document) == "prometheus-server"
    ]
    if len(documents) != 1:
        return {}
    return _literal_data_blocks(documents[0], "data:")


def _values_server_file_blocks(values_text: str) -> dict[str, str]:
    """Extract YAML mappings below serverFiles without a YAML dependency."""
    lines = values_text.splitlines()
    try:
        start = next(index for index, line in enumerate(lines) if line == "serverFiles:")
    except StopIteration:
        return {}

    blocks: dict[str, str] = {}
    current_key: str | None = None
    current_lines: list[str] = []
    for line in lines[start + 1:]:
        if line and not line.startswith("  "):
            break
        key_match = re.match(r"^  ([^ :][^:]*):$", line)
        if key_match:
            if current_key is not None:
                blocks[current_key] = "\n".join(current_lines) + "\n"
            current_key = key_match.group(1)
            current_lines = []
        elif current_key is not None:
            current_lines.append(line[2:] if line.startswith("  ") else line)
    if current_key is not None:
        blocks[current_key] = "\n".join(current_lines) + "\n"
    return blocks


def _memory_rule_names(block: str, declaration: str) -> list[str]:
    """Extract the declared Prometheus alert or recording names from one file."""
    return re.findall(rf"^\s*(?:-\s+)?{declaration}: ([^\s]+)\s*$", block, re.MULTILINE)


def _rule_expression(block: str, declaration: str, name: str) -> str | None:
    """Return a rule expression regardless of chart serialization key order."""
    for item in re.split(r"(?m)^\s*-\s+", block):
        if not re.search(
            rf"(?:^|\n)\s*{declaration}: {re.escape(name)}\s*$",
            item,
            re.MULTILINE,
        ):
            continue
        expression = re.search(
            r"(?:^|\n)\s*expr:\s*(.*?)(?=\n\s*(?:for|record):|\Z)",
            item,
            re.DOTALL,
        )
        return re.sub(r"\s+", " ", expression.group(1)).strip() if expression else None
    return None


_MEMORY_ALERT_NAMES = {
    "SolidStatsMemoryMCPNotReady",
    "SolidStatsMemoryMCPLatencyHigh",
    "SolidStatsMemoryMCPProbeErrors",
    "SolidStatsMemoryQdrantUnhealthy",
    "SolidStatsMemoryQdrantCollectionUnavailable",
    "SolidStatsMemorySnapshotMissingOrStale",
    "SolidStatsMemoryPVCCapacityHigh",
    "SolidStatsMemoryPVCMetricsMissing",
}
_MEMORY_RECORDING_NAMES = {
    "solidstats_memory:mcp_ready:max",
    "solidstats_memory:mcp_probe_duration_seconds:max",
    "solidstats_memory:mcp_probe_errors:rate5m",
    "solidstats_memory:qdrant_ready:max",
    "solidstats_memory:qdrant_collection_healthy:max",
    "solidstats_memory:qdrant_snapshot_age_seconds:max",
    "solidstats_memory:pvc_capacity_ratio:max",
}


def _check_memory_rule_files(
    values_text: str, manifest_text: str, backup_cronjob: str
) -> list[str]:
    """Require memory rule definitions in their chart-owned ConfigMap files."""
    errors: list[str] = []
    source_blocks = _values_server_file_blocks(values_text)
    rendered_blocks = _prometheus_server_data_blocks(manifest_text)
    expected = (
        ("alerting_rules.yml", "alert", _MEMORY_ALERT_NAMES),
        ("recording_rules.yml", "record", _MEMORY_RECORDING_NAMES),
    )
    for key, declaration, names in expected:
        source_block = source_blocks.get(key, "")
        rendered_block = rendered_blocks.get(key, "")
        source_names = _memory_rule_names(source_block, declaration)
        rendered_names = _memory_rule_names(rendered_block, declaration)
        if set(source_names) != names or len(source_names) != len(names):
            errors.append(f"values {key} must define each memory {declaration} exactly once")
        if set(rendered_names) != names or len(rendered_names) != len(names):
            errors.append(f"rendered {key} must define each memory {declaration} exactly once")

        for name in names:
            source_expression = _rule_expression(source_block, declaration, name)
            rendered_expression = _rule_expression(rendered_block, declaration, name)
            if not source_expression or not rendered_expression or source_expression != rendered_expression:
                errors.append(f"memory {declaration} source/render expression differs: {name}")

    for key, block in rendered_blocks.items():
        for declaration, names in (("alert", _MEMORY_ALERT_NAMES), ("record", _MEMORY_RECORDING_NAMES)):
            found = set(_memory_rule_names(block, declaration)) & names
            is_authoritative = (
                key == "alerting_rules.yml" and declaration == "alert"
            ) or (
                key == "recording_rules.yml" and declaration == "record"
            )
            if found and not is_authoritative:
                errors.append(f"memory {declaration} definitions appear under wrong ConfigMap key: {key}")

    alert_expression = _snapshot_alert_expression(rendered_blocks.get("alerting_rules.yml", ""))
    expected_expression = (
        'kube_cronjob_spec_suspend{namespace="solidstats-memory",'
        f'cronjob="{backup_cronjob}"}} == 0 and '
        "solidstats_memory:qdrant_snapshot_age_seconds:max > 93600"
    )
    if alert_expression != expected_expression:
        errors.append("rendered snapshot alert must select the sole memory backup CronJob")
    return errors


def _check_no_secret_values(doc: str, path: Path) -> list[str]:
    """Fail if a Secret document carries a populated stringData/data value."""
    errors = []
    kind = _top_value(doc, "kind")
    if kind != "Secret":
        return errors

    in_string_data = False
    in_data = False
    for line in doc.splitlines():
        stripped = line.rstrip()
        if stripped in ("stringData:", "data:"):
            in_string_data = (stripped == "stringData:")
            in_data = (stripped == "data:")
            continue

        if in_string_data or in_data:
            # End of block: unindented non-blank line
            if stripped and not line.startswith(" "):
                in_string_data = False
                in_data = False
                continue
            # Check for a non-empty key value
            if _FORBIDDEN_CREDENTIAL_KEYS.match(line):
                errors.append(
                    f"{path.relative_to(ROOT)}: Secret has a populated stringData/data value "
                    f"(line: {line.strip()!r}) — secret values must not appear in committed YAML"
                )
                break
            if _FORBIDDEN_BASE64_BLOB.match(line):
                snippet = repr(line.strip()[:40])
                errors.append(
                    f"{path.relative_to(ROOT)}: Secret has a long base64 blob in data "
                    f"(line: {snippet}...) — rendered Secrets must not be committed"
                )
                break
    return errors


def _check_namespace(doc: str, path: Path) -> list[str]:
    """Fail if a namespaced resource declares a namespace outside the allowed obs set.

    Allowed namespaces:
    - monitoring  — Phase 13+ metrics/logs stack
    - error-tracking — Phase 16+ GlitchTip error tracking (Pitfall 5 guard)
    """
    errors = []
    kind = _top_value(doc, "kind")
    if kind in _CLUSTER_SCOPED_KINDS or kind is None:
        return errors

    _ALLOWED_OBS_NAMESPACES = {"monitoring", "error-tracking"}

    # Find namespace in metadata block
    in_metadata = False
    namespace_value: str | None = None
    for line in doc.splitlines():
        stripped = line.rstrip()
        if stripped == "metadata:":
            in_metadata = True
            continue
        if in_metadata:
            if stripped and not line.startswith(" "):
                break
            if line.startswith("  namespace:") and not line.startswith("   namespace:"):
                namespace_value = line.split(":", 1)[1].strip()
                break

    if namespace_value is not None and namespace_value not in _ALLOWED_OBS_NAMESPACES:
        errors.append(
            f"{path.relative_to(ROOT)}: {kind} resource declares namespace: {namespace_value!r} "
            f"(expected one of: {sorted(_ALLOWED_OBS_NAMESPACES)})"
        )
    return errors


def _check_no_clusterrole(doc: str, path: Path) -> list[str]:
    """Fail if a document in k8s/observability/ has an RBAC kind (cluster-scoped or namespaced).

    ClusterRole, ClusterRoleBinding, Role, and RoleBinding must all live in
    operator-bootstrap files under k8s/staging/ only. obs-ci-deployer is
    namespace-scoped and holds no roles/rolebindings verbs, so it receives a 403
    trying to create/patch any RBAC — cluster-scoped or namespaced
    (T-15-07, Pitfall 4). Move any such document to k8s/staging/01-obs-rbac.yaml.
    """
    errors = []
    kind = _top_value(doc, "kind")
    if kind in _FORBIDDEN_OBS_KINDS:
        errors.append(
            f"{path.relative_to(ROOT)}: {kind} must not appear in the CI-applied "
            f"k8s/observability/ directory — move it to a k8s/staging/ operator-bootstrap "
            f"file (obs-ci-deployer cannot create/patch RBAC)"
        )
    return errors


def _check_priority_class(doc: str, path: Path) -> list[str]:
    """Fail if a pod-bearing spec is missing priorityClassName: obs-background."""
    errors = []
    kind = _top_value(doc, "kind")
    if kind not in _POD_BEARING_KINDS:
        return errors

    # For CronJob, the pod spec is nested under jobTemplate.spec.template.spec.
    # We do a tolerant scan: look for priorityClassName anywhere in the document.
    has_priority = False
    correct_value = False
    for line in doc.splitlines():
        if "priorityClassName:" in line:
            has_priority = True
            if "obs-background" in line:
                correct_value = True
            break

    if not has_priority:
        errors.append(
            f"{path.relative_to(ROOT)}: {kind} pod spec is missing priorityClassName "
            f"(must be 'obs-background')"
        )
    elif not correct_value:
        errors.append(
            f"{path.relative_to(ROOT)}: {kind} pod spec priorityClassName is not 'obs-background'"
        )
    return errors


def _check_cadvisor_scrape_config() -> list[str]:
    """Require the committed Prometheus inputs and render to retain cAdvisor scraping."""
    errors = []
    values_text = PROMETHEUS_VALUES.read_text()
    manifest_text = PROMETHEUS_MANIFEST.read_text()

    if not re.search(
        r"kubernetes-nodes-cadvisor:\s*\n\s+enabled:\s*true\b", values_text
    ):
        errors.append(
            "k8s/observability/values/prometheus-values.yaml: "
            "kubernetes-nodes-cadvisor must be enabled"
        )

    job_start = manifest_text.find("    - job_name: kubernetes-nodes-cadvisor\n")
    cadvisor_job = ""
    if job_start != -1:
        job_end = manifest_text.find("\n    - job_name:", job_start + 1)
        cadvisor_job = manifest_text[job_start:job_end if job_end != -1 else None]
    required_markers = (
        "bearer_token_file: /var/run/secrets/kubernetes.io/serviceaccount/token",
        "kubernetes_sd_configs:\n      - role: node",
        "replacement: /api/v1/nodes/$1/proxy/metrics/cadvisor",
        "replacement: kubernetes.default.svc:443",
        "ca_file: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt",
    )
    if job_start == -1 or any(marker not in cadvisor_job for marker in required_markers):
        errors.append(
            "k8s/observability/10-prometheus.yaml: rendered Prometheus config must "
            "scrape cAdvisor through the authenticated Kubernetes API proxy"
        )

    return errors


def _check_memory_monitoring_contract() -> list[str]:
    """Require the values, generated ConfigMap, and reciprocal policy to agree."""
    errors = []
    values_text = PROMETHEUS_VALUES.read_text()
    manifest_text = PROMETHEUS_MANIFEST.read_text()
    policy_text = (OBS_DIR / "95-netpol-monitoring.yaml").read_text()
    try:
        backup_cronjob = _memory_backup_cronjob_name()
    except ValueError as error:
        errors.append(str(error))
        return errors
    markers = ("solidstats-memory-observer", "kubernetes-nodes-volume-stats")
    for marker in markers:
        if marker not in values_text or marker not in manifest_text:
            errors.append(f"memory Prometheus source/render is missing: {marker}")
    if "solidstats-memory-observer" not in policy_text or "port: 9108" not in policy_text:
        errors.append("monitoring NetworkPolicy lacks observer-only TCP 9108 egress")

    source_blocks = _values_server_file_blocks(values_text)
    rendered_blocks = _prometheus_server_data_blocks(manifest_text)
    values_expression = _snapshot_alert_expression(source_blocks.get("alerting_rules.yml", ""))
    rendered_expression = _snapshot_alert_expression(rendered_blocks.get("alerting_rules.yml", ""))
    expected_expression = (
        'kube_cronjob_spec_suspend{namespace="solidstats-memory",'
        f'cronjob="{backup_cronjob}"}} == 0 and '
        "solidstats_memory:qdrant_snapshot_age_seconds:max > 93600"
    )
    if values_expression != expected_expression:
        errors.append(
            "k8s/observability/values/prometheus-values.yaml: snapshot alert "
            "must select the sole memory backup CronJob"
        )
    if rendered_expression != expected_expression:
        errors.append(
            "k8s/observability/10-prometheus.yaml: snapshot alert must select "
            "the sole memory backup CronJob"
        )
    if values_expression != rendered_expression:
        errors.append("memory snapshot alert source/render expressions differ")
    prometheus_config = rendered_blocks.get("prometheus.yml", "")
    for rule_path in (
        "/etc/config/alerting_rules.yml",
        "/etc/config/recording_rules.yml",
    ):
        if rule_path not in prometheus_config:
            errors.append(f"rendered prometheus.yml must reference {rule_path}")
    errors.extend(_check_memory_rule_files(values_text, manifest_text, backup_cronjob))
    return errors


def validate() -> int:
    if not OBS_DIR.is_dir():
        print(f"note: {OBS_DIR.relative_to(ROOT)} does not exist yet — no manifests to validate")
        print("=== obs manifest validation PASSED ===")
        return 0

    yaml_files = sorted(OBS_DIR.rglob("*.yaml"))
    if not yaml_files:
        print(f"note: no *.yaml files found under {OBS_DIR.relative_to(ROOT)} — nothing to validate")
        print("=== obs manifest validation PASSED ===")
        return 0

    all_errors: list[str] = []

    for yaml_path in yaml_files:
        text = yaml_path.read_text()
        all_errors.extend(_check_render_errors(text, yaml_path))
        docs = _split_documents(text)
        for doc in docs:
            all_errors.extend(_check_no_clusterrole(doc, yaml_path))
            all_errors.extend(_check_no_secret_values(doc, yaml_path))
            all_errors.extend(_check_namespace(doc, yaml_path))
            all_errors.extend(_check_priority_class(doc, yaml_path))

    all_errors.extend(_check_cadvisor_scrape_config())
    all_errors.extend(_check_memory_monitoring_contract())

    if all_errors:
        for err in all_errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1

    print(f"ok: validated {len(yaml_files)} manifest file(s) under {OBS_DIR.relative_to(ROOT)}")
    print("=== obs manifest validation PASSED ===")
    return 0


if __name__ == "__main__":
    sys.exit(validate())
