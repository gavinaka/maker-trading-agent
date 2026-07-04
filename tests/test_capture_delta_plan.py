from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CaptureDeltaPlanTests(unittest.TestCase):
    def test_plan_is_sequential_and_bounded(self):
        completed = subprocess.run(
            ["node", "tools/browser_capture/capture_delta.js", "--plan-only"],
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
        self.assertIn("capture_tv.js", scripts)
        self.assertEqual(
            plan["fallback"],
            "capture_all.js once only for failed, missing, stale, or invalid core evidence",
        )
        self.assertNotIn("logic", plan["fallback"].lower())

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
