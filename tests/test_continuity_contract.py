from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runtime import continuity_contract


class ContinuityContractTests(unittest.TestCase):
    LOCK = {"manifest_sha256": "a" * 64}

    def payload(self):
        return {
            "reasoning_lock_sha256": "a" * 64,
            "prior_plan": {
                "source_kind": "none", "reference": None, "source_sha256": None,
                "observed_at": None, "status": "none",
                "executable_order_count_before": 0,
                "summary": "当前没有需要继承的系统Maker订单。",
            },
            "current_plan": {
                "action": "new", "old_order_cancelled": False,
                "new_order_created": True, "executable_order_count_after": 1,
                "independent_analysis_changed_after_lock": False,
                "reason": "独立推理锁定后确认没有旧单，因此建立一张新计划订单。",
            },
            "projection_section": "opening_quote",
            "report_text": "订单生命周期：独立分析锁定后确认无旧单，本时段新建一张系统Maker订单，同一时刻仅保留这一张。",
        }

    def test_new_plan_is_bound_after_reasoning_lock(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(
            continuity_contract, "validate_reasoning_lock", return_value=self.LOCK
        ):
            root = Path(td)
            lock = root / "runtime_state" / "2026-07-12" / "reasoning_lock_midday.json"
            lock.parent.mkdir(parents=True)
            lock.write_text("{}", encoding="utf-8")
            result = continuity_contract.build_contract(
                self.payload(), reasoning_lock_path=lock,
                trading_date="2026-07-12", slot="midday", root=root
            )
            self.assertEqual(result["current_plan"]["executable_order_count_after"], 1)
            self.assertFalse(result["current_plan"]["independent_analysis_changed_after_lock"])

    def test_cancel_replace_cannot_leave_two_orders(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(
            continuity_contract, "validate_reasoning_lock", return_value=self.LOCK
        ):
            root = Path(td)
            lock = root / "runtime_state" / "2026-07-12" / "reasoning_lock_midday.json"
            lock.parent.mkdir(parents=True)
            lock.write_text("{}", encoding="utf-8")
            payload = self.payload()
            payload["current_plan"].update({
                "action": "cancel_replace", "old_order_cancelled": False,
                "new_order_created": True, "executable_order_count_after": 1,
            })
            payload["report_text"] = "订单生命周期：旧计划已经核对，本时段撤旧挂新并确保同一时刻只保留一张系统Maker订单。"
            with self.assertRaisesRegex(ValueError, "cancel_replace requires"):
                continuity_contract.build_contract(
                    payload, reasoning_lock_path=lock,
                    trading_date="2026-07-12", slot="midday", root=root
                )


if __name__ == "__main__":
    unittest.main()
