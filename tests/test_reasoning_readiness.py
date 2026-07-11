from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from runtime.reasoning_readiness import (
    build_reasoning_readiness_manifest,
    decision_contract_required,
    reasoning_readiness_required,
    validate_locked_report_for_output,
    validate_reasoning_readiness_manifest,
)


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reasoning_work_text() -> str:
    return """
六源准确性：BlockBeats、Coinglass、Exocharts、FedWatch、Farside、TradingView 均完成截图/JSON 验真且数据有效。
承重点校准：pivot 摆动未破，CVD 净斜率已重读，SMA20 已按当次图重测，VRVP/VAH/VAL/POC 用作盘面主判。
评分链：盘口与盘面分项先按证据落值，再合成总分；总评来自 Coinglass、Exocharts、TradingView 的分项证据。
胜率 rubric：胜率 rubric 锚=60，次因 -2，落值 58，再与 60 门槛比较，不把临界值倒推成可开单。
方向反证：方向主判先给多空路径，最强反证单列，失效情景写清。
风险验算：止损、TP1 止盈、TP2 清剩余、盈亏比、R、杠杆、持仓均已验算。
纪律：禁止后补理由、后补 rubric 或后补任何推理。
"""


class ReasoningReadinessTests(unittest.TestCase):
    def _seed_root(self, root: Path, trading_date: str = "2026-07-06", slot: str = "midday") -> dict[str, Path]:
        runtime = root / "runtime_state" / trading_date
        runtime.mkdir(parents=True)
        scoring = root / "scoring"
        scoring.mkdir(parents=True)
        contract = scoring / "reasoning_depth_checklist.md"
        contract.write_text("reasoning depth contract", encoding="utf-8")
        capture = runtime / "capture.json"
        capture.write_text(json.dumps({"success": True}), encoding="utf-8")
        transition = runtime / f"transition_{slot}.json"
        transition.write_text(
            json.dumps(
                {
                    "trading_date": trading_date,
                    "slot": slot,
                    "capture_manifest": {
                        "path": capture.relative_to(runtime).as_posix(),
                        "sha256": _sha256_file(capture),
                    },
                }
            ),
            encoding="utf-8",
        )
        golden = runtime / f"golden_reasoning_{slot}.json"
        golden.write_text(json.dumps({"status": "ready"}), encoding="utf-8")
        work = runtime / f"reasoning_work_{slot}.md"
        work.write_text(_reasoning_work_text(), encoding="utf-8")
        return {
            "runtime": runtime,
            "capture": capture,
            "transition": transition,
            "golden": golden,
            "work": work,
        }

    def test_readiness_required_from_20260706_midday_not_morning(self):
        self.assertFalse(reasoning_readiness_required("2026-07-06", "morning"))
        self.assertTrue(reasoning_readiness_required("2026-07-06", "midday"))
        self.assertTrue(reasoning_readiness_required("2026-07-06", "evening"))
        self.assertFalse(decision_contract_required("2026-07-10", "midday"))
        self.assertTrue(decision_contract_required("2026-07-10", "evening"))
        self.assertTrue(decision_contract_required("2026-07-11", "morning"))

    def test_decision_contract_is_required_from_cutover(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = self._seed_root(root, "2026-07-10", "evening")
            with self.assertRaisesRegex(ValueError, "decision contract is required"):
                build_reasoning_readiness_manifest(
                    "2026-07-10",
                    "evening",
                    work_file=paths["work"],
                    capture_manifest_path=paths["capture"],
                    transition_path=paths["transition"],
                    root=root,
                )

    def test_readiness_manifest_must_precede_formal_report(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = self._seed_root(root)
            report = root / "outputs" / "2026-07-06_midday_combined.md"
            report.parent.mkdir()
            report.write_text("# 2026.7.6 午间日报\n", encoding="utf-8")
            old = time.time() - 5
            os.utime(report, (old, old))
            build_reasoning_readiness_manifest(
                "2026-07-06",
                "midday",
                work_file=paths["work"],
                capture_manifest_path=paths["capture"],
                transition_path=paths["transition"],
                root=root,
            )
            with self.assertRaisesRegex(ValueError, "after the formal report"):
                validate_reasoning_readiness_manifest(
                    "2026-07-06",
                    "midday",
                    report,
                    root=root,
                )

    def test_hash_bound_analysis_lock_allows_downstream_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = self._seed_root(root)
            build_reasoning_readiness_manifest(
                "2026-07-06",
                "midday",
                work_file=paths["work"],
                capture_manifest_path=paths["capture"],
                transition_path=paths["transition"],
                root=root,
            )
            report = root / "outputs" / "2026-07-06_midday_combined.md"
            report.parent.mkdir()
            report.write_text("# 2026.7.6 午间日报\n", encoding="utf-8")
            future = time.time() + 3
            os.utime(report, (future, future))
            analysis_lock = paths["runtime"] / "analysis_lock_midday.json"
            analysis_lock.write_text(
                json.dumps(
                    {
                        "trading_date": "2026-07-06",
                        "slot": "midday",
                        "report_path": str(report.resolve()),
                        "report_sha256": _sha256_file(report),
                        "max_through_analysis_confirmed": True,
                        "analysis_validation": {
                            "reasoning_readiness_pre_md": True,
                            "reasoning_readiness_policy": "pre_md_reasoning_depth_certified_no_posthoc_rationale",
                        },
                    }
                ),
                encoding="utf-8",
            )
            self.assertIsNotNone(
                validate_locked_report_for_output(
                    "2026-07-06",
                    "midday",
                    report,
                    root=root,
                )
            )

    def test_readiness_rejects_capture_manifest_not_bound_to_transition(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = self._seed_root(root)
            other_capture = paths["runtime"] / "other_capture.json"
            other_capture.write_text(json.dumps({"success": True}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not match prepared transition"):
                build_reasoning_readiness_manifest(
                    "2026-07-06",
                    "midday",
                    work_file=paths["work"],
                    capture_manifest_path=other_capture,
                    transition_path=paths["transition"],
                    root=root,
                )

    def test_readiness_validation_rechecks_capture_transition_binding(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = self._seed_root(root)
            other_capture = paths["runtime"] / "other_capture.json"
            other_capture.write_text(json.dumps({"success": True}), encoding="utf-8")
            _, readiness_path = build_reasoning_readiness_manifest(
                "2026-07-06",
                "midday",
                work_file=paths["work"],
                capture_manifest_path=paths["capture"],
                transition_path=paths["transition"],
                root=root,
            )
            payload = json.loads(readiness_path.read_text(encoding="utf-8"))
            payload["capture_manifest"] = {
                "path": other_capture.relative_to(root).as_posix(),
                "sha256": _sha256_file(other_capture),
            }
            readiness_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not match prepared transition"):
                validate_reasoning_readiness_manifest(
                    "2026-07-06",
                    "midday",
                    root=root,
                )

    def test_downstream_output_rejects_wrong_lock_slot_or_date(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = self._seed_root(root)
            build_reasoning_readiness_manifest(
                "2026-07-06",
                "midday",
                work_file=paths["work"],
                capture_manifest_path=paths["capture"],
                transition_path=paths["transition"],
                root=root,
            )
            report = root / "outputs" / "2026-07-06_midday_combined.md"
            report.parent.mkdir()
            report.write_text("# 2026.7.6 午间日报\n", encoding="utf-8")
            future = time.time() + 3
            os.utime(report, (future, future))
            analysis_lock = paths["runtime"] / "analysis_lock_midday.json"
            analysis_lock.write_text(
                json.dumps(
                    {
                        "trading_date": "2026-07-06",
                        "slot": "evening",
                        "report_path": str(report.resolve()),
                        "report_sha256": _sha256_file(report),
                        "max_through_analysis_confirmed": True,
                        "analysis_validation": {
                            "reasoning_readiness_pre_md": True,
                            "reasoning_readiness_policy": "pre_md_reasoning_depth_certified_no_posthoc_rationale",
                        },
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "slot mismatch"):
                validate_locked_report_for_output(
                    "2026-07-06",
                    "midday",
                    report,
                    root=root,
                )

    def test_downstream_output_rejects_unlocked_formal_report(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = root / "outputs" / "2026-07-06_midday_combined.md"
            report.parent.mkdir(parents=True)
            report.write_text("# 2026.7.6 午间日报\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing analysis lock"):
                validate_locked_report_for_output(
                    "2026-07-06",
                    "midday",
                    report,
                    root=root,
                )


if __name__ == "__main__":
    unittest.main()
