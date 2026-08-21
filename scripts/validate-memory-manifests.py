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
RUNTIME_BOOTSTRAP = ROOT / "scripts" / "bootstrap-solidstats-memory-palace.py"
NAMESPACE = "solidstats-memory"
EXPECTED = {
    "00-namespace.yaml",
    "01-ci-rbac.yaml",
    "05-rbac.yaml",
    "10-qdrant.yaml",
    "20-mempalace.yaml",
    "30-network-policy.yaml",
    "40-backup.yaml",
    "50-monitoring.yaml",
}
PLACEHOLDER_RE = re.compile(r"MEMORY_OPERATOR_[A-Z0-9_]+")
IMAGE_RE = re.compile(r"^[a-z0-9][a-z0-9./:_-]*@sha256:[0-9a-f]{64}$")
SIZE_RE = re.compile(r"^[1-9][0-9]*(Ki|Mi|Gi|Ti|Pi|Ei)$")
COLLECTION_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")
QDRANT_IMAGE = (
    "ghcr.io/qdrant/qdrant/qdrant:v1.19.0-unprivileged@"
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
    require(
        'name: QDRANT__SERVICE__JWT_RBAC\n              value: "true"'
        in docs["StatefulSet/qdrant"],
        "Qdrant JWT RBAC is not enabled",
    )
    require("type: ClusterIP" in docs["Service/qdrant"], "Qdrant must be a private ClusterIP service")
    require("clusterIP: None" in docs["Service/qdrant"], "Qdrant StatefulSet requires a headless governing service")
    require("type: LoadBalancer" not in docs["Service/qdrant"] and "type: NodePort" not in docs["Service/qdrant"], "Qdrant is publicly exposed")
    require("type: ClusterIP" in docs["Service/mempalace"], "MemPalace must use an internal ClusterIP service")
    require("mountPath: /qdrant/storage" in docs["StatefulSet/qdrant"], "Qdrant storage mount is missing")
    require(
        "name: snapshots\n              mountPath: /qdrant/snapshots"
        in docs["StatefulSet/qdrant"]
        and "name: snapshots\n          emptyDir:\n            sizeLimit: 1Gi"
        in docs["StatefulSet/qdrant"],
        "Qdrant read-only root lacks a bounded writable snapshot mount",
    )
    require("claimName: mempalace-data" in docs["Deployment/mempalace"], "MemPalace PVC is missing")
    require("persistentVolumeClaimRetentionPolicy:" in docs["StatefulSet/qdrant"], "Qdrant PVC Retain policy is missing")
    require("name: MEMPALACE_BACKEND\n              value: qdrant" in docs["Deployment/mempalace"], "MemPalace backend is not Qdrant")
    require("name: MEMPALACE_QDRANT_NAMESPACE\n              value: SolidStats" in docs["Deployment/mempalace"], "MemPalace namespace is incorrect")
    mempalace = docs["Deployment/mempalace"]
    for required in (
        "name: runtime-bootstrap",
        'command: ["python", "/opt/mempalace-bootstrap/bootstrap.py"]',
        'args: ["offline"]',
        "name: MEMPALACE_EMBEDDING_MODEL\n              value: embeddinggemma",
        "name: MEMPALACE_EMBEDDING_DEVICE\n              value: cpu",
        "name: HF_HOME\n              value: /data/palace/.cache/huggingface",
        'name: HF_HUB_OFFLINE\n              value: "1"',
        'name: HF_HUB_DISABLE_TELEMETRY\n              value: "1"',
        "name: mempalace-runtime-bootstrap\n            defaultMode: 0444",
    ):
        require(required in mempalace, f"MemPalace runtime bootstrap misses: {required}")
    embedding_resources = """resources:
            requests:
              cpu: 250m
              memory: 1Gi
            limits:
              cpu: \"1\"
              memory: 3Gi"""
    require(
        mempalace.count(embedding_resources) == 2,
        "MemPalace init and runtime embedding resources must match the proven 1Gi/3Gi contract",
    )
    bootstrap = RUNTIME_BOOTSTRAP.read_text(encoding="utf-8")
    for required in (
        "QdrantBackend",
        "collection.upsert(",
        "collection.delete(ids=[PROBE_ID])",
        "collection.set_embedder_identity(",
        "backend._validate_marker_target(",
        'HF_HUB_OFFLINE") != "1"',
    ):
        require(required in bootstrap, f"runtime bootstrap source misses: {required}")
    require(
        "_write_marker(" not in bootstrap and "json.dump(" not in bootstrap,
        "runtime bootstrap must use the pinned library marker writer",
    )
    operator = (ROOT / "scripts" / "operate-solidstats-memory.py").read_text(
        encoding="utf-8"
    )
    for required in (
        '"bootstrap-runtime-palace"',
        '"synthetic_residue": 0',
        '"alias_prestate_restored": True',
    ):
        require(required in operator, f"runtime bootstrap operator misses: {required}")


def require_network_contract(docs: dict[str, str], source_has_placeholders: bool) -> None:
    policies = {key for key in docs if key.startswith("NetworkPolicy/")}
    required = {
        "NetworkPolicy/default-deny-all",
        "NetworkPolicy/allow-dns-egress",
        "NetworkPolicy/allow-mempalace-to-qdrant",
        "NetworkPolicy/allow-mempalace-qdrant-egress",
        "NetworkPolicy/allow-backup-to-qdrant",
        "NetworkPolicy/allow-backup-to-kubernetes-api",
        "NetworkPolicy/allow-backup-upload-egress",
        "NetworkPolicy/allow-prometheus-to-memory-observer",
        "NetworkPolicy/allow-memory-observer-egress",
        "NetworkPolicy/allow-memory-observer-to-mempalace",
        "NetworkPolicy/allow-host-nginx-to-mcp",
    }
    require(required <= policies, f"network policies missing: {sorted(required - policies)}")

    observer_ingress = docs["NetworkPolicy/allow-memory-observer-to-mempalace"]
    expected_observer_ingress = """spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: mempalace
  policyTypes: [Ingress]
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: solidstats-memory-observer
      ports:
        - protocol: TCP
          port: 8765"""
    require(
        observer_ingress.split("spec:\n", 1)[-1].strip() == expected_observer_ingress.split("spec:\n", 1)[-1].strip(),
        "observer-to-MemPalace ingress must be one exact same-namespace TCP 8765 policy",
    )

    mempalace_egress = docs["NetworkPolicy/allow-mempalace-qdrant-egress"]
    expected_mempalace_egress = """spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: mempalace
  policyTypes: [Egress]
  egress:
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: qdrant
      ports:
        - protocol: TCP
          port: 6333"""
    require(
        mempalace_egress.split("spec:\n", 1)[-1].strip() == expected_mempalace_egress.split("spec:\n", 1)[-1].strip(),
        "MemPalace egress must be one exact same-namespace Qdrant TCP 6333 path",
    )

    observer_egress = docs["NetworkPolicy/allow-memory-observer-egress"]
    expected_observer_egress = """spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: solidstats-memory-observer
  policyTypes: [Egress]
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: mempalace
      ports:
        - protocol: TCP
          port: 8765
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: qdrant
      ports:
        - protocol: TCP
          port: 6333"""
    require(
        observer_egress.split("spec:\n", 1)[-1].strip() == expected_observer_egress.split("spec:\n", 1)[-1].strip(),
        "observer egress must retain only its DNS, MemPalace TCP 8765, and Qdrant TCP 6333 paths",
    )

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
    for marker in (
        "serviceAccountToken:",
        "expirationSeconds: 600",
        "name: kube-root-ca.crt",
        "mountPath: /var/run/secrets/solidstats-memory",
        'cat "${api_token_path}"',
        "readOnly: true",
        "deployments/mempalace/scale",
        "original_generation",
        "original_writer_pod_count",
        "original_writer_pods_sha256",
        "metadata_source_before_sha256",
        "metadata_source_after_sha256",
        "metadata_archive_sha256",
        'cd "$1"',
        "restore_writer()",
    ):
        require(marker in backup, f"backup quiescence contract misses: {marker}")
    observer = docs["ConfigMap/solidstats-memory-observer"]
    for marker in ("def probe_http", "def parse_collection_health", "def latest_snapshot_timestamp", "def collect_metrics", "class MetricsHandler", "solidstats_memory_mcp_ready", "solidstats_memory_qdrant_collection_healthy"):
        require(marker in observer, f"observer misses {marker}")
    compile(textwrap.dedent(observer.split("exporter.py: |", 1)[1]), "exporter.py", "exec")
    deployment = docs["Deployment/solidstats-memory-observer"]
    require(
        "name: memory-observer-runtime" in deployment
        and "name: qdrant-runtime" not in deployment,
        "observer must use its read-only Qdrant credential",
    )
    require("MEMORY_OPERATOR_SUPPLIED_OBSERVER_IMAGE_DIGEST" in deployment or not PLACEHOLDER_RE.search(deployment), "observer image is not rendered")
    require("automountServiceAccountToken: false" in deployment and "port: 9108" in docs["Service/solidstats-memory-observer"], "observer boundary is incomplete")


def require_backup_api_control_contract(
    docs: dict[str, str], source_has_placeholders: bool
) -> None:
    role = docs["Role/solidstats-memory-backup"]
    binding = docs["RoleBinding/solidstats-memory-backup"]
    policy = docs["NetworkPolicy/allow-backup-to-kubernetes-api"]
    backup = docs["CronJob/solidstats-memory-backup"]
    exact_role_rules = """rules:
  - apiGroups: [\"apps\"]
    resources: [\"deployments\"]
    resourceNames: [\"mempalace\"]
    verbs: [\"get\"]
  - apiGroups: [\"apps\"]
    resources: [\"deployments/scale\"]
    resourceNames: [\"mempalace\"]
    verbs: [\"get\", \"patch\"]
  - apiGroups: [\"\"]
    resources: [\"pods\"]
    verbs: [\"list\"]"""
    require(exact_role_rules in role, "backup Role is not exact least privilege")
    for forbidden in ('"*"', "ClusterRole", "secrets", '"delete"', '"create"'):
        require(forbidden not in role, "backup Role exceeds least privilege")
    exact_subject = """subjects:
  - kind: ServiceAccount
    name: solidstats-memory-backup
    namespace: solidstats-memory
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: solidstats-memory-backup"""
    require(exact_subject in binding, "backup RoleBinding subject is not exact")
    exact_projection = """- name: kubernetes-api-access
              projected:
                defaultMode: 0400
                sources:
                  - serviceAccountToken:
                      path: token
                      expirationSeconds: 600
                  - configMap:
                      name: kube-root-ca.crt
                      items:
                        - key: ca.crt
                          path: ca.crt"""
    exact_mount = """- name: kubernetes-api-access
                  mountPath: /var/run/secrets/solidstats-memory
                  readOnly: true"""
    require(exact_projection in backup, "backup projected API identity is not exact")
    require(exact_mount in backup, "backup API identity mount is not exact")
    require("audience:" not in backup, "backup API token audience must use the API default")
    expected_policy = """spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: solidstats-memory-backup
  policyTypes: [Egress]
  egress:
    - to:
        - ipBlock:
            cidr: MEMORY_OPERATOR_MEASURED_KUBERNETES_API_EGRESS_CIDR
      ports:
        - protocol: TCP
          port: MEMORY_OPERATOR_MEASURED_KUBERNETES_API_EGRESS_PORT"""
    if source_has_placeholders:
        require(
            policy.split("spec:\n", 1)[-1].strip()
            == expected_policy.split("spec:\n", 1)[-1].strip(),
            "backup API policy source contract is not exact",
        )
        return
    cidr = field(policy, r"^            cidr:\s*(.+)$")
    port = field(policy, r"^          port:\s*(.+)$")
    require(cidr is not None and port is not None, "backup API binding is absent")
    try:
        network = ipaddress.ip_network(cidr, strict=True)
    except ValueError as error:
        raise ValidationError("backup API CIDR is invalid") from error
    require(
        network.prefixlen == network.max_prefixlen,
        "backup API destination must be one host prefix",
    )
    require(port.isdigit() and 1 <= int(port) <= 65535, "backup API port is invalid")
    resolved_spec = expected_policy.replace(
        "MEMORY_OPERATOR_MEASURED_KUBERNETES_API_EGRESS_CIDR", cidr
    ).replace("MEMORY_OPERATOR_MEASURED_KUBERNETES_API_EGRESS_PORT", port)
    require(
        policy.split("spec:\n", 1)[-1].strip()
        == resolved_spec.split("spec:\n", 1)[-1].strip(),
        "backup API policy rendered contract is not exact",
    )


def require_operator_placeholder_positions(docs: dict[str, str]) -> list[str]:
    """Keep each evidence gate in its owning field, never in comments."""
    expected = {
        "StatefulSet/qdrant": {"storage: MEMORY_OPERATOR_MEASURED_QDRANT_PVC_SIZE": 1},
        "PersistentVolumeClaim/mempalace-data": {"storage: MEMORY_OPERATOR_MEASURED_MEMPALACE_PVC_SIZE": 1},
        "Deployment/mempalace": {"image: MEMORY_OPERATOR_SUPPLIED_MEMPALACE_IMAGE_DIGEST": 2},
        "CronJob/solidstats-memory-backup": [
            "image: MEMORY_OPERATOR_SUPPLIED_BACKUP_UPLOADER_IMAGE_DIGEST",
            "value: MEMORY_OPERATOR_CONFIRMED_QDRANT_COLLECTION_NAME",
        ],
        "Deployment/solidstats-memory-observer": [
            "image: MEMORY_OPERATOR_SUPPLIED_OBSERVER_IMAGE_DIGEST",
            "value: MEMORY_OPERATOR_CONFIRMED_QDRANT_COLLECTION_NAME",
        ],
        "NetworkPolicy/allow-backup-upload-egress": ["cidr: MEMORY_OPERATOR_APPROVED_BACKUP_S3_CIDR"],
        "NetworkPolicy/allow-host-nginx-to-mcp": ["cidr: MEMORY_OPERATOR_MEASURED_HOST_NGINX_SOURCE_CIDR"],
        "NetworkPolicy/allow-backup-to-kubernetes-api": [
            "cidr: MEMORY_OPERATOR_MEASURED_KUBERNETES_API_EGRESS_CIDR",
            "port: MEMORY_OPERATOR_MEASURED_KUBERNETES_API_EGRESS_PORT",
        ],
    }
    for resource, entries in expected.items():
        counts = entries if isinstance(entries, dict) else {entry: 1 for entry in entries}
        for entry, expected_count in counts.items():
            require(docs[resource].count(entry) == expected_count, f"operator placeholders must retain expected field: {resource} {entry}")
    all_markers = PLACEHOLDER_RE.findall("\n".join(docs.values()))
    expected_markers = {
        "MEMORY_OPERATOR_SUPPLIED_MEMPALACE_IMAGE_DIGEST",
        "MEMORY_OPERATOR_SUPPLIED_OBSERVER_IMAGE_DIGEST",
        "MEMORY_OPERATOR_SUPPLIED_BACKUP_UPLOADER_IMAGE_DIGEST",
        "MEMORY_OPERATOR_MEASURED_QDRANT_PVC_SIZE",
        "MEMORY_OPERATOR_MEASURED_MEMPALACE_PVC_SIZE",
        "MEMORY_OPERATOR_MEASURED_HOST_NGINX_SOURCE_CIDR",
        "MEMORY_OPERATOR_APPROVED_BACKUP_S3_CIDR",
        "MEMORY_OPERATOR_CONFIRMED_QDRANT_COLLECTION_NAME",
        "MEMORY_OPERATOR_MEASURED_KUBERNETES_API_EGRESS_CIDR",
        "MEMORY_OPERATOR_MEASURED_KUBERNETES_API_EGRESS_PORT",
    }
    require(set(all_markers) == expected_markers, "operator placeholders differ from the ten evidence gates")
    require(len(all_markers) == 12, "operator placeholders are missing, duplicated, or misplaced")
    return sorted(set(all_markers))


def require_resolved_value_shapes(docs: dict[str, str]) -> None:
    for resource in ("StatefulSet/qdrant", "Deployment/mempalace", "Deployment/solidstats-memory-observer", "CronJob/solidstats-memory-backup"):
        image = field(docs[resource], r"^\s+image:\s*(.+)$")
        require(image is not None and IMAGE_RE.fullmatch(image) is not None, f"{resource} image must be an immutable digest")
    for resource in ("StatefulSet/qdrant", "PersistentVolumeClaim/mempalace-data"):
        size = field(docs[resource], r"^\s*storage:\s*(.+)$")
        require(size is not None and SIZE_RE.fullmatch(size) is not None, f"{resource} storage must be a positive Kubernetes quantity")
    collection_values = []
    for resource in ("CronJob/solidstats-memory-backup", "Deployment/solidstats-memory-observer"):
        value = field(docs[resource], r"- name: QDRANT_COLLECTION\n\s+value:\s*(.+)$")
        require(value is not None and COLLECTION_RE.fullmatch(value) is not None, f"{resource} collection must be lowercase")
        collection_values.append(value)
    require(collection_values[0] == collection_values[1], "backup and observer collection names must match")


def require_checked_in_staging_config(docs: dict[str, str]) -> None:
    backup = docs["CronJob/solidstats-memory-backup"]
    require("name: S3_ENDPOINT\n                  value: https://s3.twcstorage.ru" in backup, "backup endpoint must be checked in")
    require("name: S3_PREFIX\n                  value: backups/solidstats-memory/" in backup, "backup prefix must be checked in")
    require('"s3://${S3_BUCKET}/${S3_PREFIX}${backup_id}/"' in backup, "backup upload path is incorrect")
    require("key: S3_ENDPOINT" not in backup and "key: S3_PREFIX" not in backup, "backup endpoint or prefix must not be secret-backed")


def require_deploy_input_contract() -> None:
    workflow = WORKFLOW.read_text()
    secret_renderer = (ROOT / "scripts" / "render-memory-secrets.py").read_text()
    require(not re.search(r"vars\.MEMORY_", workflow), "memory workflow must not use GitHub Environment variables")
    require("MEMORY_BACKUP_S3_" not in workflow and "MEMORY_BACKUP_S3_" not in secret_renderer, "obsolete memory backup aliases remain")
    for name in ("S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "S3_BUCKET"):
        require(f"secrets.{name}" in workflow and f'required("{name}")' in secret_renderer, f"S3 secret contract missing: {name}")
    names = set(re.findall(r"secrets\.([A-Z0-9_]+)", workflow))
    established = {"DEPLOY_SSH_PRIVATE_KEY", "DEPLOY_SSH_KNOWN_HOSTS", "DEPLOY_SSH_HOST", "DEPLOY_SSH_USER", "K8S_CA_CERT", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "S3_BUCKET"}
    require(
        names - established
        == {
            "K8S_MEMORY_TOKEN",
            "MEMORY_QDRANT_API_KEY",
            "MEMORY_QDRANT_COLLECTION",
            "MEMORY_QDRANT_LOGICAL_ALIAS",
            "MEMORY_MCP_HTTP_TOKEN",
        },
        "memory-specific secret inventory changed",
    )
    identity = workflow.index("auth whoami")
    for mutation in ("--dry-run=server", "apply --server-side"):
        require(identity < workflow.index(mutation), "memory identity check must precede mutation")


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
        "render-memory-manifests.py rendered-memory",
        "validate-memory-manifests.py --manifest-dir rendered-memory",
        "00-namespace.yaml, 01-ci-rbac.yaml, and 05-rbac.yaml are operator",
    ):
        require(expected in workflow, f"memory workflow is missing: {expected}")
    for forbidden in ("secrets.K8S_TOKEN", "K8S_OBS_TOKEN", "K8S_OBS_ET_TOKEN", "ci-k3s-staging", "obs-k3s-staging", "obs-et-k3s-staging"):
        require(forbidden not in workflow, f"memory workflow references a foreign identity: {forbidden}")
    require_deploy_input_contract()


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
    require_backup_api_control_contract(docs, bool(placeholders))
    require_backup_monitoring_contract(docs)
    require_checked_in_staging_config(docs)
    require_rbac_and_workflow_contract(docs)
    require_no_secret_values(args.manifest_dir)
    if placeholders:
        placeholders = require_operator_placeholder_positions(docs)
    else:
        require_resolved_value_shapes(docs)
    if placeholders and not args.allow_operator_placeholders:
        raise ValidationError(f"unresolved operator placeholders: {', '.join(placeholders)}")
    print(f"validated {args.manifest_dir} ({len(docs)} resources)")


if __name__ == "__main__":
    try:
        main()
    except ValidationError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
