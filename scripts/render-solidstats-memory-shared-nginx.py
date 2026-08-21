#!/usr/bin/env python3
"""Patch only the SolidStats upstream in a measured shared nginx site."""

from __future__ import annotations

import os
import ipaddress
from pathlib import Path
import re
import stat
import sys


SCHEMA = "solidstats-memory-nginx-patch/v1"
MAX_BYTES = 1024 * 1024
SAFE_UPSTREAM_ROOT = re.compile(
    r"http://([0-9]{1,3}(?:\.[0-9]{1,3}){3}):([1-9][0-9]{0,4})/"
)


class PatchError(ValueError):
    """A value-free nginx patch contract failure."""


def regular(path: Path, *, private: bool) -> bytes:
    details = path.lstat()
    if stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode):
        raise PatchError("nginx patch input is invalid")
    if private and stat.S_IMODE(details.st_mode) != 0o600:
        raise PatchError("nginx patch input is invalid")
    if details.st_size <= 0 or details.st_size > MAX_BYTES:
        raise PatchError("nginx patch input is invalid")
    return path.read_bytes()


def parse_descriptor(data: bytes) -> dict[str, str]:
    try:
        lines = data.decode("ascii").splitlines()
    except UnicodeDecodeError as error:
        raise PatchError("nginx patch descriptor is invalid") from error
    result: dict[str, str] = {}
    for line in lines:
        if line.count("=") != 1:
            raise PatchError("nginx patch descriptor is invalid")
        key, value = line.split("=", 1)
        if not key or not value or key in result:
            raise PatchError("nginx patch descriptor is invalid")
        result[key] = value
    if set(result) != {
        "schema",
        "public_port",
        "public_location",
        "old_upstream",
        "new_upstream",
    }:
        raise PatchError("nginx patch descriptor is invalid")
    old_match = SAFE_UPSTREAM_ROOT.fullmatch(result.get("old_upstream", ""))
    new_match = SAFE_UPSTREAM_ROOT.fullmatch(result.get("new_upstream", ""))
    try:
        old_ip = ipaddress.ip_address(old_match.group(1) if old_match else "")
        new_ip = ipaddress.ip_address(new_match.group(1) if new_match else "")
    except ValueError as error:
        raise PatchError("nginx patch descriptor is invalid") from error
    if (
        result["schema"] != SCHEMA
        or result["public_port"] != "8443"
        or result["public_location"] != "/solidstats/"
        or old_ip != ipaddress.ip_address("127.0.0.1")
        or not new_ip.is_private
        or new_ip.is_loopback
        or int(new_match.group(2)) > 65535
        or int(old_match.group(2)) > 65535
        or result["old_upstream"] == result["new_upstream"]
    ):
        raise PatchError("nginx patch descriptor is invalid")
    return result


def find_blocks(data: bytes, declaration: bytes) -> list[tuple[int, int]]:
    matches = list(re.finditer(rb"(?m)^[ \t]*" + re.escape(declaration) + rb"[ \t]*\{[ \t]*(?:#.*)?$", data))
    blocks: list[tuple[int, int]] = []
    for match in matches:
        start = match.start()
        cursor = match.end()
        depth = 1
        while cursor < len(data):
            end = data.find(b"\n", cursor)
            if end == -1:
                end = len(data)
            line = data[cursor:end].split(b"#", 1)[0]
            depth += line.count(b"{") - line.count(b"}")
            if depth == 0:
                blocks.append((start, end + (end < len(data))))
                break
            if depth < 0:
                break
            cursor = end + 1
        else:
            raise PatchError("nginx shared-site boundary is ambiguous")
        if len(blocks) == 0 or blocks[-1][0] != start:
            raise PatchError("nginx shared-site boundary is ambiguous")
    return blocks


