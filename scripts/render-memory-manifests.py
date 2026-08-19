#!/usr/bin/env python3
"""Stage the reviewed memory manifests without modifying their bytes."""

import argparse
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "k8s" / "memory"
EXPECTED = {
    "00-namespace.yaml",
    "01-ci-rbac.yaml",
    "10-qdrant.yaml",
    "20-mempalace.yaml",
    "30-network-policy.yaml",
    "40-backup.yaml",
    "50-monitoring.yaml",
}


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
    for name in sorted(EXPECTED):
        shutil.copyfile(source_files[name], args.output_dir / name)


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(64)
