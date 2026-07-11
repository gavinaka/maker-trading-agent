from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.context_pack import (
    authoritative_runtime_files,
    authority_manifest,
    authority_read_budget,
    build_context_pack,
    ensure_context_pack,
    latest_context_block,
)
from runtime.usage_logger import append_usage
from runtime.state_store import LOGIC_FILES


class ContextPackTests(unittest.TestCase):
    def test_latest_block_stops_before_previous_date(self):
        text = """# log
## 2026-06-29（latest）
PASS
---
## 2026-06-28（old）
OLD
"""
        block = latest_context_block(text)
        self.assertIn("PASS", block)
        self.assertNotIn("OLD", block)

    def test_build_context_pack_excludes_prior_analysis_and_loads_all_authority(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for relative in LOGIC_FILES.values():
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("test authority\n", encoding="utf-8")
            (root / "sessions").mkdir(exist_ok=True)
            (root / "sessions" / "context_log.md").write_text(
                "# log\n"
                "## 2026-06-29（latest）\n"
                "- Notion 最终唯一存活页=`38efda35-a098-810c-b9c3-cdf448a9d226`；冻结 PASS\n"
                "- Word 逐页检查，无异常分页。\n"
                "- 盘口 57；总分 77；胜率 66%；Maker 反弹空。\n"
                "## 2026-06-28（old）\nOLD\n",
                encoding="utf-8",
            )
            payload, target = build_context_pack("2026-06-29", "morning", root=root)
            self.assertTrue(target.exists())
            serialized = json.dumps(payload, ensure_ascii=False)
            self.assertNotIn("盘口 57", serialized)
            self.assertNotIn("胜率 66", serialized)
            self.assertNotIn("Maker 反弹空", serialized)
            self.assertEqual(
                payload["operational_status"]["final_page_ids"],
                ["38efda35-a098-810c-b9c3-cdf448a9d226"],
            )
            self.assertTrue(payload["analysis_policy"]["full_analysis_recompute"])
            self.assertEqual(payload["analysis_policy"]["reasoning_effort"], "max")
            self.assertTrue(
                payload["analysis_policy"]["max_reasoning_confirmation_required"]
            )
            self.assertRegex(payload["authority_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(
                payload["authority_manifest"],
                authority_manifest(root),
            )
            self.assertIn(
                "scoring/reasoning_depth_checklist.md",
                payload["authoritative_runtime_files"],
            )
            self.assertIn(
                "constitution/trading_constitution.md",
                payload["authoritative_runtime_files"],
            )
            self.assertIn(
                "risk/risk_checklist.md",
                payload["authoritative_runtime_files"],
            )
            self.assertIn(
                "agents/review_agent.md",
                payload["authoritative_runtime_files"],
            )
            self.assertIn(
                "agents/footprint_agent.md",
                payload["authoritative_runtime_files"],
            )
            self.assertFalse(payload["read_policy"]["load_full_context_log"])
            self.assertTrue(payload["read_policy"]["load_authority_digest_first"])
            self.assertTrue(payload["read_policy"]["expand_authority_by_phase"])
            self.assertLessEqual(
                payload["authority_read_budget"]["total_bytes"],
                payload["authority_read_budget"]["budget_bytes"],
            )
            self.assertNotIn(
                "memory/evening-review-visual-to-notion.md",
                payload["authoritative_runtime_files"],
            )
            self.assertFalse(
                payload["read_policy"]["load_all_authoritative_methodology"]
            )
            self.assertEqual(
                set(payload["authoritative_runtime_files"]),
                set(LOGIC_FILES.values()),
            )

            first, first_target, reused = ensure_context_pack(
                "2026-06-29", "morning", root=root
            )
            self.assertTrue(reused)
            self.assertEqual(first_target, target)
            self.assertEqual(first["source_sha256"], payload["source_sha256"])

            authority_file = root / LOGIC_FILES["scoring_system"]
            authority_file.write_text("changed authority\n", encoding="utf-8")
            second, second_target, reused = ensure_context_pack(
                "2026-06-29", "morning", root=root
            )
            self.assertFalse(reused)
            self.assertEqual(second_target, target)
            self.assertNotEqual(second["authority_sha256"], payload["authority_sha256"])

    def test_missing_referenced_memory_hard_stops_context_pack(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for relative in LOGIC_FILES.values():
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("test authority\n", encoding="utf-8")
            missing = root / "memory" / "precise-numbers-no-fuzzy.md"
            missing.unlink()
            with self.assertRaisesRegex(ValueError, "missing authoritative"):
                authoritative_runtime_files(root)


class UsageLoggerTests(unittest.TestCase):
    def test_append_usage_preserves_unknown_token_counts(self):
        with tempfile.TemporaryDirectory() as td:
            target = append_usage(
                trading_date="2026-06-29",
                slot="morning",
                phase="capture",
                status="success",
                duration_ms=100,
                root=Path(td),
            )
            record = json.loads(target.read_text(encoding="utf-8"))
            self.assertIsNone(record["input_tokens"])
            self.assertEqual(record["duration_ms"], 100)

    def test_event_id_makes_usage_append_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for _ in range(2):
                target = append_usage(
                    trading_date="2026-06-29",
                    slot="midday",
                    phase="commit",
                    status="success",
                    event_id="stable-event",
                    root=root,
                )
            self.assertEqual(len(target.read_text(encoding="utf-8").splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
