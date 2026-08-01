from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CaptureDeltaPlanTests(unittest.TestCase):
    def test_manifest_schema_adds_provider_summary_without_invalidating_v1_history(self):
        schema = json.loads(
            (ROOT / "schemas/capture_run_manifest_schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn("rate_expectation_provider", schema["properties"])
        self.assertNotIn("rate_expectation_provider", schema["required"])
        provider = schema["properties"]["rate_expectation_provider"]["anyOf"][1]
        self.assertFalse(provider["additionalProperties"])
        self.assertIn("provider_fallback_used", provider["required"])
        self.assertIn("full_fallback_used", schema["properties"])
        self.assertIn("full_fallback_suppressed_reason_code", schema["properties"])

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
        self.assertEqual(
            scripts,
            [
                "capture_blockbeats.js",
                "capture_coinglass.js",
                "capture_exo.js",
                "capture_rate_expectation.js",
                "capture_farside_btc_etf.js",
                "capture_tv.js",
            ],
        )
        self.assertNotIn("reused_sources", plan)
        self.assertEqual(
            plan["fallback"],
            (
                "capture_all.js once only for eligible non-rate core evidence failure; "
                "rate-provider failure or consumed Plan C hard-stops without full fallback"
            ),
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
        state = (
            ROOT / "tools/browser_capture/rate_expectation_state.js"
        ).read_text(encoding="utf-8")
        for text in (delta, full):
            self.assertIn("requireWorkflowLease", text)
            self.assertIn("immutableManifestPath", text)
            self.assertIn("writeImmutableJson", text)
        self.assertNotIn("logic version", delta.lower())
        self.assertNotIn("reused_sources", delta)
        self.assertNotIn("hasCommittedReusableFedWatch", delta)
        self.assertIn("decideFullCaptureFallback", delta)
        self.assertIn("rate_expectation_capture_failed", state)
        self.assertIn("plan_c_attempt_already_consumed", state)
        self.assertIn("full_fallback_suppressed_reason_code", delta)


if __name__ == "__main__":
    unittest.main()