def shared_server_boundary(site: bytes) -> tuple[int, int, int, int]:
    servers = find_blocks(site, b"server")
    solidstats = find_blocks(site, b"location /solidstats/")
    personal = find_blocks(site, b"location /personal/")
    if len(solidstats) != 1 or len(personal) != 1:
        raise PatchError("nginx shared-site route boundary is ambiguous")

    solidstats_block = solidstats[0]
    personal_block = personal[0]
    solidstats_owners = [
        server
        for server in servers
        if server[0] < solidstats_block[0] and solidstats_block[1] <= server[1]
    ]
    personal_owners = [
        server
        for server in servers
        if server[0] < personal_block[0] and personal_block[1] <= server[1]
    ]
    if (
        len(solidstats_owners) != 1
        or len(personal_owners) != 1
        or solidstats_owners[0] != personal_owners[0]
    ):
        raise PatchError("nginx shared-site route boundary is ambiguous")

    server_start, server_end = solidstats_owners[0]
    server = site[server_start:server_end]
    listens: list[tuple[bytes, tuple[bytes, ...]]] = []
    depth = 0
    for raw_line in server.splitlines():
        line = raw_line.split(b"#", 1)[0].strip()
        if depth == 1 and line.startswith(b"listen"):
            if not line.endswith(b";"):
                raise PatchError("nginx shared-site listen contract is invalid")
            tokens = line[:-1].split()
            if not tokens or tokens[0] != b"listen" or len(tokens) < 2:
                raise PatchError("nginx shared-site listen contract is invalid")
            listens.append((tokens[1], tuple(tokens[2:])))
        depth += line.count(b"{") - line.count(b"}")
        if depth < 0:
            raise PatchError("nginx shared-site boundary is ambiguous")

    expected_addresses = {b"8443", b"[::]:8443"}
    expected_flags = {b"ssl", b"http2", b"default_server"}
    if (
        len(listens) != 2
        or {address for address, _ in listens} != expected_addresses
        or any(
            len(flags) != len(expected_flags) or set(flags) != expected_flags
            for _, flags in listens
        )
    ):
        raise PatchError("nginx shared-site listen contract is invalid")
    return server_start, server_end, solidstats_block[0], solidstats_block[1]


def render(site: bytes, descriptor: dict[str, str]) -> bytes:
    _, _, start, end = shared_server_boundary(site)
    block = site[start:end]
    old = descriptor["old_upstream"].encode("ascii")
    new = descriptor["new_upstream"].encode("ascii")
    pattern = re.compile(rb"(?m)^([ \t]*proxy_pass[ \t]+)" + re.escape(old) + rb"([ \t]*;[ \t]*(?:#.*)?(?:\n|$))")
    if len(pattern.findall(block)) != 1 or b"proxy_pass" not in block:
        raise PatchError("nginx SolidStats upstream does not match pre-state")
    replaced_block, count = pattern.subn(rb"\g<1>" + new + rb"\g<2>", block)
    if count != 1:
        raise PatchError("nginx SolidStats upstream is ambiguous")
    rendered = site[:start] + replaced_block + site[end:]
    reverse_pattern = re.compile(rb"(?m)^([ \t]*proxy_pass[ \t]+)" + re.escape(new) + rb"([ \t]*;[ \t]*(?:#.*)?(?:\n|$))")
    reverse_block, reverse_count = reverse_pattern.subn(rb"\g<1>" + old + rb"\g<2>", replaced_block)
    reverse = site[:start] + reverse_block + site[end:]
    if reverse_count != 1 or reverse != site:
        raise PatchError("nginx patch changed bytes outside the exact upstream")
    return rendered


def write_private(path: Path, data: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise PatchError("nginx patch output already exists")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        return 64
    site_path, descriptor_path, output_path = map(Path, argv)
    if not all(path.is_absolute() for path in (site_path, descriptor_path, output_path)):
        return 64
    try:
        site = regular(site_path, private=False)
        descriptor = parse_descriptor(regular(descriptor_path, private=True))
        write_private(output_path, render(site, descriptor))
    except (OSError, PatchError):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
