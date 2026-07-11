from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runtime.host_usage_import import summarize_session
from runtime.context_pack import authority_manifest, authority_read_plan
from runtime.phase_contract import (
    BEGIN_BUNDLE_MARKER,
    END_BUNDLE_MARKER,
    MAX_PHASE_BUNDLE_BYTES,
    build_phase_contract,
    format_phase_output,
    render_phase_contract,
)
from runtime.state_store import LOGIC_FILES


class EfficiencyContractTests(unittest.TestCase):
    def test_host_usage_sums_real_last_usage_and_counts_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "Trading-System"
            root.mkdir()
            session = Path(directory) / "rollout-thread.jsonl"
            rows = [
                {"type": "session_meta", "payload": {"id": "thread", "cwd": str(root)}},
                {"type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": 100, "cached_input_tokens": 60, "output_tokens": 10, "reasoning_output_tokens": 5}}}},
                {"type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": 200, "cached_input_tokens": 100, "output_tokens": 20, "reasoning_output_tokens": 8}}}},
                {"type": "response_item", "payload": {"type": "function_call"}},
                {"type": "event_msg", "payload": {"type": "context_compacted"}},
            ]
            session.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            result = summarize_session(session, expected_root=root)
            self.assertEqual(result["model_turns"], 2)
            self.assertEqual(result["uncached_input_tokens"], 140)
            self.assertEqual(result["tool_calls"], 1)
            self.assertEqual(result["context_compactions"], 1)

    def test_phase_contract_bundles_selected_authority_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in LOGIC_FILES.values():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"authority {relative}\n", encoding="utf-8")
            payload, target = build_phase_contract("2026-07-10", "evening", "always_read", root=root)
            text = target.read_text(encoding="utf-8")
            self.assertEqual(payload["source_files"], list(__import__("runtime.context_pack", fromlist=["authority_read_plan"]).authority_read_plan()["always_read"]))
            for relative in payload["source_files"]:
                self.assertEqual(text.count(f"## {relative}"), 1)

    def test_phase_contract_can_emit_one_complete_hash_bound_result(self):
        payload = {
            "schema_version": "authority-phase-contract-v2",
            "complete": True,
            "bundle_bytes": len("full authority".encode("utf-8")),
        }
        output = format_phase_output(
            payload,
            "full authority",
            emit_bundle=True,
        )
        self.assertIn(BEGIN_BUNDLE_MARKER, output)
        self.assertTrue(output.rstrip().endswith(END_BUNDLE_MARKER))
        self.assertEqual(output.count("full authority"), 1)

    def test_live_phase_plan_is_complete_and_each_bundle_fits_host_limit(self):
        plan = authority_read_plan()
        self.assertNotIn("analysis_scoring", plan)
        self.assertEqual(
            {
                *plan["analysis_orderflow"],
                *plan["analysis_chart_winrate"],
                *plan["analysis_agents"],
            },
            {
                LOGIC_FILES[name].replace("\\", "/")
                for name in (
                    "reasoning_depth",
                    "scoring_system",
                    "orderflow",
                    "orderflow_scoring",
                    "chart",
                    "chart_scoring",
                    "winrate",
                    "thresholds",
                    "trading_constitution",
                    "maker_principles",
                    "cannot_do",
                    "news_agent",
                    "scoring_agent",
                    "footprint_agent",
                )
            },
        )
        flattened = [path for paths in plan.values() for path in paths]
        self.assertEqual(len(flattened), len(set(flattened)))
        for phase in plan:
            payload, rendered = render_phase_contract(
                "2026-07-11",
                "morning",
                phase,
            )
            self.assertTrue(payload["complete"])
            self.assertLessEqual(payload["bundle_bytes"], MAX_PHASE_BUNDLE_BYTES)
            self.assertEqual(payload["bundle_bytes"], len(rendered.encode("utf-8")))
            for relative in payload["source_files"]:
                self.assertEqual(rendered.count(f"## {relative}"), 1)

        manifest_paths = {item["path"] for item in authority_manifest()}
        self.assertIn(LOGIC_FILES["daily_skill"].replace("\\", "/"), manifest_paths)
        self.assertNotIn(
            LOGIC_FILES["daily_skill"].replace("\\", "/"),
            plan["workflow_entry"],
        )

    def test_direct_script_entrypoints_do_not_require_pythonpath(self):
        root = Path(__file__).resolve().parents[1]
        for relative in (
            "runtime/host_usage_import.py",
            "runtime/phase_contract.py",
            "runtime/prelock_safe_search.py",
        ):
            completed = subprocess.run(
                [sys.executable, str(root / relative), "--help"],
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
