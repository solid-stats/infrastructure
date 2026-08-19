#!/usr/bin/env python3
"""Validate the uninstalled SolidStats-memory nginx template offline."""

import argparse
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "config" / "nginx" / "sites-available" / "solidstats-memory-mcp.conf.template"


def require(text: str, expected: str) -> None:
    if expected not in text:
        raise ValueError(f"nginx template is missing required directive: {expected}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-operator-placeholders", action="store_true")
    args = parser.parse_args()
    text = TEMPLATE.read_text()
    for expected in (
        "server MEMORY_OPERATOR_RESOLVED_MEMPALACE_CLUSTER_IP:8765;",
        "listen 443 ssl http2;",
        "location = /solidstats/mcp {",
        "proxy_pass http://solidstats_memory_mcp/mcp;",
        "proxy_set_header Authorization $http_authorization;",
        "proxy_buffering off;",
        "proxy_request_buffering off;",
        "location / {\n        return 404;",
        "MEMORY_OPERATOR_CONFIRMED_TLS_CERTIFICATE_PATH",
    ):
        require(text, expected)
    if "proxy_pass http://solidstats_memory_mcp;" in text:
        raise ValueError("nginx template does not map the public path to MemPalace /mcp")
    placeholders = sorted(set(re.findall(r"MEMORY_OPERATOR_[A-Z0-9_]+", text)))
    if placeholders and not args.allow_operator_placeholders:
        raise ValueError(f"unresolved operator placeholders: {', '.join(placeholders)}")
    print(f"validated {TEMPLATE.relative_to(ROOT)}")


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
