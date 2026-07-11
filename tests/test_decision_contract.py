from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.decision_contract import build_contract, validate_contract_file


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


if __name__ == "__main__":
    unittest.main()
