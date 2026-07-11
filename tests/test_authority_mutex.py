from __future__ import annotations

import argparse
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from runtime import automation_gate
from runtime.authority_mutex import (
    active_production,
    audit_path,
    claim_maintenance,
    maintenance_lock_path,
    recovery_request_path,
    recover_maintenance,
    release_maintenance,
    request_maintenance_recovery,
)
from runtime.workflow_lease import begin_lease


class AuthorityMutexTests(unittest.TestCase):
    def test_new_claim_clears_stale_recovery_request_before_lock_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stale = recovery_request_path(root)
            stale.parent.mkdir(parents=True)
            stale.write_text('{"lock_sha256":"old"}\n', encoding="utf-8")
            claimed = claim_maintenance("repair authority safely", root=root)
            self.assertFalse(stale.exists())
            self.assertTrue(maintenance_lock_path(root).exists())
            release_maintenance(claimed["token"], root=root)

    def test_maintenance_claim_refuses_active_lease_or_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lease = root / "runtime_state" / "workflow_lease.json"
            lease.parent.mkdir(parents=True)
            lease.write_text('{"status":"active"}\n', encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "production is active"):
                claim_maintenance("repair authority safely", root=root)
            lease.unlink()
            gate = root / "runtime_state" / "automation_gate" / "daily.lock.json"
            gate.parent.mkdir(parents=True)
            gate.write_text('{}\n', encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "production is active"):
                claim_maintenance("repair authority safely", root=root)

    def test_maintenance_blocks_gate_and_workflow_lease_until_owner_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            claimed = claim_maintenance("repair authority safely", root=root)
            self.assertTrue(maintenance_lock_path(root).is_file())
            args = argparse.Namespace(
                key="daily-2026-07-12-morning",
                stale_minutes=240,
                done_file=None,
                require_json_flag=[],
            )
            with (
                patch.object(automation_gate, "ROOT", root),
                patch.object(
                    automation_gate,
                    "GATE_DIR",
                    root / "runtime_state" / "automation_gate",
                ),
                self.assertRaisesRegex(RuntimeError, "maintenance mutex is active"),
            ):
                automation_gate.claim(args)
            with self.assertRaisesRegex(RuntimeError, "maintenance mutex is active"):
                begin_lease("2026-07-12", "morning", root=root)
            with self.assertRaisesRegex(RuntimeError, "token does not match"):
                release_maintenance("wrong-token", root=root)
            release_maintenance(claimed["token"], root=root)
            self.assertFalse(maintenance_lock_path(root).exists())
            audit_lines = audit_path(root).read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(audit_lines), 2)
            self.assertNotIn(claimed["token"], "\n".join(audit_lines))
            lease = begin_lease("2026-07-12", "morning", root=root)
            self.assertEqual(lease["status"], "active")

    def test_orphan_recovery_is_explicit_and_audited(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            claimed = claim_maintenance("repair authority safely", root=root)
            with self.assertRaisesRegex(ValueError, "reason must be explicit"):
                request_maintenance_recovery("short", root=root)
            requested_at = datetime(2026, 7, 11, 8, 0, tzinfo=timezone.utc)
            request = request_maintenance_recovery(
                "confirmed orphan after maintainer hard stop",
                owner="Technical expert recovery",
                root=root,
                now=requested_at,
            )
            self.assertTrue(maintenance_lock_path(root).exists())
            self.assertTrue(recovery_request_path(root).exists())
            with self.assertRaisesRegex(RuntimeError, "cooldown is still active"):
                recover_maintenance(
                    challenge=request["challenge"],
                    expected_lock_sha256=request["lock_sha256"],
                    confirm_orphaned=True,
                    root=root,
                    now=requested_at,
                )
            with self.assertRaisesRegex(RuntimeError, "challenge mismatch"):
                recover_maintenance(
                    challenge="wrong-challenge",
                    expected_lock_sha256=request["lock_sha256"],
                    confirm_orphaned=True,
                    root=root,
                    now=requested_at + timedelta(seconds=301),
                )
            recovered = recover_maintenance(
                challenge=request["challenge"],
                expected_lock_sha256=request["lock_sha256"],
                confirm_orphaned=True,
                root=root,
                now=requested_at + timedelta(seconds=301),
            )
            self.assertEqual(recovered["status"], "recovered")
            self.assertFalse(maintenance_lock_path(root).exists())
            audit = audit_path(root).read_text(encoding="utf-8")
            self.assertIn('"event": "recover_requested"', audit)
            self.assertIn('"event": "recover"', audit)
            self.assertNotIn(claimed["token"], audit)

    def test_status_reports_both_sides(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(
                active_production(root),
                {"workflow_lease": None, "automation_gate_locks": []},
            )


if __name__ == "__main__":
    unittest.main()
