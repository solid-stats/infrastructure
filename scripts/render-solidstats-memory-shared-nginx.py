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
SAFE_UPSTREAM = re.compile(r"http://([0-9]{1,3}(?:\.[0-9]{1,3}){3}):([1-9][0-9]{0,4})(/?)")


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
    old_match = SAFE_UPSTREAM.fullmatch(result.get("old_upstream", ""))
    new_match = SAFE_UPSTREAM.fullmatch(result.get("new_upstream", ""))
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
        or old_match.group(3) != new_match.group(3)
        or result["old_upstream"] == result["new_upstream"]
    ):
        raise PatchError("nginx patch descriptor is invalid")
    return result


def find_block(data: bytes, declaration: bytes) -> tuple[int, int]:
    matches = list(re.finditer(rb"(?m)^[ \t]*" + re.escape(declaration) + rb"[ \t]*\{[ \t]*(?:#.*)?$", data))
    if len(matches) != 1:
        raise PatchError("nginx shared-site boundary is ambiguous")
    start = matches[0].start()
    cursor = matches[0].end()
    depth = 1
    while cursor < len(data):
        end = data.find(b"\n", cursor)
        if end == -1:
            end = len(data)
        line = data[cursor:end].split(b"#", 1)[0]
        depth += line.count(b"{") - line.count(b"}")
        if depth == 0:
            return start, end + (end < len(data))
        if depth < 0:
            break
        cursor = end + 1
    raise PatchError("nginx shared-site boundary is ambiguous")


def render(site: bytes, descriptor: dict[str, str]) -> bytes:
    listen_matches = re.findall(rb"(?m)^[ \t]*listen[ \t]+(?:\[::\]:)?8443(?:[ \t]+ssl)?[ \t]*;", site)
    if not listen_matches:
        raise PatchError("nginx shared-site port is not exact")
    personal_before = site.count(b"location /personal/")
    if personal_before != 1:
        raise PatchError("nginx sibling route is ambiguous")
    start, end = find_block(site, b"location /solidstats/")
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
    if rendered.count(b"location /personal/") != personal_before:
        raise PatchError("nginx sibling route changed")
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
