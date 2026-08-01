from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.decision_contract import (
    build_contract,
    maker_execution_contract_required,
    reasoning_bound_contract_required,
    validate_contract_file,
)
from runtime.reasoning_contract import build_reasoning_contract
from tests.test_reasoning_contract import ReasoningContractTests


class DecisionContractTests(unittest.TestCase):
    def sample(self):
        return {
            "trading_date": "2026-07-10",
            "slot": "evening",
            "score": {"orderflow": 44, "chart": 21, "total": 65},
            "winrate": {
                "anchor": 60,
                "adjustments": [
                    {"id": "liquidity", "delta": 2, "evidence": "CVD/OI aligned"},
                    {"id": "structure", "delta": -1, "evidence": "near VAH"},
                ],
                "final": 61,
            },
            "plan": {"direction": "short", "entry": 63000, "stop": 63300, "tp1": 62250},
        }

    def test_contract_recomputes_all_business_math(self):
        contract = build_contract(self.sample())
        self.assertEqual(contract["score"]["total"], 65)
        self.assertEqual(contract["winrate"]["final"], 61)
        self.assertEqual(contract["plan"]["risk_math"]["rr_to_tp1"], 2.5)

    def test_claimed_score_or_winrate_mismatch_is_rejected(self):
        payload = self.sample()
        payload["score"]["total"] = 66
        with self.assertRaisesRegex(ValueError, r"orderflow \+ chart"):
            build_contract(payload)
        payload = self.sample()
        payload["winrate"]["final"] = 62
        with self.assertRaisesRegex(ValueError, r"anchor \+ adjustments"):
            build_contract(payload)

    def test_invalid_directional_risk_is_rejected(self):
        payload = self.sample()
        payload["plan"]["stop"] = 62000
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            build_contract(payload)

    def test_contract_hash_detects_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            contract = build_contract(self.sample())
            path.write_text(json.dumps(contract), encoding="utf-8")
            validate_contract_file(path, "2026-07-10", "evening")
            contract["score"]["total"] = 99
            path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                validate_contract_file(path, "2026-07-10", "evening")

    def extended_sample(self):
        payload = self.sample()
        payload["trading_date"] = "2026-07-11"
        payload["plan"].update(
            {
                "tp2": 61500,
                "tp1_close_pct": 50,
                "tp2_close_pct": 50,
                "defense_first_trigger": 62550,
                "defense_second_trigger": 62400,
            }
        )
        return payload

    def test_extended_maker_contract_cutover_and_frozen_execution_rules(self):
        self.assertFalse(maker_execution_contract_required("2026-07-11", "midday"))
        self.assertTrue(maker_execution_contract_required("2026-07-11", "evening"))
        contract = build_contract(self.extended_sample())
        self.assertEqual(contract["schema_version"], "trading-decision-contract-v2")
        execution = contract["plan"]["maker_execution"]
        self.assertEqual(execution["tp1_close_pct"], 50)
        self.assertEqual(execution["tp2_close_pct"], 50)
        self.assertEqual(execution["defense_first_trigger"], 62550)
        self.assertEqual(execution["defense_second_trigger"], 62400)
        self.assertEqual(
            execution["defense_second_action"], "move-stop-to-breakeven-only"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            self.assertEqual(
                validate_contract_file(path, "2026-07-11", "evening"), contract
            )

    def test_cutover_rejects_hash_valid_legacy_contract(self):
        legacy = build_contract(self.sample())
        legacy["trading_date"] = "2026-07-11"
        without_hash = dict(legacy)
        without_hash.pop("contract_sha256")
        import hashlib

        legacy["contract_sha256"] = hashlib.sha256(
            json.dumps(
                without_hash,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.json"
            path.write_text(json.dumps(legacy), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "v2 is required"):
                validate_contract_file(path, "2026-07-11", "evening")

    def test_extended_maker_contract_rejects_ledger_or_trigger_drift(self):
        payload = self.extended_sample()
        payload["plan"]["tp1_close_pct"] = 70
        payload["plan"]["tp2_close_pct"] = 30
        with self.assertRaisesRegex(ValueError, "TP1 50%"):
            build_contract(payload)
        payload = self.extended_sample()
        payload["plan"]["defense_second_trigger"] = 62399
        with self.assertRaisesRegex(ValueError, "2R"):
            build_contract(payload)

    def _v3_seed(self, root: Path):
        capture, reasoning_input = ReasoningContractTests().seed(root)
        reasoning = build_reasoning_contract(
            reasoning_input, capture_manifest_path=capture, root=root
        )
        path = (
            root
            / "runtime_state"
            / "2026-07-12"
            / "reasoning_contract_midday.json"
        )
        path.write_text(json.dumps(reasoning, ensure_ascii=False), encoding="utf-8")
        return path

    def test_v3_ladder_enumerates_every_nonempty_fill_subset(self):
        self.assertTrue(reasoning_bound_contract_required("2026-07-12", "midday"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reasoning = self._v3_seed(root)
            payload = {
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
                    "cancel_before_fill": "若结构先失效则撤销全部未成交挂单",
                },
            }
            contract = build_contract(
                payload, reasoning_contract_path=reasoning, root=root
            )
            self.assertEqual(contract["schema_version"], "trading-decision-contract-v3")
            self.assertEqual(contract["plan"]["risk_math"]["scenario_count"], 3)
            self.assertIsNone(
                contract["plan"]["maker_execution"]["defense_first_trigger"]
            )
            self.assertEqual(
                contract["plan"]["maker_execution"]["defense_trigger_basis"],
                "actual_weighted_fill_required",
            )
            self.assertEqual(
                contract["winrate"]["calibration_status"],
                "insufficient_outcome_samples",
            )
            target = root / "runtime_state" / "2026-07-12" / "decision_contract_midday.json"
            target.write_text(json.dumps(contract, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(
                validate_contract_file(
                    target, "2026-07-12", "midday", root=root
                ),
                contract,
            )

    def test_v3_rejects_any_unsafe_ladder_fill_scenario(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reasoning = self._v3_seed(root)
            payload = {
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
                        {"id": "level.bad", "price": 101, "allocation_pct": 50},
                    ],
                    "stop": 99.5,
                    "tp1": 106,
                    "tp2": 107,
                    "tp1_close_pct": 50,
                    "tp2_close_pct": 50,
                    "cancel_before_fill": "若结构先失效则撤销全部未成交挂单",
                },
            }
            with self.assertRaisesRegex(ValueError, "nominal risk exceeds 3%"):
                build_contract(payload, reasoning_contract_path=reasoning, root=root)

    def test_conditional_zone_cannot_masquerade_as_executable_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reasoning = self._v3_seed(root)
            contract = build_contract(
                {
                    "trading_date": "2026-07-12",
                    "slot": "midday",
                    "plan": {
                        "direction": "short",
                        "entry_mode": "conditional_zone",
                        "exchange": "OKX",
                        "instrument": "BTCUSDT",
                        "leverage": 5,
                        "position_notional_usdt": 750,
                        "zone_low": 100,
                        "zone_high": 101,
                        "confirmation_rule": "等待压力区出现明确拒绝后再生成精确订单",
                    },
                },
                reasoning_contract_path=reasoning,
                root=root,
            )
            self.assertFalse(contract["plan"]["executable"])
            self.assertEqual(
                contract["plan"]["execution_status"], "awaiting_confirmation"
            )

    def test_v3_uses_exact_decimal_risk_before_display_rounding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reasoning = self._v3_seed(root)
            payload = {
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
                        {"id": "level.b", "price": 100.00000001, "allocation_pct": 50},
                    ],
                    "stop": 99.39999992,
                    "tp1": 102,
                    "tp2": 103,
                    "tp1_close_pct": 50,
                    "tp2_close_pct": 50,
                    "cancel_before_fill": "结构先失效则撤销未成交挂单",
                },
            }
            with self.assertRaisesRegex(ValueError, "nominal risk exceeds 3%"):
                build_contract(payload, reasoning_contract_path=reasoning, root=root)

    def test_v3_rejects_single_entry_maker_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reasoning = self._v3_seed(root)
            payload = {
                "trading_date": "2026-07-12",
                "slot": "midday",
                "plan": {
                    "direction": "long",
                    "entry_mode": "single",
                    "exchange": "OKX",
                    "instrument": "BTCUSDT",
                    "leverage": 5,
                    "position_notional_usdt": 750,
                    "entry": 100,
                    "stop": 99.5,
                    "tp1": 102,
                    "tp2": 103,
                    "tp1_close_pct": 50,
                    "tp2_close_pct": 50,
                    "cancel_before_fill": "结构先失效则撤销未成交挂单",
                },
            }
            with self.assertRaisesRegex(ValueError, "single entry is forbidden"):
                build_contract(payload, reasoning_contract_path=reasoning, root=root)

    def test_v3_enforces_exchange_leverage_and_instrument_position_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reasoning = self._v3_seed(root)
            base = {
                "trading_date": "2026-07-12",
                "slot": "midday",
                "plan": {
                    "direction": "short",
                    "entry_mode": "conditional_zone",
                    "exchange": "BINANCE",
                    "instrument": "BTCUSDT",
                    "leverage": 5,
                    "position_notional_usdt": 750,
                    "zone_low": 100,
                    "zone_high": 101,
                    "confirmation_rule": "等待压力区出现拒绝后再生成精确订单",
                },
            }
            with self.assertRaisesRegex(ValueError, "exchange=OKX"):
                build_contract(base, reasoning_contract_path=reasoning, root=root)


if __name__ == "__main__":
    unittest.main()
