#!/usr/bin/env python3
"""Exact MemPalace v3.5.0 backup behavior-oracle response checks.

Pinned source:
https://github.com/MemPalace/mempalace/blob/v3.5.0/mempalace/mcp_server.py#L2537-L2590
"""

from __future__ import annotations

import json
from typing import Iterable, Mapping


class BackupOracleError(ValueError):
    """A value-free behavior-oracle contract failure."""


def tool_data(result: Mapping[str, object]) -> Mapping[str, object]:
    """Reject every tool error and return one structured mapping."""
    if result.get("isError") is True:
        raise BackupOracleError("behavior oracle MCP tool call failed")
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
    raise BackupOracleError("behavior oracle result is unstructured")


def validate_delete_result(
    result: Mapping[str, object], *, drawer_id: str
) -> None:
    """Require the exact successful MemPalace v3.5.0 delete result."""
    deleted_ids = result.get("deleted_ids")
    chunks_deleted = result.get("chunks_deleted")
    if (
        set(result)
        != {"success", "drawer_id", "deleted_ids", "chunks_deleted"}
        or result.get("success") is not True
        or result.get("drawer_id") != drawer_id
        or not isinstance(deleted_ids, list)
        or not deleted_ids
        or not all(isinstance(value, str) and value for value in deleted_ids)
        or type(chunks_deleted) is not int
        or chunks_deleted != len(deleted_ids)
    ):
        raise BackupOracleError("behavior oracle cleanup contract failed")


def validate_not_found_result(
    result: Mapping[str, object], *, drawer_id: str
) -> None:
    """Require the exact v3.5.0 get-drawer not-found mapping."""
    if result != {"error": f"Drawer not found: {drawer_id}"}:
        raise BackupOracleError("behavior oracle cleanup absence failed")


def require_exact_absence(
    drawer_id: str, pages: Iterable[Mapping[str, object]]
) -> None:
    """Prove exact-ID absence from one complete bounded list traversal."""
    found: set[str] = set()
    expected_total: int | None = None
    expected_offset = 0
    for page_number, page in enumerate(pages):
        drawers = page.get("drawers")
        total = page.get("total")
        count = page.get("count")
        offset = page.get("offset")
        limit = page.get("limit")
        if (
            set(page) != {"drawers", "total", "count", "offset", "limit"}
            or not isinstance(drawers, list)
            or type(total) is not int
            or type(count) is not int
            or type(offset) is not int
            or type(limit) is not int
            or count != len(drawers)
            or offset != expected_offset
            or limit < 1
            or limit > 100
            or total < 0
            or total > 10_000
            or (expected_total is not None and total != expected_total)
        ):
            raise BackupOracleError("behavior oracle inventory is invalid")
        expected_total = total
        expected_offset += count
        for item in drawers:
            if not isinstance(item, Mapping):
                raise BackupOracleError("behavior oracle inventory is invalid")
            candidate = item.get("drawer_id") or item.get("id")
            if not isinstance(candidate, str) or not candidate or candidate in found:
                raise BackupOracleError("behavior oracle inventory is invalid")
            found.add(candidate)
        if page_number >= 99:
            raise BackupOracleError("behavior oracle inventory exceeded its bound")
    if expected_total is None or len(found) != expected_total:
        raise BackupOracleError("behavior oracle inventory is incomplete")
    if drawer_id in found:
        raise BackupOracleError("behavior oracle cleanup absence failed")
