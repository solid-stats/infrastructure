#!/usr/bin/env python3
"""Render isolated unified-memory resources and private collection-role credentials."""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re

from unified_memory_recovery import bindings, canonical, private_json

ROOT = Path(__file__).resolve().parents[1]
NS = "unified-memory"
QDRANT = "http://qdrant.solidstats-memory.svc:6333"
IMAGE = re.compile(r"^[a-z0-9][a-z0-9./:_-]*@sha256:[0-9a-f]{64}$")


def resource(kind, name, spec=None, namespace=NS, **extra):
    api = "apps/v1" if kind == "Deployment" else "batch/v1" if kind == "CronJob" else "networking.k8s.io/v1" if kind == "NetworkPolicy" else "v1"
    value = {"apiVersion": api, "kind": kind, "metadata": {"name": name, "namespace": namespace}, **extra}
    if spec is not None:
        value["spec"] = spec
    return value


def labels(name):
    return {"app.kubernetes.io/name": name, "app.kubernetes.io/part-of": "unified-memory"}


def peer(namespace, name):
    return {"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": namespace}},
            "podSelector": {"matchLabels": {"app.kubernetes.io/name": name}}}


def env_secret(name, secret, key=None):
    return {"name": name, "valueFrom": {"secretKeyRef": {"name": secret, "key": key or name}}}


