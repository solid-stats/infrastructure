#!/usr/bin/env python3
import json
import os
import sys
from base64 import b64encode
from urllib.parse import quote


NAMESPACE = os.environ.get("K8S_NAMESPACE", "solid-stats-staging")


def required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        missing.append(name)
        return ""
    return value


def secret(name: str, values: dict[str, str], secret_type: str = "Opaque") -> str:
    lines = [
        "apiVersion: v1",
        "kind: Secret",
        f"type: {secret_type}",
        "metadata:",
        f"  name: {name}",
        f"  namespace: {NAMESPACE}",
        "stringData:",
    ]
    for key, value in values.items():
        lines.append(f"  {key}: {json.dumps(value)}")
    return "\n".join(lines)


missing: list[str] = []

ghcr_username = required("GHCR_USERNAME")
ghcr_token = required("GHCR_TOKEN")
postgres_password = required("POSTGRES_PASSWORD")
rabbitmq_password = required("RABBITMQ_PASSWORD")
s3_bucket = required("S3_BUCKET")
s3_access_key_id = required("S3_ACCESS_KEY_ID")
s3_secret_access_key = required("S3_SECRET_ACCESS_KEY")

fetcher_replay_source_url = required("REPLAYS_FETCHER_REPLAY_SOURCE_URL")
fetcher_replay_source_transport = os.environ.get("REPLAYS_FETCHER_REPLAY_SOURCE_TRANSPORT", "direct")
fetcher_replay_source_ssh_host = os.environ.get("REPLAYS_FETCHER_REPLAY_SOURCE_SSH_HOST", "")
fetcher_replay_source_ssh_command = os.environ.get("REPLAYS_FETCHER_REPLAY_SOURCE_SSH_COMMAND", "")

if fetcher_replay_source_transport == "ssh" and not fetcher_replay_source_ssh_host:
    missing.append("REPLAYS_FETCHER_REPLAY_SOURCE_SSH_HOST")

if missing:
    print(f"Missing required environment variables: {', '.join(sorted(set(missing)))}", file=sys.stderr)
    sys.exit(64)

docker_config = json.dumps(
    {
        "auths": {
            "ghcr.io": {
                "username": ghcr_username,
                "password": ghcr_token,
                "auth": b64encode(f"{ghcr_username}:{ghcr_token}".encode()).decode(),
            }
        }
    },
    separators=(",", ":"),
)

postgres_url = f"postgres://solid:{quote(postgres_password, safe='')}@postgres:5432/solid_stats"
rabbitmq_url = f"amqp://solid:{quote(rabbitmq_password, safe='')}@rabbitmq:5672"

fetcher_runtime = {
    "DATABASE_URL": postgres_url,
    "REPLAY_SOURCE_URL": fetcher_replay_source_url,
    "REPLAY_SOURCE_TRANSPORT": fetcher_replay_source_transport,
    "S3_BUCKET": s3_bucket,
    "S3_ACCESS_KEY_ID": s3_access_key_id,
    "S3_SECRET_ACCESS_KEY": s3_secret_access_key,
}
if fetcher_replay_source_ssh_host:
    fetcher_runtime["REPLAY_SOURCE_SSH_HOST"] = fetcher_replay_source_ssh_host
if fetcher_replay_source_ssh_command:
    fetcher_runtime["REPLAY_SOURCE_SSH_COMMAND"] = fetcher_replay_source_ssh_command

documents = [
    secret("ghcr-pull", {".dockerconfigjson": docker_config}, "kubernetes.io/dockerconfigjson"),
    secret("postgres-auth", {"POSTGRES_PASSWORD": postgres_password}),
    secret("rabbitmq-auth", {"RABBITMQ_PASSWORD": rabbitmq_password}),
    secret(
        "server-2-runtime",
        {
            "DATABASE_URL": postgres_url,
            "RABBITMQ_URL": rabbitmq_url,
            "BOOTSTRAP_ADMIN_STEAM_ID": os.environ.get("SERVER2_BOOTSTRAP_ADMIN_STEAM_ID", ""),
            "S3_BUCKET": s3_bucket,
            "S3_ACCESS_KEY_ID": s3_access_key_id,
            "S3_SECRET_ACCESS_KEY": s3_secret_access_key,
        },
    ),
    secret(
        "replay-parser-2-runtime",
        {
            "REPLAY_PARSER_AMQP_URL": rabbitmq_url,
            "REPLAY_PARSER_S3_BUCKET": s3_bucket,
            "AWS_ACCESS_KEY_ID": s3_access_key_id,
            "AWS_SECRET_ACCESS_KEY": s3_secret_access_key,
        },
    ),
    secret("replays-fetcher-runtime", fetcher_runtime),
]

print("\n---\n".join(documents))
