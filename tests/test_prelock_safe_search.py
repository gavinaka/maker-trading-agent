from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runtime.prelock_safe_search import search


class PrelockSafeSearchTests(unittest.TestCase):
    def test_search_finds_authority_but_never_prior_output_or_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authority = root / "risk" / "rules.md"
            prior = root / "outputs" / "2026-07-09_evening_combined.md"
            archive = root / "sessions" / "archive" / "old.md"
            for path in (authority, prior, archive):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("UNIQUE_NEEDLE\n", encoding="utf-8")
            matches = search(
                "UNIQUE_NEEDLE",
                trading_date="2026-07-10",
                slot="morning",
                root=root,
                fixed_strings=True,
            )
            self.assertEqual([item["path"] for item in matches], ["risk/rules.md"])


if __name__ == "__main__":
    unittest.main()
