from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runtime import report_projection


class ReportProjectionTests(unittest.TestCase):
    def report(self, root: Path, include: bool = True) -> Path:
        path = root / "outputs" / "2026-07-12_midday_combined.md"
        path.parent.mkdir(parents=True)
        fragment = "同锚证据103已经进入人类可见解读。" if include else "缺少承重内容。"
        path.write_text(f"# fixture\n{fragment}\n## ③ 后附\n完整同锚证据103已经进入后附。\n", encoding="utf-8")
        return path

    @staticmethod
    def reasoning():
        return {
            "contract_sha256": "b" * 64,
            "report_projection": {"items": [
                {"id": "projection.visible", "surface": "visible", "section": "interpretation", "text": "同锚证据103已经进入人类可见解读。"},
                {"id": "projection.appendix", "surface": "appendix", "section": "appendix", "text": "完整同锚证据103已经进入后附。"},
            ]},
        }

    def test_visible_and_appendix_projection_must_both_survive(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(
            report_projection, "validate_reasoning_contract_file", return_value=self.reasoning()
        ), mock.patch.object(
            report_projection, "_visible_sections", return_value={"interpretation": "同锚证据103已经进入人类可见解读。"}
        ):
            root = Path(td)
            report = self.report(root)
            reasoning = root / "runtime_state" / "2026-07-12" / "reasoning_contract_midday.json"
            reasoning.parent.mkdir(parents=True)
            reasoning.write_text("{}", encoding="utf-8")
            result = report_projection.validate_report_projection(
                report, reasoning, "2026-07-12", "midday", root=root
            )
            self.assertEqual(result["checked_item_count"], 2)

    def test_projection_loss_is_hard_failure(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(
            report_projection, "validate_reasoning_contract_file", return_value=self.reasoning()
        ), mock.patch.object(
            report_projection, "_visible_sections", return_value={"interpretation": "缺少承重内容。"}
        ):
            root = Path(td)
            report = self.report(root, include=False)
            reasoning = root / "runtime_state" / "2026-07-12" / "reasoning_contract_midday.json"
            reasoning.parent.mkdir(parents=True)
            reasoning.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "semantic projection missing"):
                report_projection.validate_report_projection(
                    report, reasoning, "2026-07-12", "midday", root=root
                )


if __name__ == "__main__":
    unittest.main()
