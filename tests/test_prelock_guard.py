from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.prelock_guard import (
    activate_prelock_guard,
    assert_no_active_prelock_guard,
    prelock_guard_targets,
    restore_all_active_prelock_guards,
    restore_prelock_guard,
    sha256_file,
)


class PrelockGuardTests(unittest.TestCase):
    def _seed(self, root: Path) -> dict[str, Path]:
        runtime = root / "runtime_state" / "2026-07-06"
        outputs = root / "outputs"
        sessions = root / "sessions"
        runtime.mkdir(parents=True)
        outputs.mkdir()
        sessions.mkdir()
        files = {
            "context": sessions / "context_log.md",
            "analysis": runtime / "analysis_midday.json",
            "decision": runtime / "decision_midday.json",
            "combined": outputs / "2026-07-06_midday_combined.md",
            "payload": outputs / "2026-07-06_midday_publish_payload.json",
            "render": outputs / "2026-07-06_midday_render.docx",
        }
        files["context"].write_text("midday judgment in ledger\n", encoding="utf-8")
        files["analysis"].write_text(
            json.dumps({"score": 67}), encoding="utf-8"
        )
        files["decision"].write_text(
            json.dumps({"maker": "prior short"}), encoding="utf-8"
        )
        files["combined"].write_text("prior report judgment\n", encoding="utf-8")
        files["payload"].write_text(
            json.dumps({"children": ["prior report"]}), encoding="utf-8"
        )
        files["render"].write_bytes(b"prior docx")
        return files

    def test_guard_hides_prior_judgment_files_until_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = self._seed(root)
            before = {name: sha256_file(path) for name, path in files.items()}

            targets = {
                path.relative_to(root).as_posix()
                for path in prelock_guard_targets("2026-07-06", "evening", root=root)
            }
            self.assertIn("runtime_state/2026-07-06/decision_midday.json", targets)
            self.assertIn("sessions/context_log.md", targets)

            payload, manifest = activate_prelock_guard(
                "2026-07-06", "evening", root=root
            )
            self.assertEqual(payload["status"], "active")
            self.assertEqual(len(payload["entries"]), len(files))
            for path in files.values():
                self.assertFalse(path.exists())
            with self.assertRaisesRegex(RuntimeError, "pre-lock guard is still active"):
                assert_no_active_prelock_guard("2026-07-06", "evening", root=root)

            restored, _ = restore_prelock_guard(
                "2026-07-06", "evening", root=root, reason="test"
            )
            self.assertEqual(restored["status"], "restored")
            self.assertTrue(manifest.exists())
            for name, path in files.items():
                self.assertTrue(path.exists(), name)
                self.assertEqual(sha256_file(path), before[name])
            assert_no_active_prelock_guard("2026-07-06", "evening", root=root)

    def test_recovery_restores_all_active_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = self._seed(root)
            activate_prelock_guard("2026-07-06", "evening", root=root)
            for path in files.values():
                self.assertFalse(path.exists())

            restored = restore_all_active_prelock_guards(root=root, reason="test")
            self.assertEqual(len(restored), 1)
            for path in files.values():
                self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
