#!/usr/bin/env python3
"""Apply and exactly roll back the SolidStats Codex MCP client policy."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat


CLIENT_NAME = "solidstats_memory"
PUBLIC_PATH = "/solidstats/mcp"
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
ENABLED_TOOLS = (
    "mempalace_search",
    "mempalace_list_rooms",
    "mempalace_list_drawers",
    "mempalace_get_drawer",
    "mempalace_check_duplicate",
    "mempalace_add_drawer",
    "mempalace_delete_drawer",
)
FORBIDDEN_TOOL_PARTS = (
    "tunnel",
    "_kg_",
    "diary",
    "checkpoint",
    "mine",
    "sync",
    "hook",
    "admin",
    "update",
    "bulk_delete",
)


class PolicyError(ValueError):
    """A secret-free client policy contract failure."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _safe_file(path: Path) -> tuple[bytes, int]:
    if not path.is_absolute():
        raise PolicyError("client config path must be absolute")
    try:
        details = path.lstat()
    except OSError as error:
        raise PolicyError("client config is unavailable") from error
    if (
        stat.S_ISLNK(details.st_mode)
        or not stat.S_ISREG(details.st_mode)
        or details.st_uid != os.getuid()
        or stat.S_IMODE(details.st_mode) & 0o077
    ):
        raise PolicyError("client config file is unsafe")
    try:
        return path.read_bytes(), stat.S_IMODE(details.st_mode)
    except OSError as error:
        raise PolicyError("client config is unavailable") from error


def _safe_private_parent(path: Path) -> None:
    if not path.is_absolute():
        raise PolicyError("client prestate path must be absolute")
    try:
        details = path.parent.lstat()
    except OSError as error:
        raise PolicyError("client prestate directory is unavailable") from error
    if (
        stat.S_ISLNK(details.st_mode)
        or not stat.S_ISDIR(details.st_mode)
        or details.st_uid != os.getuid()
        or stat.S_IMODE(details.st_mode) & 0o077
    ):
        raise PolicyError("client prestate directory is unsafe")


