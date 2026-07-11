from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runtime.automation_memory_guard import inspect_memory


class AutomationMemoryGuardTests(unittest.TestCase):
    def test_mechanical_memory_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.md"
            path.write_text("2026-07-10 evening delivery complete; manifest=runtime_state/x.json", encoding="utf-8")
            self.assertEqual(inspect_memory(path)["status"], "clean")

    def test_trading_judgment_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.md"
            path.write_text("观望，总分58，胜率58%，压力位63000", encoding="utf-8")
            result = inspect_memory(path)
            self.assertEqual(result["status"], "blocked")
            self.assertIn("score", result["violations"])


if __name__ == "__main__":
    unittest.main()
