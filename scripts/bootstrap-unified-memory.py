#!/usr/bin/env python3
"""Validate target-specific MemPalace state and exercise disposable MCP writes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid
from urllib import request

from unified_memory_recovery import bindings, Qdrant


def validate_alias_bindings(config, observer):
    aliases = {binding["alias_name"]: binding["collection_name"] for row in bindings(config)
               for binding in observer.call("GET", "/collections/" + row["physical"] + "/aliases")["aliases"]}
    if any(aliases.get(row["alias"]) != row["physical"] for row in bindings(config)):
        raise ValueError("remote alias binding differs")

def validate(config, palace):
    from mempalace.backends.base import PalaceRef
    from mempalace.backends.qdrant import QdrantBackend, _QdrantConfig
    palace = Path(palace)
    reference = PalaceRef(id=str(palace), local_path=str(palace))
    backend = QdrantBackend()
    options = _QdrantConfig.from_options({"url": config["qdrantUrl"], "namespace": config["qdrantNamespace"],
                                         "api_key": os.environ["MEMPALACE_QDRANT_API_KEY"]})
    backend._validate_marker_target(reference, options)
    client = Qdrant(config["qdrantUrl"], os.environ["MEMPALACE_QDRANT_API_KEY"])
    observer = Qdrant(config["qdrantUrl"], os.environ["UNIFIED_OBSERVER_API_KEY"])
    validate_alias_bindings(config, observer)
    for row in bindings(config):
        expected = backend._remote_collection_name(palace=reference, collection_name=row["logicalName"], config=options)
        if row["alias"] != expected:
            raise ValueError("deterministic alias binding differs")
        identity = backend._get_embedder_identity(reference, row["logicalName"])
        if identity is None or identity.model_name != "embeddinggemma" or identity.dimension != row["dimension"]:
            raise ValueError("stored embedder identity differs")
        info = client.call("GET", "/collections/" + row["alias"])
        if any(info["config"]["params"]["vectors"].get(key) != value for key, value in {"size": row["dimension"], "distance": row["distance"]}.items()):
            raise ValueError("runtime collection configuration differs")
    # Exact image/cache acceptance: first real model inference, no download or re-embed.
    from mempalace.embedding import get_embedding_function
    vector = get_embedding_function(device="cpu", model="embeddinggemma")(input=["Unified memory startup"])
    if len(vector) != 1 or len(vector[0]) != 384:
        raise ValueError("offline embedding cache unavailable")


def probe(config):
    token = os.environ["MEMPALACE_MCP_HTTP_TOKEN"]
    session = None
    sequence = 0
    def call(method, params):
        nonlocal session, sequence
        sequence += 1
        body = json.dumps({"jsonrpc": "2.0", "id": sequence, "method": method, "params": params}).encode()
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "Authorization": "Bearer " + token}
        if session:
            headers.update({"Mcp-Session-Id": session, "MCP-Protocol-Version": "2025-06-18"})
        operation = request.Request("http://127.0.0.1:8765/mcp", data=body, headers=headers, method="POST")
        with request.urlopen(operation, timeout=90) as response:
            raw = response.read(2 * 1024 * 1024)
            session = session or response.headers.get("Mcp-Session-Id")
        if raw.startswith(b"data:"):
            raw = next(line[5:].strip() for line in raw.splitlines() if line.startswith(b"data:"))
        result = json.loads(raw)
        if "error" in result or result.get("id") != sequence:
            raise ValueError("MCP protocol failure")
        result = result["result"]
        if result.get("isError"):
            raise ValueError("MCP tool failure")
        return result
    def tool(name, arguments):
        result = call("tools/call", {"name": name, "arguments": arguments})
        if isinstance(result.get("structuredContent"), dict):
            return result["structuredContent"]
        return json.loads(next(row["text"] for row in result["content"] if row["type"] == "text"))
    initialized = call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "unified-backup-oracle", "version": "1"}})
    if initialized.get("protocolVersion") != "2025-06-18":
        raise ValueError("MCP negotiation failure")
    nonce = uuid.uuid4().hex
    marker = "unified-backup-oracle:" + nonce
    created = tool("mempalace_add_drawer", {"wing": config["probeWing"], "room": "uat-" + nonce, "content": marker, "added_by": "backup-oracle"})
    identifier = created.get("drawer_id") or created.get("id")
    if not isinstance(identifier, str) or not identifier:
        raise ValueError("probe capture failed")
    try:
        if tool("mempalace_get_drawer", {"drawer_id": identifier}).get("content") != marker:
            raise ValueError("probe read-back failed")
    finally:
        deleted = tool("mempalace_delete_drawer", {"drawer_id": identifier})
        if deleted.get("success") is not True or deleted.get("drawer_id") != identifier or not deleted.get("deleted_ids"):
            raise ValueError("probe exact cleanup failed")
    if tool("mempalace_get_drawer", {"drawer_id": identifier}) != {"error": "Drawer not found: " + identifier}:
        raise ValueError("probe absence failed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("validate", "probe"))
    parser.add_argument("--bindings", type=Path, required=True)
    parser.add_argument("--palace", default="/data/palace")
    args = parser.parse_args()
    config = json.loads(args.bindings.read_text())
    if args.operation == "validate":
        validate(config, args.palace)
    else:
        probe(config)
    print("PASS: unified runtime " + args.operation)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("FAIL: unified runtime validation", file=sys.stderr)
        raise SystemExit(1)
