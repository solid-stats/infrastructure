#!/usr/bin/env python3
"""Probe the authenticated SolidStats MemPalace Streamable HTTP contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import tempfile
from typing import Callable, Mapping, Protocol
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request


PROTOCOL_VERSION = "2025-06-18"
MAX_BODY_BYTES = 4 * 1024 * 1024
SHA256 = re.compile(r"^[0-9a-f]{64}$")
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
SAFE_CODE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
CLIENT_NAME = "solidstats_memory"
PUBLIC_PATH = "/solidstats/mcp"
REQUIRED_TOOLS = (
    "mempalace_search",
    "mempalace_list_rooms",
    "mempalace_list_drawers",
    "mempalace_get_drawer",
    "mempalace_check_duplicate",
    "mempalace_add_drawer",
    "mempalace_delete_drawer",
)
EVIDENCE_KEYS = {
    "archive_untrusted",
    "auth_checks",
    "capture_shape_valid",
    "cleanup_exact",
    "cleanup_supported",
    "dedup_checked",
    "invalid_rejected",
    "mcp_checks",
    "missing_rejected",
    "private_boundary",
    "protocol_version_match",
    "qdrant_6333_blocked",
    "qdrant_6334_blocked",
    "read_back_verified",
    "required_tool_count",
    "schema_digest_recorded",
    "schema_sha256",
    "scoped_recall",
    "semantic_miss_fallback",
    "session_contract",
    "session_propagated",
    "tool_count",
    "untrusted_origin_rejected",
    "valid_accepted",
}


class ProbeError(ValueError):
    """A value-free probe contract failure."""


class HttpProbeResult:
    """Bounded internal HTTP result; raw bodies never enter evidence."""

    def __init__(
        self,
        status: int,
        headers: Mapping[str, str],
        payload: object | None,
        body_sha256: str,
    ) -> None:
        self.status = status
        self.headers = {str(key).lower(): str(value) for key, value in headers.items()}
        self.payload = payload
        self.body_sha256 = body_sha256


class Transport(Protocol):
    def request(
        self,
        message: dict[str, object],
        *,
        session_id: str | None,
        token_mode: str,
        protocol_version: str | None,
    ) -> HttpProbeResult: ...


class McpSession:
    """One negotiated stateless or sessionful MCP connection."""

    def __init__(
        self,
        transport: Transport,
        *,
        session_id: str | None,
        protocol_version: str,
    ) -> None:
        self.transport = transport
        self.session_id = session_id
        self.protocol_version = protocol_version
        self.next_id = 2


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ProbeError("probe request is not canonical JSON") from error


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _decode_payload(raw: bytes, *, expected_id: object | None) -> object | None:
    if not raw:
        return None
    candidates = [raw]
    candidates.extend(
        line[5:].strip()
        for line in raw.splitlines()
        if line.startswith(b"data:") and line[5:].strip()
    )
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(value, Mapping) or value.get("jsonrpc") != "2.0":
            continue
        if expected_id is None or value.get("id") == expected_id:
            return value
    raise ProbeError("MCP response is malformed")


def _validate_url(url: str) -> str:
    parsed = urllib_parse.urlsplit(url)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != PUBLIC_PATH
        or parsed.query
        or parsed.fragment
    ):
        raise ProbeError("public MCP URL is invalid")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ProbeError("public MCP URL must use TLS")
    return url


class StreamableHttpTransport:
    """Standard-library MCP Streamable HTTP transport with bounded raw storage."""

    def __init__(
        self,
        url: str,
        token: str,
        *,
        opener: Callable[..., object] = urllib_request.urlopen,
        timeout: float = 30.0,
        raw_root: Path | None = None,
    ) -> None:
        self.url = _validate_url(url)
        if not isinstance(token, str) or not token or "\n" in token or "\r" in token:
            raise ProbeError("valid bearer token is unavailable")
        if not isinstance(timeout, (int, float)) or timeout <= 0 or not math.isfinite(timeout):
            raise ProbeError("probe timeout is invalid")
        self.token = token
        self.opener = opener
        self.timeout = float(timeout)
        self.raw_root = Path(raw_root) if raw_root is not None else None
        if self.raw_root is not None:
            try:
                details = self.raw_root.lstat()
            except OSError as error:
                raise ProbeError("private raw storage is unavailable") from error
            if (
                stat.S_ISLNK(details.st_mode)
                or not stat.S_ISDIR(details.st_mode)
                or stat.S_IMODE(details.st_mode) & 0o077
            ):
                raise ProbeError("private raw storage is unsafe")

    def request(
        self,
        message: dict[str, object],
        *,
        session_id: str | None,
        token_mode: str,
        protocol_version: str | None,
    ) -> HttpProbeResult:
        if token_mode not in {"missing", "invalid", "untrusted-origin", "valid"}:
            raise ProbeError("auth probe mode is invalid")
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if token_mode == "invalid":
            headers["Authorization"] = "Bearer phase21-invalid-probe"
        elif token_mode in {"untrusted-origin", "valid"}:
            headers["Authorization"] = f"Bearer {self.token}"
        if token_mode == "untrusted-origin":
            headers["Origin"] = "https://phase21-untrusted.invalid"
        if session_id is not None:
            if not session_id.isascii() or not session_id.isprintable():
                raise ProbeError("MCP session contract is invalid")
            headers["Mcp-Session-Id"] = session_id
        if protocol_version is not None:
            headers["MCP-Protocol-Version"] = protocol_version
        request = urllib_request.Request(
            self.url,
            data=_canonical(message),
            headers=headers,
            method="POST",
        )
        status: int
        response_headers: Mapping[str, str]
        raw: bytes
        try:
            with self.opener(request, timeout=self.timeout) as response:
                status = int(response.status)
                response_headers = dict(response.headers.items())
                raw = response.read(MAX_BODY_BYTES + 1)
        except urllib_error.HTTPError as error:
            status = int(error.code)
            response_headers = dict(error.headers.items()) if error.headers else {}
            try:
                raw = error.read(MAX_BODY_BYTES + 1)
            finally:
                error.close()
        except (OSError, TimeoutError, socket.timeout, urllib_error.URLError) as error:
            raise ProbeError("public MCP request failed") from error
        if len(raw) > MAX_BODY_BYTES:
            raise ProbeError("public MCP response exceeds its bound")
        content_type = next(
            (
                str(value).split(";", 1)[0].strip().lower()
                for key, value in response_headers.items()
                if str(key).lower() == "content-type"
            ),
            "",
        )
        if status == 200:
            if content_type not in {"application/json", "text/event-stream"}:
                raise ProbeError("public MCP response content type is invalid")
            if not raw:
                raise ProbeError("MCP response is malformed")
        forbidden_echoes = (
            self.token.encode("utf-8"),
            b"phase21-invalid-probe",
        )
        header_bytes = "\n".join(
            f"{key}:{value}" for key, value in response_headers.items()
        ).encode("utf-8", errors="replace")
        if any(value and (value in raw or value in header_bytes) for value in forbidden_echoes):
            raise ProbeError("public MCP response echoed authorization material")
        body_sha256 = hashlib.sha256(raw).hexdigest()
        expected_id = message.get("id")
        with tempfile.TemporaryDirectory(
            prefix="solidstats-mcp-probe-", dir=self.raw_root
        ) as temporary:
            directory = Path(temporary)
            os.chmod(directory, 0o700)
            raw_path = directory / "response.bin"
            descriptor = os.open(
                raw_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            with os.fdopen(descriptor, "wb") as output:
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
            stored_raw = raw_path.read_bytes()
            if status == 200:
                payload = _decode_payload(stored_raw, expected_id=expected_id)
            else:
                try:
                    payload = _decode_payload(stored_raw, expected_id=expected_id)
                except ProbeError:
                    payload = None
        return HttpProbeResult(status, response_headers, payload, body_sha256)


def http_probe(
    transport: Transport,
    message: Mapping[str, object],
    *,
    session_id: str | None = None,
    token_mode: str = "valid",
    protocol_version: str | None = None,
) -> HttpProbeResult:
    """Send one bounded MCP POST through the injected transport."""
    result = transport.request(
        dict(message),
        session_id=session_id,
        token_mode=token_mode,
        protocol_version=protocol_version,
    )
    if not isinstance(result, HttpProbeResult):
        raise ProbeError("MCP transport contract is invalid")
    if not SHA256.fullmatch(result.body_sha256):
        raise ProbeError("MCP response digest is invalid")
    return result


def _initialize_message(request_id: int = 1) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "initialize",
        "params": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "phase21-cutover-probe", "version": "1"},
        },
    }


def mcp_initialize(transport: Transport) -> McpSession:
    """Negotiate MCP, preserve a returned session, and send initialized."""
    initialized = http_probe(
        transport, _initialize_message(), token_mode="valid"
    )
    if initialized.status != 200 or not isinstance(initialized.payload, Mapping):
        raise ProbeError("MCP initialization failed")
    if "error" in initialized.payload:
        raise ProbeError("MCP initialization failed")
    result = initialized.payload.get("result")
    if not isinstance(result, Mapping):
        raise ProbeError("MCP initialization result is invalid")
    protocol_version = result.get("protocolVersion")
    capabilities = result.get("capabilities")
    if protocol_version != PROTOCOL_VERSION or not isinstance(capabilities, Mapping):
        raise ProbeError("MCP protocol negotiation failed")
    if not isinstance(capabilities.get("tools"), Mapping):
        raise ProbeError("MCP tools capability is unavailable")
    session_id = initialized.headers.get("mcp-session-id")
    session = McpSession(
        transport,
        session_id=session_id,
        protocol_version=protocol_version,
    )
    notification = http_probe(
        transport,
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        session_id=session_id,
        token_mode="valid",
        protocol_version=protocol_version,
    )
    if notification.status not in {200, 202, 204}:
        raise ProbeError("MCP initialized notification failed")
    return session


def _mcp_request(
    session: McpSession, method: str, params: Mapping[str, object]
) -> Mapping[str, object]:
    request_id = session.next_id
    session.next_id += 1
    response = http_probe(
        session.transport,
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": dict(params),
        },
        session_id=session.session_id,
        token_mode="valid",
        protocol_version=session.protocol_version,
    )
    if response.status != 200 or not isinstance(response.payload, Mapping):
        raise ProbeError("MCP request failed")
    if response.payload.get("id") != request_id or "error" in response.payload:
        raise ProbeError("MCP response contract is invalid")
    result = response.payload.get("result")
    if not isinstance(result, Mapping):
        raise ProbeError("MCP result contract is invalid")
    return result


def mcp_list_tools(session: McpSession) -> dict[str, object]:
    """List every tool page and retain schemas only in process memory."""
    tools: dict[str, object] = {}
    cursor: str | None = None
    for _page in range(20):
        params: dict[str, object] = {}
        if cursor is not None:
            params["cursor"] = cursor
        result = _mcp_request(session, "tools/list", params)
        listed = result.get("tools")
        if not isinstance(listed, list):
            raise ProbeError("MCP tool list is invalid")
        for item in listed:
            if not isinstance(item, Mapping):
                raise ProbeError("MCP tool list is invalid")
            name = item.get("name")
            schema = item.get("inputSchema")
            if not isinstance(name, str) or not isinstance(schema, Mapping) or name in tools:
                raise ProbeError("MCP tool list is invalid")
            tool_schema: dict[str, object] = {"inputSchema": dict(schema)}
            output_schema = item.get("outputSchema")
            if output_schema is not None:
                if not isinstance(output_schema, Mapping):
                    raise ProbeError("MCP tool list is invalid")
                tool_schema["outputSchema"] = dict(output_schema)
            tools[name] = tool_schema
        next_cursor = result.get("nextCursor")
        if next_cursor is None:
            return tools
        if not isinstance(next_cursor, str) or not next_cursor:
            raise ProbeError("MCP tool cursor is invalid")
        cursor = next_cursor
    raise ProbeError("MCP tool pagination exceeded its bound")


def mcp_call(
    session: McpSession, tool_name: str, arguments: Mapping[str, object]
) -> Mapping[str, object]:
    """Call one exact tool and reject protocol-level or tool-level errors."""
    if not isinstance(tool_name, str) or not tool_name:
        raise ProbeError("MCP tool name is invalid")
    result = _mcp_request(
        session,
        "tools/call",
        {"name": tool_name, "arguments": dict(arguments)},
    )
    if result.get("isError") is True:
        raise ProbeError("MCP tool call failed")
    return result


def _tool_data(result: Mapping[str, object]) -> Mapping[str, object]:
    structured = result.get("structuredContent")
    if isinstance(structured, Mapping):
        return structured
    content = result.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, Mapping) or item.get("type") != "text":
                continue
            text = item.get("text")
            if not isinstance(text, str):
                continue
            try:
                decoded = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(decoded, Mapping):
                return decoded
    raise ProbeError("MCP tool result is not structured")


def _first_drawer_id(value: object) -> str | None:
    if isinstance(value, Mapping):
        for key in ("drawer_id", "id"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
        for item in value.values():
            found = _first_drawer_id(item)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _first_drawer_id(item)
            if found is not None:
                return found
    return None


def _capture_shape(content: str) -> bool:
    return all(
        f"{field}:" in content
        for field in ("Task", "Outcome", "Decisions", "Validation", "Sources")
    )


def probe_auth_matrix(transport: Transport) -> tuple[dict[str, object], McpSession]:
    """Require missing/invalid rejection and a valid initialized session."""
    statuses: dict[str, int] = {}
    for mode in ("missing", "invalid", "untrusted-origin"):
        result = http_probe(transport, _initialize_message(), token_mode=mode)
        statuses[mode] = result.status
    if (
        statuses["missing"] not in {401, 403}
        or statuses["invalid"] not in {401, 403}
        or statuses["untrusted-origin"] not in {400, 403}
    ):
        raise ProbeError("public MCP auth rejection failed")
    session = mcp_initialize(transport)
    return (
        {
            "missing_rejected": True,
            "invalid_rejected": True,
            "untrusted_origin_rejected": True,
            "valid_accepted": True,
            "protocol_version_match": True,
            "session_contract": "sessionful" if session.session_id else "stateless",
            "session_propagated": True,
        },
        session,
    )


def probe_private_boundary(
    hostname: str,
    *,
    connector: Callable[..., object] = socket.create_connection,
    timeout: float = 2.0,
) -> dict[str, object]:
    """Require both public Qdrant ports to reject TCP connections."""
    if not isinstance(hostname, str) or not hostname or any(
        character.isspace() for character in hostname
    ):
        raise ProbeError("public boundary host is invalid")
    blocked: dict[int, bool] = {}
    for port in (6333, 6334):
        try:
            connection = connector((hostname, port), timeout=timeout)
        except OSError:
            blocked[port] = True
        else:
            blocked[port] = False
            try:
                connection.close()
            except OSError:
                pass
    if not all(blocked.values()):
        raise ProbeError("Qdrant is publicly reachable")
    return {
        "qdrant_6333_blocked": True,
        "qdrant_6334_blocked": True,
    }


def probe_behavior_matrix(
    session: McpSession,
    tools: Mapping[str, object],
    *,
    wing: str,
    archive_wing: str,
    synthetic_content: str,
) -> dict[str, object]:
    """Exercise scoped recall, fallback, archive, capture, and exact cleanup."""
    if any(name not in tools for name in REQUIRED_TOOLS):
        raise ProbeError("required MCP tool is unavailable")
    if not _capture_shape(synthetic_content):
        raise ProbeError("synthetic capture shape is invalid")
    schema_digest = _digest({name: tools[name] for name in REQUIRED_TOOLS})

    _tool_data(
        mcp_call(
            session,
            "mempalace_search",
            {"query": "phase21 cutover", "wing": wing, "limit": 1},
        )
    )
    _tool_data(
        mcp_call(
            session,
            "mempalace_search",
            {"query": "phase21 semantic miss fixture", "wing": wing, "limit": 1},
        )
    )
    _tool_data(mcp_call(session, "mempalace_list_rooms", {"wing": wing}))
    fallback = _tool_data(
        mcp_call(
            session,
            "mempalace_list_drawers",
            {"wing": wing, "limit": 1, "offset": 0},
        )
    )
    fallback_id = _first_drawer_id(fallback)
    if fallback_id is not None:
        _tool_data(
            mcp_call(
                session, "mempalace_get_drawer", {"drawer_id": fallback_id}
            )
        )
    _tool_data(
        mcp_call(
            session,
            "mempalace_search",
            {"query": "phase21 historical lead", "wing": archive_wing, "limit": 1},
        )
    )
    _tool_data(
        mcp_call(
            session,
            "mempalace_check_duplicate",
            {"content": synthetic_content, "threshold": 0.9},
        )
    )
    created = _tool_data(
        mcp_call(
            session,
            "mempalace_add_drawer",
            {
                "wing": wing,
                "room": "migrations",
                "content": synthetic_content,
                "added_by": "phase21-cutover-probe",
            },
        )
    )
    drawer_id = _first_drawer_id(created)
    if drawer_id is None:
        raise ProbeError("synthetic capture did not return an exact ID")
    read_back = _tool_data(
        mcp_call(session, "mempalace_get_drawer", {"drawer_id": drawer_id})
    )
    if read_back.get("content") != synthetic_content:
        raise ProbeError("synthetic capture read-back failed")
    deleted = _tool_data(
        mcp_call(
            session, "mempalace_delete_drawer", {"drawer_id": drawer_id}
        )
    )
    cleanup_exact = deleted.get("deleted") is True
    if not cleanup_exact:
        raise ProbeError("synthetic capture cleanup failed")
    return {
        "tool_count": len(tools),
        "required_tool_count": len(REQUIRED_TOOLS),
        "schema_sha256": schema_digest,
        "schema_digest_recorded": True,
        "scoped_recall": True,
        "semantic_miss_fallback": True,
        "archive_untrusted": True,
        "dedup_checked": True,
        "capture_shape_valid": True,
        "read_back_verified": True,
        "cleanup_supported": True,
        "cleanup_exact": True,
    }


def build_client_commands(
    *, name: str, url: str, token_env: str
) -> dict[str, tuple[str, ...]]:
    """Build only the exact `solidstats_memory` add/get/remove commands."""
    if name != CLIENT_NAME:
        raise ProbeError("client name is invalid")
    url = _validate_url(url)
    if not isinstance(token_env, str) or not ENV_NAME.fullmatch(token_env):
        raise ProbeError("client token environment name is invalid")
    return {
        "add": (
            "codex",
            "mcp",
            "add",
            CLIENT_NAME,
            "--url",
            url,
            "--bearer-token-env-var",
            token_env,
        ),
        "get": ("codex", "mcp", "get", CLIENT_NAME),
        "remove": ("codex", "mcp", "remove", CLIENT_NAME),
    }


def probe_client_policy(
    *, config: Path, url: str, token_env: str, policy_script: Path | None = None
) -> None:
    """Validate the exact effective allowlist in the machine-local client config."""
    script = policy_script or Path(__file__).with_name(
        "configure-solidstats-memory-client.py"
    )
    result = subprocess.run(
        (
            os.sys.executable,
            str(script),
            "validate",
            "--config",
            str(config),
            "--name",
            CLIENT_NAME,
            "--url",
            _validate_url(url),
            "--token-env",
            token_env,
        ),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise ProbeError("client tool policy validation failed")


def _validate_evidence_node(value: object, *, key: str = "root", depth: int = 0) -> None:
    if depth > 8:
        raise ProbeError("probe evidence nesting is invalid")
    if isinstance(value, Mapping):
        for child_key, child in value.items():
            if not isinstance(child_key, str) or child_key not in EVIDENCE_KEYS:
                raise ProbeError("probe evidence field is invalid")
            _validate_evidence_node(child, key=child_key, depth=depth + 1)
        return
    if isinstance(value, bool):
        return
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return
    if isinstance(value, str):
        if key.endswith("sha256") and SHA256.fullmatch(value):
            return
        if key == "session_contract" and value in {"stateless", "sessionful"}:
            return
        if key.endswith("code") and SAFE_CODE.fullmatch(value):
            return
    raise ProbeError("probe evidence contains a private or unsupported value")


def validate_probe_evidence(evidence: Mapping[str, object]) -> None:
    """Recursively reject non-aggregate evidence and private-value surfaces."""
    _validate_evidence_node(evidence)


def write_probe_evidence(path: Path, evidence: Mapping[str, object]) -> None:
    """Write validated aggregate evidence atomically with mode 0600."""
    validate_probe_evidence(evidence)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    raw = _canonical(evidence) + b"\n"
    temporary = path.with_name(f".{path.name}.tmp")
    if path.exists() or path.is_symlink() or temporary.exists() or temporary.is_symlink():
        raise ProbeError("probe evidence destination already exists")
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    except OSError as error:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise ProbeError("probe evidence could not be written") from error


def _synthetic_content(run_id: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{7,63}", run_id):
        raise ProbeError("probe run identity is invalid")
    return (
        f"Task: {run_id}\n"
        "Outcome: disposable cutover behavior probe\n"
        "Decisions: exact-id cleanup required\n"
        "Validation: authenticated read-back\n"
        "Sources: phase-21-cutover-probe"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    full = subparsers.add_parser("full")
    full.add_argument("--url", required=True)
    full.add_argument("--token-env", required=True)
    full.add_argument("--run-id", required=True)
    full.add_argument("--wing", default="infrastructure")
    full.add_argument("--archive-wing", default="infrastructure-archive")
    full.add_argument("--evidence", type=Path)
    full.add_argument("--raw-root", type=Path)
    boundary = subparsers.add_parser("private-boundary")
    boundary.add_argument("--host", required=True)
    client_policy = subparsers.add_parser("client-policy")
    client_policy.add_argument("--config", required=True, type=Path)
    client_policy.add_argument("--url", required=True)
    client_policy.add_argument("--token-env", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one requested probe and print a single value-free result line."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        if args.command == "private-boundary":
            probe_private_boundary(args.host)
            print("PASS: private boundary probe completed")
            return 0
        if args.command == "client-policy":
            probe_client_policy(
                config=args.config,
                url=args.url,
                token_env=args.token_env,
            )
            print("PASS: client tool policy probe completed")
            return 0
        if not ENV_NAME.fullmatch(args.token_env):
            raise ProbeError("token environment name is invalid")
        token = os.environ.get(args.token_env)
        if not token:
            raise ProbeError("valid bearer token is unavailable")
        transport = StreamableHttpTransport(
            args.url, token, raw_root=args.raw_root
        )
        auth, session = probe_auth_matrix(transport)
        tools = mcp_list_tools(session)
        behavior = probe_behavior_matrix(
            session,
            tools,
            wing=args.wing,
            archive_wing=args.archive_wing,
            synthetic_content=_synthetic_content(args.run_id),
        )
        evidence = {"auth_checks": auth, "mcp_checks": behavior}
        validate_probe_evidence(evidence)
        if args.evidence is not None:
            write_probe_evidence(args.evidence, evidence)
        print("PASS: authenticated MCP behavior probe completed")
        return 0
    except (OSError, ProbeError) as error:
        print(f"FAIL: {error}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
