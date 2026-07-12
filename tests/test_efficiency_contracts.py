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
    BEGIN_PART_MARKER,
    END_BUNDLE_MARKER,
    END_PART_MARKER,
    MAX_PHASE_BUNDLE_BYTES,
    MAX_TRANSPORT_OUTPUT_BYTES,
    MAX_TRANSPORT_PART_BYTES,
    build_phase_contract,
    format_phase_part_output,
    format_phase_output,
    render_phase_contract,
    split_phase_transport,
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
                {"type": "turn_context", "payload": {"turn_id": "turn", "cwd": str(root), "model": "gpt-test", "effort": "max"}},
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

    def test_large_full_bundle_requires_bounded_transport_parts(self):
        payload = {
            "schema_version": "authority-phase-contract-v2",
            "complete": True,
            "bundle_bytes": MAX_TRANSPORT_OUTPUT_BYTES,
        }
        rendered = "界" * MAX_TRANSPORT_OUTPUT_BYTES
        with self.assertRaisesRegex(ValueError, "use --emit-part"):
            format_phase_output(payload, rendered, emit_bundle=True)

    def test_transport_parts_are_lossless_bounded_and_hash_bound(self):
        rendered = ("完整权威\n" * 12000) + "END"
        payload = {
            "schema_version": "authority-phase-contract-v2",
            "complete": True,
            "bundle_bytes": len(rendered.encode("utf-8")),
        }
        parts = split_phase_transport(rendered)
        self.assertEqual("".join(parts), rendered)
        self.assertGreater(len(parts), 1)
        for part in parts[:-1]:
            self.assertTrue(part.endswith("\n"))
        bundle_hashes = set()
        for index, part in enumerate(parts, start=1):
            self.assertLessEqual(len(part.encode("utf-8")), MAX_TRANSPORT_PART_BYTES)
            output = format_phase_part_output(payload, rendered, part_index=index)
            header = json.loads(output.splitlines()[0])
            bundle_hashes.add(header["bundle_sha256"])
            self.assertEqual(header["part_index"], index)
            self.assertEqual(header["part_count"], len(parts))
            self.assertEqual(header["part_bytes"], len(part.encode("utf-8")))
            self.assertLessEqual(len(output.encode("utf-8")), MAX_TRANSPORT_OUTPUT_BYTES)
            self.assertIn(BEGIN_PART_MARKER.format(index=index, count=len(parts)), output)
            self.assertTrue(output.endswith(END_PART_MARKER.format(index=index, count=len(parts))))
        self.assertEqual(len(bundle_hashes), 1)
        with self.assertRaises(ValueError):
            format_phase_part_output(payload, rendered, part_index=0)
        with self.assertRaises(ValueError):
            format_phase_part_output(payload, rendered, part_index=len(parts) + 1)

    def test_transport_handles_empty_and_overlong_multibyte_lines(self):
        self.assertEqual(split_phase_transport(""), [""])
        with self.assertRaises(ValueError):
            split_phase_transport("authority", max_part_bytes=0)

        rendered = "界" * (MAX_TRANSPORT_PART_BYTES + 7)
        parts = split_phase_transport(rendered)
        self.assertGreater(len(parts), 1)
        self.assertEqual("".join(parts), rendered)
        for part in parts:
            self.assertLessEqual(len(part.encode("utf-8")), MAX_TRANSPORT_PART_BYTES)

        boundary = ("a" * MAX_TRANSPORT_PART_BYTES) + "\nnext"
        boundary_parts = split_phase_transport(boundary)
        self.assertEqual("".join(boundary_parts), boundary)
        self.assertEqual(len(boundary_parts[0].encode("utf-8")), MAX_TRANSPORT_PART_BYTES)

    def test_live_phase_plan_is_complete_and_each_transport_part_fits_host_limit(self):
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
                    "scoring_contract",
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
            parts = split_phase_transport(rendered)
            self.assertEqual("".join(parts), rendered)
            for index, part in enumerate(parts, start=1):
                self.assertLessEqual(len(part.encode("utf-8")), MAX_TRANSPORT_PART_BYTES)
                output = format_phase_part_output(payload, rendered, part_index=index)
                self.assertLessEqual(len(output.encode("utf-8")), MAX_TRANSPORT_OUTPUT_BYTES)
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
            "runtime/automation_gate.py",
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
