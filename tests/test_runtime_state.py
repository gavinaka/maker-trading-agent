from __future__ import annotations

import tempfile
import unittest
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from runtime.delta_engine import compare_snapshots, scan_source_snapshot
from runtime.dependency_graph import (
    active_post_lock_nodes,
    affected_nodes,
    required_analysis_nodes,
    required_post_lock_nodes,
)
from runtime.delivery_evidence import SLOT_CN, validate_delivery_evidence
from runtime.state_store import (
    LOGIC_FILES,
    commit_transition,
    exclusive_lock,
    file_hash,
    prepare_transition,
)
from runtime.workflow_lease import (
    abandon_lease,
    assert_lease,
    begin_lease,
    recover_lease,
)


def seed_inbox(inbox: Path) -> None:
    inbox.mkdir(parents=True, exist_ok=True)
    names = [
        "blockbeats.json",
        "blockbeats.png",
        "coinglass.png",
        "exocharts.png",
        "farside_btc_etf.json",
        "farside_btc_etf.png",
        "fedwatch.png",
        "tradingview_btc_1d.png",
        "tradingview_btc_1d_liq.png",
        "tradingview_btc_4h.png",
        "tradingview_btc_4h_liq.png",
        "tradingview_btc_1h.png",
        "tradingview_btc_1h_liq.png",
        "tradingview_btc_15m.png",
        "tradingview_btc_15m_liq.png",
    ]
    for name in names:
        if name == "blockbeats.json":
            rows = [{"title": f"important flash {index}"} for index in range(3)]
            (inbox / name).write_text(
                json.dumps(
                    {
                        "important_only": True,
                        "capture_window_hours": 12,
                        "selection_policy": (
                            "last_12h_all_important_then_top3_by_fundamental_priority"
                        ),
                        "window_covered": True,
                        "candidate_rows": rows,
                        "selected_rows": rows,
                        "rows": rows,
                    }
                ),
                encoding="utf-8",
            )
        elif name == "farside_btc_etf.json":
            (inbox / name).write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "source": "farside_btc_etf",
                        "url": "https://farside.co.uk/btc/",
                        "unit": "US$m",
                        "latest": {
                            "date": "02 Jul 2026",
                            "date_iso": "2026-07-02",
                            "total_usd_m": 223.5,
                            "direction": "inflow",
                            "funds": {"IBIT": 223.5, "FBTC": 0.0},
                        },
                        "previous": {
                            "date": "01 Jul 2026",
                            "date_iso": "2026-07-01",
                            "total_usd_m": -296.0,
                            "direction": "outflow",
                        },
                        "rows": [
                            {
                                "date": "01 Jul 2026",
                                "date_iso": "2026-07-01",
                                "total_usd_m": -296.0,
                                "direction": "outflow",
                            },
                            {
                                "date": "02 Jul 2026",
                                "date_iso": "2026-07-02",
                                "total_usd_m": 223.5,
                                "direction": "inflow",
                            },
                        ],
                        "validity": {
                            "title_match": True,
                            "table_found": True,
                            "has_total_column": True,
                            "latest_daily_row": True,
                            "latest_total_is_number": True,
                            "latest_row_complete": True,
                        },
                    }
                ),
                encoding="utf-8",
            )
        else:
            (inbox / name).write_bytes(name.encode("ascii"))


def seed_logic_files(root: Path) -> None:
    for relative in LOGIC_FILES.values():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("test authority\n", encoding="utf-8")


def seed_evidence_snapshot(
    root: Path,
    trading_date: str,
    slot: str,
    run_id: str = "0" * 32,
) -> dict:
    inbox = root / "data_sources" / "inbox" / trading_date
    target = root / "runtime_state" / trading_date / "evidence" / slot / run_id
    target.mkdir(parents=True, exist_ok=True)
    files = []
    for source in sorted(inbox.iterdir(), key=lambda item: item.name):
        if not source.is_file() or source.stat().st_size <= 0:
            continue
        destination = target / source.name
        destination.write_bytes(source.read_bytes())
        files.append(
            {
                "path": source.name,
                "sha256": file_hash(destination),
                "size": destination.stat().st_size,
            }
        )
    return {
        "root": f"evidence/{slot}/{run_id}",
        "created_at": "2026-06-30T00:00:00Z",
        "files": files,
    }


def seed_capture_manifest(
    root: Path,
    trading_date: str,
    slot: str,
    *,
    full: bool,
) -> None:
    import json

    directory = root / "runtime_state" / trading_date
    directory.mkdir(parents=True, exist_ok=True)
    suffix = "_full" if full else ""
    evidence_snapshot = seed_evidence_snapshot(root, trading_date, slot)
    (directory / f"capture_{slot}{suffix}.json").write_text(
        json.dumps(
            {
                "date": trading_date,
                "slot": slot,
                "mode": "full_base" if slot == "morning" else "conservative_delta",
                "completed_at": "2026-06-30T00:00:00Z",
                "evidence_snapshot": evidence_snapshot,
                "success": True,
            }
        ),
        encoding="utf-8",
    )


