#!/usr/bin/env python3
"""Offline, fail-closed validation for the isolated SolidStats-memory boundary."""

import argparse
import ipaddress
import re
import sys
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST_DIR = ROOT / "k8s" / "memory"
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-memory.yml"
NAMESPACE = "solidstats-memory"
EXPECTED = {
    "00-namespace.yaml",
    "01-ci-rbac.yaml",
    "10-qdrant.yaml",
    "20-mempalace.yaml",
    "30-network-policy.yaml",
    "40-backup.yaml",
    "50-monitoring.yaml",
}
PLACEHOLDER_RE = re.compile(r"MEMORY_OPERATOR_[A-Z0-9_]+")
QDRANT_IMAGE = (
    "ghcr.io/qdrant/qdrant:v1.19.0-unprivileged@"
    "sha256:18a245d16eb663d4f6ad054123371243248d8256a8067f352cd6e88d512fee0b"
)


class ValidationError(Exception):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def documents(text: str) -> list[str]:
    parts = [part for part in re.split(r"(?m)^---[ \t]*$", text) if part.strip()]
    return parts


def field(doc: str, expression: str) -> str | None:
    match = re.search(expression, doc, flags=re.MULTILINE)
    return match.group(1).strip() if match else None


def validate_documents(manifest_dir: Path) -> dict[str, str]:
    files = {path.name for path in manifest_dir.glob("*.yaml")}
    require(files == EXPECTED, f"manifest set differs from contract: {sorted(files ^ EXPECTED)}")
    all_docs: dict[str, str] = {}
    for path in sorted(manifest_dir.glob("*.yaml")):
        for index, doc in enumerate(documents(path.read_text()), start=1):
            api_version = field(doc, r"^apiVersion:\s*(.+)$")
            kind = field(doc, r"^kind:\s*(.+)$")
            name = field(doc, r"^metadata:\n(?:  .*\n)*?  name:\s*(.+)$")
            require(api_version is not None, f"{path.name}:{index} lacks apiVersion")
            require(kind is not None, f"{path.name}:{index} lacks kind")
            require(name is not None, f"{path.name}:{index} lacks metadata.name")
            key = f"{kind}/{name}"
            require(key not in all_docs, f"duplicate resource {key}")
            all_docs[key] = doc
            if kind != "Namespace":
                require(f"namespace: {NAMESPACE}" in doc, f"{key} is outside {NAMESPACE}")
            require("namespace: solid-stats-staging" not in doc, f"{key} references staging")
            require("namespace: monitoring" not in doc, f"{key} mutates monitoring")
            require("kind: ClusterRole" not in doc and "kind: ClusterRoleBinding" not in doc, f"{key} is cluster-scoped RBAC")
    return all_docs


def require_workload_safety(docs: dict[str, str]) -> None:
    workloads = [doc for key, doc in docs.items() if key.split("/", 1)[0] in {"Deployment", "StatefulSet", "CronJob"}]
    require(len(workloads) == 4, "expected Qdrant, MemPalace, observer, and backup workloads")
    for doc in workloads:
        name = field(doc, r"^metadata:\n(?:  .*\n)*?  name:\s*(.+)$") or "unnamed"
        require("serviceAccountName:" in doc and "serviceAccountName: default" not in doc, f"{name} lacks dedicated ServiceAccount")
        require("automountServiceAccountToken: false" in doc, f"{name} permits service-account tokens")
        for required in (
            "runAsNonRoot: true",
            "type: RuntimeDefault",
            "allowPrivilegeEscalation: false",
            "readOnlyRootFilesystem: true",
            "drop: [\"ALL\"]",
            "resources:",
            "requests:",
            "limits:",
        ):
            require(required in doc, f"{name} misses workload safeguard: {required}")
    for name in ("StatefulSet/qdrant", "Deployment/mempalace"):
        doc = docs[name]
        require("readinessProbe:" in doc and "livenessProbe:" in doc, f"{name} lacks probes")
    require(QDRANT_IMAGE in docs["StatefulSet/qdrant"], "Qdrant image digest is not pinned to the verified artifact")
    require("type: ClusterIP" in docs["Service/qdrant"], "Qdrant must be a private ClusterIP service")
    require("clusterIP: None" in docs["Service/qdrant"], "Qdrant StatefulSet requires a headless governing service")
    require("type: LoadBalancer" not in docs["Service/qdrant"] and "type: NodePort" not in docs["Service/qdrant"], "Qdrant is publicly exposed")
    require("type: ClusterIP" in docs["Service/mempalace"], "MemPalace must use an internal ClusterIP service")
    require("mountPath: /qdrant/storage" in docs["StatefulSet/qdrant"], "Qdrant storage mount is missing")
    require("claimName: mempalace-data" in docs["Deployment/mempalace"], "MemPalace PVC is missing")
    require("persistentVolumeClaimRetentionPolicy:" in docs["StatefulSet/qdrant"], "Qdrant PVC Retain policy is missing")
    require("name: MEMPALACE_BACKEND\n              value: qdrant" in docs["Deployment/mempalace"], "MemPalace backend is not Qdrant")
    require("name: MEMPALACE_QDRANT_NAMESPACE\n              value: SolidStats" in docs["Deployment/mempalace"], "MemPalace namespace is incorrect")


