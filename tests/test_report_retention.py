from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from runtime.report_retention import collect_actions, execute_actions, run_retention_cleanup
from runtime import report_retention


def _write(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _touch_mtime(path: Path, day: str) -> None:
    timestamp = datetime.strptime(day, "%Y-%m-%d").timestamp()
    os.utime(path, (timestamp, timestamp))


class ReportRetentionTests(unittest.TestCase):
    def test_collects_expired_reproducible_artifacts_only(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "data_sources" / "inbox" / "2026-07-04" / "coinglass.png")
            _write(root / "data_sources" / "inbox" / "2026-07-05" / "coinglass.png")
            _write(root / "outputs" / "blockbeats" / "2026-07-04_midday_1.png")
            _write(root / "outputs" / "blockbeats" / "2026-07-05_midday_1.png")
            _write(root / "outputs" / "2026-07-04_midday_cards.json")
            _write(root / "outputs" / "2026-07-04_midday_publish_payload.json")
            _write(root / "outputs" / "2026-07-04_midday_combined.md")
            _write(root / "outputs" / "2026-07-04_midday_render.docx")
            _write(root / "outputs" / "2026-07-04_独立审查报告.html")
            legacy_script = _write(root / "outputs" / "_legacy_push.py")
            _touch_mtime(legacy_script, "2026-07-04")

            for name in ("captures", "evidence", "publish_attempts", "word_qa"):
                _write(root / "runtime_state" / "2026-07-04" / name / "artifact.json")
            _write(root / "runtime_state" / "2026-07-04" / "visual_crops" / "crop.png")
            old_quality_audit = _write(
                root / "runtime_state" / "quality_audit" / "pages" / "page.png"
            )
            _touch_mtime(old_quality_audit, "2026-07-04")
            _touch_mtime(old_quality_audit.parent, "2026-07-04")
            _touch_mtime(old_quality_audit.parent.parent, "2026-07-04")
            _write(root / "runtime_state" / "2026-07-04" / "delivery_midday.json")
            _write(root / "runtime_state" / "2026-07-05" / "evidence" / "artifact.json")
            _write(root / "runtime_state" / "automation_gate" / "daily-2026-07-04.done")

            actions = collect_actions(
                root=root,
                today=date(2026, 7, 6),
                keep_days=2,
            )
            paths = {item.path for item in actions}

            self.assertIn("data_sources/inbox/2026-07-04", paths)
            self.assertIn("outputs/blockbeats/2026-07-04_midday_1.png", paths)
            self.assertIn("outputs/2026-07-04_midday_cards.json", paths)
            self.assertIn("outputs/2026-07-04_midday_publish_payload.json", paths)
            self.assertIn("outputs/2026-07-04_midday_combined.md", paths)
            self.assertIn("outputs/2026-07-04_独立审查报告.html", paths)
            self.assertIn("outputs/_legacy_push.py", paths)
            self.assertIn("runtime_state/2026-07-04/captures", paths)
            self.assertIn("runtime_state/2026-07-04/evidence", paths)
            self.assertIn("runtime_state/2026-07-04/publish_attempts", paths)
            self.assertIn("runtime_state/2026-07-04/word_qa", paths)
            self.assertIn("runtime_state/2026-07-04/visual_crops", paths)
            self.assertIn("runtime_state/quality_audit", paths)

            self.assertNotIn("data_sources/inbox/2026-07-05", paths)
            self.assertNotIn("outputs/blockbeats/2026-07-05_midday_1.png", paths)
            self.assertNotIn("outputs/2026-07-04_midday_render.docx", paths)
            self.assertNotIn("runtime_state/2026-07-04/delivery_midday.json", paths)
            self.assertNotIn("runtime_state/2026-07-05/evidence", paths)
            self.assertNotIn("runtime_state/automation_gate/daily-2026-07-04.done", paths)

    def test_execute_removes_only_collected_candidates(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_inbox = _write(root / "data_sources" / "inbox" / "2026-07-04" / "source.png")
            combined = _write(root / "outputs" / "2026-07-04_midday_combined.md")
            canonical_docx = _write(root / "outputs" / "2026-07-04_midday_render.docx")
            delivery = _write(root / "runtime_state" / "2026-07-04" / "delivery_midday.json")
            old_evidence = _write(root / "runtime_state" / "2026-07-04" / "evidence" / "proof.png")
            current_evidence = _write(root / "runtime_state" / "2026-07-05" / "evidence" / "proof.png")

            actions = collect_actions(
                root=root,
                today=date(2026, 7, 6),
                keep_days=2,
            )
            execute_actions(actions, root=root)

            self.assertFalse(old_inbox.parent.exists())
            self.assertFalse(combined.exists())
            self.assertFalse(old_evidence.parent.exists())
            self.assertTrue(canonical_docx.exists())
            self.assertTrue(delivery.exists())
            self.assertTrue(current_evidence.exists())

    def test_execute_writes_manifest_for_post_delivery_automation(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            combined = _write(root / "outputs" / "2026-07-04_evening_combined.md")
            html = _write(root / "outputs" / "2026-07-04_独立审查报告.html")
            canonical_docx = _write(root / "outputs" / "2026-07-04_evening_render.docx")
            delivery = _write(root / "runtime_state" / "2026-07-04" / "delivery_evening.json")
            manifest = root / "runtime_state" / "2026-07-06" / "retention_cleanup_evening.json"

            payload = run_retention_cleanup(
                root=root,
                today=date(2026, 7, 6),
                keep_days=2,
                execute=True,
                manifest_path=manifest,
                reason="post_delivery:2026-07-06:evening",
            )

            self.assertEqual(payload["mode"], "execute")
            self.assertEqual(payload["reason"], "post_delivery:2026-07-06:evening")
            self.assertTrue(manifest.is_file())
            self.assertFalse(combined.exists())
            self.assertFalse(html.exists())
            self.assertTrue(canonical_docx.exists())
            self.assertTrue(delivery.exists())

    def test_temp_scripts_can_be_excluded_from_candidates(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = _write(root / "outputs" / "_legacy_push.py")
            _touch_mtime(script, "2026-07-04")

            actions = collect_actions(
                root=root,
                today=date(2026, 7, 6),
                keep_days=2,
                include_temp_scripts=False,
            )

            self.assertNotIn("outputs/_legacy_push.py", {item.path for item in actions})

    def test_human_readable_cli_prints_payload_actions(self) -> None:
        payload = {
            "mode": "dry-run",
            "cutoff": "2026-07-11",
            "count": 1,
            "bytes": 7,
            "actions": [
                {
                    "kind": "runtime_state_heavy",
                    "path": "runtime_state/old/crops",
                    "bytes": 7,
                    "reason": "expired",
                }
            ],
        }
        with mock.patch.object(report_retention, "run_retention_cleanup", return_value=payload):
            with mock.patch("sys.argv", ["report_retention.py"]):
                with mock.patch("builtins.print") as output:
                    self.assertEqual(report_retention.main(), 0)
        rendered = "\n".join(str(call.args[0]) for call in output.call_args_list)
        self.assertIn("runtime_state/old/crops", rendered)


if __name__ == "__main__":
    unittest.main()
