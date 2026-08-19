#!/usr/bin/env python3
# scripts/validate-obs-manifests.py
# Static gate for Phase 13 observability manifests (DEP-04).
# Checks every *.yaml under k8s/observability/ (recursively) for:
#   1. No secret values — Secret documents must have empty/absent stringData/data
#   2. Namespace — every namespaced resource declares namespace: monitoring
#   3. PriorityClass — every pod-bearing spec has priorityClassName: obs-background
#   4. Prometheus target ingress — the default-denied exporters admit only
#      Prometheus on their metrics ports
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
MONITORING_NETWORK_POLICY = OBS_DIR / "95-netpol-monitoring.yaml"

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


def _check_prometheus_target_ingress_policy() -> list[str]:
    """Require the least-privilege ingress rule for default-denied scrape targets."""
    errors = []
    if not MONITORING_NETWORK_POLICY.is_file():
        return [
            "k8s/observability/95-netpol-monitoring.yaml: missing Prometheus target "
            "ingress NetworkPolicy"
        ]

    policy = next(
        (
            doc
            for doc in _split_documents(MONITORING_NETWORK_POLICY.read_text())
            if _top_value(doc, "kind") == "NetworkPolicy"
            and "  name: allow-prometheus-target-ingress" in doc
        ),
        "",
    )
    if not policy:
        return [
            "k8s/observability/95-netpol-monitoring.yaml: missing "
            "allow-prometheus-target-ingress NetworkPolicy"
        ]

    target_selector = """  podSelector:
    matchExpressions:
      - key: app.kubernetes.io/name
        operator: In
        values:
          - alloy
          - kube-state-metrics
          - prometheus-postgres-exporter"""
    target_values = re.findall(r"(?m)^          - (.+)$", policy)
    if target_selector not in policy or target_values != [
        "alloy",
        "kube-state-metrics",
        "prometheus-postgres-exporter",
    ]:
        errors.append(
            "k8s/observability/95-netpol-monitoring.yaml: "
            "allow-prometheus-target-ingress must select exactly alloy, "
            "kube-state-metrics, and prometheus-postgres-exporter"
        )

    expected_ingress = """  ingress:
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: prometheus
              app.kubernetes.io/component: server
      ports:"""
    if expected_ingress not in policy:
        errors.append(
            "k8s/observability/95-netpol-monitoring.yaml: "
            "allow-prometheus-target-ingress must admit only the Prometheus server"
        )

    if "  policyTypes:\n    - Ingress\n  ingress:" not in policy:
        errors.append(
            "k8s/observability/95-netpol-monitoring.yaml: "
            "allow-prometheus-target-ingress must be ingress-only"
        )

    ingress_body = policy.split("  ingress:\n", 1)[-1]
    has_extra_source = any(
        marker in policy
        for marker in ("\n        - namespaceSelector:", "\n        - ipBlock:")
    )
    if (
        f"\n{ingress_body}".count("\n    - ") != 1
        or policy.count("\n        - podSelector:") != 1
        or has_extra_source
    ):
        errors.append(
            "k8s/observability/95-netpol-monitoring.yaml: "
            "allow-prometheus-target-ingress must not admit additional sources"
        )

    allowed_ports = (12345, 8080, 9187)
    if policy.count("\n        - port:") != len(allowed_ports) or "endPort:" in policy:
        errors.append(
            "k8s/observability/95-netpol-monitoring.yaml: "
            "allow-prometheus-target-ingress must not allow additional ports"
        )

    for port in allowed_ports:
        if f"        - port: {port}\n          protocol: TCP" not in policy:
            errors.append(
                "k8s/observability/95-netpol-monitoring.yaml: "
                f"allow-prometheus-target-ingress must allow Prometheus TCP {port}"
            )

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
    all_errors.extend(_check_prometheus_target_ingress_policy())

    if all_errors:
        for err in all_errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1

    print(f"ok: validated {len(yaml_files)} manifest file(s) under {OBS_DIR.relative_to(ROOT)}")
    print("=== obs manifest validation PASSED ===")
    return 0


if __name__ == "__main__":
    sys.exit(validate())
