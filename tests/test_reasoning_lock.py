from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime import reasoning_lock


class ReasoningLockTests(unittest.TestCase):
    DATE = "2026-07-12"
    SLOT = "midday"

    def seed(self, root: Path):
        date_root = root / "runtime_state" / self.DATE
        date_root.mkdir(parents=True)
        records = {}
        for key in sorted(reasoning_lock.REQUIRED_INPUTS):
            path = date_root / f"{key}.json"
            path.write_text(f'{{"key":"{key}"}}', encoding="utf-8")
            records[key] = reasoning_lock._file_record(path, root)
        readiness_path = date_root / "reasoning_readiness_midday.json"
        readiness_path.write_text('{"status":"ready"}', encoding="utf-8")
        return records, readiness_path

    def test_lock_freezes_complete_input_set_and_detects_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            records, readiness_path = self.seed(root)
            readiness = dict(records)
            host = {"model": "gpt-test", "reasoning_effort": "high"}
            with patch.object(
                reasoning_lock,
                "validate_reasoning_readiness_manifest",
                return_value=(readiness, readiness_path),
            ), patch.object(
                reasoning_lock,
                "validate_host_capability_manifest",
                return_value=host,
            ):
                payload, target = reasoning_lock.write_reasoning_lock(
                    self.DATE, self.SLOT, root=root
                )
                self.assertEqual(set(payload["inputs"]), reasoning_lock.REQUIRED_INPUTS)
                reasoning_lock.validate_reasoning_lock(
                    target, self.DATE, self.SLOT, root=root
                )
                (root / records["reasoning_contract"]["path"]).write_text(
                    '{"changed":true}', encoding="utf-8"
                )
                with self.assertRaisesRegex(ValueError, "input changed"):
                    reasoning_lock.validate_reasoning_lock(
                        target, self.DATE, self.SLOT, root=root
                    )

    def test_below_high_host_cannot_create_independent_lock(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            records, readiness_path = self.seed(root)
            with patch.object(
                reasoning_lock,
                "validate_reasoning_readiness_manifest",
                return_value=(dict(records), readiness_path),
            ), patch.object(
                reasoning_lock,
                "validate_host_capability_manifest",
                return_value={"model": "gpt-test", "reasoning_effort": "medium"},
            ):
                with self.assertRaisesRegex(ValueError, "at least high"):
                    reasoning_lock.write_reasoning_lock(
                        self.DATE, self.SLOT, root=root
                    )


if __name__ == "__main__":
    unittest.main()
