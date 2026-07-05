from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CaptureDeltaPlanTests(unittest.TestCase):
    def test_plan_is_sequential_and_bounded(self):
        completed = subprocess.run(
            [
                "node",
                "tools/browser_capture/capture_delta.js",
                "--slot",
                "midday",
                "--plan-only",
            ],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=True,
        )
        plan = json.loads(completed.stdout)
        scripts = [item["script"] for item in plan["captures"]]
        self.assertIn("capture_coinglass.js", scripts)
        self.assertIn("capture_exo.js", scripts)
        self.assertIn("capture_farside_btc_etf.js", scripts)
        self.assertIn("capture_tv.js", scripts)
        self.assertEqual(
            plan["fallback"],
            "capture_all.js once only for failed, missing, stale, or invalid core evidence",
        )
        self.assertNotIn("logic", plan["fallback"].lower())

    def test_plan_accepts_explicit_evening_slot(self):
        completed = subprocess.run(
            [
                "node",
                "tools/browser_capture/capture_delta.js",
                "--slot",
                "evening",
                "--plan-only",
            ],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=True,
        )
        self.assertEqual(json.loads(completed.stdout)["slot"], "evening")

    def test_delta_rejects_unsupported_slot(self):
        completed = subprocess.run(
            [
                "node",
                "tools/browser_capture/capture_delta.js",
                "--slot",
                "morning",
                "--plan-only",
            ],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("unsupported delta slot", completed.stderr)

    def test_delta_rejects_conflicting_legacy_evening_alias(self):
        completed = subprocess.run(
            [
                "node",
                "tools/browser_capture/capture_delta.js",
                "--slot",
                "midday",
                "--evening",
                "--plan-only",
            ],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("cannot be combined", completed.stderr)

    def test_capture_sources_use_immutable_slot_manifests_and_workflow_lease(self):
        delta = (ROOT / "tools/browser_capture/capture_delta.js").read_text(
            encoding="utf-8"
        )
        full = (ROOT / "tools/browser_capture/capture_all.js").read_text(
            encoding="utf-8"
        )
        for text in (delta, full):
            self.assertIn("requireWorkflowLease", text)
            self.assertIn("immutableManifestPath", text)
            self.assertIn("writeImmutableJson", text)
        self.assertNotIn("logic version", delta.lower())


if __name__ == "__main__":
    unittest.main()
