from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FedWatchCapturePolicyTests(unittest.TestCase):
    def test_collector_navigates_and_waits_for_real_probability_tool(self) -> None:
        source = (ROOT / "tools/browser_capture/capture_fedwatch.js").read_text(
            encoding="utf-8"
        )
        contract = (
            ROOT / "data_sources/rate_expectation_provider_contract.json"
        ).read_text(encoding="utf-8")
        self.assertIn("await page.goto(URL", source)
        self.assertIn("CONTRACT.cme.ready_marker", source)
        self.assertIn("Target Rate Probabilities", contract)
        self.assertIn("if (!ready)", source)

    def test_cme_collector_is_primary_only_and_seals_closed_result(self) -> None:
        source = (ROOT / "tools/browser_capture/capture_fedwatch.js").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("capture_kalshi_feddecision.js", source)
        self.assertNotIn("api.elections.kalshi.com", source)
        self.assertIn("cme_tool_content_load_error", source)
        self.assertIn("cme_page_schema_unclassified", source)
        self.assertIn("attempt_sha256", source)

    def test_provider_state_machine_is_the_unique_six_source_entry(self) -> None:
        full = (ROOT / "tools/browser_capture/capture_all.js").read_text(
            encoding="utf-8"
        )
        delta = (ROOT / "tools/browser_capture/capture_delta.js").read_text(
            encoding="utf-8"
        )
        orchestrator = (
            ROOT / "tools/browser_capture/capture_rate_expectation.js"
        ).read_text(encoding="utf-8")
        for source in (full, delta):
            self.assertIn("capture_rate_expectation.js", source)
            self.assertNotIn("'capture_fedwatch.js'", source)
        self.assertIn("decision.action === 'select_primary'", orchestrator)
        self.assertIn("decision.action === 'hard_stop'", orchestrator)
        self.assertEqual(orchestrator.count("capture_kalshi_feddecision.js"), 1)
        self.assertIn("VNEXT_PYTHON_EXECUTABLE", orchestrator)
        self.assertIn("runtime_vnext.rate_expectation", orchestrator)
        self.assertLess(
            orchestrator.index("VNEXT_PYTHON_EXECUTABLE"),
            orchestrator.index("capture_kalshi_feddecision.js"),
        )

    def test_authority_forbids_host_clock_comparison_of_display_time(self) -> None:
        collector_policy = (ROOT / "data_sources/collectors/fedwatch.md").read_text(
            encoding="utf-8"
        )
        skill = (ROOT / ".agents/skills/daily-report/SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("不得把它与主机", collector_policy)
        self.assertIn("触发重采或硬停", collector_policy)
        self.assertIn("never compare it with the host UTC/Beijing/file clock", skill)
        self.assertIn("never hard-stop or recapture", skill)


if __name__ == "__main__":
    unittest.main()
