from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runtime import report_contract
from runtime.report_state_extract import extract_report_state


DECISION = {
    "score": {"orderflow": 50, "chart": 19, "total": 69},
    "winrate": {"final": 64},
    "plan": {
        "risk_math": {
            "entry": 118000,
            "stop": 118500,
            "rr_to_tp1": 2.5,
        }
    },
}


class ReportContractTests(unittest.TestCase):
    def test_cutover_starts_at_2026_07_11_evening(self):
        self.assertFalse(report_contract.report_contract_required("2026-07-11", "midday"))
        self.assertTrue(report_contract.report_contract_required("2026-07-11", "evening"))
        self.assertTrue(report_contract.report_contract_required("2026-07-12", "morning"))

    def test_contract_generates_and_requires_three_exact_standalone_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "runtime_state" / "2026-07-11"
            state.mkdir(parents=True)
            decision = state / "decision_contract_evening.json"
            decision.write_text("{}\n", encoding="utf-8")
            with mock.patch.object(
                report_contract, "validate_contract_file", return_value=DECISION
            ):
                payload, target = report_contract.write_report_contract(
                    "2026-07-11",
                    "evening",
                    gate_summary="可交易",
                    decision_contract_path=decision,
                    root=root,
                )
                report = root / "outputs" / "2026-07-11_evening_combined.md"
                report.parent.mkdir()
                report.write_text(
                    "# fixture\n" + "\n".join(payload["lines"].values()) + "\n",
                    encoding="utf-8",
                )
                validated, validated_target = (
                    report_contract.validate_report_contract_manifest(
                        "2026-07-11", "evening", report, root=root
                    )
                )
            self.assertEqual(validated, payload)
            self.assertEqual(validated_target, target)
            self.assertEqual(payload["lines"]["gate"], "门禁沿用：可交易")
            self.assertEqual(
                payload["lines"]["score"],
                "盘口：50/70　盘面：19/30　总分：69　胜率自估：64%",
            )
            self.assertIn("5倍杠杆名义风险2.11864%", payload["lines"]["risk"])
            with mock.patch(
                "runtime.report_state_extract.parse_daily_text_contract",
                return_value=None,
            ):
                extracted = extract_report_state(
                    report.read_text(encoding="utf-8"),
                    trading_date="2026-07-11",
                    slot="evening",
                )
            self.assertEqual(extracted["notion_state"]["gate_summary"], "可交易")
            self.assertEqual(extracted["analysis_archive"]["scores"]["orderflow"], 50)
            self.assertEqual(extracted["analysis_archive"]["scores"]["chart"]["total"], 19)
            self.assertEqual(extracted["analysis_archive"]["scores"]["total"], 69)
            self.assertEqual(extracted["analysis_archive"]["scores"]["winrate"], 64)
            self.assertTrue(extracted["analysis_archive"]["risk_state"]["summary"])
            report.write_text(
                report.read_text(encoding="utf-8") + payload["lines"]["score"] + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                report_contract, "validate_contract_file", return_value=DECISION
            ), self.assertRaisesRegex(ValueError, "exactly one standalone canonical score"):
                report_contract.validate_report_contract_manifest(
                    "2026-07-11", "evening", report, root=root
                )

    def test_gate_summary_rejects_embedded_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "runtime_state" / "2026-07-11"
            state.mkdir(parents=True)
            decision = state / "decision_contract_evening.json"
            decision.write_text("{}", encoding="utf-8")
            with mock.patch.object(
                report_contract, "validate_contract_file", return_value=DECISION
            ), self.assertRaisesRegex(ValueError, "standalone field"):
                report_contract.build_report_contract(
                    "2026-07-11",
                    "evening",
                    gate_summary="可交易｜元数据",
                    decision_contract_path=decision,
                    root=root,
                )


if __name__ == "__main__":
    unittest.main()