def seed_complete_delivery(root: Path, trading_date: str, slot: str) -> str:
    from datetime import datetime, timedelta, timezone

    page_id = "38ffda35-a098-817d-8e2b-fa12afe16d8c"
    commit_id = "1" * 64
    lease_id = "2" * 64
    outputs = root / "outputs"
    state = root / "runtime_state" / trading_date
    qa_dir = state / "word_qa" / slot / "attempt-1-test"
    sessions = root / "sessions"
    outputs.mkdir(parents=True)
    state.mkdir(parents=True)
    qa_dir.mkdir(parents=True)
    sessions.mkdir(parents=True)

    report = outputs / f"{trading_date}_{slot}_combined.md"
    docx = outputs / f"{trading_date}_{slot}_render.docx"
    pdf = qa_dir / f"{trading_date}_{slot}_render.pdf"
    page = qa_dir / "page-1.png"
    report.write_text("# report\n", encoding="utf-8")
    docx.write_bytes(b"docx")
    pdf.write_bytes(b"pdf")
    page.write_bytes(b"png")
    report_hash = file_hash(report)
    docx_hash = file_hash(docx)
    capture_manifest = {
        "path": f"captures/{slot}/full_base_run1234567890abcdef.json",
        "sha256": "c" * 64,
        "evidence_snapshot": {
            "root": f"evidence/{slot}/run1234567890abcdef",
        },
    }
    source_binding = {
        "capture_manifest_path": (
            f"runtime_state/{trading_date}/"
            f"captures/{slot}/full_base_run1234567890abcdef.json"
        ),
        "capture_manifest_sha256": "c" * 64,
        "evidence_snapshot_root": (
            f"runtime_state/{trading_date}/evidence/{slot}/run1234567890abcdef"
        ),
        "sources": {},
    }
    now = datetime.now(timezone.utc) - timedelta(seconds=2)
    (state / f"render_{slot}.json").write_text(
        json.dumps(
            {
                "status": "success",
                "trading_date": trading_date,
                "slot": slot,
                "source_sha256": report_hash,
                "docx_path": str(docx),
                "docx_sha256": docx_hash,
            }
        ),
        encoding="utf-8",
    )
    (state / f"word_qa_{slot}.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "visual_qa_pass": True,
                "trading_date": trading_date,
                "slot": slot,
                "backend": "word_com",
                "docx_path": str(docx),
                "docx_sha256": docx_hash,
                "pdf_path": str(pdf),
                "pdf_sha256": file_hash(pdf),
                "pages": [{"path": str(page), "sha256": file_hash(page)}],
                "reviewed_at": now.isoformat(),
            }
        ),
        encoding="utf-8",
    )
    (state / f"publish_{slot}.json").write_text(
        json.dumps(
            {
                "status": "success",
                "trading_date": trading_date,
                "slot": slot,
                "page_id": page_id,
                "frozen_verifier_pass": True,
                "unique_page_pass": True,
                "report_sha256": report_hash,
                "source_binding": source_binding,
                "published_at": now.isoformat(),
            }
        ),
        encoding="utf-8",
    )
    state_payload = {
        "trading_date": trading_date,
        "slot": slot,
        "commit_id": commit_id,
        "report_sha256": report_hash,
        "capture_manifest": capture_manifest,
    }
    resolved_name = "base.json" if slot == "morning" else f"resolved_{slot}.json"
    (state / resolved_name).write_text(json.dumps(state_payload), encoding="utf-8")
    (state / "current.json").write_text(json.dumps(state_payload), encoding="utf-8")
    (sessions / "context_log.md").write_text(
        f"## {trading_date}（{SLOT_CN[slot]}日报）\n"
        f"- 报告 SHA-256=`{report_hash}`，Word SHA-256=`{docx_hash}`。\n"
        f"- Word 逐页视觉 QA PASS。\n"
        f"- render manifest=`runtime_state/{trading_date}/render_{slot}.json`，"
        f"Word QA manifest=`runtime_state/{trading_date}/word_qa_{slot}.json`，"
        f"publish manifest=`runtime_state/{trading_date}/publish_{slot}.json`。\n"
        f"- Notion 最终页=`{page_id}`，冻结 verifier PASS。\n",
        encoding="utf-8",
    )
    evidence = validate_delivery_evidence(
        trading_date,
        slot,
        page_id,
        current=state_payload,
        root=root,
    )
    (state / f"delivery_{slot}.json").write_text(
        json.dumps(
            {
                "schema_version": "2.0",
                "trading_date": trading_date,
                "slot": slot,
                "commit_id": commit_id,
                "workflow_lease_id": lease_id,
                "page_id": page_id,
                "published_at": evidence["published_at"],
                "frozen_verifier_pass": True,
                "unique_page_pass": True,
                "word_visual_qa_pass": True,
                "context_log_recorded": True,
                "evidence": evidence,
            }
        ),
        encoding="utf-8",
    )
    return page_id


