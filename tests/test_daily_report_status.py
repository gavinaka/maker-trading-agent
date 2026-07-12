from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from runtime import daily_report_status as status


class DailyReportStatusTests(unittest.TestCase):
    def test_midday_ready_to_claim_after_prior_delivery_complete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def fake_delivery_complete(_date: str, slot: str, _root: Path) -> bool:
                return slot == "morning"

            with patch.object(status, "_delivery_complete", fake_delivery_complete):
                payload = status.daily_status(root, "2026-07-08", "midday")

            self.assertEqual(payload["next_action"]["state"], "ready_to_claim")
            self.assertEqual(
                payload["next_action"]["gate_key"],
                "daily-2026-07-08-midday",
            )

    def test_daily_complete_requires_delivery_and_done_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gate = root / "runtime_state" / "automation_gate"
            gate.mkdir(parents=True)
            (gate / "daily-2026-07-08-morning.done.json").write_text(
                json.dumps({"key": "daily-2026-07-08-morning"}),
                encoding="utf-8",
            )

            with patch.object(status, "_delivery_complete", return_value=True):
                payload = status.daily_status(root, "2026-07-08", "morning")

            self.assertEqual(payload["next_action"]["state"], "complete")

    def test_daily_active_lease_blocks_new_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "runtime_state"
            state.mkdir(parents=True)
            (state / "workflow_lease.json").write_text(
                json.dumps(
                    {
                        "status": "active",
                        "trading_date": "2026-07-08",
                        "slot": "morning",
                        "token": "secret-token",
                        "lease_id": "a" * 64,
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(status, "_delivery_complete", return_value=False):
                payload = status.daily_status(root, "2026-07-08", "midday")

            self.assertEqual(
                payload["next_action"]["state"],
                "blocked_by_other_active_lease",
            )
            self.assertNotIn("token", payload["workflow_lease"]["payload"])

    def test_daily_gate_lock_is_orphaned_until_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gate = root / "runtime_state" / "automation_gate"
            gate.mkdir(parents=True)
            (gate / "daily-2026-07-08-midday.lock.json").write_text(
                json.dumps(
                    {
                        "key": "daily-2026-07-08-midday",
                        "token": "gate-token",
                        "claimed_at": (
                            datetime.now().astimezone() - timedelta(minutes=5)
                        ).isoformat(timespec="seconds"),
                    }
                ),
                encoding="utf-8",
            )

            def fake_delivery_complete(_date: str, slot: str, _root: Path) -> bool:
                return slot == "morning"

            with patch.object(status, "_delivery_complete", fake_delivery_complete):
                payload = status.daily_status(root, "2026-07-08", "midday")

            self.assertEqual(
                payload["next_action"]["state"],
                "orphaned_automation_gate",
            )
            self.assertTrue(payload["gate"]["locked"])

    def test_daily_partial_artifacts_require_manual_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "runtime_state" / "2026-07-08"
            state.mkdir(parents=True)
            (state / "analysis_midday.json").write_text(
                json.dumps({"slot": "midday"}),
                encoding="utf-8",
            )

            def fake_delivery_complete(_date: str, slot: str, _root: Path) -> bool:
                return slot == "morning"

            with patch.object(status, "_delivery_complete", fake_delivery_complete):
                payload = status.daily_status(root, "2026-07-08", "midday")

            self.assertEqual(
                payload["next_action"]["state"],
                "manual_review_required",
            )
            self.assertIn("analysis", payload["artifacts"]["partial_keys"])

    def test_future_midday_requires_same_day_pretrade_gate_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def fake_delivery_complete(_date: str, slot: str, _root: Path) -> bool:
                return slot == "morning"

            with patch.object(status, "_delivery_complete", fake_delivery_complete):
                payload = status.daily_status(root, "2026-07-12", "midday")

            self.assertEqual(
                payload["next_action"]["state"], "manual_review_required"
            )
            self.assertIn(
                "same_day_pretrade_gate_contract_missing_or_invalid",
                payload["next_action"]["reasons"],
            )

    def test_future_morning_can_claim_before_gate_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(status, "_delivery_complete", return_value=False):
                payload = status.daily_status(root, "2026-07-12", "morning")
            self.assertEqual(payload["next_action"]["state"], "ready_to_claim")
            self.assertTrue(payload["pretrade_gate_contract"]["required"])
            self.assertFalse(payload["pretrade_gate_contract"]["valid"])

    def test_monthly_artifact_without_gate_needs_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reviews = root / "reviews"
            reviews.mkdir()
            (reviews / "2026-07_monthly.md").write_text(
                "# monthly review\n",
                encoding="utf-8",
            )

            payload = status.periodic_status(root, "monthly", "2026-07-31")

            self.assertEqual(
                payload["next_action"]["state"],
                "existing_artifact_needs_verification",
            )
            self.assertTrue(payload["artifacts"]["exists"]["review_markdown"])

    def test_weekly_done_gate_is_complete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gate = root / "runtime_state" / "automation_gate"
            gate.mkdir(parents=True)
            (gate / "weekly-2026-W28.done.json").write_text(
                json.dumps({"key": "weekly-2026-W28"}),
                encoding="utf-8",
            )

            payload = status.periodic_status(root, "weekly", "2026-07-12")

            self.assertEqual(payload["next_action"]["state"], "complete")
            self.assertEqual(payload["next_action"]["gate_key"], "weekly-2026-W28")


if __name__ == "__main__":
    unittest.main()
