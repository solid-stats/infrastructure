#!/usr/bin/env python3
"""Render operator-gated memory manifest values into a disposable directory."""

import argparse
import ipaddress
import os
import re
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "k8s" / "memory"
IMAGE_RE = re.compile(r"^[a-z0-9][a-z0-9./:_-]*@sha256:[0-9a-f]{64}$")
SIZE_RE = re.compile(r"^[1-9][0-9]*(Mi|Gi|Ti)$")
COLLECTION_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")


def required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"missing required environment variable: {name}")
    return value


def valid_image(name: str) -> str:
    value = required(name)
    if not IMAGE_RE.fullmatch(value):
        raise ValueError(f"{name} must be an immutable image digest")
    return value


def valid_size(name: str) -> str:
    value = required(name)
    if not SIZE_RE.fullmatch(value):
        raise ValueError(f"{name} must be a positive Kubernetes storage quantity")
    return value


def valid_cidr(name: str) -> str:
    value = required(name)
    try:
        return str(ipaddress.ip_network(value, strict=False))
    except ValueError as error:
        raise ValueError(f"{name} must be a CIDR") from error


def valid_collection() -> str:
    value = required("MEMORY_QDRANT_COLLECTION")
    if not COLLECTION_RE.fullmatch(value):
        raise ValueError("MEMORY_QDRANT_COLLECTION must be a lowercase Qdrant collection name")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    replacements = {
        "MEMORY_OPERATOR_SUPPLIED_MEMPALACE_IMAGE_DIGEST": valid_image("MEMORY_MEMPALACE_IMAGE"),
        "MEMORY_OPERATOR_SUPPLIED_BACKUP_UPLOADER_IMAGE_DIGEST": valid_image("MEMORY_BACKUP_UPLOADER_IMAGE"),
        "MEMORY_OPERATOR_MEASURED_QDRANT_PVC_SIZE": valid_size("MEMORY_QDRANT_PVC_SIZE"),
        "MEMORY_OPERATOR_MEASURED_MEMPALACE_PVC_SIZE": valid_size("MEMORY_MEMPALACE_PVC_SIZE"),
        "MEMORY_OPERATOR_MEASURED_HOST_NGINX_SOURCE_CIDR": valid_cidr("MEMORY_HOST_NGINX_SOURCE_CIDR"),
        "MEMORY_OPERATOR_APPROVED_BACKUP_S3_CIDR": valid_cidr("MEMORY_BACKUP_S3_CIDR"),
        "MEMORY_OPERATOR_CONFIRMED_QDRANT_COLLECTION_NAME": valid_collection(),
    }

    if args.output_dir.exists():
        raise ValueError(f"output directory already exists: {args.output_dir}")
    shutil.copytree(SOURCE_DIR, args.output_dir)
    for path in args.output_dir.glob("*.yaml"):
        text = path.read_text()
        for placeholder, value in replacements.items():
            text = text.replace(placeholder, value)
        path.write_text(text)


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(64)