class DeltaEngineTests(unittest.TestCase):
    def test_unchanged_snapshot_still_requires_full_analysis_recompute(self):
        with tempfile.TemporaryDirectory() as td:
            inbox = Path(td)
            seed_inbox(inbox)
            first = scan_source_snapshot(inbox)
            delta = compare_snapshots(first, scan_source_snapshot(inbox))
            self.assertEqual(delta["changed_sources"], [])
            self.assertEqual(delta["source_affected_nodes"], [])
            self.assertEqual(
                set(delta["invalidated_nodes"]), required_analysis_nodes()
            )

    def test_coinglass_change_invalidates_orderflow_not_news(self):
        with tempfile.TemporaryDirectory() as td:
            inbox = Path(td)
            seed_inbox(inbox)
            first = scan_source_snapshot(inbox)
            (inbox / "coinglass.png").write_bytes(b"changed")
            delta = compare_snapshots(first, scan_source_snapshot(inbox))
            nodes = set(delta["source_affected_nodes"])
            self.assertIn("score:orderflow", nodes)
            self.assertIn("decision:maker", nodes)
            self.assertNotIn("feature:news", nodes)
            self.assertIn("feature:news", set(delta["invalidated_nodes"]))

    def test_missing_source_is_reported(self):
        with tempfile.TemporaryDirectory() as td:
            inbox = Path(td)
            seed_inbox(inbox)
            (inbox / "exocharts.png").unlink()
            delta = compare_snapshots(None, scan_source_snapshot(inbox))
            self.assertIn("exocharts", delta["missing_required_sources"])

    def test_partial_tradingview_pair_is_not_complete(self):
        with tempfile.TemporaryDirectory() as td:
            inbox = Path(td)
            seed_inbox(inbox)
            (inbox / "tradingview_btc_1h_liq.png").unlink()
            snapshot = scan_source_snapshot(inbox)
            self.assertFalse(snapshot["tradingview_1h"]["valid"])
            self.assertIn(
                "tradingview_btc_1h_liq.png",
                snapshot["tradingview_1h"]["missing_artifacts"],
            )

    def test_zero_byte_artifact_is_not_complete(self):
        with tempfile.TemporaryDirectory() as td:
            inbox = Path(td)
            seed_inbox(inbox)
            (inbox / "coinglass.png").write_bytes(b"")
            self.assertFalse(scan_source_snapshot(inbox)["coinglass"]["valid"])

    def test_blockbeats_without_important_only_is_invalid(self):
        with tempfile.TemporaryDirectory() as td:
            inbox = Path(td)
            seed_inbox(inbox)
            (inbox / "blockbeats.json").write_text(
                json.dumps({"important_only": False}),
                encoding="utf-8",
            )
            source = scan_source_snapshot(inbox)["blockbeats"]
            self.assertTrue(source["mechanically_complete"])
            self.assertFalse(source["valid"])
            self.assertIn(
                "blockbeats.json must record important_only=true",
                source["invalid_reasons"],
            )

    def test_farside_btc_etf_without_numeric_latest_total_is_invalid(self):
        with tempfile.TemporaryDirectory() as td:
            inbox = Path(td)
            seed_inbox(inbox)
            payload = json.loads((inbox / "farside_btc_etf.json").read_text())
            payload["latest"]["total_usd_m"] = "223.5"
            (inbox / "farside_btc_etf.json").write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            source = scan_source_snapshot(inbox)["farside_btc_etf"]
            self.assertTrue(source["mechanically_complete"])
            self.assertFalse(source["valid"])
            self.assertIn(
                "farside_btc_etf.json latest.total_usd_m must be numeric",
                source["invalid_reasons"],
            )

    def test_farside_placeholder_zero_row_without_published_funds_is_invalid(self):
        with tempfile.TemporaryDirectory() as td:
            inbox = Path(td)
            seed_inbox(inbox)
            payload = json.loads((inbox / "farside_btc_etf.json").read_text())
            payload["latest"].update(
                {
                    "date": "14 Jul 2026",
                    "date_iso": "2026-07-14",
                    "total_usd_m": 0.0,
                    "direction": "flat",
                    "funds": {"IBIT": None, "FBTC": None},
                }
            )
            payload["validity"]["latest_row_complete"] = False
            (inbox / "farside_btc_etf.json").write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            source = scan_source_snapshot(inbox)["farside_btc_etf"]
            self.assertFalse(source["valid"])
            self.assertIn(
                "farside_btc_etf.json latest row must contain at least one published fund value",
                source["invalid_reasons"],
            )