def generated(config, image):
    if "REQUIRED" in json.dumps(config):
        raise ValueError("operator placeholders remain")
    if config.get("schema") != "unified-memory-deployment-input/v1" or config.get("qdrantVersion") != "1.19.0":
        raise ValueError("reviewed deployment and Qdrant versions required")
    if type(config.get("minimumBackupFreeBytes")) is not int or config["minimumBackupFreeBytes"] <= 0:
        raise ValueError("measured backup scratch floor required")
    if not IMAGE.fullmatch(image):
        raise ValueError("immutable image digest required")
    if config.get("namespace") != NS or config.get("qdrantUrl") != QDRANT or config.get("palacePath") != "/data/palace":
        raise ValueError("fixed runtime boundary differs")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", config["qdrantNamespace"]):
        raise ValueError("backend namespace required")
    if not re.fullmatch(r"[1-9][0-9]*(Mi|Gi)", config["pvcSize"]):
        raise ValueError("explicit PVC size required")
    for field in ("hostNginxSourceCidr", "backupS3Cidr"):
        network = ipaddress.ip_network(config[field], strict=True)
        if network.prefixlen == 0:
            raise ValueError("unrestricted network prefix rejected")
    for group in ("requests", "limits"):
        for field in ("cpu", "memory"):
            value = config["resources"][group][field]
            if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*(m|Mi|Gi)?", value):
                raise ValueError("explicit resource quantities required")
    if not isinstance(config.get("probeWing"), str) or not config["probeWing"]:
        raise ValueError("approved probe wing required")
    rows = bindings(config)
    for row in rows:
        prefix = "mempalace_" + config["qdrantNamespace"] + "_" + hashlib.sha256(b"/data/palace").hexdigest()[:16] + "_"
        if row["alias"] != prefix + row["logicalName"] or row["alias"] == row["physical"]:
            raise ValueError("deterministic runtime alias differs")
        if row["dimension"] != 384:
            raise ValueError("embeddinggemma dimension differs")
    namespace = json.loads((ROOT / "k8s/unified-memory/00-namespace.yaml").read_text())
    runtime_labels, backup_labels = labels("unified-mempalace"), labels("unified-memory-backup")
    security = {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}}
    pod_security = {"runAsNonRoot": True, "runAsUser": 1000, "runAsGroup": 1000, "fsGroup": 1000, "seccompProfile": {"type": "RuntimeDefault"}}
    data = {name: (ROOT / "scripts" / name).read_text() for name in
            ("bootstrap-unified-memory.py", "unified_memory_recovery.py")}
    data["bindings.json"] = canonical(config).decode()
    configmap = resource("ConfigMap", "unified-memory-code", data=data)
    volumes = [{"name": "data", "persistentVolumeClaim": {"claimName": "unified-memory-data"}},
               {"name": "code", "configMap": {"name": "unified-memory-code", "defaultMode": 292}}, {"name": "tmp", "emptyDir": {}}]
    mounts = [{"name": "data", "mountPath": "/data"}, {"name": "code", "mountPath": "/opt/unified-memory", "readOnly": True},
              {"name": "tmp", "mountPath": "/tmp"}]
    environment = [{"name": name, "value": value} for name, value in {
        "MEMPALACE_BACKEND": "qdrant", "MEMPALACE_QDRANT_URL": QDRANT,
        "MEMPALACE_QDRANT_NAMESPACE": config["qdrantNamespace"], "MEMPALACE_EMBEDDING_MODEL": "embeddinggemma",
        "MEMPALACE_EMBEDDING_DEVICE": "cpu", "MEMPALACE_MCP_ALLOW_PEER_WRITER": "1", "MEMPALACE_DATA_DIR": "/data/palace",
        "HF_HOME": "/data/palace/.cache/huggingface", "HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
        "PYTHONDONTWRITEBYTECODE": "1"}.items()]
    environment += [env_secret(name, "unified-memory-runtime") for name in ("MEMPALACE_QDRANT_API_KEY", "MEMPALACE_MCP_HTTP_TOKEN")]
    base = {"image": image, "imagePullPolicy": "IfNotPresent", "securityContext": security,
            "resources": config["resources"], "volumeMounts": mounts, "env": environment}
    init = {**base, "name": "validate-target", "command": ["python3", "/opt/unified-memory/bootstrap-unified-memory.py", "validate",
            "--bindings", "/opt/unified-memory/bindings.json"]}
    init["env"] = [*environment, env_secret("UNIFIED_OBSERVER_API_KEY", "unified-memory-observer", "QDRANT_API_KEY")]
    server = {**base, "name": "mempalace", "command": ["mempalace-mcp"],
              "args": ["--palace", "/data/palace", "--backend", "qdrant", "--transport", "http", "--host", "0.0.0.0", "--port", "8765"],
              "ports": [{"name": "mcp", "containerPort": 8765}],
              "readinessProbe": {"httpGet": {"path": "/healthz", "port": "mcp"}, "initialDelaySeconds": 10},
              "livenessProbe": {"httpGet": {"path": "/healthz", "port": "mcp"}, "initialDelaySeconds": 30}}
    runtime = resource("Deployment", "mempalace", {"replicas": 1, "strategy": {"type": "Recreate"},
                        "selector": {"matchLabels": runtime_labels}, "template": {"metadata": {"labels": runtime_labels},
                        "spec": {"serviceAccountName": "mempalace", "automountServiceAccountToken": False, "securityContext": pod_security,
                                 "initContainers": [init], "containers": [server], "volumes": volumes}}})
    backup_env = [{"name": "QDRANT_URL", "value": QDRANT}, {"name": "UNIFIED_WRITERS_QUIESCED", "value": "1"},
                  {"name": "S3_ENDPOINT", "value": "https://s3.twcstorage.ru"}, {"name": "S3_PREFIX", "value": "backups/unified-memory/"},
                  {"name": "RECOVERY_POINT", "valueFrom": {"fieldRef": {"fieldPath": "metadata.name"}}},
                  {"name": "PYTHONDONTWRITEBYTECODE", "value": "1"}]
    backup_env += [env_secret(name, "unified-memory-backup") for name in
                   ("QDRANT_API_KEY", "S3_BUCKET", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")]
    backup_container = {"name": "backup", "image": image, "imagePullPolicy": "IfNotPresent",
        "command": ["python3", "/opt/unified-memory/unified_memory_recovery.py", "backup", "--bindings", "/opt/unified-memory/bindings.json",
                    "--palace", "/data", "--package", "/work/package", "--publish"],
        "env": backup_env, "securityContext": security,
        "resources": {"requests": {"cpu": "100m", "memory": "256Mi"}, "limits": {"cpu": "1", "memory": "1Gi"}},
        "volumeMounts": [*mounts, {"name": "work", "mountPath": "/work"}]}
    backup_job = resource("CronJob", "unified-memory-backup", {"suspend": True, "schedule": "30 6 * * *", "timeZone": "Europe/Moscow",
        "concurrencyPolicy": "Forbid", "successfulJobsHistoryLimit": 7, "failedJobsHistoryLimit": 7,
        "jobTemplate": {"spec": {"activeDeadlineSeconds": 3600, "backoffLimit": 0, "ttlSecondsAfterFinished": 604800,
        "template": {"metadata": {"labels": backup_labels}, "spec": {"restartPolicy": "Never", "serviceAccountName": "unified-memory-backup",
        "automountServiceAccountToken": False, "securityContext": pod_security, "containers": [backup_container],
        "volumes": [*volumes, {"name": "work", "emptyDir": {}}]}}}}})
    resources = [namespace, resource("ServiceAccount", "mempalace", automountServiceAccountToken=False),
        resource("ServiceAccount", "unified-memory-backup", automountServiceAccountToken=False),
        resource("PersistentVolumeClaim", "unified-memory-data", {"accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": config["pvcSize"]}}}),
        configmap, runtime, resource("Service", "mempalace", {"type": "ClusterIP", "selector": runtime_labels,
        "ports": [{"name": "mcp", "port": 8765, "targetPort": "mcp"}]}), backup_job,
        resource("NetworkPolicy", "default-deny-all", {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]}),
        resource("NetworkPolicy", "allow-dns", {"podSelector": {}, "policyTypes": ["Egress"], "egress": [{"to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}},
        "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}}}],
        "ports": [{"protocol": protocol, "port": 53} for protocol in ("UDP", "TCP")]}]}),
        resource("NetworkPolicy", "allow-qdrant", {"podSelector": {}, "policyTypes": ["Egress"],
        "egress": [{"to": [peer("solidstats-memory", "qdrant")], "ports": [{"protocol": "TCP", "port": 6333}]}]}),
        resource("NetworkPolicy", "allow-host-nginx", {"podSelector": {"matchLabels": runtime_labels}, "policyTypes": ["Ingress"],
        "ingress": [{"from": [{"ipBlock": {"cidr": config["hostNginxSourceCidr"]}}], "ports": [{"protocol": "TCP", "port": 8765}]}]}),
        resource("NetworkPolicy", "allow-backup-s3", {"podSelector": {"matchLabels": backup_labels}, "policyTypes": ["Egress"],
        "egress": [{"to": [{"ipBlock": {"cidr": config["backupS3Cidr"]}}], "ports": [{"protocol": "TCP", "port": 443}]}]}),
        json.loads((ROOT / "k8s/unified-memory/30-shared-qdrant-ingress.yaml").read_text())]
    return {"apiVersion": "v1", "kind": "List", "items": resources}


