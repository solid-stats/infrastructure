#!/usr/bin/env python3
"""Bind one reviewed suspended backup source to one active rendered candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
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
    template = cronjobs[0].get("spec", {}).get("jobTemplate")
    encoded = json.dumps(template, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()
    return digest(encoded)


def render(source: Path, rendered: Path, active_source: Path, active_rendered: Path, descriptor: Path) -> None:
    source_raw = safe(source)
    rendered_raw = safe(rendered)
    if source_raw != rendered_raw:
        raise ValueError("rendered backup is not the exact reviewed source")
    marker = b"  suspend: true\n"
    if source_raw.count(marker) != 1:
        raise ValueError("suspended source marker differs")
    active = source_raw.replace(marker, b"  suspend: false\n", 1)
    suspended_template = canonical_template(source_raw)
    active_template = canonical_template(active)
    if suspended_template != active_template:
        raise ValueError("activation changed the canonical Job template")
    exclusive(active_source, active)
    exclusive(active_rendered, active)
    evidence = {
        "schema": "solidstats-memory-backup-activation-render/v1",
        "source_suspended_sha256": digest(source_raw),
        "rendered_suspended_sha256": digest(rendered_raw),
        "active_candidate_sha256": digest(active),
        "canonical_job_template_sha256": active_template,
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
    args = parser.parse_args()
    try:
        render(args.source, args.rendered, args.active_source, args.active_rendered, args.descriptor)
        print("PASS: backup activation provenance rendered")
        return 0
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(f"FAIL: {error}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
