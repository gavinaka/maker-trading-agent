from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runtime import report_contract
from runtime import pretrade_gate
from runtime.report_state_extract import extract_report_state
from runtime.decision_contract import build_contract
from runtime.reasoning_contract import build_reasoning_contract
from tests.test_reasoning_contract import ReasoningContractTests


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
    def write_gate_binding(self, root: Path, trading_date: str, slot: str) -> None:
        pretrade_gate.write_pretrade_gate_contract(
            trading_date,
            source_reference="11111111-2222-3333-4444-555555555555",
            source_observed_at=f"{trading_date}T08:20:00+08:00",
            subjective_conclusion="可交易",
            emotion_stable=True,
            rhythm_consistent=True,
            result_dependency=False,
            continuous_stop_loss_count=0,
            physical_condition="normal",
            root=root,
        )
        state = root / "runtime_state" / trading_date
        binding = pretrade_gate.transition_binding(
            trading_date, slot, root=root
        )
        (state / f"transition_{slot}.json").write_text(
            json.dumps({"pretrade_gate_contract": binding}),
            encoding="utf-8",
        )

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
            self.write_gate_binding(root, "2026-07-11", "evening")
            with mock.patch.object(
                report_contract, "validate_contract_file", return_value=DECISION
            ):
                payload, target = report_contract.write_report_contract(
                    "2026-07-11",
                    "evening",
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

    def test_contract_requires_transition_bound_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "runtime_state" / "2026-07-11"
            state.mkdir(parents=True)
            decision = state / "decision_contract_evening.json"
            decision.write_text("{}", encoding="utf-8")
            with mock.patch.object(
                report_contract, "validate_contract_file", return_value=DECISION
            ), self.assertRaises((FileNotFoundError, ValueError)):
                report_contract.build_report_contract(
                    "2026-07-11",
                    "evening",
                    decision_contract_path=decision,
                    root=root,
                )

    def test_v3_report_uses_honest_conviction_and_all_fill_scenarios(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture, reasoning_input = ReasoningContractTests().seed(root)
            reasoning_payload = build_reasoning_contract(
                reasoning_input, capture_manifest_path=capture, root=root
            )
            state = root / "runtime_state" / "2026-07-12"
            reasoning = state / "reasoning_contract_midday.json"
            reasoning.write_text(
                json.dumps(reasoning_payload, ensure_ascii=False), encoding="utf-8"
            )
            decision_payload = build_contract(
                {
                    "trading_date": "2026-07-12",
                    "slot": "midday",
                    "plan": {
                        "direction": "long",
                        "entry_mode": "ladder",
                        "exchange": "OKX",
                        "instrument": "BTCUSDT",
                        "leverage": 5,
                        "position_notional_usdt": 750,
                        "entry_levels": [
                            {"id": "level.a", "price": 100, "allocation_pct": 50},
                            {"id": "level.b", "price": 100.1, "allocation_pct": 50},
                        ],
                        "stop": 99.5,
                        "tp1": 102,
                        "tp2": 103,
                        "tp1_close_pct": 50,
                        "tp2_close_pct": 50,
                        "cancel_before_fill": "结构失效则撤销全部未成交挂单",
                    },
                },
                reasoning_contract_path=reasoning,
                root=root,
            )
            decision = state / "decision_contract_midday.json"
            decision.write_text(
                json.dumps(decision_payload, ensure_ascii=False), encoding="utf-8"
            )
            self.write_gate_binding(root, "2026-07-12", "midday")
            payload = report_contract.build_report_contract(
                "2026-07-12",
                "midday",
                decision_contract_path=decision,
                root=root,
            )
            self.assertIn("计划时置信度，非回测命中率", payload["lines"]["score"])
            self.assertIn("3种非空成交情景", payload["lines"]["risk"])
            self.assertIn("全部情景均达到1:2.5且不高于3%", payload["lines"]["risk"])
            self.assertNotIn("代表入场", payload["lines"]["risk"])


if __name__ == "__main__":
    unittest.main()
