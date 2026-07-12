from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.decision_contract import (
    build_contract,
    maker_execution_contract_required,
    validate_contract_file,
)


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
        with self.assertRaisesRegex(ValueError, "orderflow \+ chart"):
            build_contract(payload)
        payload = self.sample()
        payload["winrate"]["final"] = 62
        with self.assertRaisesRegex(ValueError, "anchor \+ adjustments"):
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


if __name__ == "__main__":
    unittest.main()
