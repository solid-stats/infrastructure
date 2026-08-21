#!/usr/bin/env python3
"""Bind one reviewed suspended backup source to one active rendered candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat

import yaml


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def safe(path: Path) -> bytes:
    details = path.lstat()
    if not stat.S_ISREG(details.st_mode) or stat.S_ISLNK(details.st_mode):
        raise ValueError("activation input is unsafe")
    return path.read_bytes()


def exclusive(path: Path, raw: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())


def canonical_template(raw: bytes) -> str:
    documents = [item for item in yaml.safe_load_all(raw) if isinstance(item, dict)]
    cronjobs = [item for item in documents if item.get("kind") == "CronJob" and item.get("metadata", {}).get("name") == "solidstats-memory-backup"]
    if len(cronjobs) != 1:
        raise ValueError("activation CronJob is missing or ambiguous")
    template = canonicalize_template(cronjobs[0].get("spec", {}).get("jobTemplate"))
    encoded = json.dumps(template, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()
    return digest(encoded)


def canonicalize_template(template: object) -> object:
    if not isinstance(template, dict):
        raise ValueError("activation Job template is invalid")
    value = json.loads(json.dumps(template, allow_nan=False))
    pod_spec = value.get("spec", {}).get("template", {}).get("spec", {})
    if not isinstance(pod_spec, dict):
        raise ValueError("activation Pod template is invalid")
    for key, default in (
        ("dnsPolicy", "ClusterFirst"),
        ("schedulerName", "default-scheduler"),
    ):
        if pod_spec.get(key) == default:
            pod_spec.pop(key)
    if pod_spec.get("serviceAccount") == pod_spec.get("serviceAccountName"):
        pod_spec.pop("serviceAccount", None)
    for group in ("containers", "initContainers"):
        for container in pod_spec.get(group, []):
            if container.get("terminationMessagePath") == "/dev/termination-log":
                container.pop("terminationMessagePath")
            if container.get("terminationMessagePolicy") == "File":
                container.pop("terminationMessagePolicy")
            for environment in container.get("env", []):
                field_ref = environment.get("valueFrom", {}).get("fieldRef", {})
                if field_ref.get("apiVersion") == "v1":
                    field_ref.pop("apiVersion")
            for probe_name in ("startupProbe", "readinessProbe", "livenessProbe"):
                probe = container.get(probe_name, {})
                if probe.get("successThreshold") == 1:
                    probe.pop("successThreshold")

    def prune(item: object) -> object:
        if isinstance(item, dict):
            result = {
                key: prune(child)
                for key, child in item.items()
                if child is not None
            }
            return {key: child for key, child in result.items() if child != {}}
        if isinstance(item, list):
            return [prune(child) for child in item]
        return item

    return prune(value)


IMAGE = re.compile(r"^[a-z0-9][a-z0-9./:_-]*@sha256:[0-9a-f]{64}$")
COLLECTION = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")
PLACEHOLDERS = {
    b"MEMORY_OPERATOR_SUPPLIED_MEMPALACE_IMAGE_DIGEST": ("mempalace_image", 2),
    b"MEMORY_OPERATOR_SUPPLIED_BACKUP_UPLOADER_IMAGE_DIGEST": ("uploader_image", 2),
    b"MEMORY_OPERATOR_CONFIRMED_QDRANT_COLLECTION_NAME": ("private_collection", 1),
}


def bindings(path: Path) -> dict[bytes, bytes]:
    details = path.lstat()
    if (
        not stat.S_ISREG(details.st_mode)
        or stat.S_ISLNK(details.st_mode)
        or stat.S_IMODE(details.st_mode) != 0o600
        or details.st_uid != os.getuid()
    ):
        raise ValueError("activation config is unsafe")
    value = json.loads(path.read_text(encoding="ascii"))
    if not isinstance(value, dict):
        raise ValueError("activation config is invalid")
    result: dict[bytes, bytes] = {}
    for placeholder, (key, _) in PLACEHOLDERS.items():
        item = value.get(key)
        if not isinstance(item, str):
            raise ValueError("activation binding is unavailable")
        if key.endswith("_image"):
            valid = IMAGE.fullmatch(item) is not None
        else:
            valid = COLLECTION.fullmatch(item) is not None
        if not valid:
            raise ValueError("activation binding is invalid")
        result[placeholder] = item.encode("ascii")
    return result


def render(
    source: Path,
    rendered: Path,
    active_source: Path,
    active_rendered: Path,
    descriptor: Path,
    operator_config: Path,
) -> None:
    source_raw = safe(source)
    rendered_raw = safe(rendered)
    expected_rendered = source_raw
    for placeholder, (_, expected_count) in PLACEHOLDERS.items():
        if expected_rendered.count(placeholder) != expected_count:
            raise ValueError("source placeholder cardinality differs")
    for placeholder, replacement in bindings(operator_config).items():
        expected_rendered = expected_rendered.replace(placeholder, replacement)
    if expected_rendered != rendered_raw:
        raise ValueError("rendered backup does not derive from reviewed source")
    marker = b"  suspend: true\n"
    if source_raw.count(marker) != 1 or rendered_raw.count(marker) != 1:
        raise ValueError("suspended source marker differs")
    active_source_raw = source_raw.replace(marker, b"  suspend: false\n", 1)
    active_rendered_raw = rendered_raw.replace(marker, b"  suspend: false\n", 1)
    if canonical_template(source_raw) != canonical_template(active_source_raw):
        raise ValueError("activation changed the canonical Job template")
    rendered_template = canonical_template(rendered_raw)
    if rendered_template != canonical_template(active_rendered_raw):
        raise ValueError("activation changed the rendered Job template")
    exclusive(active_source, active_source_raw)
    exclusive(active_rendered, active_rendered_raw)
    evidence = {
        "schema": "solidstats-memory-backup-activation-render/v1",
        "source_suspended_sha256": digest(source_raw),
        "rendered_suspended_sha256": digest(rendered_raw),
        "active_candidate_sha256": digest(active_rendered_raw),
        "canonical_job_template_sha256": rendered_template,
        "source_render_exact": True,
    }
    exclusive(descriptor, json.dumps(evidence, separators=(",", ":"), sort_keys=True).encode() + b"\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("rendered", type=Path)
    parser.add_argument("active_source", type=Path)
    parser.add_argument("active_rendered", type=Path)
    parser.add_argument("descriptor", type=Path)
    parser.add_argument("--operator-config", type=Path, required=True)
    args = parser.parse_args()
    try:
        render(
            args.source,
            args.rendered,
            args.active_source,
            args.active_rendered,
            args.descriptor,
            args.operator_config,
        )
        print("PASS: backup activation provenance rendered")
        return 0
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(f"FAIL: {error}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