class DependencyTests(unittest.TestCase):
    def _analysis_lock(self, slot: str, commit_id: str) -> dict:
        return {
            "trading_date": "2026-06-29",
            "slot": slot,
            "commit_id": commit_id,
            "report_sha256": "a" * 64,
            "max_reasoning_confirmed": True,
            "five_source_validation_passed": True,
            "full_analysis_confirmed": True,
            "prior_judgment_read_before_lock": False,
            "max_through_analysis_confirmed": True,
            "max_through_post_lock_confirmed": True,
            "analysis_validation": {
                "lint_passed": True,
                "report_state_validated": True,
                "report_state_omissions": [],
                "source_coverage_validated": True,
                "position_coupling_absent": True,
            },
            "completed_nodes": sorted(required_analysis_nodes(slot)),
            "post_lock_completed_nodes": sorted(required_post_lock_nodes(slot)),
        }

    def test_prepare_hard_stops_without_full_workflow_depth_confirmation(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, "full workflow depth"):
                prepare_transition(
                    "2026-06-30",
                    "morning",
                    root=Path(td),
                    max_reasoning_confirmed=False,
                )

    def test_prepare_records_full_workflow_depth_without_exposing_parent_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            seed_logic_files(root)
            seed_inbox(root / "data_sources" / "inbox" / "2026-06-30")
            seed_capture_manifest(root, "2026-06-30", "morning", full=True)
            transition, _ = prepare_transition(
                "2026-06-30",
                "morning",
                root=root,
                max_reasoning_confirmed=True,
            )
            self.assertTrue(
                transition["analysis_policy"]["full_workflow_depth_confirmed"]
            )
            self.assertEqual(
                transition["analysis_policy"]["minimum_host_reasoning_effort"],
                "high",
            )
            self.assertNotIn("parent_state", transition)

    def test_prepare_uses_immutable_evidence_snapshot_not_mutable_inbox(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trading_date = "2026-06-30"
            seed_logic_files(root)
            inbox = root / "data_sources" / "inbox" / trading_date
            seed_inbox(inbox)
            seed_capture_manifest(root, trading_date, "morning", full=True)
            original_hash = file_hash(
                root
                / "runtime_state"
                / trading_date
                / "evidence"
                / "morning"
                / ("0" * 32)
                / "exocharts.png"
            )
            (inbox / "exocharts.png").write_bytes(b"overwritten later")
            transition, _ = prepare_transition(
                trading_date,
                "morning",
                root=root,
                max_reasoning_confirmed=True,
            )
            exo_hash = transition["sources"]["exocharts"]["files"][0]["sha256"]
            self.assertEqual(exo_hash, original_hash)

    def test_prepare_requires_successful_capture_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            seed_logic_files(root)
            seed_inbox(root / "data_sources" / "inbox" / "2026-06-30")
            with self.assertRaisesRegex(ValueError, "capture manifest is missing"):
                prepare_transition(
                    "2026-06-30",
                    "morning",
                    root=root,
                    max_reasoning_confirmed=True,
                )

    def test_notion_position_change_is_decoupled_from_decisions(self):
        nodes = affected_nodes({"notion_positions"})
        self.assertNotIn("decision:main_account", nodes)
        self.assertNotIn("decision:maker", nodes)
        self.assertNotIn("score:total", nodes)
        self.assertNotIn("score:winrate", nodes)

    def test_farside_btc_etf_change_affects_spot_flow_confirmation(self):
        nodes = affected_nodes({"farside_btc_etf"})
        self.assertIn("feature:spot_etf_flow", nodes)
        self.assertIn("feature:fundamentals", nodes)
        self.assertIn("feature:liquidity_confirmation", nodes)
        self.assertIn("score:winrate", nodes)
        self.assertIn("decision:maker", nodes)

    def test_full_analysis_graph_includes_quality_assurance_nodes(self):
        nodes = required_analysis_nodes("evening")
        for node in {
            "validation:five_sources",
            "validation:six_sources",
            "transcription:farside_btc_etf",
            "analysis:spot_etf_flow_confirmation",
            "analysis:risk",
            "analysis:scenarios",
            "output:quality_review",
        }:
            self.assertIn(node, nodes)
        self.assertEqual(
            required_post_lock_nodes("evening"),
            {"post_lock:prior_plan_continuity"},
        )
        self.assertEqual(
            active_post_lock_nodes(
                {
                    "post_lock:prior_plan_continuity",
                    "post_lock:evening_independent_review",
                }
            ),
            {"post_lock:prior_plan_continuity"},
        )

    def test_decision_is_not_carried_in_resolved_shared_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            directory = root / "runtime_state" / "2026-06-29"
            directory.mkdir(parents=True)
            transition = {
                "schema_version": "3.0",
                "trading_date": "2026-06-29",
                "slot": "midday",
                "state_version": 2,
                "parent_version": 1,
                "logic_version": {},
                "sources": {},
                "capture_manifest": {
                    "path": "capture_midday.json",
                    "sha256": "a" * 64,
                    "mode": "conservative_delta",
                    "completed_at": "2026-06-29T00:00:00Z",
                },
                "changed_sources": [],
                "source_affected_nodes": [],
                "invalidated_nodes": sorted(required_analysis_nodes("midday")),
                "post_lock_nodes": sorted(required_post_lock_nodes("midday")),
                "analysis_policy": {
                    "reasoning_effort": "max",
                    "max_reasoning_confirmed": True,
                    "use_highest_available_model": True,
                    "full_analysis_recompute": True,
                    "prior_decision_access": "post_analysis_lock_only",
                    "reuse_prior_analysis": False,
                    "insufficient_reasoning_resources": "halt",
                },
                "collection_mode": "incremental",
                "full_fallback_used": False,
                "fallback_reasons": [],
            }
            import json

            (directory / "transition_midday.json").write_text(
                json.dumps(transition), encoding="utf-8"
            )
            (directory / "current.json").write_text(
                json.dumps(
                    {
                        "state_version": 1,
                        "slot": "morning",
                        "features": {"trend": "down"},
                        "scores": {"total": 70},
                    }
                ),
                encoding="utf-8",
            )
            commit_id = "1" * 64
            lock = self._analysis_lock("midday", commit_id)
            resolved, _ = commit_transition(
                "2026-06-29",
                "midday",
                {
                    "analysis_archive": {"scores": {"total": 71}},
                    "decision": {"maker": {"direction": "short"}},
                    "notion_state": {"positions": "flat"},
                },
                lock,
                commit_id,
                root=root,
            )
            self.assertNotIn("decision", resolved)
            self.assertNotIn("features", resolved)
            self.assertNotIn("scores", resolved)
            self.assertNotIn("analysis_archive", resolved)
            self.assertTrue((directory / "analysis_midday.json").exists())
            self.assertTrue((directory / "decision_midday.json").exists())
            self.assertNotIn("judgment_cache", resolved)

    def test_prepare_hard_stops_when_snapshot_source_is_missing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trading_date = "2026-06-30"
            seed_logic_files(root)
            inbox = root / "data_sources" / "inbox" / trading_date
            seed_inbox(inbox)
            seed_capture_manifest(root, trading_date, "morning", full=True)
            (
                root
                / "runtime_state"
                / trading_date
                / "evidence"
                / "morning"
                / ("0" * 32)
                / "exocharts.png"
            ).unlink()
            with self.assertRaisesRegex(ValueError, "evidence file is missing"):
                prepare_transition(
                    trading_date,
                    "morning",
                    root=root,
                    max_reasoning_confirmed=True,
                )

    def test_empty_analysis_and_unknown_updates_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            directory = root / "runtime_state" / "2026-06-29"
            directory.mkdir(parents=True)
            import json

            transition = {
                "schema_version": "3.0",
                "trading_date": "2026-06-29",
                "slot": "morning",
                "state_version": 1,
                "parent_version": None,
                "logic_version": {},
                "sources": {},
                "capture_manifest": {
                    "path": "capture_morning_full.json",
                    "sha256": "a" * 64,
                    "mode": "full_base",
                    "completed_at": "2026-06-29T00:00:00Z",
                },
                "changed_sources": [],
                "source_affected_nodes": [],
                "missing_required_sources": [],
                "invalidated_nodes": sorted(required_analysis_nodes("morning")),
                "post_lock_nodes": sorted(required_post_lock_nodes("morning")),
                "analysis_policy": {
                    "reasoning_effort": "max",
                    "max_reasoning_confirmed": True,
                },
                "collection_mode": "full_base",
                "full_fallback_used": False,
                "fallback_reasons": [],
            }
            (directory / "transition_morning.json").write_text(
                json.dumps(transition), encoding="utf-8"
            )
            commit_id = "2" * 64
            lock = self._analysis_lock("morning", commit_id)
            with self.assertRaisesRegex(ValueError, "unsupported state updates"):
                commit_transition(
                    "2026-06-29",
                    "morning",
                    {
                        "analysis_archive": {},
                        "decision": {},
                        "notion_state": {"positions": "flat"},
                        "judgment_cache": {"direction": "short"},
                    },
                    lock,
                    commit_id,
                    root=root,
                )

    def test_commit_requires_analysis_validation_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            directory = root / "runtime_state" / "2026-06-29"
            directory.mkdir(parents=True)
            transition = {
                "schema_version": "3.0",
                "trading_date": "2026-06-29",
                "slot": "morning",
                "state_version": 1,
                "parent_version": None,
                "logic_version": {},
                "sources": {},
                "capture_manifest": {
                    "path": "capture_morning_full.json",
                    "sha256": "a" * 64,
                    "mode": "full_base",
                    "completed_at": "2026-06-29T00:00:00Z",
                },
                "changed_sources": [],
                "source_affected_nodes": [],
                "missing_required_sources": [],
                "invalidated_nodes": sorted(required_analysis_nodes("morning")),
                "post_lock_nodes": sorted(required_post_lock_nodes("morning")),
                "analysis_policy": {
                    "reasoning_effort": "max",
                    "max_reasoning_confirmed": True,
                },
                "collection_mode": "full_base",
                "full_fallback_used": False,
                "fallback_reasons": [],
            }
            (directory / "transition_morning.json").write_text(
                json.dumps(transition), encoding="utf-8"
            )
            commit_id = "5" * 64
            lock = self._analysis_lock("morning", commit_id)
            lock.pop("analysis_validation")
            with self.assertRaisesRegex(ValueError, "analysis_validation"):
                commit_transition(
                    "2026-06-29",
                    "morning",
                    {
                        "analysis_archive": {"scores": {"total": 71}},
                        "decision": {"maker": {"direction": "short"}},
                        "notion_state": {"positions": "flat"},
                    },
                    lock,
                    commit_id,
                    root=root,
                )

    def test_duplicate_commit_is_idempotent_but_different_result_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            directory = root / "runtime_state" / "2026-06-29"
            directory.mkdir(parents=True)
            import json

            transition = {
                "schema_version": "3.0",
                "trading_date": "2026-06-29",
                "slot": "morning",
                "state_version": 1,
                "parent_version": None,
                "logic_version": {},
                "sources": {},
                "capture_manifest": {
                    "path": "capture_morning_full.json",
                    "sha256": "a" * 64,
                    "mode": "full_base",
                    "completed_at": "2026-06-29T00:00:00Z",
                },
                "changed_sources": [],
                "source_affected_nodes": [],
                "missing_required_sources": [],
                "invalidated_nodes": sorted(required_analysis_nodes("morning")),
                "post_lock_nodes": sorted(required_post_lock_nodes("morning")),
                "analysis_policy": {
                    "reasoning_effort": "max",
                    "max_reasoning_confirmed": True,
                },
                "collection_mode": "full_base",
                "full_fallback_used": False,
                "fallback_reasons": [],
            }
            (directory / "transition_morning.json").write_text(
                json.dumps(transition), encoding="utf-8"
            )
            updates = {
                "analysis_archive": {"scores": {"total": 71}},
                "decision": {"maker": {"direction": "short"}},
                "notion_state": {"positions": "flat"},
            }
            stable_commit = "3" * 64
            lock = self._analysis_lock("morning", stable_commit)
            commit_transition(
                "2026-06-29",
                "morning",
                updates,
                lock,
                stable_commit,
                root=root,
            )
            duplicate, _ = commit_transition(
                "2026-06-29",
                "morning",
                updates,
                lock,
                stable_commit,
                root=root,
            )
            self.assertTrue(duplicate["idempotent_reuse"])
            with self.assertRaisesRegex(ValueError, "different result"):
                commit_transition(
                    "2026-06-29",
                    "morning",
                    updates,
                    self._analysis_lock("morning", "4" * 64),
                    "4" * 64,
                    root=root,
                )

    def test_same_slot_reissue_requires_explicit_authorization_before_delivery(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trading_date = "2026-06-30"
            seed_logic_files(root)
            seed_inbox(root / "data_sources" / "inbox" / trading_date)
            seed_capture_manifest(root, trading_date, "midday", full=True)
            directory = root / "runtime_state" / trading_date
            morning_state = {
                "slot": "morning",
                "state_version": 1,
                "logic_version": {},
                "sources": {},
                "commit_id": "1" * 64,
            }
            midday_state = {
                "slot": "midday",
                "state_version": 2,
                "parent_version": 1,
                "logic_version": {},
                "sources": {},
                "commit_id": "2" * 64,
                "report_sha256": "a" * 64,
                "capture_manifest": {"path": "captures/midday/old.json"},
            }
            (directory / "base.json").write_text(
                json.dumps(morning_state), encoding="utf-8"
            )
            (directory / "current.json").write_text(
                json.dumps(midday_state), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "already committed"):
                prepare_transition(
                    trading_date,
                    "midday",
                    root=root,
                    max_reasoning_confirmed=True,
                    full_recollection_performed=True,
                )
            transition, _ = prepare_transition(
                trading_date,
                "midday",
                root=root,
                max_reasoning_confirmed=True,
                full_recollection_performed=True,
                allow_same_slot_reissue=True,
            )
            self.assertEqual(transition["parent_version"], 1)
            self.assertEqual(transition["state_version"], 2)
            self.assertEqual(
                transition["reissue"]["previous_commit_id"], "2" * 64
            )

    def test_same_slot_reissue_commit_overwrites_only_with_explicit_authorization(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            directory = root / "runtime_state" / "2026-06-29"
            directory.mkdir(parents=True)
            transition = {
                "schema_version": "3.0",
                "trading_date": "2026-06-29",
                "slot": "midday",
                "state_version": 2,
                "parent_version": 1,
                "logic_version": {},
                "sources": {},
                "capture_manifest": {
                    "path": "captures/midday/full_recollection_new.json",
                    "sha256": "a" * 64,
                    "mode": "full_recollection",
                    "completed_at": "2026-06-29T00:00:00Z",
                    "evidence_snapshot": {"root": "evidence/midday/new"},
                },
                "changed_sources": ["fedwatch"],
                "source_affected_nodes": [],
                "missing_required_sources": [],
                "invalidated_nodes": sorted(required_analysis_nodes("midday")),
                "post_lock_nodes": sorted(required_post_lock_nodes("midday")),
                "analysis_policy": {
                    "reasoning_effort": "max",
                    "max_reasoning_confirmed": True,
                    "use_highest_available_model": True,
                    "full_analysis_recompute": True,
                    "prior_decision_access": "post_analysis_lock_only",
                    "reuse_prior_analysis": False,
                    "insufficient_reasoning_resources": "halt",
                },
                "collection_mode": "full_recollection",
                "full_fallback_used": True,
                "fallback_reasons": ["publish evidence expired"],
                "reissue": {
                    "kind": "same_slot_reissue_before_delivery",
                    "previous_commit_id": "2" * 64,
                    "previous_state_version": 2,
                },
            }
            (directory / "transition_midday.json").write_text(
                json.dumps(transition), encoding="utf-8"
            )
            old_state = {
                "slot": "midday",
                "state_version": 2,
                "commit_id": "2" * 64,
                "report_sha256": "a" * 64,
            }
            (directory / "current.json").write_text(
                json.dumps(old_state), encoding="utf-8"
            )
            (directory / "resolved_midday.json").write_text(
                json.dumps(old_state), encoding="utf-8"
            )
            updates = {
                "analysis_archive": {"scores": {"total": 69}},
                "decision": {"maker": {"direction": "long"}},
                "notion_state": {"positions": "not_read_before_lock"},
            }
            new_commit = "6" * 64
            lock = self._analysis_lock("midday", new_commit)
            with self.assertRaisesRegex(ValueError, "different result"):
                commit_transition(
                    "2026-06-29",
                    "midday",
                    updates,
                    lock,
                    new_commit,
                    root=root,
                )
            resolved, _ = commit_transition(
                "2026-06-29",
                "midday",
                updates,
                lock,
                new_commit,
                root=root,
                allow_same_slot_reissue=True,
            )
            self.assertEqual(resolved["commit_id"], new_commit)
            self.assertEqual(
                json.loads((directory / "current.json").read_text())["commit_id"],
                new_commit,
            )

    def test_same_slot_reissue_is_blocked_after_delivery_manifest_exists(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            directory = root / "runtime_state" / "2026-06-29"
            directory.mkdir(parents=True)
            (directory / "current.json").write_text(
                json.dumps({"slot": "midday", "commit_id": "2" * 64}),
                encoding="utf-8",
            )
            (directory / "transition_midday.json").write_text(
                json.dumps(
                    {
                        "slot": "midday",
                        "reissue": {"kind": "same_slot_reissue_before_delivery"},
                    }
                ),
                encoding="utf-8",
            )
            (directory / "delivery_midday.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "already delivered"):
                commit_transition(
                    "2026-06-29",
                    "midday",
                    {
                        "analysis_archive": {"scores": {"total": 69}},
                        "decision": {"maker": {"direction": "long"}},
                        "notion_state": {"positions": "flat"},
                    },
                    self._analysis_lock("midday", "7" * 64),
                    "7" * 64,
                    root=root,
                    allow_same_slot_reissue=True,
                )

    def test_session_lock_rejects_concurrent_owner(self):
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "session.lock"
            with exclusive_lock(lock_path):
                with self.assertRaisesRegex(RuntimeError, "already running"):
                    with exclusive_lock(lock_path):
                        pass

    def test_logic_version_change_invalidates_analysis_without_recollection(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            seed_logic_files(root)
            trading_date = "2026-06-30"
            inbox = root / "data_sources" / "inbox" / trading_date
            seed_inbox(inbox)
            snapshot = scan_source_snapshot(inbox)
            directory = root / "runtime_state" / trading_date
            directory.mkdir(parents=True)
            import json

            (directory / "current.json").write_text(
                json.dumps(
                    {
                        "slot": "morning",
                        "state_version": 1,
                        "logic_version": {"old": "version"},
                        "sources": snapshot,
                    }
                ),
                encoding="utf-8",
            )
            capture_dir = directory / "captures" / "midday"
            capture_dir.mkdir(parents=True)
            capture = capture_dir / ("conservative_delta_" + "a" * 32 + ".json")
            capture.write_text(
                json.dumps(
                    {
                        "date": trading_date,
                        "slot": "midday",
                        "mode": "conservative_delta",
                        "run_id": "a" * 32,
                        "workflow_lease_id": "b" * 64,
                        "completed_at": "2026-06-30T04:00:00Z",
                        "evidence_snapshot": seed_evidence_snapshot(
                            root, trading_date, "midday", "a" * 32
                        ),
                        "success": True,
                        "fallback_reasons": [],
                    }
                ),
                encoding="utf-8",
            )
            transition, _ = prepare_transition(
                trading_date,
                "midday",
                root=root,
                max_reasoning_confirmed=True,
                capture_manifest_path=capture,
                workflow_lease_id="b" * 64,
            )
            self.assertEqual(
                transition["analysis_invalidation_reasons"],
                ["logic version changed"],
            )
            self.assertEqual(transition["fallback_reasons"], [])
            self.assertFalse(transition["full_fallback_used"])
            self.assertEqual(transition["collection_mode"], "incremental")

    def test_capture_manifest_is_bound_to_slot_and_lease(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            seed_logic_files(root)
            trading_date = "2026-06-30"
            seed_inbox(root / "data_sources" / "inbox" / trading_date)
            directory = root / "runtime_state" / trading_date
            capture_dir = directory / "captures" / "midday"
            capture_dir.mkdir(parents=True)
            import json

            capture = capture_dir / ("conservative_delta_" + "c" * 32 + ".json")
            capture.write_text(
                json.dumps(
                    {
                        "date": trading_date,
                        "slot": "evening",
                        "mode": "conservative_delta",
                        "run_id": "c" * 32,
                        "workflow_lease_id": "d" * 64,
                        "completed_at": "2026-06-30T04:00:00Z",
                        "success": True,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "invalid capture manifest"):
                prepare_transition(
                    trading_date,
                    "midday",
                    root=root,
                    max_reasoning_confirmed=True,
                    capture_manifest_path=capture,
                    workflow_lease_id="d" * 64,
                )

    def test_prepare_allows_capture_from_explicitly_recovered_lease(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            seed_logic_files(root)
            trading_date = "2026-06-30"
            seed_inbox(root / "data_sources" / "inbox" / trading_date)
            directory = root / "runtime_state" / trading_date
            capture_dir = directory / "captures" / "morning"
            capture_dir.mkdir(parents=True)
            old_lease_id = "1" * 64
            new_lease_id = "2" * 64
            capture = capture_dir / ("full_base_" + "a" * 32 + ".json")
            capture.write_text(
                json.dumps(
                    {
                        "date": trading_date,
                        "slot": "morning",
                        "mode": "full_base",
                        "run_id": "a" * 32,
                        "workflow_lease_id": old_lease_id,
                        "completed_at": "2026-06-30T00:00:00Z",
                        "evidence_snapshot": seed_evidence_snapshot(
                            root, trading_date, "morning", "a" * 32
                        ),
                        "success": True,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "workflow_lease"):
                prepare_transition(
                    trading_date,
                    "morning",
                    root=root,
                    max_reasoning_confirmed=True,
                    capture_manifest_path=capture,
                    workflow_lease_id=new_lease_id,
                )
            transition, _ = prepare_transition(
                trading_date,
                "morning",
                root=root,
                max_reasoning_confirmed=True,
                replace_prepared_transition=True,
                capture_manifest_path=capture,
                workflow_lease_id=new_lease_id,
                recovered_from_workflow_lease={
                    "trading_date": trading_date,
                    "slot": "morning",
                    "lease_id": old_lease_id,
                    "status": "abandoned",
                    "closed_at": "2026-06-30T00:05:00+00:00",
                    "recovery_reason": "resume after hard stop",
                },
            )
            self.assertEqual(
                transition["capture_lease_recovery"]["captured_workflow_lease_id"],
                old_lease_id,
            )
            self.assertEqual(
                transition["capture_lease_recovery"]["active_workflow_lease_id"],
                new_lease_id,
            )

    def test_prepare_refreshes_recovery_binding_in_comparable_transition(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            seed_logic_files(root)
            trading_date = "2026-06-30"
            seed_inbox(root / "data_sources" / "inbox" / trading_date)
            directory = root / "runtime_state" / trading_date
            capture_dir = directory / "captures" / "morning"
            capture_dir.mkdir(parents=True)
            old_lease_id = "1" * 64
            new_lease_id = "2" * 64
            capture = capture_dir / ("full_base_" + "a" * 32 + ".json")
            capture.write_text(
                json.dumps(
                    {
                        "date": trading_date,
                        "slot": "morning",
                        "mode": "full_base",
                        "run_id": "a" * 32,
                        "workflow_lease_id": old_lease_id,
                        "completed_at": "2026-06-30T00:00:00Z",
                        "evidence_snapshot": seed_evidence_snapshot(
                            root, trading_date, "morning", "a" * 32
                        ),
                        "success": True,
                    }
                ),
                encoding="utf-8",
            )
            original, target = prepare_transition(
                trading_date,
                "morning",
                root=root,
                max_reasoning_confirmed=True,
                capture_manifest_path=capture,
                workflow_lease_id=old_lease_id,
            )
            self.assertNotIn("capture_lease_recovery", original)

            with self.assertRaisesRegex(ValueError, "workflow_lease"):
                prepare_transition(
                    trading_date,
                    "morning",
                    root=root,
                    max_reasoning_confirmed=True,
                    capture_manifest_path=capture,
                    workflow_lease_id=new_lease_id,
                    recovered_from_workflow_lease={
                        "trading_date": trading_date,
                        "slot": "morning",
                        "lease_id": "3" * 64,
                        "status": "abandoned",
                        "closed_at": "2026-06-30T00:05:00+00:00",
                        "recovery_reason": "resume after hard stop",
                    },
                )
            self.assertNotIn(
                "capture_lease_recovery",
                json.loads(target.read_text(encoding="utf-8")),
            )

            recovery = {
                "trading_date": trading_date,
                "slot": "morning",
                "lease_id": old_lease_id,
                "status": "abandoned",
                "closed_at": "2026-06-30T00:05:00+00:00",
                "recovery_reason": "resume after hard stop",
            }
            refreshed, _ = prepare_transition(
                trading_date,
                "morning",
                root=root,
                max_reasoning_confirmed=True,
                capture_manifest_path=capture,
                workflow_lease_id=new_lease_id,
                recovered_from_workflow_lease=recovery,
            )
            self.assertTrue(refreshed["recovery_binding_refreshed"])
            self.assertNotIn("idempotent_reuse", refreshed)
            persisted = json.loads(target.read_text(encoding="utf-8"))
            self.assertNotIn("recovery_binding_refreshed", persisted)
            self.assertEqual(
                persisted["capture_lease_recovery"]["captured_workflow_lease_id"],
                old_lease_id,
            )
            self.assertEqual(
                persisted["capture_lease_recovery"]["active_workflow_lease_id"],
                new_lease_id,
            )

            before_retry = target.read_bytes()
            reused, _ = prepare_transition(
                trading_date,
                "morning",
                root=root,
                max_reasoning_confirmed=True,
                capture_manifest_path=capture,
                workflow_lease_id=new_lease_id,
                recovered_from_workflow_lease=recovery,
            )
            self.assertTrue(reused["idempotent_reuse"])
            self.assertEqual(target.read_bytes(), before_retry)

    def test_delta_full_fallback_requires_hash_bound_full_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            seed_logic_files(root)
            trading_date = "2026-06-30"
            inbox = root / "data_sources" / "inbox" / trading_date
            seed_inbox(inbox)
            snapshot = scan_source_snapshot(inbox)
            directory = root / "runtime_state" / trading_date
            capture_dir = directory / "captures" / "midday"
            capture_dir.mkdir(parents=True)
            import json

            (directory / "current.json").write_text(
                json.dumps(
                    {
                        "slot": "morning",
                        "state_version": 1,
                        "logic_version": {},
                        "sources": snapshot,
                    }
                ),
                encoding="utf-8",
            )
            capture = capture_dir / ("conservative_delta_" + "e" * 32 + ".json")
            capture.write_text(
                json.dumps(
                    {
                        "date": trading_date,
                        "slot": "midday",
                        "mode": "conservative_delta",
                        "run_id": "e" * 32,
                        "workflow_lease_id": "f" * 64,
                        "completed_at": "2026-06-30T04:00:00Z",
                        "evidence_snapshot": seed_evidence_snapshot(
                            root, trading_date, "midday", "e" * 32
                        ),
                        "success": True,
                        "full_fallback_used": True,
                        "fallback_code": 0,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "immutable full manifest"):
                prepare_transition(
                    trading_date,
                    "midday",
                    root=root,
                    max_reasoning_confirmed=True,
                    capture_manifest_path=capture,
                    workflow_lease_id="f" * 64,
                )


class WorkflowLeaseTests(unittest.TestCase):
    def test_concurrent_begin_has_exactly_one_winner(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            def claim():
                try:
                    return begin_lease("2026-06-30", "morning", root=root)["lease_id"]
                except (FileExistsError, RuntimeError):
                    return None

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: claim(), range(2)))
            self.assertEqual(sum(result is not None for result in results), 1)

    def test_lease_spans_slots_and_requires_explicit_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = begin_lease("2026-06-30", "morning", root=root)
            assert_lease("2026-06-30", "morning", first["token"], root=root)
            with self.assertRaisesRegex(RuntimeError, "another workflow lease"):
                begin_lease("2026-07-01", "morning", root=root)
            recovered = recover_lease(
                "2026-07-01",
                "morning",
                reason="host crashed after capture",
                root=root,
            )
            self.assertNotEqual(first["lease_id"], recovered["lease_id"])
            abandon_lease(
                recovered["token"],
                reason="test cleanup after explicit recovery",
                root=root,
            )
            audit = (
                root / "runtime_state" / "workflow_lease_audit.jsonl"
            ).read_text(encoding="utf-8")
            self.assertIn('"event": "recovered"', audit)
            self.assertIn('"event": "abandoned"', audit)

    def test_archived_abandoned_lease_can_be_recovered_explicitly(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = begin_lease("2026-06-30", "morning", root=root)
            abandon_lease(
                first["token"],
                reason="hard stop after immutable capture",
                root=root,
            )
            recovered = recover_lease(
                "2026-06-30",
                "morning",
                reason="resume with existing immutable capture",
                from_lease_id=first["lease_id"],
                root=root,
            )
            self.assertNotEqual(first["lease_id"], recovered["lease_id"])
            self.assertEqual(
                recovered["recovered_from_workflow_lease"]["lease_id"],
                first["lease_id"],
            )
            self.assertEqual(
                recovered["recovered_from_workflow_lease"]["status"],
                "abandoned",
            )
            audit = (
                root / "runtime_state" / "workflow_lease_audit.jsonl"
            ).read_text(encoding="utf-8")
            self.assertIn('"event": "recover_archived"', audit)

    def test_already_delivered_slot_is_blocked_before_capture(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            seed_complete_delivery(root, "2026-06-30", "morning")
            with self.assertRaisesRegex(RuntimeError, "already delivered"):
                begin_lease("2026-06-30", "morning", root=root)

    def test_prior_delivery_must_be_hash_closed_before_next_slot(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            directory = root / "runtime_state" / "2026-06-30"
            directory.mkdir(parents=True)
            (directory / "delivery_morning.json").write_text(
                json.dumps(
                    {
                        "trading_date": "2026-06-30",
                        "slot": "morning",
                        "frozen_verifier_pass": True,
                        "unique_page_pass": True,
                        "word_visual_qa_pass": True,
                        "context_log_recorded": True,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "complete delivery manifest"):
                begin_lease("2026-06-30", "midday", root=root)

    def test_incomplete_delivery_record_does_not_block_recovery_run(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            directory = root / "runtime_state" / "2026-06-30"
            directory.mkdir(parents=True)
            (directory / "delivery_morning.json").write_text(
                json.dumps(
                    {
                        "trading_date": "2026-06-30",
                        "slot": "morning",
                        "frozen_verifier_pass": True,
                        "unique_page_pass": True,
                        "word_visual_qa_pass": True,
                        "context_log_recorded": True,
                    }
                ),
                encoding="utf-8",
            )
            lease = begin_lease("2026-06-30", "morning", root=root)
            self.assertEqual(lease["slot"], "morning")

    def test_next_slot_begins_after_complete_prior_delivery(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            seed_complete_delivery(root, "2026-06-30", "morning")
            lease = begin_lease("2026-06-30", "midday", root=root)
            self.assertEqual(lease["slot"], "midday")

    def test_delivered_slot_stays_blocked_after_current_advances(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            seed_complete_delivery(root, "2026-06-30", "morning")
            current = root / "runtime_state" / "2026-06-30" / "current.json"
            current.write_text(
                json.dumps(
                    {
                        "trading_date": "2026-06-30",
                        "slot": "midday",
                        "commit_id": "3" * 64,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "already delivered"):
                begin_lease("2026-06-30", "morning", root=root)

    def test_legacy_recorded_delivery_blocks_duplicate_without_publish_payload(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            seed_complete_delivery(root, "2026-06-30", "morning")
            delivery_path = root / "runtime_state" / "2026-06-30" / "delivery_morning.json"
            delivery = json.loads(delivery_path.read_text(encoding="utf-8"))
            delivery["evidence"].pop("context_log_block_sha256")
            delivery["evidence"].pop("source_binding")
            delivery_path.write_text(json.dumps(delivery), encoding="utf-8")
            publish_path = root / "runtime_state" / "2026-06-30" / "publish_morning.json"
            publish = json.loads(publish_path.read_text(encoding="utf-8"))
            publish.pop("source_binding")
            publish_path.write_text(json.dumps(publish), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "already delivered"):
                begin_lease("2026-06-30", "morning", root=root)

    def test_legacy_v2_delivery_still_counts_when_live_evidence_validates(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            seed_complete_delivery(root, "2026-06-30", "morning")
            delivery_path = root / "runtime_state" / "2026-06-30" / "delivery_morning.json"
            delivery = json.loads(delivery_path.read_text(encoding="utf-8"))
            delivery["evidence"].pop("context_log_block_sha256")
            delivery["evidence"].pop("source_binding")
            delivery_path.write_text(json.dumps(delivery), encoding="utf-8")
            lease = begin_lease("2026-06-30", "midday", root=root)
            self.assertEqual(lease["slot"], "midday")


if __name__ == "__main__":
    unittest.main()
