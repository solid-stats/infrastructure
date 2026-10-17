#!/usr/bin/env python3
"""Stage reviewed memory manifests and derive the backup oracle from source."""

import argparse
import base64
import re
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "k8s" / "memory"
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
OPERATOR_ONLY = {"05-rbac.yaml"}


def render_backup_oracle(manifest: bytes, oracle: bytes) -> bytes:
    """Replace only the generated oracle payload, preserving other manifest bytes."""
    rendered, count = re.subn(
        rb"(?m)^(  solidstats_memory_backup_oracle\.py: )[A-Za-z0-9+/=]+",
        lambda match: match[1] + base64.b64encode(oracle),
        manifest,
    )
    if count != 1:
        raise ValueError("exactly one backup oracle payload is required")
    return rendered


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    source_files = {path.name: path for path in SOURCE_DIR.glob("*.yaml")}
    if set(source_files) != EXPECTED or any(not path.is_file() for path in source_files.values()):
        raise ValueError("memory source manifest set differs from contract")
    if args.output_dir.exists():
        raise ValueError(f"output directory already exists: {args.output_dir}")
    args.output_dir.mkdir()
    for name in sorted(EXPECTED - OPERATOR_ONLY):
        if name == "40-backup.yaml":
            oracle = (ROOT / "scripts" / "solidstats_memory_backup_oracle.py").read_bytes()
            (args.output_dir / name).write_bytes(
                render_backup_oracle(source_files[name].read_bytes(), oracle)
            )
        else:
            shutil.copyfile(source_files[name], args.output_dir / name)


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(64)
