#!/usr/bin/env python3
"""Render SolidStats-memory secrets from deploy-time environment variables."""

import json
import os
import sys


NAMESPACE = "solidstats-memory"
missing: list[str] = []


def required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        missing.append(name)
        return ""
    return value


def secret(name: str, values: dict[str, str]) -> str:
    lines = [
        "apiVersion: v1",
        "kind: Secret",
        "type: Opaque",
        "metadata:",
        f"  name: {name}",
        f"  namespace: {NAMESPACE}",
        "stringData:",
    ]
    lines.extend(f"  {key}: {json.dumps(value)}" for key, value in values.items())
    return "\n".join(lines)


qdrant_api_key = required("MEMORY_QDRANT_API_KEY")
mcp_http_token = required("MEMORY_MCP_HTTP_TOKEN")
s3_bucket = required("S3_BUCKET")
s3_access_key_id = required("S3_ACCESS_KEY_ID")
s3_secret_access_key = required("S3_SECRET_ACCESS_KEY")

if missing:
    print(f"Missing required environment variables: {', '.join(sorted(missing))}", file=sys.stderr)
    raise SystemExit(64)

print(
    "\n---\n".join(
        [
            secret("qdrant-runtime", {"QDRANT_API_KEY": qdrant_api_key}),
            secret(
                "mempalace-runtime",
                {
                    "MEMPALACE_QDRANT_API_KEY": qdrant_api_key,
                    "MEMPALACE_MCP_HTTP_TOKEN": mcp_http_token,
                },
            ),
            secret(
                "memory-backup-runtime",
                {
                    "QDRANT_API_KEY": qdrant_api_key,
                    "S3_BUCKET": s3_bucket,
                    "AWS_ACCESS_KEY_ID": s3_access_key_id,
                    "AWS_SECRET_ACCESS_KEY": s3_secret_access_key,
                },
            ),
        ]
    )
)
