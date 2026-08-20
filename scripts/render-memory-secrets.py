#!/usr/bin/env python3
"""Render SolidStats-memory secrets from deploy-time environment variables."""

import base64
import hashlib
import hmac
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


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def jwt(secret_value: str, payload: dict[str, object]) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    segments = [
        b64url(json.dumps(part, sort_keys=True, separators=(",", ":")).encode())
        for part in (header, payload)
    ]
    signing_input = ".".join(segments).encode("ascii")
    signature = hmac.new(secret_value.encode(), signing_input, hashlib.sha256).digest()
    return ".".join((*segments, b64url(signature)))


qdrant_api_key = required("MEMORY_QDRANT_API_KEY")
qdrant_collection = required("MEMORY_QDRANT_COLLECTION")
mcp_http_token = required("MEMORY_MCP_HTTP_TOKEN")
s3_bucket = required("S3_BUCKET")
s3_access_key_id = required("S3_ACCESS_KEY_ID")
s3_secret_access_key = required("S3_SECRET_ACCESS_KEY")

if missing:
    print(f"Missing required environment variables: {', '.join(sorted(missing))}", file=sys.stderr)
    raise SystemExit(64)

collection_access = [{"collection": qdrant_collection, "access": "rw"}]
mempalace_qdrant_token = jwt(
    qdrant_api_key, {"sub": "solidstats-memory-mempalace", "access": collection_access}
)
backup_qdrant_token = jwt(
    qdrant_api_key, {"sub": "solidstats-memory-backup", "access": collection_access}
)
observer_qdrant_token = jwt(
    qdrant_api_key,
    {
        "sub": "solidstats-memory-observer",
        "access": [{"collection": qdrant_collection, "access": "r"}],
    },
)

print(
    "\n---\n".join(
        [
            secret("qdrant-runtime", {"QDRANT_API_KEY": qdrant_api_key}),
            secret(
                "mempalace-runtime",
                {
                    "MEMPALACE_QDRANT_API_KEY": mempalace_qdrant_token,
                    "MEMPALACE_MCP_HTTP_TOKEN": mcp_http_token,
                },
            ),
            secret(
                "memory-backup-runtime",
                {
                    "QDRANT_API_KEY": backup_qdrant_token,
                    "S3_BUCKET": s3_bucket,
                    "AWS_ACCESS_KEY_ID": s3_access_key_id,
                    "AWS_SECRET_ACCESS_KEY": s3_secret_access_key,
                },
            ),
            secret(
                "memory-observer-runtime",
                {"QDRANT_API_KEY": observer_qdrant_token},
            ),
        ]
    )
)