def _exclusive_write(path: Path, raw: bytes) -> None:
    _safe_private_parent(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    created = False
    try:
        descriptor = os.open(path, flags, 0o600)
        created = True
        with os.fdopen(descriptor, "wb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as error:
        if created:
            try:
                path.unlink()
            except OSError:
                pass
        raise PolicyError("private client state could not be written") from error


def _atomic_replace(path: Path, raw: bytes, mode: int) -> None:
    temporary = path.with_name(f".{path.name}.solidstats-memory.tmp")
    if temporary.exists() or temporary.is_symlink():
        raise PolicyError("client config temporary path already exists")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    created = False
    try:
        descriptor = os.open(temporary, flags, mode)
        created = True
        with os.fdopen(descriptor, "wb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as error:
        if created:
            try:
                temporary.unlink()
            except OSError:
                pass
        raise PolicyError("client config could not be replaced atomically") from error


def _section_bounds(raw: bytes) -> tuple[int, int]:
    exact = list(
        re.finditer(
            rb"(?m)^\[mcp_servers\.solidstats_memory\][ \t]*(?:#.*)?$",
            raw,
        )
    )
    mentions = list(
        re.finditer(
            rb"(?m)^\[[^\]\r\n]*solidstats_memory[^\]\r\n]*\]"
            rb"[ \t]*(?:#.*)?$",
            raw,
        )
    )
    if len(exact) != 1 or len(mentions) != 1:
        raise PolicyError("target client registration is missing or ambiguous")
    start = exact[0].start()
    following = re.search(rb"(?m)^\[", raw[exact[0].end() :])
    end = len(raw) if following is None else exact[0].end() + following.start()
    return start, end


def _parse_basic_string(section: bytes, key: bytes) -> str:
    matches = list(
        re.finditer(
            rb"(?m)^"
            + re.escape(key)
            + rb"[ \t]*=[ \t]*(\"(?:[^\"\\]|\\.)*\")"
            + rb"[ \t]*(?:#.*)?$",
            section,
        )
    )
    if len(matches) != 1:
        raise PolicyError("target client registration is missing or drifted")
    try:
        value = json.loads(matches[0].group(1).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PolicyError("target client registration is malformed") from error
    if not isinstance(value, str):
        raise PolicyError("target client registration is malformed")
    return value


def _validate_url(url: str) -> None:
    from urllib.parse import urlsplit

    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != PUBLIC_PATH
        or parsed.query
        or parsed.fragment
    ):
        raise PolicyError("target client URL is invalid")


def inspect_policy(
    raw: bytes, *, url: str, token_env: str, require_policy: bool
) -> tuple[int, int]:
    _validate_url(url)
    if not ENV_NAME.fullmatch(token_env):
        raise PolicyError("target client token environment name is invalid")
    start, end = _section_bounds(raw)
    section = raw[start:end]
    if _parse_basic_string(section, b"url") != url:
        raise PolicyError("target client URL is drifted")
    if _parse_basic_string(section, b"bearer_token_env_var") != token_env:
        raise PolicyError("target client token binding is drifted")
    enabled = list(re.finditer(rb"(?m)^enabled_tools[ \t]*=[ \t]*(.+)$", section))
    disabled = list(re.finditer(rb"(?m)^disabled_tools[ \t]*=", section))
    if disabled or len(enabled) > 1:
        raise PolicyError("target client has a conflicting tool policy")
    if require_policy:
        if len(enabled) != 1:
            raise PolicyError("target client tool allowlist is missing")
        try:
            observed = json.loads(enabled[0].group(1).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PolicyError("target client tool allowlist is malformed") from error
        if observed != list(ENABLED_TOOLS):
            raise PolicyError("target client tool allowlist is drifted")
        if any(part in tool for tool in observed for part in FORBIDDEN_TOOL_PARTS):
            raise PolicyError("target client tool allowlist exposes a forbidden capability")
    elif enabled:
        raise PolicyError("target client already has a tool policy")
    return start, end


def capture(config: Path, prestate: Path) -> None:
    raw, _ = _safe_file(config)
    if prestate.exists() and not prestate.is_symlink():
        previous, _ = _safe_file(prestate)
        if previous != raw:
            raise PolicyError("client config prestate already exists with different bytes")
        return
    _exclusive_write(prestate, raw)


def apply(config: Path, prestate: Path, *, url: str, token_env: str) -> None:
    raw, mode = _safe_file(config)
    _safe_file(prestate)
    start, end = inspect_policy(raw, url=url, token_env=token_env, require_policy=False)
    section = raw[start:end]
    newline = b"\r\n" if b"\r\n" in section else b"\n"
    line = (
        b"enabled_tools = "
        + json.dumps(list(ENABLED_TOOLS), separators=(",", ":")).encode("ascii")
        + newline
    )
    if not section.endswith((b"\n", b"\r")):
        line = newline + line
    updated = raw[:end] + line + raw[end:]
    metadata = prestate.with_suffix(prestate.suffix + ".policy.json")
    metadata_raw = json.dumps(
        {
            "schema": "solidstats-memory-client-policy/v1",
            "accepted_sha256": [_sha256(raw), _sha256(updated)],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii") + b"\n"
    if metadata.exists() and not metadata.is_symlink():
        previous_metadata, _ = _safe_file(metadata)
        if previous_metadata != metadata_raw:
            raise PolicyError("client policy rollback metadata is drifted")
    else:
        _exclusive_write(metadata, metadata_raw)
    _atomic_replace(config, updated, mode)
    observed, _ = _safe_file(config)
    if observed != updated:
        raise PolicyError("client config policy read-back failed")
    inspect_policy(observed, url=url, token_env=token_env, require_policy=True)


def validate(config: Path, *, url: str, token_env: str) -> None:
    raw, _ = _safe_file(config)
    inspect_policy(raw, url=url, token_env=token_env, require_policy=True)


def rollback(config: Path, prestate: Path) -> None:
    current, mode = _safe_file(config)
    original, _ = _safe_file(prestate)
    accepted = {_sha256(original)}
    metadata = prestate.with_suffix(prestate.suffix + ".policy.json")
    if metadata.exists() and not metadata.is_symlink():
        raw_metadata, _ = _safe_file(metadata)
        try:
            decoded = json.loads(raw_metadata)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PolicyError("client policy rollback metadata is malformed") from error
        if decoded.get("schema") != "solidstats-memory-client-policy/v1" or not isinstance(
            decoded.get("accepted_sha256"), list
        ):
            raise PolicyError("client policy rollback metadata is malformed")
        digests = decoded["accepted_sha256"]
        if any(
            not isinstance(item, str) or re.fullmatch(r"[0-9a-f]{64}", item) is None
            for item in digests
        ):
            raise PolicyError("client policy rollback metadata is malformed")
        accepted.update(digests)
    if _sha256(current) not in accepted:
        raise PolicyError("client config drift prevents exact rollback")
    if current != original:
        _atomic_replace(config, original, mode)
    restored, _ = _safe_file(config)
    if restored != original:
        raise PolicyError("client config exact rollback failed")


def authorize_current(config: Path, prestate: Path) -> None:
    raw, _ = _safe_file(config)
    metadata = prestate.with_suffix(prestate.suffix + ".policy.json")
    current, mode = _safe_file(metadata)
    decoded = json.loads(current)
    accepted = decoded.get("accepted_sha256")
    if not isinstance(accepted, list) or not all(isinstance(item, str) for item in accepted):
        raise PolicyError("client policy rollback metadata is malformed")
    digest = _sha256(raw)
    if digest not in accepted:
        accepted.append(digest)
    updated = json.dumps(decoded, separators=(",", ":"), sort_keys=True).encode("ascii") + b"\n"
    _atomic_replace(metadata, updated, mode)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("capture", "apply", "validate", "rollback", "authorize-current"))
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--prestate", type=Path)
    parser.add_argument("--name", default=CLIENT_NAME)
    parser.add_argument("--url")
    parser.add_argument("--token-env")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.name != CLIENT_NAME:
            raise PolicyError("target client name is invalid")
        if args.command in {"capture", "apply", "rollback", "authorize-current"} and args.prestate is None:
            raise PolicyError("client config prestate path is required")
        if args.command in {"apply", "validate"} and (
            args.url is None or args.token_env is None
        ):
            raise PolicyError("target client binding is required")
        if args.command == "capture":
            capture(args.config, args.prestate)
        elif args.command == "authorize-current":
            authorize_current(args.config, args.prestate)
        elif args.command == "apply":
            apply(args.config, args.prestate, url=args.url, token_env=args.token_env)
        elif args.command == "validate":
            validate(args.config, url=args.url, token_env=args.token_env)
        else:
            rollback(args.config, args.prestate)
        print(f"PASS: client policy {args.command} completed")
        return 0
    except (OSError, PolicyError) as error:
        print(f"FAIL: {error}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