def require_network_contract(docs: dict[str, str], source_has_placeholders: bool) -> None:
    policies = {key for key in docs if key.startswith("NetworkPolicy/")}
    required = {
        "NetworkPolicy/default-deny-all",
        "NetworkPolicy/allow-dns-egress",
        "NetworkPolicy/allow-mempalace-to-qdrant",
        "NetworkPolicy/allow-backup-to-qdrant",
        "NetworkPolicy/allow-backup-upload-egress",
        "NetworkPolicy/allow-prometheus-to-memory-observer",
        "NetworkPolicy/allow-memory-observer-egress",
        "NetworkPolicy/allow-host-nginx-to-mcp",
    }
    require(required <= policies, f"network policies missing: {sorted(required - policies)}")
    host_policy = docs["NetworkPolicy/allow-host-nginx-to-mcp"]
    backup_policy = docs["NetworkPolicy/allow-backup-upload-egress"]
    if source_has_placeholders:
        require("cidr: MEMORY_OPERATOR_MEASURED_HOST_NGINX_SOURCE_CIDR" in host_policy, "host nginx source must remain an explicit gate")
        require("cidr: MEMORY_OPERATOR_APPROVED_BACKUP_S3_CIDR" in backup_policy, "backup egress must remain an explicit gate")
        return
    for policy in (host_policy, backup_policy):
        cidr = field(policy, r"^            cidr:\s*(.+)$")
        require(cidr is not None, "rendered network policy lacks an egress or ingress CIDR")
        try:
            ipaddress.ip_network(cidr, strict=False)
        except ValueError as error:
            raise ValidationError(f"invalid rendered network CIDR: {cidr}") from error


def require_backup_monitoring_contract(docs: dict[str, str]) -> None:
    backup = docs["CronJob/solidstats-memory-backup"]
    require("suspend: true" in backup, "backup must start suspended")
    require("/collections/${QDRANT_COLLECTION}/snapshots" in backup, "backup misses Qdrant snapshot API")
    require("backups/solidstats-memory/" in backup, "backup prefix is incorrect")
    require("mempalace-metadata.tar" in backup and "SHA256SUMS" in backup, "backup misses metadata or checksums")
    observer = docs["ConfigMap/solidstats-memory-observer"]
    for marker in ("def probe_http", "def parse_collection_health", "def latest_snapshot_timestamp", "def collect_metrics", "class MetricsHandler", "solidstats_memory_mcp_ready", "solidstats_memory_qdrant_collection_healthy"):
        require(marker in observer, f"observer misses {marker}")
    compile(textwrap.dedent(observer.split("exporter.py: |", 1)[1]), "exporter.py", "exec")
    deployment = docs["Deployment/solidstats-memory-observer"]
    require("MEMORY_OPERATOR_SUPPLIED_OBSERVER_IMAGE_DIGEST" in deployment or not PLACEHOLDER_RE.search(deployment), "observer image is not rendered")
    require("automountServiceAccountToken: false" in deployment and "port: 9108" in docs["Service/solidstats-memory-observer"], "observer boundary is incomplete")


def require_rbac_and_workflow_contract(docs: dict[str, str]) -> None:
    role = docs["Role/memory-ci-deployer"]
    binding = docs["RoleBinding/memory-ci-deployer"]
    require("namespace: solidstats-memory" in role and "namespace: solidstats-memory" in binding, "CI RBAC must be namespace-scoped")
    require('resources: ["namespaces"]' not in role and '"delete"' not in role, "CI RBAC exceeds the deployment boundary")
    workflow = WORKFLOW.read_text()
    for expected in (
        "K8S_NAMESPACE: solidstats-memory",
        "infrastructure-memory-deploy-${{ github.ref }}",
        "validate-memory-manifests.py --allow-operator-placeholders",
        "render-memory-manifests.py --output-dir rendered-memory",
        "validate-memory-manifests.py --manifest-dir rendered-memory",
        "00-namespace.yaml and 01-ci-rbac.yaml are operator bootstrap",
    ):
        require(expected in workflow, f"memory workflow is missing: {expected}")
    for forbidden in ("secrets.K8S_TOKEN", "K8S_OBS_TOKEN", "K8S_OBS_ET_TOKEN", "ci-k3s-staging", "obs-k3s-staging", "obs-et-k3s-staging"):
        require(forbidden not in workflow, f"memory workflow references a foreign identity: {forbidden}")


def require_no_secret_values(manifest_dir: Path) -> None:
    for path in manifest_dir.glob("*.yaml"):
        text = path.read_text()
        require(not re.search(r"(?m)^\s*stringData:\s*$", text), f"{path.name} embeds Secret data")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    parser.add_argument("--allow-operator-placeholders", action="store_true")
    args = parser.parse_args()
    require(args.manifest_dir.is_dir(), f"manifest directory not found: {args.manifest_dir}")
    all_text = "\n".join(path.read_text() for path in args.manifest_dir.glob("*.yaml"))
    placeholders = sorted(set(PLACEHOLDER_RE.findall(all_text)))
    docs = validate_documents(args.manifest_dir)
    require_workload_safety(docs)
    require_network_contract(docs, bool(placeholders))
    require_backup_monitoring_contract(docs)
    require_rbac_and_workflow_contract(docs)
    require_no_secret_values(args.manifest_dir)
    if placeholders and not args.allow_operator_placeholders:
        raise ValidationError(f"unresolved operator placeholders: {', '.join(placeholders)}")
    print(f"validated {args.manifest_dir} ({len(docs)} resources)")


if __name__ == "__main__":
    try:
        main()
    except ValidationError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