def jwt(key, subject, collections, access):
    def encode(value):
        return base64.urlsafe_b64encode(canonical(value)).rstrip(b"=").decode()
    unsigned = encode({"alg": "HS256", "typ": "JWT"}) + "." + encode({"sub": subject, "access": [
        {"collection": name, "access": access} for name in collections]})
    return unsigned + "." + base64.urlsafe_b64encode(hmac.new(key.encode(), unsigned.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()


def secrets(config, admin_key, http_token, s3):
    rows = bindings(config)
    if not admin_key or not http_token or set(s3) != {"S3_BUCKET", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"} or not all(s3.values()):
        raise ValueError("complete private role inputs required")
    return {"apiVersion": "v1", "kind": "List", "items": [
        resource("Secret", "unified-memory-runtime", type="Opaque", stringData={
            "MEMPALACE_QDRANT_API_KEY": jwt(admin_key, "unified-memory-runtime", [row["alias"] for row in rows], "rw"),
            "MEMPALACE_MCP_HTTP_TOKEN": http_token}),
        resource("Secret", "unified-memory-backup", type="Opaque", stringData={
            "QDRANT_API_KEY": jwt(admin_key, "unified-memory-backup", [row["physical"] for row in rows], "rw"), **s3}),
        resource("Secret", "unified-memory-observer", type="Opaque", stringData={
            "QDRANT_API_KEY": jwt(admin_key, "unified-memory-observer", [name for row in rows for name in (row["physical"], row["alias"])], "r")})]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--admin-key-file", type=Path)
    parser.add_argument("--http-token-file", type=Path)
    parser.add_argument("--s3-file", type=Path)
    args = parser.parse_args()
    config = json.loads(args.inputs.read_text())
    result = generated(config, args.image)
    if args.output.exists():
        raise ValueError("render output must be absent")
    private_inputs = (args.admin_key_file, args.http_token_file, args.s3_file)
    private_secrets = None
    if any(private_inputs):
        if not all(private_inputs):
            raise ValueError("all private role inputs required")
        for path in private_inputs:
            if path.is_symlink() or (os.name != "nt" and path.stat().st_mode & 0o077):
                raise ValueError("owner-only secret input required")
        private_secrets = secrets(config, args.admin_key_file.read_text().strip(),
                                  args.http_token_file.read_text().strip(), json.loads(args.s3_file.read_text()))
    args.output.mkdir(mode=0o700)
    private_json(args.output / "resources.json", result)
    if private_secrets:
        private_json(args.output / "secrets.json", private_secrets)
    print("PASS: unified resources rendered; private output retained")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("FAIL: unified manifest rendering", file=__import__("sys").stderr)
        raise SystemExit(1)
