from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime import pretrade_gate


SOURCE_PAGE_ID = "11111111-2222-3333-4444-555555555555"


class PretradeGateContractTests(unittest.TestCase):
    def _write(self, root: Path, **overrides):
        values = {
            "source_reference": SOURCE_PAGE_ID,
            "source_observed_at": "2026-07-11T08:20:00+08:00",
            "subjective_conclusion": "可交易",
            "emotion_stable": True,
            "rhythm_consistent": True,
            "result_dependency": False,
            "continuous_stop_loss_count": 0,
            "physical_condition": "normal",
        }
        values.update(overrides)
        return pretrade_gate.write_pretrade_gate_contract(
            "2026-07-11", root=root, **values
        )

    def test_live_gate_is_immutable_and_hash_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload, target = self._write(root)
            validated, validated_target = pretrade_gate.validate_pretrade_gate_contract(
                "2026-07-11", "evening", root=root
            )
            self.assertEqual(validated, payload)
            self.assertEqual(validated_target, target)
            self.assertTrue(payload["allow_trade_today"])
            self.assertEqual(payload["source_slot"], "morning")
            with self.assertRaisesRegex(ValueError, "immutable"):
                self._write(root, subjective_conclusion="不可交易")

    def test_tradable_conclusion_rejects_blocking_field(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "conflicts"):
                self._write(Path(directory), continuous_stop_loss_count=3)

    def test_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, target = self._write(root)
            payload = json.loads(target.read_text(encoding="utf-8"))
            payload["subjective_conclusion"] = "不可交易"
            target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid or changed"):
                pretrade_gate.validate_pretrade_gate_contract(
                    "2026-07-11", "evening", root=root
                )

    def test_transition_binding_detects_gate_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write(root)
            state = root / "runtime_state" / "2026-07-11"
            binding = pretrade_gate.transition_binding(
                "2026-07-11", "evening", root=root
            )
            (state / "transition_evening.json").write_text(
                json.dumps({"pretrade_gate_contract": binding}), encoding="utf-8"
            )
            pretrade_gate.assert_transition_binding(
                "2026-07-11", "evening", root=root
            )
            transition = json.loads(
                (state / "transition_evening.json").read_text(encoding="utf-8")
            )
            transition["pretrade_gate_contract"]["sha256"] = "0" * 64
            (state / "transition_evening.json").write_text(
                json.dumps(transition), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "missing or stale"):
                pretrade_gate.assert_transition_binding(
                    "2026-07-11", "evening", root=root
                )


if __name__ == "__main__":
    unittest.main()
