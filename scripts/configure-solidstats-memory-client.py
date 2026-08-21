#!/usr/bin/env python3
"""Apply and exactly roll back the SolidStats Codex MCP client policy."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import functools
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tomllib
from typing import Callable


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


_HELD_CONFIG_LOCKS: dict[Path, tuple[int, int]] = {}


@contextmanager
def _client_config_lock(config: Path):
    """Serialize every participating config writer with durable ownership."""
    config = config.resolve(strict=True)
    held = _HELD_CONFIG_LOCKS.get(config)
    if held is not None:
        _HELD_CONFIG_LOCKS[config] = (held[0], held[1] + 1)
        try:
            yield
        finally:
            _HELD_CONFIG_LOCKS[config] = (held[0], held[1])
        return
    lock_path = config.with_name(f".{config.name}.solidstats-memory.lock")
    descriptor = os.open(
        lock_path,
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_uid != os.getuid()
            or stat.S_IMODE(details.st_mode) & 0o077
        ):
            raise PolicyError("client config lock is unsafe")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise PolicyError("client config is locked by another writer") from error
        owner = json.dumps(
            {
                "schema": "solidstats-memory-client-lock/v1",
                "pid": os.getpid(),
                "config_sha256": _sha256(config.read_bytes()),
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii") + b"\n"
        os.ftruncate(descriptor, 0)
        os.write(descriptor, owner)
        os.fsync(descriptor)
        _HELD_CONFIG_LOCKS[config] = (descriptor, 1)
        yield
    finally:
        _HELD_CONFIG_LOCKS.pop(config, None)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _locked_config_writer(function):
    @functools.wraps(function)
    def wrapped(config: Path, *args, **kwargs):
        with _client_config_lock(Path(config)):
            return function(Path(config), *args, **kwargs)

    return wrapped


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


def _atomic_replace(
    path: Path, raw: bytes, mode: int, *, expected_raw: bytes | None = None
) -> None:
    expected_identity: tuple[int, int] | None = None
    if expected_raw is not None:
        details = path.lstat()
        expected_identity = (details.st_dev, details.st_ino)
        if path.read_bytes() != expected_raw:
            raise PolicyError("client config changed before replacement")
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
        if expected_raw is not None:
            current_details = path.lstat()
            if (
                path.is_symlink()
                or (current_details.st_dev, current_details.st_ino)
                != expected_identity
                or path.read_bytes() != expected_raw
            ):
                raise PolicyError("client config changed before replacement")
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except PolicyError:
        if created:
            try:
                temporary.unlink()
            except OSError:
                pass
        raise
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


@_locked_config_writer
def capture(config: Path, prestate: Path) -> None:
    raw, _ = _safe_file(config)
    if prestate.exists() and not prestate.is_symlink():
        previous, _ = _safe_file(prestate)
        if previous != raw:
            raise PolicyError("client config prestate already exists with different bytes")
        return
    _exclusive_write(prestate, raw)


@_locked_config_writer
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


@_locked_config_writer
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


@_locked_config_writer
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


def _registration_bounds(raw: bytes, name: str) -> tuple[int, int]:
    if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name) is None:
        raise PolicyError("legacy client name is invalid")
    heading = re.compile(
        rb"(?m)^\[mcp_servers\." + re.escape(name.encode("ascii")) + rb"\][ \t]*(?:#.*)?$"
    )
    matches = list(heading.finditer(raw))
    if len(matches) != 1:
        raise PolicyError("legacy client registration is missing or ambiguous")
    start = matches[0].start()
    following = re.search(rb"(?m)^\[", raw[matches[0].end() :])
    end = len(raw) if following is None else matches[0].end() + following.start()
    return start, end


def _remove_registration(raw: bytes, name: str) -> bytes:
    start, end = _registration_bounds(raw, name)
    return raw[:start] + raw[end:]


def _restore_registration(raw: bytes, recorded: bytes, name: str) -> bytes:
    """Reinsert only one recorded registration into otherwise-current bytes."""
    start, end = _registration_bounds(recorded, name)
    section = recorded[start:end]
    try:
        current = _registration_mapping(raw, name)
    except PolicyError:
        current = None
    if current is not None:
        if current != _registration_mapping(recorded, name):
            raise PolicyError("client registration drift prevents compensation")
        return raw
    separator = b"" if not raw or raw.endswith((b"\n", b"\r")) else b"\n"
    restored = raw + separator + section
    if _registration_mapping(restored, name) != _registration_mapping(recorded, name):
        raise PolicyError("client registration compensation differs")
    return restored


def _registration_mapping(raw: bytes, name: str) -> dict[str, object]:
    try:
        decoded = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise PolicyError("client config TOML is malformed") from error
    servers = decoded.get("mcp_servers")
    registration = servers.get(name) if isinstance(servers, dict) else None
    if not isinstance(registration, dict):
        raise PolicyError("client registration is missing or malformed")
    return registration


@_locked_config_writer
def rollback_registration_transaction(
    config: Path,
    prestate: Path,
    result: Path,
    *,
    url: str,
    token_env: str,
    legacy_name: str = "mempalace",
    timeout_seconds: int = 30,
    remove: Callable[[bytes], object] | None = None,
    stage: Callable[[str], None] | None = None,
) -> None:
    """Remove the replacement registration without overwriting unrelated drift."""
    current, config_mode = _safe_file(config)
    original_prestate, prestate_mode = _safe_file(prestate)
    inspect_policy(current, url=url, token_env=token_env, require_policy=True)
    recorded_replacement = _registration_mapping(current, CLIENT_NAME)
    if _registration_mapping(current, legacy_name) != _registration_mapping(
        original_prestate, legacy_name
    ):
        raise PolicyError("legacy client registration drift prevents rollback")
    metadata = prestate.with_suffix(prestate.suffix + ".policy.json")
    metadata_before = None
    metadata_mode = 0o600
    if metadata.exists() or metadata.is_symlink():
        metadata_before, metadata_mode = _safe_file(metadata)
    stage_hook = stage or (lambda _name: None)

    try:
        latest, latest_mode = _safe_file(config)
        if (
            _registration_mapping(latest, legacy_name)
            != _registration_mapping(original_prestate, legacy_name)
            or _registration_mapping(latest, CLIENT_NAME) != recorded_replacement
        ):
            raise PolicyError("client registration drift prevents rollback")
        current, config_mode = latest, latest_mode
        updated = _remove_registration(current, CLIENT_NAME)

        def exact_remove(expected: bytes) -> None:
            _atomic_replace(
                config, expected, config_mode, expected_raw=current
            )

        remove_callback = remove or exact_remove
        stage_hook("prepared_replace")
        remove_callback(updated)
        stage_hook("removed")
        observed, _ = _safe_file(config)
        if observed != updated:
            raise PolicyError("replacement client rollback read-back differs")
        stage_hook("readback")
        _atomic_replace(prestate, updated, prestate_mode)
        if metadata.exists() and not metadata.is_symlink():
            metadata.unlink()
        stage_hook("prestate")
        evidence = (
            b"schema=solidstats-memory-client-rollback/v1\n"
            + b"replacement_client_absent=true\nlegacy_client_preserved=true\n"
            + b"unrelated_current_bytes_preserved=true\n"
            + f"pre_rollback_sha256={_sha256(current)}\n".encode("ascii")
            + f"post_rollback_sha256={_sha256(updated)}\n".encode("ascii")
        )
        _exclusive_write(result, evidence)
        stage_hook("evidence")
    except BaseException as error:
        try:
            observed, _ = _safe_file(config)
            if observed != current:
                if observed == updated:
                    compensated = current
                else:
                    try:
                        target_present = (
                            _registration_mapping(observed, CLIENT_NAME)
                            == recorded_replacement
                        )
                    except PolicyError:
                        target_present = False
                    compensated = (
                        observed
                        if target_present
                        else _restore_registration(observed, current, CLIENT_NAME)
                    )
                if compensated != observed:
                    _atomic_replace(
                        config, compensated, config_mode, expected_raw=observed
                    )
                if compensated != current:
                    raise PolicyError(
                        "unrelated client drift preserved; exact compensation refused"
                    )
            _atomic_replace(prestate, original_prestate, prestate_mode)
            if metadata_before is None:
                if metadata.exists() and not metadata.is_symlink():
                    metadata.unlink()
            else:
                _atomic_replace(metadata, metadata_before, metadata_mode)
            if result.exists() and not result.is_symlink():
                result.unlink()
        except (OSError, PolicyError) as rollback_error:
            raise PolicyError(
                "replacement client rollback failed and exact compensation failed"
            ) from rollback_error
        if isinstance(error, PolicyError):
            raise
        raise PolicyError("replacement client rollback transaction failed") from error


def _authorize_exact_states(prestate: Path, states: tuple[bytes, ...]) -> None:
    metadata = prestate.with_suffix(prestate.suffix + ".policy.json")
    raw, mode = _safe_file(metadata)
    try:
        decoded = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PolicyError("client policy rollback metadata is malformed") from error
    accepted = decoded.get("accepted_sha256")
    if decoded.get("schema") != "solidstats-memory-client-policy/v1" or not isinstance(
        accepted, list
    ):
        raise PolicyError("client policy rollback metadata is malformed")
    if any(not isinstance(item, str) or re.fullmatch(r"[0-9a-f]{64}", item) is None for item in accepted):
        raise PolicyError("client policy rollback metadata is malformed")
    decoded["accepted_sha256"] = sorted(set(accepted) | {_sha256(item) for item in states})
    updated = json.dumps(decoded, separators=(",", ":"), sort_keys=True).encode("ascii") + b"\n"
    _atomic_replace(metadata, updated, mode)


@_locked_config_writer
def capture_pre_retirement(
    config: Path, result: Path, *, url: str, token_env: str, legacy_name: str = "mempalace"
) -> bytes:
    current, _ = _safe_file(config)
    inspect_policy(current, url=url, token_env=token_env, require_policy=True)
    without_legacy = _remove_registration(current, legacy_name)
    unrelated = _remove_registration(without_legacy, CLIENT_NAME)
    evidence = (
        b"schema=solidstats-memory-client-pre-retirement/v1\n"
        + b"sequence=650\nlegacy_client_present=true\nnew_client_live=true\n"
        + b"client_policy_readback=true\nsolidstats_client_count=2\n"
        + f"unrelated_sha256={_sha256(unrelated)}\n".encode("ascii")
    )
    if result.exists() and not result.is_symlink():
        previous, _ = _safe_file(result)
        if previous != evidence:
            raise PolicyError("client pre-retirement evidence is drifted")
    else:
        _exclusive_write(result, evidence)
    return unrelated


@_locked_config_writer
def retire_transaction(
    config: Path,
    prestate: Path,
    result: Path,
    *,
    url: str,
    token_env: str,
    legacy_name: str = "mempalace",
    timeout_seconds: int = 30,
    remove: Callable[[bytes], object] | None = None,
    stage: Callable[[str], None] | None = None,
) -> None:
    """Retire one exact registration with pre-authorized exact rollback."""
    current, mode = _safe_file(config)
    _safe_file(prestate)
    inspect_policy(current, url=url, token_env=token_env, require_policy=True)
    recorded_legacy = _registration_mapping(current, legacy_name)
    recorded_target = _registration_mapping(current, CLIENT_NAME)
    stage_hook = stage or (lambda _name: None)
    stage_hook("before_replace")
    latest, latest_mode = _safe_file(config)
    if (
        _registration_mapping(latest, legacy_name) != recorded_legacy
        or _registration_mapping(latest, CLIENT_NAME) != recorded_target
    ):
        raise PolicyError("client registration drift prevents retirement")
    inspect_policy(latest, url=url, token_env=token_env, require_policy=True)
    current, mode = latest, latest_mode
    retired = _remove_registration(current, legacy_name)
    inspect_policy(retired, url=url, token_env=token_env, require_policy=True)
    retirement_prestate = result.with_suffix(result.suffix + ".prestate")
    if retirement_prestate.exists() and not retirement_prestate.is_symlink():
        previous, _ = _safe_file(retirement_prestate)
        if previous != current:
            raise PolicyError("client retirement prestate is drifted")
    else:
        _exclusive_write(retirement_prestate, current)
    pre_retirement_result = result.with_name("client-pre-retirement.result")
    unrelated_pre = capture_pre_retirement(
        config, pre_retirement_result, url=url, token_env=token_env, legacy_name=legacy_name
    )
    _authorize_exact_states(prestate, (current, retired))

    final_current, final_mode = _safe_file(config)
    stage_hook("prepared_replace")
    if final_current != current:
        raise PolicyError("client config changed during retirement preparation")
    current, mode = final_current, final_mode
    retired = _remove_registration(current, legacy_name)

    def exact_remove(expected: bytes) -> None:
        _atomic_replace(config, expected, mode, expected_raw=current)

    remove_callback = remove or exact_remove
    try:
        remove_callback(retired)
        stage_hook("removed")
        observed, _ = _safe_file(config)
        stage_hook("readback")
        if observed != retired:
            raise PolicyError("legacy client retirement read-back differs")
        inspect_policy(observed, url=url, token_env=token_env, require_policy=True)
        unrelated_post = _remove_registration(observed, CLIENT_NAME)
        if unrelated_post != unrelated_pre:
            raise PolicyError("unrelated client registration bytes differ")
        stage_hook("policy")
        evidence = (
            b"schema=solidstats-memory-client-retirement/v3\n"
            + b"sequence=700\npre_retirement_sequence=650\nrecovery_gate_sequence=600\n"
            + f"prestate_sha256={_sha256(current)}\n".encode("ascii")
            + f"retired_sha256={_sha256(retired)}\n".encode("ascii")
            + f"unrelated_pre_sha256={_sha256(unrelated_pre)}\n".encode("ascii")
            + f"unrelated_post_sha256={_sha256(unrelated_post)}\n".encode("ascii")
            + b"legacy_client_absent=true\nnew_client_live=true\n"
            + b"unrelated_unchanged=true\nretirement_readback=true\n"
            + b"sole_solidstats_client=true\nsolidstats_client_count=1\n"
        )
        _exclusive_write(result, evidence)
        stage_hook("evidence")
    except BaseException as error:
        try:
            observed, _ = _safe_file(config)
            if observed != current:
                if observed == retired:
                    compensated = current
                else:
                    try:
                        target_present = (
                            _registration_mapping(observed, legacy_name)
                            == recorded_legacy
                        )
                    except PolicyError:
                        target_present = False
                    compensated = (
                        observed
                        if target_present
                        else _restore_registration(observed, current, legacy_name)
                    )
                if compensated != observed:
                    _atomic_replace(config, compensated, mode, expected_raw=observed)
                if compensated != current:
                    raise PolicyError(
                        "unrelated client drift preserved; exact compensation refused"
                    )
            restored, _ = _safe_file(config)
            if restored != current:
                raise PolicyError("client retirement rollback read-back failed")
            if result.exists() and not result.is_symlink():
                result.unlink()
        except (OSError, PolicyError) as rollback_error:
            raise PolicyError("client retirement failed and exact rollback failed") from rollback_error
        if isinstance(error, PolicyError):
            raise
        raise PolicyError("client retirement transaction failed") from error


@_locked_config_writer
def restore_retirement(
    config: Path,
    result: Path,
    *,
    legacy_name: str = "mempalace",
) -> None:
    current, mode = _safe_file(config)
    retirement_prestate = result.with_suffix(result.suffix + ".prestate")
    original, _ = _safe_file(retirement_prestate)
    expected = _remove_registration(original, legacy_name)
    if current != expected:
        raise PolicyError("retired client state drift prevents compensation")
    _atomic_replace(config, original, mode)
    restored, _ = _safe_file(config)
    if restored != original:
        raise PolicyError("legacy client compensation read-back failed")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("capture", "apply", "validate", "rollback", "rollback-current", "authorize-current", "pre-retirement", "retire", "restore-retirement"))
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--prestate", type=Path)
    parser.add_argument("--name", default=CLIENT_NAME)
    parser.add_argument("--url")
    parser.add_argument("--token-env")
    parser.add_argument("--result", type=Path)
    parser.add_argument("--legacy-name", default="mempalace")
    parser.add_argument("--timeout-seconds", type=int, default=30)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.name != CLIENT_NAME:
            raise PolicyError("target client name is invalid")
        if args.command in {"capture", "apply", "rollback", "rollback-current", "authorize-current", "retire"} and args.prestate is None:
            raise PolicyError("client config prestate path is required")
        if args.command in {"apply", "validate", "rollback-current", "pre-retirement", "retire"} and (
            args.url is None or args.token_env is None
        ):
            raise PolicyError("target client binding is required")
        if args.command in {"rollback-current", "pre-retirement", "retire", "restore-retirement"} and args.result is None:
            raise PolicyError("client retirement result path is required")
        if args.command == "capture":
            capture(args.config, args.prestate)
        elif args.command == "authorize-current":
            authorize_current(args.config, args.prestate)
        elif args.command == "apply":
            apply(args.config, args.prestate, url=args.url, token_env=args.token_env)
        elif args.command == "validate":
            validate(args.config, url=args.url, token_env=args.token_env)
        elif args.command == "rollback-current":
            if args.timeout_seconds < 1 or args.timeout_seconds > 3600:
                raise PolicyError("client rollback timeout is invalid")
            rollback_registration_transaction(
                args.config,
                args.prestate,
                args.result,
                url=args.url,
                token_env=args.token_env,
                legacy_name=args.legacy_name,
                timeout_seconds=args.timeout_seconds,
            )
        elif args.command == "pre-retirement":
            capture_pre_retirement(
                args.config, args.result, url=args.url, token_env=args.token_env,
                legacy_name=args.legacy_name,
            )
        elif args.command == "retire":
            if args.timeout_seconds < 1 or args.timeout_seconds > 3600:
                raise PolicyError("client retirement timeout is invalid")
            retire_transaction(
                args.config,
                args.prestate,
                args.result,
                url=args.url,
                token_env=args.token_env,
                legacy_name=args.legacy_name,
                timeout_seconds=args.timeout_seconds,
            )
        elif args.command == "restore-retirement":
            restore_retirement(
                args.config,
                args.result,
                legacy_name=args.legacy_name,
            )
        else:
            rollback(args.config, args.prestate)
        print(f"PASS: client policy {args.command} completed")
        return 0
    except (OSError, PolicyError) as error:
        print(f"FAIL: {error}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
