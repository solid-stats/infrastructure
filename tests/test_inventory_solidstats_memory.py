#!/usr/bin/env python3
"""Execution checks for the generated MemPalace v3.5.0 oracle program."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "scripts" / "inventory-solidstats-memory.py"
SPEC = importlib.util.spec_from_file_location("memory_inventory", INVENTORY_PATH)
assert SPEC and SPEC.loader
INVENTORY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INVENTORY)


class OracleProgramTests(unittest.TestCase):
    def test_generated_v350_oracle_program_compiles(self) -> None:
        program = INVENTORY._oracle_program()
        compile(program, "mempalace-v350-oracle.py", "exec")
        self.assertIn("ChromaCollection", program)
        self.assertIn("_remote_collection_name", program)


if __name__ == "__main__":
    unittest.main()
