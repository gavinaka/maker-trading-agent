from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import uuid
import zipfile
import zlib
from decimal import Decimal
from itertools import combinations
from pathlib import Path
from unittest.mock import patch

from runtime_vnext.artifacts import ArtifactStore
from runtime_vnext.controller import (
    AUTOMATIC_ATTEMPT_LIMIT_BY_STAGE,
    DEFAULT_AUTOMATIC_ATTEMPT_LIMIT,
    RunController,
    _load_blockbeats_rows,
    _load_report_presentation_contract,
)
from runtime_vnext.errors import FailureClass, WorkflowFailure
from runtime_vnext.delivery_renderer import (
    WORD_QA_REVIEW_CHECKLIST_KEYS,
    WORD_QA_REVIEW_CHECKLIST_VERSION,
    prepare_run_qa,
)
from runtime_vnext.domain_ir import to_plain
from runtime_vnext.domain_ir.registry import REGISTRY
from runtime_vnext.golden_samples import load_contract
from runtime_vnext.gates import (
    REQUIRED_REPORT_SECTIONS,
    REQUIRED_SOURCES,
    SOURCE_ROLES,
    evaluate_decision,
    evaluate_delivery,
    evaluate_evidence,
    evidence_snapshot_sha256,
    evaluate_reasoning,
    evaluate_shadow_delivery,
    decision_model_sha256,
    reasoning_model_sha256,
    _typed_direction_prose_issue,
)
from runtime_vnext.methodology import (
    CONTROL_PLANE_FILES,
    MANIFEST_V3_POLICY,
    PHASE_FILES,
    PHASE_SEMANTIC_FILES,
    SEMANTIC_RUNTIME_FILES,
    build_methodology_manifest,
    canonical_sha256,
    load_scoring_policy,
    sha256_file,
)
from runtime_vnext.plan_semantics import assess_order_lifecycle
from runtime_vnext.pretrade_gate import build_pretrade_gate_contract
from runtime_vnext.rate_expectation import (
    canonical_json_sha256 as rate_canonical_sha256,
    normalize_kalshi_payload,
)
from runtime_vnext.reasoning_pipeline import build_pipeline_units
from runtime_vnext.reasoning_submission import (
    assemble_reasoning_submission,
    load_reasoning_submission_contract,
)
from runtime_vnext.report_compiler import compile_projected_report
from runtime_vnext.validation.evidence import (
    _extreme_proof_failures,
    _validate_tradingview,
    _validate_tradingview_profile_sidecar_binding,
)
from runtime_vnext.validation.reasoning import _validate_claim_layers
from runtime_vnext.legacy_capture_adapter import (
    _rate_expectation_meta,
    adapt_legacy_capture,
)
from outputs.render_from_combined import render_canonical
from runtime_vnext.validation.report import (
    certify_report_projection_input,
    certify_presentation_contract,
    evaluate_gold_template_fidelity,
    evaluate_human_reasoning_depth,
    run_compatibility_lint,
)
from tests.test_rate_expectation import _fixture as rate_expectation_fixture


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_presentation_contract(root: Path) -> dict:
    payload = json.loads(
        (root / "governance" / "vnext_report_presentation_contract.json").read_text(
            encoding="utf-8"
        )
    )
    return certify_presentation_contract(payload)


class VNextWorkflowTests(unittest.TestCase):
    @staticmethod
    def exact_prefill_defense_plan(
        entries: list[float],
        allocations: list[float],
        stop: float,
        *,
        direction: str = "short",
    ) -> dict:
        decimal_entries = [Decimal(str(value)) for value in entries]
        decimal_allocations = [Decimal(str(value)) for value in allocations]
        decimal_stop = Decimal(str(stop))

        def plain(value: Decimal) -> str:
            return format(value.normalize(), "f")

        def number(value: Decimal) -> int | float:
            return int(value) if value == value.to_integral() else float(value)

        trigger_scenarios = []
        for size in range(1, len(decimal_entries) + 1):
            for indexes in combinations(range(len(decimal_entries)), size):
                allocation_total = sum(
                    (decimal_allocations[index] for index in indexes), Decimal("0")
                )
                weighted_fill = sum(
                    (
                        decimal_entries[index] * decimal_allocations[index]
                        for index in indexes
                    ),
                    Decimal("0"),
                ) / allocation_total
                risk_distance = abs(decimal_stop - weighted_fill)
                sign = Decimal("1") if direction == "long" else Decimal("-1")
                first_trigger = weighted_fill + sign * Decimal("1.5") * risk_distance
                second_trigger = weighted_fill + sign * Decimal("2") * risk_distance
                levels = [index + 1 for index in indexes]
                trigger_scenarios.append(
                    {
                        "risk_scenario_id": "fill-" + "-".join(map(str, levels)),
                        "filled_level_indexes": levels,
                        "weighted_fill": number(weighted_fill),
                        "first_trigger_price_raw": plain(first_trigger),
                        "second_trigger_price_raw": plain(second_trigger),
                        "rounding_rule": "exact_no_rounding",
                        "rounding_step": None,
                        "first_trigger_price": number(first_trigger),
                        "second_trigger_price": number(second_trigger),
                    }
                )
        full_ladder = trigger_scenarios[-1]["weighted_fill"]
        return {
            "mode": "ladder_prefill_exact_scenarios",
            "prefill_anchor": {
                "kind": "planned_full_ladder_weighted_fill",
                "weighted_fill": full_ladder,
                "is_actual_fill": False,
                "is_single_entry": False,
            },
            "trigger_scenarios": trigger_scenarios,
            "postfill_recalculation": {
                "required": True,
                "anchor": "actual_weighted_fill",
                "replace_prefill_projection": True,
            },
            "first_stop_rule": "confirmed_post_fill_4h_structural_extreme",
            "second_action": "move_stop_to_breakeven_only",
        }

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for relative in {item for values in PHASE_FILES.values() for item in values}:
            source = REPO_ROOT / relative
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        for relative in CONTROL_PLANE_FILES:
            source = REPO_ROOT / relative
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        for relative in ("outputs/report_lint.py", "outputs/report_structure_gate.py"):
            source = REPO_ROOT / relative
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        self.controller = RunController(self.root)
        self.date = "2026-07-13"
        self.slot = "morning"
        self.run_mode = (
            "shadow" if "shadow" in self._testMethodName.lower() else "production"
        )
        self.run_root = self.controller.begin(
            self.date,
            self.slot,
            run_mode=self.run_mode,
            authorization_ref=f"test-{self.run_mode}-approval",
            run_id="run-test",
        )
        self.controller.record_host_capability(self.run_root, self.host_capability())
        self.gate = None
        if self.run_mode == "production":
            self.gate = self.controller.record_pretrade_gate(
                self.run_root,
                source_reference="38efda35-a098-810c-b9c3-cdf448a9d226",
                source_observed_at="2026-07-13T06:00:00+08:00",
                subjective_conclusion="可交易",
                emotion_stable=True,
                rhythm_consistent=True,
                result_dependency=False,
                continuous_stop_loss_count=0,
                physical_condition="normal",
            )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def host_capability(self) -> dict:
        payload = {
            "schema_version": "codex-host-capability-v2",
            "status": "verified",
            "trading_date": self.date,
            "slot": self.slot,
            "model": "gpt-5.6-sol",
            "reasoning_effort": "xhigh",
            "minimum_effort": "xhigh",
            "effort_policy": "at_least_minimum",
            "thread_id": "019f-test-thread",
        }
        payload["manifest_sha256"] = canonical_sha256(payload)
        return payload

    def evidence(self) -> dict:
        capture = self.root / "capture"
        capture.mkdir(exist_ok=True)
        capture_run_id = "11111111-1111-4111-8111-111111111111"
        profile_capture_nonce = "22222222-2222-4222-8222-222222222222"
        sources = {}
        for source in REQUIRED_SOURCES:
            structured = source in {"BlockBeats", "Farside"}
            filename = (
                "blockbeats.json"
                if source == "BlockBeats"
                else "farside_btc_etf.json"
                if source == "Farside"
                else f"{source.lower()}.png"
            )
            path = capture / filename
            content = None
            if source == "BlockBeats":
                content = {
                    "important_only": True,
                    "capture_window_hours": 12,
                    "window_covered": True,
                    "selected_count_required": 3,
                    "selected_rows": [
                        {
                            "selected_rank": index,
                            "time": f"7/13 0{index}:00",
                            "title": f"重要事件{index}",
                            "body": f"BlockBeats 消息，事件{index}仅作为当期基本面证据。",
                            "analysis_priority": {
                                "tier": "T2行业",
                                "priority_bucket": "crypto_market_structure",
                            },
                        }
                        for index in range(1, 4)
                    ],
                }
            elif source == "Farside":
                content = {
                    "schema_version": "1.0",
                    "latest": {
                        "date": "10 Jul 2026",
                        "date_iso": "2026-07-10",
                        "total_usd_m": -210.4,
                        "direction": "outflow",
                        "funds": {"IBIT": -210.4, "FBTC": 0.0},
                    },
                }
            if structured:
                path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
            else:
                path.write_bytes(self.valid_png_bytes())
            record = {
                "path": path.relative_to(self.root).as_posix(),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
            item = {
                "status": "valid",
                "role": SOURCE_ROLES[source],
                "observed_at": "2026-07-13T06:30:00+08:00",
                "artifacts": [record],
                "meta": {},
            }
            if source == "TradingView":
                item["timeframes"] = ["1D", "4H", "1H", "15m"]
                item["artifacts"] = []
                for frame in item["timeframes"]:
                    frame_path = capture / f"tradingview_btc_{frame.lower()}.png"
                    frame_path.write_bytes(self.valid_png_bytes())
                    item["artifacts"].append(
                        {
                            "path": frame_path.relative_to(self.root).as_posix(),
                            "sha256": sha256_file(frame_path),
                            "bytes": frame_path.stat().st_size,
                            "timeframe": frame,
                        }
                    )
                profile_sidecar = capture / "tradingview_profile_state.json"
                profile_sidecar.write_text(
                    json.dumps(
                        {
                            "schema_version": "tradingview-profile-state-v2",
                            "capture_run_id": capture_run_id,
                            "capture_nonce": profile_capture_nonce,
                            "source_mode": "user_drawn_manual_only",
                            "platform_indicator_policy": "hide_and_never_use",
                            "aggregate_state": "hidden",
                            "timeframes": {
                                frame: {
                                    "initial_state": "hidden",
                                    "final_state": "hidden",
                                    "correction_attempted": False,
                                    "certification_basis": "profile_control",
                                }
                                for frame in ("1d", "4h", "1h", "15m")
                            },
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                item["artifacts"].append(
                    {
                        "path": profile_sidecar.relative_to(self.root).as_posix(),
                        "sha256": sha256_file(profile_sidecar),
                        "bytes": profile_sidecar.stat().st_size,
                    }
                )
            elif source == "Coinglass":
                for window in ("48h", "24h"):
                    liquidation_path = capture / f"liqheatmap_{window}.png"
                    liquidation_path.write_bytes(self.valid_png_bytes())
                    item["artifacts"].append(
                        {
                            "path": liquidation_path.relative_to(self.root).as_posix(),
                            "sha256": sha256_file(liquidation_path),
                            "bytes": liquidation_path.stat().st_size,
                            "kind": "liquidation_map",
                        }
                    )
            elif source == "BlockBeats":
                item["meta"] = {
                    "important_only": True,
                    "capture_window_hours": 12,
                    "window_covered": True,
                    "selected_count_required": 3,
                    "selected_row_count": 3,
                }
            elif source == "Farside":
                item["meta"] = {
                    "latest_total_usd_m": -210.4,
                    "latest_complete_date": "2026-07-10",
                    "flow_direction": "outflow",
                }
            sources[source] = item
        payload = {
            "schema_version": "evidence-snapshot-v1",
            "trading_date": self.date,
            "slot": self.slot,
            "captured_at": "2026-07-13T06:35:00+08:00",
            "capture_run_id": capture_run_id,
            "tradingview_profile_binding": {
                "schema_version": "tradingview-profile-capture-binding-v1",
                "capture_run_id": capture_run_id,
                "capture_nonce": profile_capture_nonce,
                "sidecar_filename": "tradingview_profile_state.json",
                "sidecar_schema_version": "tradingview-profile-state-v2",
            },
            "sources": sources,
        }
        payload["snapshot_sha256"] = evidence_snapshot_sha256(payload)
        return payload

    def plan_c_evidence(self) -> dict:
        evidence = self.evidence()
        contract, cme_result, raw = rate_expectation_fixture(
            "2026-07-12T22:35:00Z"
        )
        capture_run_id = evidence["capture_run_id"]
        cme_result["capture_run_id"] = capture_run_id
        cme_result["attempt_sha256"] = rate_canonical_sha256(
            cme_result, exclude="attempt_sha256"
        )
        raw["capture_run_id"] = capture_run_id
        raw["cme_attempt_sha256"] = cme_result["attempt_sha256"]
        raw["raw_sha256"] = rate_canonical_sha256(raw, exclude="raw_sha256")
        normalized = normalize_kalshi_payload(contract, cme_result, raw)
        provenance = {
            "schema_version": contract["provenance_schema_version"],
            "logical_source": contract["logical_source"],
            "capture_run_id": capture_run_id,
            "selection_mode": "kalshi_plan_c_fallback",
            "provider_id": "kalshi_public_market_data_api",
            "series_ticker": "KXFEDDECISION",
            "fallback_reason_code": cme_result["defect_code"],
            "primary_attempt_artifact_path": "cme_fedwatch_result.json",
            "raw_artifact_paths": ["kalshi_feddecision_raw.json"],
            "normalized_artifact_path": "fedwatch.json",
            "selected_artifact_paths": [
                "cme_fedwatch_result.json",
                "fedwatch.json",
                "kalshi_feddecision_raw.json",
            ],
        }
        provenance["provenance_sha256"] = rate_canonical_sha256(
            provenance, exclude="provenance_sha256"
        )
        old_record = evidence["sources"]["FedWatch"]["artifacts"][0]
        capture = (self.root / old_record["path"]).parent
        artifacts = []
        for filename, payload in (
            ("cme_fedwatch_result.json", cme_result),
            ("kalshi_feddecision_raw.json", raw),
            ("fedwatch.json", normalized),
            ("rate_expectation_provenance.json", provenance),
        ):
            target = capture / filename
            target.write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            artifacts.append(
                {
                    "path": target.relative_to(self.root).as_posix(),
                    "sha256": sha256_file(target),
                    "bytes": target.stat().st_size,
                }
            )
        selection = contract["selection_modes"]["kalshi_plan_c_fallback"]
        evidence["schema_version"] = "evidence-snapshot-v2"
        evidence["sources"]["FedWatch"]["artifacts"] = artifacts
        evidence["sources"]["FedWatch"]["meta"] = {
            "provider_id": selection["provider_id"],
            "selection_mode": "kalshi_plan_c_fallback",
            "series_ticker": selection["series_ticker"],
            "acquisition_channel": selection["acquisition_channel"],
            "method_class": selection["method_class"],
            "method_equivalence": selection["method_equivalence"],
            "sample_source_class": selection["sample_source_class"],
            "quote_basis_code": selection["quote_basis_code"],
            "normalization_method_code": selection["normalization_method_code"],
            "fallback_reason_code": cme_result["defect_code"],
            "provenance_sha256": provenance["provenance_sha256"],
        }
        evidence["snapshot_sha256"] = evidence_snapshot_sha256(evidence)
        return evidence

    def cme_primary_evidence(self) -> dict:
        evidence = self.evidence()
        contract = json.loads(
            (self.root / "data_sources" / "rate_expectation_provider_contract.json").read_text(
                encoding="utf-8"
            )
        )
        source = evidence["sources"]["FedWatch"]
        screenshot_record = source["artifacts"][0]
        capture = (self.root / screenshot_record["path"]).parent
        cme_result = {
            "schema_version": contract["cme_attempt_schema_version"],
            "capture_run_id": evidence["capture_run_id"],
            "provider_id": "cme_fedwatch_ui",
            "status": "passed",
            "defect_code": None,
            "started_at": "2026-07-12T22:34:00Z",
            "completed_at": "2026-07-12T22:35:00Z",
            "output": {
                "path": "fedwatch.png",
                "sha256": screenshot_record["sha256"],
                "bytes": screenshot_record["bytes"],
            },
        }
        cme_result["attempt_sha256"] = rate_canonical_sha256(
            cme_result, exclude="attempt_sha256"
        )
        provenance = {
            "schema_version": contract["provenance_schema_version"],
            "logical_source": contract["logical_source"],
            "capture_run_id": evidence["capture_run_id"],
            "selection_mode": "cme_primary",
            "provider_id": "cme_fedwatch_ui",
            "series_ticker": None,
            "fallback_reason_code": "none",
            "primary_attempt_artifact_path": "cme_fedwatch_result.json",
            "raw_artifact_paths": [],
            "normalized_artifact_path": None,
            "selected_artifact_paths": [
                "cme_fedwatch_result.json",
                "fedwatch.png",
            ],
        }
        provenance["provenance_sha256"] = rate_canonical_sha256(
            provenance, exclude="provenance_sha256"
        )
        for filename, payload in (
            ("cme_fedwatch_result.json", cme_result),
            ("rate_expectation_provenance.json", provenance),
        ):
            target = capture / filename
            target.write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            source["artifacts"].append(
                {
                    "path": target.relative_to(self.root).as_posix(),
                    "sha256": sha256_file(target),
                    "bytes": target.stat().st_size,
                }
            )
        selection = contract["selection_modes"]["cme_primary"]
        evidence["schema_version"] = "evidence-snapshot-v2"
        source["meta"] = {
            "provider_id": selection["provider_id"],
            "selection_mode": "cme_primary",
            "series_ticker": selection["series_ticker"],
            "acquisition_channel": selection["acquisition_channel"],
            "method_class": selection["method_class"],
            "method_equivalence": selection["method_equivalence"],
            "sample_source_class": selection["sample_source_class"],
            "quote_basis_code": selection["quote_basis_code"],
            "normalization_method_code": selection["normalization_method_code"],
            "fallback_reason_code": "none",
            "provenance_sha256": provenance["provenance_sha256"],
        }
        evidence["snapshot_sha256"] = evidence_snapshot_sha256(evidence)
        return evidence

    def reasoning(self, evidence: dict) -> dict:
        records = {
            source: evidence["sources"][source]["artifacts"]
            for source in REQUIRED_SOURCES
        }
        paths = {source: [item["path"] for item in values] for source, values in records.items()}
        blockbeats_payload = json.loads((self.root / paths["BlockBeats"][0]).read_text(encoding="utf-8"))
        method_metrics = {
            "obs_bb": {
                "tier": 2,
                "event_window_hours": 12,
                "selected_event_count": 3,
                "selected_event_sha256": [
                    canonical_sha256(row)
                    for row in blockbeats_payload["selected_rows"]
                ],
            },
            "obs_cg": {
                "pivot": {
                    "timeframe": "1h",
                    "start_price": 100,
                    "end_price": 97,
                    "dominant_leg": "down",
                    "trendline_status": "intact",
                    "anchor_reset": False,
                },
                "price_direction": "down",
                "cvd_direction": "down",
                "oi_direction": "down",
                "funding_direction": "down",
                "funding_sign": "negative",
                "combination_id": "C80",
                "effect_divergence": {
                    "cvd_break": "lower_low",
                    "price_confirmation": "confirmed",
                    "interpretation": "none",
                },
                "price_break_status": "new_low_or_breakdown",
                "oi_price_context": "long_liquidation",
                "main_triad_direction": "bearish",
                "main_triad_rationale": "CVD与价格在同一主腿同步下行，OI下降体现多头清算而非资金费率单变量翻向。",
                "funding_effect": "weaken",
                "final_direction": "bearish",
                "funding_single_variable_flip": False,
                "liquidation_map": {
                    "role": "auxiliary_only",
                    "threshold": 0.85,
                    "captured_timeframes": ["48h", "24h"],
                    "current_price": 97,
                    "levels": [
                        {"side": "above", "price": 100, "timeframe": "48h", "strength": "strong"},
                        {"side": "below", "price": 95, "timeframe": "24h", "strength": "medium"},
                    ],
                },
            },
            "obs_exo": {
                "capture_profile": {
                    "exchange": "Bybit",
                    "symbol": "BTCUSD",
                    "timeframe": "D",
                    "tick_multiplier": 120,
                    "cluster_type": "Bid-Ask Profile",
                    "text_type": "Imbalance",
                    "candle_type": "None",
                    "fpbs_enabled": True,
                    "vwap_enabled": True,
                },
                "ohlc": {"open": 100, "high": 101, "low": 96, "close": 97},
                "poc": 98,
                "delta": -12,
                "cvd": -24,
                "volume": 1200,
                "cross_check_result": "confirm",
            },
            "obs_fw": {
                "data_as_of": "2026-07-13T06:00:00+08:00",
                "next_fomc_date": "2026-07-29",
                "current_probabilities": {"hold": 65, "hike_25bp": 35},
                "change_1d": {"hold": -2, "hike_25bp": 2},
                "change_1w": {"hold": -6, "hike_25bp": 6},
                "change_1m": {"hold": -12, "hike_25bp": 12},
            },
            "obs_fs": {
                "latest_complete_date": "2026-07-10",
                "latest_total_usd_m": -210.4,
                "flow_direction": "outflow",
            },
            "obs_tv": {
                "timeframes": {
                    "1d": {"price": 97, "sma20": 103, "structure": "bearish"},
                    "4h": {"price": 97, "sma20": 101, "structure": "bearish"},
                    "1h": {"price": 97, "sma20": 99, "structure": "bearish"},
                    "15m": {"price": 97, "sma20": 97.5, "structure": "bullish"},
                },
                "volume_profile": {
                    "source_mode": "user_drawn_manual_only",
                    "status": "readable",
                    "platform_indicator_state": "hidden",
                    "platform_vrvp_used": False,
                    "automated_values_used": False,
                    "zones": [{
                        "lower_bound": 98,
                        "upper_bound": 100,
                        "timeframe": "1h",
                        "role": "value_area",
                    }],
                    "reason": "",
                },
                "chart_basis": {
                    "support_levels": [95, 96],
                    "resistance_levels": [98, 100],
                    "swing_highs": [100.2, 100.5],
                    "swing_lows": [94.8, 94.5],
                    "structure_zones": [
                        {
                            "lower_bound": 98,
                            "upper_bound": 100,
                            "timeframe": "1h",
                            "role": "resistance",
                        },
                        {
                            "lower_bound": 100.2,
                            "upper_bound": 100.5,
                            "timeframe": "4h",
                            "role": "resistance",
                        },
                        {
                            "lower_bound": 100.1,
                            "upper_bound": 100.2,
                            "timeframe": "1h",
                            "role": "resistance",
                        },
                    ],
                    "volume_price_state": "confirm",
                    "fibonacci_levels": [98.5, 100],
                    "trendline_status": "intact",
                },
                "chart_component_scores": {
                    "chart.support_resistance": 8,
                    "chart.liquidity_hunt": 8,
                    "chart.sma20_interaction": 4,
                    "chart.volume_price": 2,
                    "chart.fibonacci_trendline": 1,
                },
                "chart_component_rationales": {
                    "chart.support_resistance": "多周期支撑阻力由当前截图逐级核对并保留失效边界。",
                    "chart.liquidity_hunt": "用户手绘价值区只判断位置概率，清算层级仅形成辅助确认。",
                    "chart.sma20_interaction": "日线四小时与一小时均位于各自SMA20下方。",
                    "chart.volume_price": "当前量价只提供有限确认而不单独决定方向。",
                    "chart.fibonacci_trendline": "趋势线与回撤工具仅用于位置质量而不承担方向。",
                },
                "chart_scoring_basis": {
                    "included_timeframes": ["1d", "4h", "1h"],
                    "excluded_timeframes": ["15m"],
                    "fifteen_minute_role": "maker_entry_only",
                },
            },
        }

        def structured_observation(item_id: str, source: str, fact: str) -> dict:
            metrics = method_metrics[item_id]
            record = records[source][0]
            return {
                "id": item_id,
                "source": source,
                "kind": "structured_observation",
                "observed_at": evidence["sources"][source]["observed_at"],
                "fact": fact,
                "uncertainty": "结构化抓取仍可能受源站字段变更影响，必须以哈希绑定文件为准。",
                "metrics": metrics,
                "evidence_refs": paths[source],
                "structured_binding": {
                    "artifact_path": record["path"],
                    "artifact_sha256": record["sha256"],
                    "metrics_sha256": canonical_sha256(metrics),
                },
            }

        def visual_observation(
            item_id: str,
            source: str,
            fact: str,
            *,
            pivot: bool = False,
            timeframe: str | None = None,
        ) -> dict:
            metrics = method_metrics[item_id]
            def leaf_paths(value, prefix=""):
                if isinstance(value, dict):
                    result = []
                    for key, child in value.items():
                        child_prefix = f"{prefix}.{key}" if prefix else str(key)
                        result.extend(leaf_paths(child, child_prefix))
                    return result or ([prefix] if prefix else [])
                if isinstance(value, list):
                    result = []
                    for index, child in enumerate(value):
                        result.extend(leaf_paths(child, f"{prefix}[{index}]"))
                    return result or ([prefix] if prefix else [])
                return [prefix]

            metric_keys = leaf_paths(metrics)
            source_records = records[source]
            citations = []
            buckets = {}
            for metric_path in metric_keys:
                if source == "TradingView" and metric_path.startswith("timeframes."):
                    timeframe = metric_path.split(".", 2)[1]
                    record = next(
                        item
                        for item in source_records
                        if str(item.get("timeframe", "")).lower() == timeframe
                    )
                elif source == "TradingView" and metric_path.startswith(
                    "chart_basis.structure_zones["
                ):
                    zone_index = int(metric_path.split("[", 1)[1].split("]", 1)[0])
                    zone_timeframe = str(
                        metrics["chart_basis"]["structure_zones"][zone_index][
                            "timeframe"
                        ]
                    ).lower()
                    record = next(
                        item
                        for item in source_records
                        if str(item.get("timeframe", "")).lower() == zone_timeframe
                    )
                else:
                    record = source_records[0]
                buckets.setdefault(record["path"], []).append(metric_path)
            for record_path, bucket in buckets.items():
                for offset in range(0, len(bucket), 6):
                    citations.append({
                        "evidence_ref": record_path,
                        "metric_paths": bucket[offset : offset + 6],
                        "crop": [0, 0, 800, 450],
                    })
            cited_paths = {citation["evidence_ref"] for citation in citations}
            cited_hashes = [
                record["sha256"]
                for record in source_records
                if record["path"] in cited_paths
            ]
            item = {
                "id": item_id,
                "source": source,
                "kind": "visual_judgment",
                "observed_at": evidence["sources"][source]["observed_at"],
                "fact": fact,
                "uncertainty": "截图转录存在视觉误差风险，所有数值必须由第二遍复核确认。",
                "alternate_interpretation": "同一局部图形也可能只是短时噪声，因此保留相反解释并绑定失效条件。",
                "metrics": metrics,
                "evidence_refs": paths[source],
                "visual_citations": citations,
                "visual_review": {
                    "status": "confirmed",
                    "primary_reader": "primary-semantic-pass",
                    "reviewer": "second-visual-pass",
                    "reviewed_at": "2026-07-13T06:40:00+08:00",
                    "metrics_sha256": canonical_sha256(metrics),
                    "evidence_sha256": canonical_sha256(
                        {"artifact_sha256s": sorted(set(cited_hashes))}
                    ),
                    "notes": "第二遍按局部坐标逐项复核，未把模糊区域解释成确定事实。",
                },
            }
            if pivot:
                item.update({"pivot_id": "pivot-1h-a", "timeframe": "1H", "subject": "BTC"})
            elif timeframe:
                item.update({"timeframe": timeframe, "subject": "BTC"})
            return item

        observations = [
            structured_observation("obs_bb", "BlockBeats", "重要快讯先分层，再与当期价格实现交叉验证。"),
            visual_observation("obs_cg", "Coinglass", "同一小时枢轴内价格、CVD与OI共同偏空。", pivot=True),
            visual_observation("obs_exo", "Exocharts", "日线足迹确认主动卖出保持占优，但不替代一小时四维主判。", timeframe="D"),
            visual_observation("obs_fw", "FedWatch", "利率概率与多窗口变化只构成宏观背景。"),
            structured_observation("obs_fs", "Farside", "最新完整交易日ETF净流出确认现货侧偏弱。"),
            visual_observation(
                "obs_tv",
                "TradingView",
                "日线到十五分钟结构分层后仍以偏空机会质量为主。",
                timeframe="1D/4H/1H/15m",
            ),
        ]
        event_hashes = method_metrics["obs_bb"]["selected_event_sha256"]
        event_realization_claim_ids = [
            f"claim_event_realization_{index}"
            for index in range(1, len(event_hashes) + 1)
        ]
        claims = [
            {"id": "claim_fundamental", "claim_type": "fundamental_context", "account": "shared", "conclusion": "基本面事件、利率预期与ETF流量共同构成当期背景但不单源翻向", "support_ids": ["obs_bb", "obs_fw", "obs_fs"], "counter_ids": [], "invalidation": "任一结构化源失效后必须重新采集并停止沿用当前背景"},
            {"id": "claim_orderflow", "claim_type": "orderflow_interpretation", "account": "shared", "direction": "short", "conclusion": "同一一小时枢轴的订单流主腿偏空并得到足迹确认", "support_ids": ["obs_cg", "obs_exo"], "counter_ids": [], "invalidation": "价格与主动成交共同转强且形成新锚点后当前盘口解释失效", "score_assessment": {"score": 60, "extreme_confirmed": False, "rationale": "价格、CVD与OI在同一主腿偏空且足迹确认，但组合未进入宪法定义的极端集合。"}},
            {"id": "claim_chart", "claim_type": "chart_interpretation", "account": "shared", "conclusion": "四周期结构与用户手绘价值区共同限定当前机会质量而不替代订单流方向", "support_ids": ["obs_tv"], "counter_ids": [], "invalidation": "一小时与四小时结构共同翻多后当前盘面解释失效"},
            *[
                {
                    "id": claim_id,
                    "claim_type": "fundamental_event_realization",
                    "account": "shared",
                    "selected_event_sha256": event_sha256,
                    "realization_state": realization_state,
                    "conclusion": "该事件的影响已按本轮基本面事实与当前价格结构独立核验兑现状态",
                    "support_ids": ["claim_fundamental", "claim_chart"],
                    "counter_ids": [],
                    "invalidation": "当前价格结构改变或事件影响通道重估后需重新核验该事件兑现状态",
                }
                for claim_id, event_sha256, realization_state in zip(
                    event_realization_claim_ids,
                    event_hashes,
                    ("partially_realized", "not_realized", "conflicted"),
                    strict=True,
                )
            ],
            {"id": "claim_realization", "claim_type": "fundamental_price_realization", "account": "shared", "realization_state": "partially_realized", "conclusion": "三项事件分别核验后，基本面总体影响仅部分被价格实现且仍需盘面确认", "support_ids": ["claim_fundamental", "claim_chart", *event_realization_claim_ids], "counter_ids": [], "invalidation": "任一事件兑现状态或当前价格结构改变后重新汇总总体兑现状态"},
            {"id": "claim_etf", "claim_type": "etf_confirmation", "account": "shared", "price_relation": "confirm", "conclusion": "ETF净流出与同锚价格下行形成确认，但不越权替代盘面与盘口", "support_ids": ["obs_cg", "obs_fs"], "counter_ids": [], "invalidation": "后续持续净流入或同锚价格方向改变会削弱当前确认", "method_tags": ["etf.confirmation_only"]},
            {"id": "claim_liqmap", "claim_type": "liquidation_confirmation", "account": "shared", "confirmation_result": "confirm", "conclusion": "固定周期清算图只辅助确认用户手绘价值区附近的磁吸概率", "support_ids": ["obs_cg", "claim_chart"], "counter_ids": [], "invalidation": "清算图与用户手绘价值区冲突时下调猎杀置信度", "method_tags": ["liquidation.auxiliary_only"]},
            {"id": "claim_liq", "claim_type": "liquidity_hunt", "account": "shared", "conclusion": "用户手绘价值区上沿附近存在反抽后的流动性猎杀概率", "support_ids": ["claim_chart", "claim_liqmap"], "counter_ids": [], "invalidation": "一小时有效站稳上沿后猎杀假设失效", "method_tags": ["VRVP.user_drawn_manual_only", "manual_vrvp.readable", "liquidity.probability_not_direction"]},
            {"id": "claim_regime_main", "claim_type": "market_regime", "account": "main", "conclusion": "基本面部分兑现且中期结构偏弱，主账户市场阶段仍属谨慎偏空", "support_ids": ["claim_realization", "claim_orderflow", "claim_chart"], "counter_ids": [], "invalidation": "四小时与基本面兑现关系共同翻多时主账户阶段失效"},
            {"id": "claim_regime_maker", "claim_type": "market_regime", "account": "maker", "conclusion": "盘口与盘面偏空但短周期存在反抽，Maker阶段为等待高质量边缘", "support_ids": ["claim_realization", "claim_orderflow", "claim_chart"], "counter_ids": [], "invalidation": "订单流与一小时结构共同翻多时Maker阶段失效"},
            {
                "id": "claim_counter_main",
                "claim_type": "strongest_counterevidence",
                "account": "main",
                "conclusion": "十五分钟结构已转强，是当前对主账户偏空判断最直接的反证",
                "support_ids": ["claim_regime_main", "claim_chart", "claim_etf"],
                "counter_ids": [],
                "invalidation": "若基本面转暖没有获得结构确认则该反证减弱",
                "current_basis": {
                    "mode": "all",
                    "clauses": [
                        {"owner_type": "observation", "owner_id": "obs_tv", "field": "timeframes.15m.structure", "operator": "equals", "value": "bullish"},
                    ],
                },
                "trigger_logic": {
                    "mode": "all",
                    "effect": "counter",
                    "clauses": [
                        {"owner_type": "observation", "owner_id": "obs_tv", "field": "timeframes.1d.structure", "operator": "becomes", "value": "bullish"},
                        {"owner_type": "observation", "owner_id": "obs_fs", "field": "flow_direction", "operator": "becomes", "value": "inflow"},
                    ],
                },
            },
            {
                "id": "claim_counter_maker",
                "claim_type": "strongest_counterevidence",
                "account": "maker",
                "conclusion": "十五分钟结构已转强，显示Maker空头入场前仍可能出现更强反抽",
                "support_ids": ["claim_regime_maker", "claim_chart", "claim_orderflow"],
                "counter_ids": [],
                "invalidation": "若反抽未延续且盘口维持偏空则该反证自然减弱",
                "current_basis": {
                    "mode": "all",
                    "clauses": [
                        {"owner_type": "observation", "owner_id": "obs_tv", "field": "timeframes.15m.structure", "operator": "equals", "value": "bullish"},
                    ],
                },
                "trigger_logic": {
                    "mode": "all",
                    "effect": "counter",
                    "clauses": [
                        {"owner_type": "observation", "owner_id": "obs_tv", "field": "timeframes.1h.structure", "operator": "becomes", "value": "bullish"},
                        {"owner_type": "observation", "owner_id": "obs_cg", "field": "final_direction", "operator": "becomes", "value": "bullish"},
                        {"owner_type": "observation", "owner_id": "obs_exo", "field": "cross_check_result", "operator": "equals_at_trigger", "value": "confirm"},
                    ],
                },
            },
            {
                "id": "claim_invalidation_main",
                "claim_type": "invalidation_path",
                "account": "main",
                "conclusion": "若日线重新站稳关键结构且现货承接恢复则主账户判断失效",
                "support_ids": ["claim_counter_main", "claim_regime_main", "claim_chart"],
                "counter_ids": [],
                "invalidation": "该条件本身就是主账户判断失效路径",
                "structural_noise_buffer": {
                    "schema_version": "structural-noise-buffer-v2",
                    "status": "certified",
                    "method_code": "pre_risk_tradingview_structure_noise_judgment",
                    "observation_id": "obs_tv",
                    "timeframe": "4h",
                    "visual_evidence_ref": next(
                        item["path"]
                        for item in records["TradingView"]
                        if str(item.get("timeframe", "")).lower() == "4h"
                    ),
                    "anchor_kind": "structure_zone_outer_boundary",
                    "anchor_source_field": "metrics.chart_basis.structure_zones[1].upper_bound",
                    "anchor_price": 100.5,
                    "noise_outer_boundary": 100.8,
                    "price_distance": 0.5,
                    "risk_budget_input_used": False,
                    "insufficiency_reason_code": None,
                },
                "current_basis": {
                    "mode": "all",
                    "clauses": [
                        {"owner_type": "observation", "owner_id": "obs_tv", "field": "timeframes.1d.structure", "operator": "equals", "value": "bearish"},
                    ],
                },
                "trigger_logic": {
                    "mode": "all",
                    "effect": "invalidate",
                    "clauses": [
                        {"owner_type": "observation", "owner_id": "obs_tv", "field": "timeframes.1d.structure", "operator": "becomes", "value": "bullish"},
                        {"owner_type": "observation", "owner_id": "obs_tv", "field": "timeframes.4h.structure", "operator": "becomes", "value": "bullish"},
                        {"owner_type": "observation", "owner_id": "obs_fs", "field": "flow_direction", "operator": "becomes", "value": "inflow"},
                    ],
                },
            },
            {
                "id": "claim_invalidation_maker",
                "claim_type": "invalidation_path",
                "account": "maker",
                "conclusion": "若一小时重新站稳价值区上沿且订单流同步转强则Maker判断失效",
                "support_ids": ["claim_counter_maker", "claim_regime_maker", "claim_chart"],
                "counter_ids": [],
                "invalidation": "该条件本身就是Maker判断失效路径",
                "structural_noise_buffer": {
                    "schema_version": "structural-noise-buffer-v2",
                    "status": "certified",
                    "method_code": "pre_risk_tradingview_structure_noise_judgment",
                    "observation_id": "obs_tv",
                    "timeframe": "1h",
                    "visual_evidence_ref": next(
                        item["path"]
                        for item in records["TradingView"]
                        if str(item.get("timeframe", "")).lower() == "1h"
                    ),
                    "anchor_kind": "structure_zone_outer_boundary",
                    "anchor_source_field": "metrics.chart_basis.structure_zones[2].upper_bound",
                    "anchor_price": 100.2,
                    "noise_outer_boundary": 100.3,
                    "price_distance": 0.15,
                    "risk_budget_input_used": False,
                    "insufficiency_reason_code": None,
                },
                "current_basis": {
                    "mode": "all",
                    "clauses": [
                        {"owner_type": "observation", "owner_id": "obs_tv", "field": "timeframes.1h.structure", "operator": "equals", "value": "bearish"},
                        {"owner_type": "observation", "owner_id": "obs_cg", "field": "final_direction", "operator": "equals", "value": "bearish"},
                    ],
                },
                "trigger_logic": {
                    "mode": "all",
                    "effect": "invalidate",
                    "clauses": [
                        {"owner_type": "observation", "owner_id": "obs_tv", "field": "timeframes.1h.structure", "operator": "becomes", "value": "bullish"},
                        {"owner_type": "observation", "owner_id": "obs_cg", "field": "pivot.anchor_reset", "operator": "becomes", "value": True},
                        {"owner_type": "observation", "owner_id": "obs_cg", "field": "final_direction", "operator": "becomes", "value": "bullish"},
                        {"owner_type": "observation", "owner_id": "obs_exo", "field": "cross_check_result", "operator": "equals_at_trigger", "value": "confirm"},
                    ],
                },
            },
            {"id": "claim_main", "claim_type": "main_account_thesis", "account": "main", "direction": "short", "conclusion": "基本面未完全兑现且主账户阶段偏弱，主账户维持谨慎偏空", "support_ids": ["claim_regime_main", "claim_realization", "claim_etf"], "counter_ids": ["claim_counter_main"], "invalidation": "日线重新站稳关键结构并出现现货持续净流入", "invalidation_id": "claim_invalidation_main"},
            {"id": "claim_maker", "claim_type": "maker_thesis", "account": "maker", "direction": "short", "conclusion": "同一小时订单流与Maker阶段偏空，反抽至高质量边缘后计划做空", "support_ids": ["claim_regime_maker", "claim_orderflow", "claim_chart", "claim_liq"], "counter_ids": ["claim_counter_maker"], "invalidation": "一小时价格与主动成交共同转强并站稳上沿", "invalidation_id": "claim_invalidation_maker", "method_tags": ["orderflow.pivot", "orderflow.price_cvd", "orderflow.oi", "orderflow.funding", "orderflow.footprint_confirmation"]},
            {"id": "claim_cannot", "claim_type": "cannot_do", "account": "maker", "prohibition": "追空", "conclusion": "Maker不能在低位右侧追空或在计划边缘外临时成交", "support_ids": ["claim_maker", "claim_counter_maker", "claim_invalidation_maker"], "counter_ids": [], "invalidation": "只有Maker既定失效路径成立后才允许重建判断"},
        ]
        gold_methodology = {
            "independent_synthesis": {
                "market_stage_claim_id": "claim_regime_maker",
                "dominant_leg": "down",
                "primary_evidence_claim_ids": ["claim_orderflow", "claim_chart"],
                "strongest_counter_claim_id": "claim_counter_maker",
                "action_claim_id": "claim_maker",
            },
            "fundamental_price_realization": {
                "fundamental_claim_id": "claim_fundamental",
                "price_claim_id": "claim_chart",
                "realization_claim_id": "claim_realization",
                "realization_state": "partially_realized",
                "historical_market_fact_used": False,
            },
            "fundamental_event_assessments": [
                {
                    "selected_event_sha256": event_sha256,
                    "impact_channel": impact_channel,
                    "expected_effect": expected_effect,
                    "realization_claim_id": realization_claim_id,
                    "counter_claim_ids": ["claim_orderflow", "claim_chart"],
                    "boundary_code": "no_standalone_direction_requires_cross_source_realization",
                }
                for event_sha256, realization_claim_id, impact_channel, expected_effect in zip(
                    event_hashes,
                    event_realization_claim_ids,
                    ("liquidity", "regulation", "risk_appetite"),
                    (
                        "two_sided_or_conditional",
                        "no_material_effect",
                        "adverse_for_risk_assets",
                    ),
                    strict=True,
                )
            ],
            "same_pivot_orderflow": {
                "observation_id": "obs_cg",
                "claim_id": "claim_orderflow",
                "leg_selected": True,
                "pullback_anchor_checked": True,
                "four_dimensions_same_anchor": True,
            },
            "footprint_cross_check": {
                "observation_id": "obs_exo",
                "claim_id": "claim_orderflow",
                "relationship": "confirm",
            },
            "multi_timeframe_transition": {
                "observation_id": "obs_tv",
                "claim_id": "claim_chart",
                "transition_summary": "日线、四小时与一小时仍偏空，十五分钟仅保留短线反抽反证。",
            },
            "volume_profile_liquidity": {
                "claim_id": "claim_chart",
                "liquidation_observation_id": "obs_cg",
                "user_drawn_profile_primary": True,
                "liquidation_auxiliary": True,
                "liquidation_confirmation": "confirm",
            },
            "etf_flow_relation": {
                "observation_id": "obs_fs",
                "claim_id": "claim_etf",
                "price_relation": "confirm",
            },
            "account_separation": {
                "main_priority": ["fundamentals", "chart", "orderflow"],
                "maker_priority": ["orderflow", "chart", "fundamentals"],
                "main_claim_id": "claim_main",
                "maker_claim_id": "claim_maker",
                "main_regime_claim_id": "claim_regime_main",
                "maker_regime_claim_id": "claim_regime_maker",
                "main_counter_claim_id": "claim_counter_main",
                "maker_counter_claim_id": "claim_counter_maker",
                "main_invalidation_claim_id": "claim_invalidation_main",
                "maker_invalidation_claim_id": "claim_invalidation_maker",
                "conflict_policy": "preserve_independent_outputs",
                "forced_consensus": False,
            },
            "scenario_tree": [
                {"account": "main", "kind": "base", "claim_id": "claim_main", "trigger_claim_ids": ["claim_regime_main"], "action": "retain_certified_assessment"},
                {"account": "main", "kind": "counter", "claim_id": "claim_counter_main", "trigger_claim_ids": ["claim_chart"], "action": "reassess_on_typed_counter"},
                {"account": "main", "kind": "invalidation", "claim_id": "claim_invalidation_main", "trigger_claim_ids": ["claim_regime_main"], "action": "invalidate_and_recollect_evidence"},
                {"account": "maker", "kind": "base", "claim_id": "claim_maker", "trigger_claim_ids": ["claim_orderflow"], "action": "retain_certified_assessment"},
                {"account": "maker", "kind": "counter", "claim_id": "claim_counter_maker", "trigger_claim_ids": ["claim_chart"], "action": "reassess_on_typed_counter"},
                {"account": "maker", "kind": "invalidation", "claim_id": "claim_invalidation_maker", "trigger_claim_ids": ["claim_regime_maker"], "action": "invalidate_and_recollect_evidence"},
            ],
            "cannot_do_derivation": {
                "claim_id": "claim_cannot",
                "basis_claim_ids": ["claim_maker", "claim_counter_maker", "claim_invalidation_maker"],
            },
        }
        section_text = {
            "opening_quote": "以下结论仅来自本时段完整六源证据与独立分析。",
            "cannot_do": "追空：禁止在低位右侧追空，只能在认证区间左侧分档挂单",
            "fundamentals": "重要快讯和利率预期没有形成翻多证据，ETF净流出削弱现货承接",
            "orderflow_label": "同一1H枢轴",
            "orderflow_text": "价格回落、未平仓量下降且主动卖出成交占优，盘口整体偏空。",
            "interpretation": "短线反抽属于反证而非主方向，等待价格回到高质量边缘",
            "chart_label": "机会质量保持中等偏上",
            "daily_line": "日线仍位于关键结构压力下方，暂未完成趋势转强",
            "hourly_line": "一小时价值区上沿构成反抽压力，十五分钟只用于执行确认",
            "trend_confirmation": "趋势尚未翻多，主账户谨慎偏空，Maker等待反抽做空。",
            "support_resistance": "1H支撑98.20；1H压力99.80–100.00；取消观察位96.50。",
            "strategy": "主账户保持谨慎偏空，不因盘口短期波动改写中线方向",
            "maker_strategy": "只在99.80–100.00区间分档限价做空，价格不到区间不成交",
            "maker_tp": "TP1与TP2均由风险决策合同生成，正文不得手工改写数值",
            "maker_sl": "100.35，未成交前取消价与成交后止损严格区分",
            "defense_first": "成交后若后续形成并确认4H新极点则按新极点规则处理，不预填极点价",
            "defense_second": "仅把剩余仓位止损移至保本损",
            "defense_note": "任何防守动作都以系统计划为准，不映射用户实际持仓",
            "defense_cancel": "未成交前触及96.50只取消订单；成交后止损为100.35",
            "independent_boundary": "主账户与Maker计划互不干扰，并与用户实际持仓完全解耦",
        }
        section_claims = {
            "cannot_do": ["claim_cannot"],
            "fundamentals": ["claim_main", "claim_etf"],
            "orderflow_text": ["claim_maker"],
            "interpretation": ["claim_maker", "claim_counter_maker"],
            "daily_line": ["claim_main"],
            "hourly_line": ["claim_liq"],
            "trend_confirmation": ["claim_main", "claim_maker"],
            "support_resistance": ["claim_liq", "claim_invalidation_maker"],
            "strategy": ["claim_main"],
            "maker_strategy": ["claim_maker"],
            "maker_tp": ["claim_maker"],
            "maker_sl": ["claim_invalidation_maker"],
            "defense_first": ["claim_invalidation_maker"],
            "defense_second": ["claim_maker"],
            "defense_note": ["claim_maker"],
            "defense_cancel": ["claim_invalidation_maker"],
            "independent_boundary": ["claim_main", "claim_maker"],
        }
        sections = {
            name: {"text": text, "claim_ids": section_claims.get(name, [])}
            for name, text in section_text.items()
        }
        methodology_manifest = json.loads((self.run_root / "methodology_manifest.json").read_text(encoding="utf-8"))
        payload = {
            "schema_version": "reasoning-model-v5",
            "trading_date": self.date,
            "slot": self.slot,
            "evidence_snapshot_sha256": evidence["snapshot_sha256"],
            "reasoning_authority_sha256": methodology_manifest["phases"]["reasoning"]["phase_sha256"],
            "observations": observations,
            "claims": claims,
            "methodology": gold_methodology,
            "scenario_tree": [
                {"id": "scenario_main_base", "account": "main", "scenario_type": "base", "owner_claim_id": "claim_main"},
                {"id": "scenario_main_counter", "account": "main", "scenario_type": "counter", "owner_claim_id": "claim_counter_main"},
                {"id": "scenario_main_invalidation", "account": "main", "scenario_type": "invalidation", "owner_claim_id": "claim_invalidation_main"},
                {"id": "scenario_maker_base", "account": "maker", "scenario_type": "base", "owner_claim_id": "claim_maker"},
                {"id": "scenario_maker_counter", "account": "maker", "scenario_type": "counter", "owner_claim_id": "claim_counter_maker"},
                {"id": "scenario_maker_invalidation", "account": "maker", "scenario_type": "invalidation", "owner_claim_id": "claim_invalidation_maker"}
            ],
        }
        return assemble_reasoning_submission(
            payload,
            evidence=evidence,
            reasoning_authority_sha256=methodology_manifest["phases"][
                "reasoning"
            ]["phase_sha256"],
            contract=load_reasoning_submission_contract(root=self.root),
            full_policy=load_scoring_policy(root=self.root),
        )

    def decision(self, reasoning: dict) -> dict:
        run = self.controller.store.load_run(self.run_root)
        execution_authorization = (
            {
                "source_kind": "sealed_shadow_run",
                "source_sha256": run["run_sha256"],
                "live_execution_allowed": False,
                "reason_code": "shadow_mode_forbids_live_execution",
            }
            if self.run_mode == "shadow"
            else {
                "source_kind": "notion_pretrade_gate",
                "source_sha256": self.gate["manifest_sha256"],
                "live_execution_allowed": True,
                "reason_code": "pretrade_gate_allows_live_execution",
            }
        )
        continuity_contract = (
            {
                "schema_version": "shadow-execution-continuity-vnext-v1",
                "reasoning_sha256": reasoning["reasoning_sha256"],
                "run_sha256": run["run_sha256"],
                "live_state_read": False,
                "order_mutation_attempted": False,
                "execution_action": "not_attempted",
                "plan_valid_until": f"{self.date}T23:30:00+08:00",
                "reason_code": "shadow_mode_forbids_live_execution",
            }
            if self.run_mode == "shadow"
            else {
                "schema_version": "post-reasoning-continuity-contract-vnext-v1",
                "reasoning_sha256": reasoning["reasoning_sha256"],
                "prior_plan": {
                    "source_kind": "none",
                    "reference": "",
                    "source_sha256": "",
                    "observed_at": None,
                    "status": "none",
                    "executed_pct": 0,
                    "executable_order_count_before": 0,
                    "daily_trade_count_before": 0,
                    "summary": "本轮没有可核验的既有系统Maker计划，按新计划处理。",
                },
                "current_plan": {
                    "action": "new",
                    "old_order_cancelled": False,
                    "new_order_created": True,
                    "executable_order_count_after": 1,
                    "executed_pct": 0,
                    "daily_trade_count_after": 0,
                    "valid_until": f"{self.date}T23:30:00+08:00",
                    "independent_analysis_changed_after_lock": False,
                    "reason": "独立推理已锁定且无既有订单，因此只新建一个左侧Maker计划。",
                },
            }
        )
        return {
            "schema_version": "decision-model-v7",
            "run_id": run["run_id"],
            "run_sha256": run["run_sha256"],
            "run_mode": run["run_mode"],
            "trading_date": self.date,
            "slot": self.slot,
            "evidence_snapshot_sha256": reasoning["evidence_snapshot_sha256"],
            "reasoning_sha256": reasoning["reasoning_sha256"],
            "execution_authorization": execution_authorization,
            "main_account": {
                "direction": "short",
                "claim_id": "claim_main",
                "plan_state": "new",
                "action": "build",
                "exchange": "Binance",
                "instrument": "BTCUSDT",
                "position_notional_usdt": 3000,
                "leverage": 5,
                "entry_mode": "staged_ladder",
                "entry_zone_basis": {
                    "observation_id": "obs_tv",
                    "zone_kind": "manual_profile",
                    "zone_index": 0,
                },
                "entries": [99.5, 99.6, 99.7, 99.8],
                "entry_allocations_pct": [25, 25, 25, 25],
                "stop_basis": {
                    "observation_id": "obs_tv",
                    "claim_id": "claim_invalidation_main",
                    "timeframe": "4h",
                    "anchor_kind": "structure_zone_outer_boundary",
                    "anchor_source_field": "metrics.chart_basis.structure_zones[1].upper_bound",
                    "anchor_price": 100.5,
                    "buffer_basis_code": "current_run_typed_market_noise_allowance",
                    "buffer_claim_id": "claim_invalidation_main",
                    "outward_buffer_price": 0.5,
                    "buffer_backsolved_from_risk": False,
                    "derived_stop": 101.0,
                },
                "stop": 101.0,
                "tp1": 96.0,
                "final_take_profit": 94.0,
                "tp1_close_pct": 20,
                "counter_claim_id": "claim_counter_main",
                "invalidation_claim_id": "claim_invalidation_main",
                "scenario_ids": [
                    "scenario_main_base",
                    "scenario_main_counter",
                    "scenario_main_invalidation",
                ],
                "plan_state_reason_code": "new_typed_plan",
            },
            "maker": {
                "claim_id": "claim_maker",
                "combination_id": "C80",
                "direction": "short",
                "plan_state": "qualified",
                "threshold_eligible": True,
                "plan_constructible": True,
                "plan_constructibility": {
                    "status": "constructible",
                    "primary_reason_code": "constructible",
                    "failure_codes": [],
                    "entry_zone_basis": {
                        "observation_id": "obs_tv",
                        "zone_kind": "manual_profile",
                        "zone_index": 0,
                    },
                    "claim_ids": [
                        "claim_maker",
                        "claim_counter_maker",
                        "claim_invalidation_maker",
                    ],
                },
                "execution_action": (
                    "not_attempted" if self.run_mode == "shadow" else "place_order"
                ),
                "order_transition_action": (
                    "not_attempted" if self.run_mode == "shadow" else "new"
                ),
                "strategy_type": "反弹空",
                "order_method": "Maker",
                "entry_type": "left",
                "exchange": "OKX",
                "instrument": "BTCUSDT",
                "position_notional_usdt": 750,
                "cannot_do_code": "追空",
                "cannot_do_claim_id": "claim_cannot",
                "orderflow_score": 60,
                "extreme_confirmed": False,
                "orderflow_scorecard": {
                    "score": 60,
                    "claim_ids": ["claim_maker"],
                },
                "chart_components": {
                    "chart.support_resistance": 8,
                    "chart.liquidity_hunt": 8,
                    "chart.sma20_interaction": 4,
                    "chart.volume_price": 2,
                    "chart.fibonacci_trendline": 1,
                },
                "chart_scorecard": {
                    "chart.support_resistance": {
                        "score": 8,
                        "claim_ids": ["claim_liq", "claim_invalidation_maker"],
                    },
                    "chart.liquidity_hunt": {
                        "score": 8,
                        "claim_ids": ["claim_liq"],
                    },
                    "chart.sma20_interaction": {
                        "score": 4,
                        "claim_ids": ["claim_chart", "claim_regime_maker"],
                        "timeframe_relations": {
                            "1d": "below",
                            "4h": "below",
                            "1h": "below"
                        },
                    },
                    "chart.volume_price": {
                        "score": 2,
                        "claim_ids": ["claim_maker"],
                    },
                    "chart.fibonacci_trendline": {
                        "score": 1,
                        "claim_ids": ["claim_invalidation_maker"],
                    },
                },
                "chart_score": 23,
                "total_score": 83,
                "win_rate": 64,
                "entry_reach_probability": 58,
                "entry_reach_probability_basis": {
                    "applicability": "applicable",
                    "claim_ids": ["claim_maker", "claim_counter_maker"],
                    "reference_source": "TradingView",
                    "reference_timeframe": "1h",
                    "reference_price": 97,
                    "reference_entry": 99.8,
                    "entry_distance": 2.8,
                    "reach_direction": "up_to_entry",
                },
                "order_lifecycle": {
                    "schema_version": "maker-order-lifecycle-v1",
                    "state": "fillable",
                    "legal_fill_path_exists": True,
                    "legal_cancel_path_exists": True,
                    "fill_probability": None,
                    "fill_probability_applicability": "not_estimated_lifecycle_only",
                    "reason_code": "fillable",
                },
                "winrate_rubric": {
                    "anchor": 68,
                    "anchor_claim_ids": [
                        "claim_orderflow",
                        "claim_chart",
                        "claim_invalidation_maker",
                    ],
                    "anchor_rationale": "盘口轴与结构位置轴均已按类型化 claim 和可达来源认证；基准锚不读取计划状态、60%门槛或开单结果。",
                    "adjustments": [
                        {
                            "reason_code": "maker_counter_current",
                            "label": "十五分钟转强反证",
                            "delta": -4,
                            "claim_ids": ["claim_counter_maker"],
                            "rationale": "十五分钟结构已转强，因此从基准锚下调四个百分点。",
                        }
                    ],
                    "signal_dispositions": [
                        {
                            "signal_type": "etf_confirmation",
                            "claim_id": "claim_etf",
                            "disposition": "no_adjustment",
                            "adjustment_reason_code": None,
                            "no_adjustment_reason_code": "reviewed_no_independent_incremental_effect"
                        },
                        {
                            "signal_type": "fundamental_price_realization",
                            "claim_id": "claim_realization",
                            "disposition": "no_adjustment",
                            "adjustment_reason_code": None,
                            "no_adjustment_reason_code": "event_price_attribution_unavailable"
                        }
                    ],
                    "counter_resolution": {
                        "counter_claim_id": "claim_counter_maker",
                        "disposition": "adjusted",
                        "adjustment_reason_code": "maker_counter_current",
                        "residual_clause_indexes": [0],
                        "resolution_claim_ids": [],
                    },
                    "final": 64,
                },
                "risk_plan": {
                    "entries": [99.8, 100.0],
                    "entry_allocations_pct": [50, 50],
                    "stop_basis": {
                        "observation_id": "obs_tv",
                        "claim_id": "claim_invalidation_maker",
                        "timeframe": "1h",
                        "anchor_kind": "structure_zone_outer_boundary",
                        "anchor_source_field": "metrics.chart_basis.structure_zones[2].upper_bound",
                        "anchor_price": 100.2,
                        "buffer_basis_code": "current_run_typed_market_noise_allowance",
                        "buffer_claim_id": "claim_invalidation_maker",
                        "outward_buffer_price": 0.15,
                        "buffer_backsolved_from_risk": False,
                        "derived_stop": 100.35,
                    },
                    "stop": 100.35,
                    "tp1": 98.0,
                    "tp2": 97.0,
                    "tp1_close_pct": 50,
                    "tp2_close_pct": 50,
                    "leverage": 5,
                    "cancel_before_fill": 96.5,
                },
                "defense_plan": {
                    "mode": "ladder_prefill_exact_scenarios",
                    "prefill_anchor": {
                        "kind": "planned_full_ladder_weighted_fill",
                        "weighted_fill": 99.9,
                        "is_actual_fill": False,
                        "is_single_entry": False,
                    },
                    "trigger_scenarios": [
                        {
                            "risk_scenario_id": "fill-1",
                            "filled_level_indexes": [1],
                            "weighted_fill": 99.8,
                            "first_trigger_price_raw": "98.975",
                            "second_trigger_price_raw": "98.7",
                            "rounding_rule": "exact_no_rounding",
                            "rounding_step": None,
                            "first_trigger_price": 98.975,
                            "second_trigger_price": 98.7,
                        },
                        {
                            "risk_scenario_id": "fill-2",
                            "filled_level_indexes": [2],
                            "weighted_fill": 100.0,
                            "first_trigger_price_raw": "99.475",
                            "second_trigger_price_raw": "99.3",
                            "rounding_rule": "exact_no_rounding",
                            "rounding_step": None,
                            "first_trigger_price": 99.475,
                            "second_trigger_price": 99.3,
                        },
                        {
                            "risk_scenario_id": "fill-1-2",
                            "filled_level_indexes": [1, 2],
                            "weighted_fill": 99.9,
                            "first_trigger_price_raw": "99.225",
                            "second_trigger_price_raw": "99",
                            "rounding_rule": "exact_no_rounding",
                            "rounding_step": None,
                            "first_trigger_price": 99.225,
                            "second_trigger_price": 99.0,
                        },
                    ],
                    "postfill_recalculation": {
                        "required": True,
                        "anchor": "actual_weighted_fill",
                        "replace_prefill_projection": True,
                    },
                    "first_stop_rule": "confirmed_post_fill_4h_structural_extreme",
                    "second_action": "move_stop_to_breakeven_only",
                },
            },
            "continuity_contract": continuity_contract,
        }

    def prepare_through_reasoning(self) -> tuple[dict, dict]:
        raw_evidence = self.evidence()
        self.controller.accept_evidence(
            self.run_root,
            raw_evidence,
            evidence_files_root=self.root,
        )
        evidence = self.controller.store.load_stage_payload(self.run_root, "evidence", "evidence")
        reasoning = self.reasoning(evidence)
        self.controller.accept_reasoning(self.run_root, reasoning)
        reasoning = self.controller.store.load_stage_payload(self.run_root, "reasoning", "reasoning")
        return evidence, reasoning

    def prepare_through_decision(self) -> tuple[dict, dict, dict]:
        evidence, reasoning = self.prepare_through_reasoning()
        decision = self.decision(reasoning)
        self.controller.accept_decision(self.run_root, decision)
        decision = self.controller.store.load_stage_payload(self.run_root, "decision", "decision")
        return evidence, reasoning, decision

    def evaluate_reasoning_candidate(self, evidence: dict, payload: dict):
        methodology = json.loads(
            (self.run_root / "methodology_manifest.json").read_text(encoding="utf-8")
        )
        return evaluate_reasoning(
            payload,
            evidence=evidence,
            reasoning_authority_sha256=methodology["phases"]["reasoning"]["phase_sha256"],
            evidence_root=self.root,
            methodology_root=self.root,
        )

    def reasoning_fixture(self) -> dict:
        self.controller.accept_evidence(
            self.run_root,
            self.evidence(),
            evidence_files_root=self.root,
        )
        evidence = self.controller.store.load_stage_payload(
            self.run_root,
            "evidence",
            "evidence",
        )
        return self.reasoning(evidence)

    def profile_sidecar_record(self, evidence: dict) -> dict:
        return next(
            record
            for record in evidence["sources"]["TradingView"]["artifacts"]
            if Path(record["path"]).name == "tradingview_profile_state.json"
        )

    def rewrite_profile_sidecar(
        self,
        evidence: dict,
        *,
        mutate=None,
        raw: str | None = None,
        refresh_record: bool = True,
    ) -> None:
        record = self.profile_sidecar_record(evidence)
        target = self.root / record["path"]
        if raw is None:
            payload = json.loads(target.read_text(encoding="utf-8"))
            if mutate is not None:
                mutate(payload)
            raw = json.dumps(payload, ensure_ascii=False)
        target.write_text(raw, encoding="utf-8")
        if refresh_record:
            record["sha256"] = sha256_file(target)
            record["bytes"] = target.stat().st_size

    def tradingview_profile_binding_codes(
        self,
        evidence: dict,
        reasoning: dict,
    ) -> set[str]:
        tradingview = next(
            item for item in reasoning["observations"] if item["source"] == "TradingView"
        )
        issues = []
        _validate_tradingview_profile_sidecar_binding(
            tradingview,
            evidence,
            self.root,
            load_scoring_policy(root=self.root)["tradingview_profile_policy"],
            issues,
        )
        return {item.code for item in issues}

    def file_record(self, relative: str, content: bytes) -> dict:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return {
            "path": path.relative_to(self.root).as_posix(),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }

    @staticmethod
    def valid_docx_bytes() -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(
                "[Content_Types].xml",
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
            )
            archive.writestr(
                "_rels/.rels",
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
            )
            archive.writestr(
                "word/document.xml",
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body/></w:document>',
            )
        return buffer.getvalue()

    @staticmethod
    def valid_png_bytes() -> bytes:
        def chunk(kind: bytes, payload: bytes) -> bytes:
            checksum = zlib.crc32(kind)
            checksum = zlib.crc32(payload, checksum) & 0xFFFFFFFF
            return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)

        width, height = 800, 450
        ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        image = zlib.compress((b"\x00" + (b"\x00" * width * 3)) * height)
        return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", image) + chunk(b"IEND", b"")

    @staticmethod
    def valid_pdf_bytes() -> bytes:
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 10 10] /Contents 4 0 R >>",
            b"<< /Length 0 >>\nstream\n\nendstream",
        ]
        payload = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for index, body in enumerate(objects, start=1):
            offsets.append(len(payload))
            payload.extend(f"{index} 0 obj\n".encode("ascii"))
            payload.extend(body + b"\nendobj\n")
        xref = len(payload)
        payload.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
        payload.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            payload.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
        payload.extend(
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii")
        )
        return bytes(payload)

    def delivery(self, *, unique_page_count: int = 1) -> dict:
        checkpoint = self.controller.store.load_checkpoint(self.run_root)
        run = self.controller.store.load_run(self.run_root)
        report_outputs = checkpoint["completed"]["report"]["outputs"]
        report = report_outputs["combined"]
        tag = uuid.uuid4().hex
        run_relative = self.run_root.relative_to(self.root)
        delivery_assets = run_relative / "delivery_assets"
        word_attempt = (
            delivery_assets / "word_qa" / f"attempt-001-{tag[:8]}"
        )
        docx = self.file_record(
            (
                delivery_assets
                / f"{self.date}_{self.slot}_render.docx"
            ).as_posix(),
            self.valid_docx_bytes(),
        )
        pdf = self.file_record(
            (
                word_attempt
                / f"{self.date}_{self.slot}_render.pdf"
            ).as_posix(),
            self.valid_pdf_bytes(),
        )
        page = self.file_record(
            (word_attempt / "page-1.png").as_posix(),
            self.valid_png_bytes(),
        )
        page["page"] = 1
        cards_spec = report_outputs["cards_spec"]
        card_images = [report_outputs[f"card_{index}"] for index in range(1, 4)]
        card_sha256s = [record["sha256"] for record in card_images]
        word_payload = {
            "schema_version": "word-qa-vnext-v2",
            "status": "passed",
            "visual_qa_pass": True,
            "created_at": "2026-07-13T08:25:00+08:00",
            "trading_date": self.date,
            "slot": self.slot,
            "run_id": run["run_id"],
            "run_sha256": run["run_sha256"],
            "attempts": 1,
            "cache_hit": False,
            "backend": "word_com",
            "page_renderer": "pdftoppm.exe",
            "report_sha256": report["sha256"],
            "docx": docx,
            "docx_sha256": docx["sha256"],
            "pdf": pdf,
            "pdf_sha256": pdf["sha256"],
            "page_count": 1,
            "inspected_pages": [1],
            "page_images": [page],
            "reviewer": "Codex",
            "reviewed_at": "2026-07-13T08:27:00+08:00",
            "review_checklist_version": WORD_QA_REVIEW_CHECKLIST_VERSION,
            "review_checklist": {
                key: True for key in WORD_QA_REVIEW_CHECKLIST_KEYS
            },
        }
        qa = self.file_record(
            (delivery_assets / "word_qa.json").as_posix(),
            json.dumps(word_payload, ensure_ascii=False).encode("utf-8"),
        )
        publish_payload = {
            "schema_version": "publish-vnext-v1",
            "status": "passed",
            "structure_pass": True,
            "visual_contract_pass": True,
            "unique_page_count": unique_page_count,
            "report_sha256": report["sha256"],
            "page_id": "38efda35-a098-810c-b9c3-cdf448a9d226",
            "children_signature_sha256": "a" * 64,
            "cards_spec_sha256": cards_spec["sha256"],
            "card_sha256s": card_sha256s,
            "published_at": "2026-07-13T08:29:00+08:00",
        }
        publish_manifest = self.file_record(
            f"delivery/{tag}/publish.json",
            json.dumps(publish_payload, ensure_ascii=False).encode("utf-8"),
        )
        verification_payload = {
            "schema_version": "notion-verification-vnext-v1",
            "status": "passed",
            "structure_pass": True,
            "visual_contract_pass": True,
            "unique_page_count": unique_page_count,
            "report_sha256": report["sha256"],
            "page_id": publish_payload["page_id"],
            "children_signature_sha256": publish_payload["children_signature_sha256"],
            "cards_spec_sha256": cards_spec["sha256"],
            "card_sha256s": card_sha256s,
            "readback_at": "2026-07-13T08:30:00+08:00",
        }
        verification_manifest = self.file_record(
            f"delivery/{tag}/notion_verification.json",
            json.dumps(verification_payload, ensure_ascii=False).encode("utf-8"),
        )
        return {
            "schema_version": "delivery-model-v1",
            "report": report,
            "render": {
                "docx": docx,
                "pdf": pdf,
                "word_qa": qa,
            },
            "cards": {
                "spec": cards_spec,
                "images": card_images,
            },
            "publish": {
                "manifest": publish_manifest,
                "verification": verification_manifest,
            },
        }

    def shadow_delivery(self) -> dict:
        production = self.delivery()
        return {
            "schema_version": "shadow-delivery-model-v1",
            "report": production["report"],
            "render": production["render"],
            "cards": production["cards"],
            "publish": {
                "status": "not_attempted",
                "reason": "shadow_mode_forbids_notion",
            },
        }

    def rewrite_delivery_word_qa(self, delivery: dict, mutate) -> dict:
        record = delivery["render"]["word_qa"]
        path = self.root / record["path"]
        payload = json.loads(path.read_text(encoding="utf-8"))
        mutate(payload)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        record["sha256"] = sha256_file(path)
        record["bytes"] = path.stat().st_size
        return payload

    def test_methodology_manifest_is_phase_scoped_and_contains_additions(self):
        manifest = build_methodology_manifest(root=self.root)
        self.assertEqual(manifest["schema_version"], "methodology-manifest-v3")
        self.assertEqual(
            manifest["policy"],
            MANIFEST_V3_POLICY,
        )
        self.assertRegex(manifest["domain_registry_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(set(manifest["phases"]), {"evidence", "reasoning", "report"})
        for phase_name, phase in manifest["phases"].items():
            self.assertTrue(phase["files"])
            self.assertEqual(
                [record["path"] for record in phase["semantic_files"]],
                list(PHASE_SEMANTIC_FILES[phase_name]),
            )
            self.assertRegex(phase["phase_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(
                phase["semantic_phase_sha256"],
                r"^[0-9a-f]{64}$",
            )
        self.assertEqual(
            tuple(
                record["path"] for record in manifest["semantic_runtime"]["files"]
            ),
            SEMANTIC_RUNTIME_FILES,
        )
        self.assertRegex(
            manifest["semantic_runtime"]["semantic_runtime_sha256"],
            r"^[0-9a-f]{64}$",
        )
        self.assertRegex(manifest["semantic_contract_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(manifest["release_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(manifest["manifest_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            {record["path"] for record in manifest["control_plane"]["files"]},
            set(CONTROL_PLANE_FILES),
        )
        self.assertRegex(manifest["control_plane"]["control_sha256"], r"^[0-9a-f]{64}$")
        control_file = self.root / "runtime_vnext" / "gates.py"
        control_file.write_text(
            control_file.read_text(encoding="utf-8") + "\n# epoch-change-test\n",
            encoding="utf-8",
        )
        changed = build_methodology_manifest(root=self.root)
        # The public gate facade participates in semantic dispatch.  A byte
        # change can redirect which stage validator runs, so it must rotate
        # both semantic and release identity even though it owns no policy.
        self.assertNotEqual(
            changed["semantic_contract_sha256"],
            manifest["semantic_contract_sha256"],
        )
        self.assertNotEqual(
            changed["release_sha256"],
            manifest["release_sha256"],
        )
        self.assertNotEqual(
            changed["control_plane"]["control_sha256"],
            manifest["control_plane"]["control_sha256"],
        )
        self.assertNotEqual(changed["manifest_sha256"], manifest["manifest_sha256"])

    def test_methodology_control_hash_binds_blockbeats_priority_helper(self):
        manifest = build_methodology_manifest(root=self.root)
        evidence = manifest["phases"]["evidence"]
        helper_relative = "tools/browser_capture/blockbeats_priority.js"
        self.assertNotIn(
            helper_relative,
            {record["path"] for record in evidence["files"]},
        )
        self.assertIn(
            helper_relative,
            {record["path"] for record in manifest["control_plane"]["files"]},
        )

        helper = self.root / helper_relative
        helper.write_text(
            helper.read_text(encoding="utf-8") + "\n// evidence-epoch-change-test\n",
            encoding="utf-8",
        )
        changed = build_methodology_manifest(root=self.root)
        self.assertEqual(
            changed["phases"]["evidence"]["phase_sha256"],
            evidence["phase_sha256"],
        )
        self.assertNotEqual(
            changed["control_plane"]["control_sha256"],
            manifest["control_plane"]["control_sha256"],
        )
        self.assertNotEqual(changed["manifest_sha256"], manifest["manifest_sha256"])

    def test_golden_contract_contains_metadata_and_invariants_only(self):
        contract = load_contract(
            self.root / "governance" / "vnext_golden_sample_contract.json"
        )
        self.assertEqual(contract["sample_count"], 8)
        self.assertEqual(contract["total_pages"], 58)
        self.assertTrue(contract["visual_qa"]["all_pages_inspected"])
        self.assertEqual(
            set(contract["samples"][0]),
            {"file", "sha256", "bytes", "page_count", "paragraphs"},
        )
        self.assertIn("etf_net_flow", contract["july_additions"]["required"])
        self.assertNotIn("vrvp", contract["required_markers"])
        self.assertNotIn("liquidation_map", contract["required_markers"])
        self.assertIn(
            "historical_narrative_as_market_evidence",
            contract["runtime_boundary"]["forbidden"],
        )

    def test_run_v2_hashes_authorization_and_requires_exact_requested_effort(self):
        run = self.controller.store.load_run(self.run_root)
        methodology = json.loads(
            (self.run_root / "methodology_manifest.json").read_text(encoding="utf-8")
        )
        raw_reference = f"test-{self.run_mode}-approval"
        self.assertEqual(run["schema_version"], "daily-run-vnext-v2")
        self.assertEqual(run["run_mode"], self.run_mode)
        self.assertNotIn("methodology_sha256", run)
        self.assertEqual(
            {
                "semantic_contract_sha256": run["semantic_contract_sha256"],
                "release_sha256": run["release_sha256"],
                "methodology_manifest_sha256": run[
                    "methodology_manifest_sha256"
                ],
            },
            {
                "semantic_contract_sha256": methodology[
                    "semantic_contract_sha256"
                ],
                "release_sha256": methodology["release_sha256"],
                "methodology_manifest_sha256": methodology["manifest_sha256"],
            },
        )
        self.assertEqual(
            run["authorization_ref_sha256"],
            hashlib.sha256(raw_reference.encode("utf-8")).hexdigest(),
        )
        persisted_control_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                self.run_root / "run.json",
                self.run_root / "events.jsonl",
                self.root / "runtime_state_vnext" / "active_run.json",
            )
        )
        self.assertNotIn(raw_reference, persisted_control_text)
        for stale_effort in ("high", "max", "ultra"):
            with self.subTest(stale_effort=stale_effort):
                with self.assertRaisesRegex(ValueError, "xhigh reasoning effort"):
                    self.controller.begin(
                        "2026-07-14",
                        "midday",
                        requested_effort=stale_effort,
                        run_mode="shadow",
                        authorization_ref=f"explicit-{stale_effort}-request-must-fail",
                    )

    def test_run_v2_rejects_partial_or_mixed_authority_profiles(self):
        path = self.run_root / "run.json"
        original = path.read_bytes()
        run = json.loads(original.decode("utf-8"))

        for mutation in ("partial", "mixed"):
            with self.subTest(mutation=mutation):
                candidate = dict(run)
                candidate.pop("run_sha256")
                if mutation == "partial":
                    candidate.pop("release_sha256")
                else:
                    candidate["methodology_sha256"] = candidate[
                        "methodology_manifest_sha256"
                    ]
                candidate["run_sha256"] = canonical_sha256(candidate)
                path.write_text(
                    json.dumps(candidate, ensure_ascii=False, indent=2, sort_keys=True)
                    + "\n",
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(RuntimeError, "authority binding"):
                    self.controller.store.load_run(self.run_root)
                path.write_bytes(original)

    def test_legacy_nonterminal_run_is_status_only_and_cannot_resume(self):
        run_path = self.run_root / "run.json"
        run = json.loads(run_path.read_text(encoding="utf-8"))
        run["schema_version"] = "daily-run-vnext-v1"
        run.pop("run_mode")
        run.pop("authorization_kind")
        run.pop("authorization_ref_sha256")
        run.pop("run_sha256")
        run["run_sha256"] = canonical_sha256(run)
        run_path.write_text(
            json.dumps(run, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.assertEqual(self.controller.status(self.run_root)["run_mode"], "legacy_unknown")
        with self.assertRaisesRegex(WorkflowFailure, "explicit retirement"):
            self.controller.record_host_capability(self.run_root, self.host_capability())

    def test_v2_run_with_legacy_authority_profile_is_status_only(self):
        run_path = self.run_root / "run.json"
        run = json.loads(run_path.read_text(encoding="utf-8"))
        legacy_methodology_sha256 = run.pop("methodology_manifest_sha256")
        run.pop("semantic_contract_sha256")
        run.pop("release_sha256")
        run["methodology_sha256"] = legacy_methodology_sha256
        run.pop("run_sha256")
        run["run_sha256"] = canonical_sha256(run)
        run_path.write_text(
            json.dumps(run, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        self.assertEqual(run["schema_version"], "daily-run-vnext-v2")
        with self.assertRaisesRegex(WorkflowFailure, "explicit retirement"):
            self.controller.record_host_capability(
                self.run_root,
                self.host_capability(),
            )

    def test_create_run_initialization_failure_releases_owned_active_lease(self):
        isolated = self.root / "initialization-failure"
        store = ArtifactStore(
            isolated,
            authority_root=self.root,
        )
        active_path = isolated / "runtime_state_vnext" / "active_run.json"
        methodology = build_methodology_manifest(root=self.root)
        with patch(
            "runtime_vnext.artifacts.ArtifactStore._append_event",
            side_effect=OSError("simulated initialization failure"),
        ):
            with self.assertRaisesRegex(OSError, "simulated initialization failure"):
                store.create_run(
                    "2026-07-14",
                    "morning",
                    methodology_manifest=methodology,
                    run_mode="shadow",
                    authorization_ref="test-initialization-failure-approval",
                    run_id="run-initialization-failure",
                )
        self.assertFalse(active_path.exists())
        self.assertFalse(
            (isolated / "runtime_state_vnext" / "2026-07-14" / "morning" / "current.json").exists()
        )

    def test_dead_initialization_lease_is_preserved_then_recovered(self):
        self.controller.retire_run(
            self.run_root,
            self.retirement_authorization(),
        )
        active_path = self.root / "runtime_state_vnext" / "active_run.json"
        orphaned = {
            "schema_version": "active-run-vnext-v1",
            "run_id": "run-dead-initializer",
            "trading_date": "2026-07-12",
            "slot": "evening",
            "claimed_at": "2026-07-12T23:59:00+08:00",
            "lifecycle": "initializing",
            "initializer_pid": 2147483647,
        }
        orphaned["active_sha256"] = canonical_sha256(orphaned)
        active_path.write_text(json.dumps(orphaned), encoding="utf-8")
        next_run = self.controller.begin(
            "2026-07-14",
            "morning",
            run_mode=self.run_mode,
            authorization_ref="test-init-recovery-approval",
            run_id="run-after-init-recovery",
        )
        self.assertTrue((next_run / "run.json").is_file())
        self.assertEqual(
            len(list(active_path.parent.glob("active_run.orphan-init-*.json"))),
            1,
        )

    def test_live_initialization_lease_is_not_reclaimed(self):
        self.controller.retire_run(
            self.run_root,
            self.retirement_authorization(),
        )
        active_path = self.root / "runtime_state_vnext" / "active_run.json"
        live = {
            "schema_version": "active-run-vnext-v1",
            "run_id": "run-live-initializer",
            "trading_date": "2026-07-12",
            "slot": "evening",
            "claimed_at": "2026-07-12T23:59:00+08:00",
            "lifecycle": "initializing",
            "initializer_pid": os.getpid(),
        }
        live["active_sha256"] = canonical_sha256(live)
        active_path.write_text(json.dumps(live), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "another vNext report run is active"):
            self.controller.begin(
                "2026-07-14",
                "morning",
                run_mode=self.run_mode,
                authorization_ref="test-live-initializer-approval",
                run_id="run-must-not-steal-initializer",
            )

    def test_second_run_is_blocked_while_slot_has_a_current_run(self):
        with self.assertRaisesRegex(RuntimeError, "already has a run"):
            self.controller.begin(
                self.date,
                self.slot,
                run_mode=self.run_mode,
                authorization_ref="test-duplicate-approval",
                run_id="run-duplicate",
            )

    def test_explicit_retirement_releases_global_run_without_deleting_audit(self):
        authorization = self.retirement_authorization()
        self.controller.retire_run(self.run_root, authorization)
        self.assertEqual(self.controller.status(self.run_root)["status"], "retired")
        self.assertTrue((self.run_root / "retirement.json").is_file())
        self.assertFalse(
            (self.root / "runtime_state_vnext" / "active_run.json").exists()
        )
        next_run = self.controller.begin(
            self.date,
            "midday",
            run_mode=self.run_mode,
            authorization_ref="test-after-retirement-approval",
            run_id="run-after-retirement",
        )
        self.assertTrue((next_run / "run.json").is_file())

    def test_retired_run_can_be_superseded_in_the_same_slot_without_deleting_audit(self):
        authorization = self.retirement_authorization()
        self.controller.retire_run(self.run_root, authorization)
        replacement = self.controller.begin(
            self.date,
            self.slot,
            run_mode=self.run_mode,
            authorization_ref="test-same-slot-retirement-approval",
            run_id="run-after-same-slot-retirement",
        )
        replacement_run = self.controller.store.load_run(replacement)
        current = json.loads(
            (self.root / "runtime_state_vnext" / self.date / self.slot / "current.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(replacement_run["supersedes_run_id"], "run-test")
        self.assertEqual(current["run_id"], "run-after-same-slot-retirement")
        self.assertTrue((self.run_root / "retirement.json").is_file())
        self.assertTrue((self.run_root / "checkpoint.json").is_file())

    def test_terminal_active_lease_left_by_crash_is_safely_reconciled(self):
        active_path = self.root / "runtime_state_vnext" / "active_run.json"
        stale_active = active_path.read_text(encoding="utf-8")
        self.prepare_through_decision()
        self.controller.compile_report(self.run_root)
        self.controller.accept_delivery(self.run_root, self.delivery())
        self.assertFalse(active_path.exists())
        active_path.write_text(stale_active, encoding="utf-8")
        next_run = self.controller.begin(
            "2026-07-14",
            "morning",
            run_mode=self.run_mode,
            authorization_ref="test-terminal-recovery-approval",
            run_id="run-after-terminal-recovery",
        )
        self.assertTrue((next_run / "run.json").is_file())
        events = (self.run_root / "events.jsonl").read_text(encoding="utf-8")
        self.assertIn("terminal_active_run_reconciled", events)

    def test_shadow_complete_releases_active_and_allows_next_run(self):
        self.prepare_through_decision()
        self.controller.compile_report(self.run_root)
        self.controller.accept_shadow_delivery(self.run_root, self.shadow_delivery())
        checkpoint = self.controller.store.load_checkpoint(self.run_root)
        self.assertEqual(checkpoint["status"], "shadow_complete")
        self.assertEqual(checkpoint["completion_mode"], "shadow")
        self.assertIs(checkpoint["notion_published"], False)
        self.assertFalse(
            (self.root / "runtime_state_vnext" / "active_run.json").exists()
        )
        next_run = self.controller.begin(
            "2026-07-14",
            "morning",
            run_mode="shadow",
            authorization_ref="test-after-shadow-complete-approval",
            run_id="run-after-shadow-complete",
        )
        self.assertTrue((next_run / "run.json").is_file())

    def test_authorized_shadow_repeat_preserves_prior_same_slot_sample(self):
        self.prepare_through_decision()
        self.controller.compile_report(self.run_root)
        self.controller.accept_shadow_delivery(self.run_root, self.shadow_delivery())
        with self.assertRaisesRegex(RuntimeError, "already has a run"):
            self.controller.begin(
                self.date,
                self.slot,
                run_mode="shadow",
                authorization_ref="test-shadow-repeat-without-allow-approval",
                run_id="run-shadow-repeat-without-authorization",
            )
        replacement = self.controller.begin(
            self.date,
            self.slot,
            run_mode="shadow",
            authorization_ref="test-shadow-repeat-approved",
            run_id="run-authorized-shadow-repeat",
            allow_shadow_repeat=True,
        )
        replacement_run = self.controller.store.load_run(replacement)
        self.assertEqual(replacement_run["supersedes_run_id"], "run-test")
        self.assertEqual(replacement_run["supersedes_terminal_status"], "shadow_complete")
        self.assertIs(replacement_run["shadow_repeat"], True)
        self.assertTrue((self.run_root / "sample_outcome.json").is_file())

    def test_shadow_terminal_active_lease_is_safely_reconciled(self):
        active_path = self.root / "runtime_state_vnext" / "active_run.json"
        stale_active = active_path.read_text(encoding="utf-8")
        self.prepare_through_decision()
        self.controller.compile_report(self.run_root)
        self.controller.accept_shadow_delivery(self.run_root, self.shadow_delivery())
        active_path.write_text(stale_active, encoding="utf-8")
        next_run = self.controller.begin(
            "2026-07-14",
            "morning",
            run_mode="shadow",
            authorization_ref="test-shadow-terminal-recovery-approval",
            run_id="run-after-shadow-terminal-recovery",
        )
        self.assertTrue((next_run / "run.json").is_file())
        events = (self.run_root / "events.jsonl").read_text(encoding="utf-8")
        self.assertIn("terminal_active_run_reconciled", events)

    def test_nonterminal_active_lease_is_never_reconciled(self):
        with self.assertRaisesRegex(RuntimeError, "another vNext report run is active"):
            self.controller.begin(
                "2026-07-14",
                "morning",
                run_mode=self.run_mode,
                authorization_ref="test-active-lease-approval",
                run_id="run-must-not-steal-active",
            )

    def retirement_authorization(self):
        authorization = {
            "schema_version": "run-retirement-authorization-v1",
            "approved": True,
            "run_id": "run-test",
            "trading_date": self.date,
            "slot": self.slot,
            "reason": "用户明确决定跳过本时段并保留全部失败证据",
            "reviewer_reference": "user",
            "approval_reference": "codex-task-test",
            "retired_at": "2026-07-13T08:10:00+08:00",
        }
        authorization["manifest_sha256"] = canonical_sha256(authorization)
        return authorization

    def test_explicit_retirement_cannot_race_live_stage_owner(self):
        self.controller.store.begin_attempt(self.run_root, "evidence")
        with self.assertRaisesRegex(RuntimeError, "stage attempt is already active"):
            self.controller.retire_run(
                self.run_root,
                self.retirement_authorization(),
            )
        self.assertTrue(
            (self.root / "runtime_state_vnext" / "active_run.json").is_file()
        )

    def test_checkpoint_tampering_is_detected(self):
        path = self.run_root / "checkpoint.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["status"] = "complete"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "invalid vNext checkpoint"):
            self.controller.status(self.run_root)

    def test_out_of_order_stage_is_blocked_by_checkpoint(self):
        with self.assertRaisesRegex(RuntimeError, "expects evidence"):
            self.controller.store.begin_attempt(self.run_root, "reasoning")

    def test_live_stage_attempt_blocks_duplicate_controller(self):
        self.controller.store.begin_attempt(self.run_root, "evidence")
        with self.assertRaisesRegex(RuntimeError, "stage attempt is already active"):
            self.controller.store.begin_attempt(self.run_root, "evidence")

    def test_dead_stage_attempt_is_preserved_before_retry(self):
        _, first_root = self.controller.store.begin_attempt(self.run_root, "evidence")
        with patch("runtime_vnext.artifacts._pid_is_alive", return_value=False):
            second, _ = self.controller.store.begin_attempt(self.run_root, "evidence")
        self.assertEqual(second, 2)
        orphan = json.loads((first_root / "orphaned.json").read_text(encoding="utf-8"))
        self.assertEqual(orphan["schema_version"], "stage-orphan-vnext-v1")
        self.assertRegex(orphan["orphan_sha256"], r"^[0-9a-f]{64}$")

    def test_orphaned_reasoning_attempt_does_not_count_as_logic_failure(self):
        self.controller.accept_evidence(
            self.run_root,
            self.evidence(),
            evidence_files_root=self.root,
        )
        evidence = self.controller.store.load_stage_payload(
            self.run_root, "evidence", "evidence"
        )
        self.controller.store.begin_attempt(self.run_root, "reasoning")
        broken = self.reasoning(evidence)
        broken["claims"][-1]["support_ids"] = ["future_claim"]
        with patch("runtime_vnext.artifacts._pid_is_alive", return_value=False):
            with self.assertRaises(WorkflowFailure) as caught:
                self.controller.accept_reasoning(self.run_root, broken)
        self.assertEqual(
            caught.exception.failure_class,
            FailureClass.REASONING_CONSISTENCY,
        )
        self.assertEqual(self.controller.status(self.run_root)["status"], "retryable_failure")

    def test_dead_controller_lock_is_preserved_and_recovered(self):
        lock_path = self.run_root / ".controller.lock"
        lock_path.write_text(
            json.dumps(
                {
                    "schema_version": "controller-lock-vnext-v1",
                    "lock_id": "orphaned-lock",
                    "pid": 2147483647,
                    "claimed_at": "2026-07-13T06:00:00+08:00",
                }
            ),
            encoding="utf-8",
        )
        with self.controller.store.controller_lock(self.run_root):
            self.assertTrue(lock_path.exists())
        self.assertFalse(lock_path.exists())
        self.assertEqual(len(list(self.run_root.glob(".controller.lock.orphan-*.json"))), 1)

    def test_live_controller_lock_is_not_stolen(self):
        lock_path = self.run_root / ".controller.lock"
        lock_path.write_text(
            json.dumps(
                {
                    "schema_version": "controller-lock-vnext-v1",
                    "lock_id": "live-lock",
                    "pid": os.getpid(),
                    "claimed_at": "2026-07-13T06:00:00+08:00",
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(RuntimeError, "another controller process"):
            with self.controller.store.controller_lock(self.run_root):
                pass

    def test_host_capability_tampering_blocks_later_stage(self):
        path = self.run_root / "host_capability.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["reasoning_effort"] = "low"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(WorkflowFailure) as caught:
            self.controller.accept_evidence(
                self.run_root,
                self.evidence(),
                evidence_files_root=self.root,
            )
        self.assertEqual(caught.exception.failure_class, FailureClass.MANUAL_REVIEW)

    def test_evidence_gate_returns_all_defects_in_one_result(self):
        broken = self.evidence()
        del broken["sources"]["FedWatch"]
        broken["sources"]["TradingView"]["timeframes"] = ["1D"]
        broken["sources"]["BlockBeats"]["meta"]["important_only"] = False
        result = evaluate_evidence(broken, root=self.root)
        codes = {item.code for item in result.defects}
        self.assertFalse(result.passed)
        self.assertIn("source.missing", codes)
        self.assertIn("tradingview.timeframe_missing", codes)
        self.assertIn("blockbeats.contract", codes)

    def test_stale_farside_complete_date_is_rejected(self):
        payload = self.evidence()
        payload["sources"]["Farside"]["meta"]["latest_complete_date"] = "2026-06-01"
        result = evaluate_evidence(payload, root=self.root)
        self.assertFalse(result.passed)
        self.assertIn("farside.date_stale", {item.code for item in result.defects})

    def test_farside_all_dash_placeholder_cannot_masquerade_as_zero_flow(self):
        payload = self.evidence()
        source = payload["sources"]["Farside"]
        record = source["artifacts"][0]
        target = self.root / record["path"]
        target.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "latest": {
                        "date": "14 Jul 2026",
                        "date_iso": "2026-07-14",
                        "total_usd_m": 0,
                        "direction": "flat",
                        "funds": {"IBIT": None, "FBTC": None},
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        record["sha256"] = sha256_file(target)
        record["bytes"] = target.stat().st_size
        source["meta"] = {
            "latest_total_usd_m": 0,
            "latest_complete_date": "2026-07-14",
            "flow_direction": "flat",
        }
        result = evaluate_evidence(payload, root=self.root)
        self.assertFalse(result.passed)
        self.assertIn(
            "farside.incomplete_latest_row",
            {item.code for item in result.defects},
        )

    def test_reasoning_requires_all_july_additions_and_three_scenarios(self):
        self.controller.accept_evidence(
            self.run_root,
            self.evidence(),
            evidence_files_root=self.root,
        )
        evidence = self.controller.store.load_stage_payload(self.run_root, "evidence", "evidence")
        payload = self.reasoning(evidence)
        payload["claims"] = [
            item
            for item in payload["claims"]
            if item["claim_type"] not in {"etf_confirmation", "liquidation_confirmation"}
        ]
        payload["scenario_tree"] = [
            item for item in payload["scenario_tree"] if item["scenario_type"] == "base"
        ]
        methodology = json.loads(
            (self.run_root / "methodology_manifest.json").read_text(encoding="utf-8")
        )
        result = evaluate_reasoning(
            payload,
            evidence=evidence,
                reasoning_authority_sha256=methodology["phases"]["reasoning"]["phase_sha256"],
            evidence_root=self.root,
            methodology_root=self.root,
        )
        codes = {item.code for item in result.defects}
        self.assertIn("claim.type_missing", codes)
        self.assertIn("scenario.matrix_incomplete", codes)

    def test_liquidation_confirmation_requires_coinglass_and_chart_claim(self):
        self.controller.accept_evidence(
            self.run_root,
            self.evidence(),
            evidence_files_root=self.root,
        )
        evidence = self.controller.store.load_stage_payload(
            self.run_root, "evidence", "evidence"
        )
        for support_ids in (
            ["obs_cg"],
            ["obs_cg", "obs_tv"],
            ["obs_cg", "obs_cg", "claim_chart", "claim_chart"],
        ):
            with self.subTest(support_ids=support_ids):
                payload = self.reasoning(evidence)
                claim = next(
                    item for item in payload["claims"]
                    if item["id"] == "claim_liqmap"
                )
                claim["support_ids"] = support_ids
                result = self.evaluate_reasoning_candidate(evidence, payload)
                self.assertIn(
                    "liquidation.source_boundary",
                    {item.code for item in result.defects},
                )

    def test_coinglass_observation_rejects_legacy_liquidation_result_owner(self):
        self.controller.accept_evidence(
            self.run_root,
            self.evidence(),
            evidence_files_root=self.root,
        )
        evidence = self.controller.store.load_stage_payload(
            self.run_root, "evidence", "evidence"
        )
        payload = self.reasoning(evidence)
        coinglass = next(
            item for item in payload["observations"]
            if item["source"] == "Coinglass"
        )
        coinglass["metrics"]["liquidation_confirmation_result"] = "confirm"
        result = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertIn(
            "liquidation.metric_ownership",
            {item.code for item in result.defects},
        )

    def test_manual_profile_readable_rejects_ordinary_support_drawing(self):
        payload = self.reasoning_fixture()
        tradingview = next(
            item for item in payload["observations"] if item["source"] == "TradingView"
        )
        tradingview["metrics"]["volume_profile"]["zones"][0]["role"] = "support"
        issues = []
        _validate_tradingview(
            tradingview,
            load_scoring_policy(root=self.root),
            issues,
        )
        self.assertIn(
            "tradingview.manual_profile_zone_role",
            {item.code for item in issues},
        )

    def test_manual_profile_insufficient_is_local_and_scores_zero(self):
        payload = self.reasoning_fixture()
        tradingview = next(
            item for item in payload["observations"] if item["source"] == "TradingView"
        )
        profile = tradingview["metrics"]["volume_profile"]
        profile.update({
            "status": "insufficient",
            "platform_indicator_state": "unknown",
            "zones": [],
            "reason": "用户手绘成交量分布本轮不可读",
        })
        tradingview["metrics"]["chart_component_scores"]["chart.liquidity_hunt"] = 0
        tradingview["metrics"]["chart_component_rationales"]["chart.liquidity_hunt"] = (
            "手绘成交量分布证据不足，本维度不生成位置与概率。"
        )
        issues = []
        _validate_tradingview(
            tradingview,
            load_scoring_policy(root=self.root),
            issues,
        )
        profile_codes = {
            item.code
            for item in issues
            if item.code.startswith("tradingview.profile")
            or item.code.startswith("tradingview.manual_profile")
            or item.code.startswith("tradingview.insufficient")
        }
        self.assertEqual(profile_codes, set())

    def test_manual_profile_insufficient_rejects_nonzero_score_and_point_values(self):
        payload = self.reasoning_fixture()
        tradingview = next(
            item for item in payload["observations"] if item["source"] == "TradingView"
        )
        profile = tradingview["metrics"]["volume_profile"]
        profile.update({
            "status": "insufficient",
            "platform_indicator_state": "unknown",
            "zones": [],
            "reason": "用户手绘成交量分布本轮不可读",
            "poc": 99,
        })
        issues = []
        _validate_tradingview(
            tradingview,
            load_scoring_policy(root=self.root),
            issues,
        )
        codes = {item.code for item in issues}
        self.assertIn("tradingview.insufficient_liquidity_score", codes)
        self.assertIn("tradingview.profile_point_value_forbidden", codes)

    def test_platform_and_automated_profile_values_are_never_accepted(self):
        payload = self.reasoning_fixture()
        tradingview = next(
            item for item in payload["observations"] if item["source"] == "TradingView"
        )
        profile = tradingview["metrics"]["volume_profile"]
        profile["platform_vrvp_used"] = True
        profile["automated_values_used"] = True
        issues = []
        _validate_tradingview(
            tradingview,
            load_scoring_policy(root=self.root),
            issues,
        )
        codes = {item.code for item in issues}
        self.assertIn("tradingview.platform_vrvp_forbidden", codes)
        self.assertIn("tradingview.automated_profile_values_forbidden", codes)

    def test_profile_sidecar_accepts_current_capture_and_certified_absence(self):
        evidence = self.evidence()
        reasoning = self.reasoning(evidence)
        self.assertEqual(
            self.tradingview_profile_binding_codes(evidence, reasoning),
            set(),
        )

        def certify_absence(payload):
            payload["aggregate_state"] = "absent"
            for state in payload["timeframes"].values():
                state.update({
                    "initial_state": "absent",
                    "final_state": "absent",
                    "correction_attempted": False,
                    "certification_basis": "certified_legend_inventory",
                })

        self.rewrite_profile_sidecar(evidence, mutate=certify_absence)
        reasoning = self.reasoning(evidence)
        tradingview = next(
            item for item in reasoning["observations"] if item["source"] == "TradingView"
        )
        tradingview["metrics"]["volume_profile"]["platform_indicator_state"] = "absent"
        self.assertEqual(
            self.tradingview_profile_binding_codes(evidence, reasoning),
            set(),
        )

    def test_evidence_gate_rejects_cross_run_profile_binding(self):
        drifts = {
            "capture_run_id": "33333333-3333-4333-8333-333333333333",
            "capture_nonce": "not-a-current-run-nonce",
            "schema_version": "tradingview-profile-capture-binding-v9",
            "sidecar_filename": "../tradingview_profile_state.json",
            "sidecar_schema_version": "tradingview-profile-state-v9",
        }
        for key, value in drifts.items():
            with self.subTest(key=key):
                evidence = self.evidence()
                evidence["tradingview_profile_binding"][key] = value
                result = evaluate_evidence(evidence, root=self.root)
                self.assertIn(
                    "tradingview.profile_binding_mismatch",
                    {item.code for item in result.defects},
                )

    def test_missing_or_corrupt_profile_sidecar_requires_only_local_fallback(self):
        for defect in ("missing", "corrupt"):
            with self.subTest(defect=defect):
                evidence = self.evidence()
                if defect == "missing":
                    record = self.profile_sidecar_record(evidence)
                    evidence["sources"]["TradingView"]["artifacts"].remove(record)
                else:
                    self.rewrite_profile_sidecar(
                        evidence,
                        raw="{not-json",
                        refresh_record=True,
                    )
                reasoning = self.reasoning(evidence)
                self.assertIn(
                    "tradingview.profile_sidecar_fallback_required",
                    self.tradingview_profile_binding_codes(evidence, reasoning),
                )
                tradingview = next(
                    item
                    for item in reasoning["observations"]
                    if item["source"] == "TradingView"
                )
                profile = tradingview["metrics"]["volume_profile"]
                profile.update({
                    "status": "insufficient",
                    "platform_indicator_state": "unknown",
                    "zones": [],
                    "reason": "平台状态无法认证，手绘成交量分布本轮证据不足",
                })
                tradingview["metrics"]["chart_component_scores"][
                    "chart.liquidity_hunt"
                ] = 0
                self.assertNotIn(
                    "tradingview.profile_sidecar_fallback_required",
                    self.tradingview_profile_binding_codes(evidence, reasoning),
                )

    def test_profile_sidecar_rejects_hash_state_aggregate_and_cross_run_drift(self):
        for defect in (
            "hash",
            "aggregate",
            "state_transition",
            "visible_without_correction",
            "absence_certification",
            "capture_run_id",
            "capture_nonce",
            "binding_nonce",
        ):
            with self.subTest(defect=defect):
                evidence = self.evidence()
                if defect == "hash":
                    self.rewrite_profile_sidecar(
                        evidence,
                        mutate=lambda payload: payload.update({"aggregate_state": "visible"}),
                        refresh_record=False,
                    )
                elif defect == "aggregate":
                    self.rewrite_profile_sidecar(
                        evidence,
                        mutate=lambda payload: payload.update({"aggregate_state": "visible"}),
                    )
                elif defect == "state_transition":
                    self.rewrite_profile_sidecar(
                        evidence,
                        mutate=lambda payload: payload["timeframes"]["1h"].update({
                            "initial_state": "hidden",
                            "final_state": "hidden",
                            "correction_attempted": True,
                        }),
                    )
                elif defect == "visible_without_correction":
                    self.rewrite_profile_sidecar(
                        evidence,
                        mutate=lambda payload: (
                            payload.update({"aggregate_state": "visible"}),
                            payload["timeframes"]["1h"].update({
                                "initial_state": "visible",
                                "final_state": "visible",
                                "correction_attempted": False,
                                "certification_basis": "profile_control",
                            }),
                        ),
                    )
                elif defect == "absence_certification":
                    def uncertified_absence(payload):
                        payload["aggregate_state"] = "absent"
                        for state in payload["timeframes"].values():
                            state.update({
                                "initial_state": "absent",
                                "final_state": "absent",
                                "correction_attempted": False,
                                "certification_basis": "unverified",
                            })
                    self.rewrite_profile_sidecar(evidence, mutate=uncertified_absence)
                elif defect == "capture_run_id":
                    self.rewrite_profile_sidecar(
                        evidence,
                        mutate=lambda payload: payload.update({
                            "capture_run_id": "33333333-3333-4333-8333-333333333333"
                        }),
                    )
                elif defect == "capture_nonce":
                    self.rewrite_profile_sidecar(
                        evidence,
                        mutate=lambda payload: payload.update({
                            "capture_nonce": "44444444-4444-4444-8444-444444444444"
                        }),
                    )
                else:
                    evidence["tradingview_profile_binding"]["capture_nonce"] = (
                        "55555555-5555-4555-8555-555555555555"
                    )
                reasoning = self.reasoning(evidence)
                self.assertIn(
                    "tradingview.profile_sidecar_fallback_required",
                    self.tradingview_profile_binding_codes(evidence, reasoning),
                )

    def test_valid_profile_sidecar_must_be_an_explicit_evidence_reference(self):
        evidence = self.evidence()
        reasoning = self.reasoning(evidence)
        tradingview = next(
            item for item in reasoning["observations"] if item["source"] == "TradingView"
        )
        tradingview["evidence_refs"] = [
            value
            for value in tradingview["evidence_refs"]
            if Path(value).name != "tradingview_profile_state.json"
        ]
        self.assertIn(
            "tradingview.profile_sidecar_reference_missing",
            self.tradingview_profile_binding_codes(evidence, reasoning),
        )

    def test_liquidation_map_must_be_neutral_when_manual_profile_is_insufficient(self):
        payload = self.reasoning_fixture()
        observations = {item["id"]: item for item in payload["observations"]}
        claims = {item["id"]: item for item in payload["claims"]}
        observations["obs_tv"]["metrics"]["volume_profile"]["status"] = "insufficient"
        observations["obs_tv"]["metrics"]["volume_profile"]["zones"] = []
        observations["obs_tv"]["metrics"]["volume_profile"]["reason"] = (
            "用户手绘成交量分布本轮不可读"
        )
        issues = []
        policy = load_scoring_policy(root=self.root)
        evidence = self.controller.store.load_stage_payload(
            self.run_root, "evidence", "evidence"
        )
        _validate_claim_layers(
            observations, claims, evidence, self.root, policy, issues
        )
        self.assertIn(
            "liquidation.manual_profile_substitution",
            {item.code for item in issues},
        )
        claims["claim_liqmap"]["confirmation_result"] = "neutral"
        claims["claim_liqmap"]["conclusion"] = (
            "清算图保持中性，不提供手绘区域流动性概率确认"
        )
        issues = []
        _validate_claim_layers(
            observations, claims, evidence, self.root, policy, issues
        )
        self.assertNotIn(
            "liquidation.manual_profile_substitution",
            {item.code for item in issues},
        )
        self.assertNotIn(
            "liquidation.confirmation_text_drift",
            {item.code for item in issues},
        )

        for conclusion in (
            "清算图不替代手绘区域，但强烈确认磁吸概率",
            "清算图保持中性，但形成确认",
        ):
            with self.subTest(conclusion=conclusion):
                claims["claim_liqmap"]["conclusion"] = conclusion
                issues = []
                _validate_claim_layers(
                    observations, claims, evidence, self.root, policy, issues
                )
                self.assertNotIn(
                    "liquidation.confirmation_text_drift",
                    {item.code for item in issues},
                )

    def test_typed_state_control_is_independent_of_chinese_synonyms(self):
        evidence = self.evidence()
        payload = self.reasoning(evidence)
        prose_by_claim_type = {
            "fundamental_price_realization": (
                "综合三项事件与盘面后保留本轮跨源判断，详细状态只读取类型化字段。"
            ),
            "etf_confirmation": (
                "该跨源节点只承担规定范围内的辅助作用，详细状态只读取类型化字段。"
            ),
            "liquidation_confirmation": (
                "该辅助节点仅记录清算工件与图表区域的关系，详细状态只读取类型化字段。"
            ),
        }
        for claim in payload["claims"]:
            if claim["claim_type"] in prose_by_claim_type:
                claim["conclusion"] = prose_by_claim_type[claim["claim_type"]]

        result = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertTrue(result.passed, [(item.code, item.path) for item in result.defects])
        self.assertTrue(
            {
                "fundamental.realization_text_drift",
                "etf.price_relation_text_drift",
                "liquidation.confirmation_text_drift",
            }.isdisjoint({item.code for item in result.defects})
        )

        typed_tamper_cases = (
            ("fundamental_price_realization", "realization_state", "unknown"),
            ("etf_confirmation", "price_relation", "weaken"),
            ("liquidation_confirmation", "confirmation_result", "ambiguous"),
        )
        for claim_type, field, value in typed_tamper_cases:
            with self.subTest(claim_type=claim_type):
                tampered = copy.deepcopy(payload)
                claim = next(
                    item
                    for item in tampered["claims"]
                    if item["claim_type"] == claim_type
                )
                claim[field] = value
                result = self.evaluate_reasoning_candidate(evidence, tampered)
                self.assertFalse(result.passed)

    def test_claim_topology_treats_counter_and_invalidation_as_siblings(self):
        evidence = self.evidence()
        contract = load_reasoning_submission_contract(root=self.root)
        policy = load_scoring_policy(root=self.root)
        authority_sha256 = json.loads(
            (self.run_root / "methodology_manifest.json").read_text(
                encoding="utf-8"
            )
        )["phases"]["reasoning"]["phase_sha256"]

        def project(candidate):
            return assemble_reasoning_submission(
                candidate,
                evidence=evidence,
                reasoning_authority_sha256=authority_sha256,
                contract=contract,
                full_policy=policy,
            )

        sibling_candidate = self.reasoning(evidence)
        for claim in sibling_candidate["claims"]:
            if claim["claim_type"] != "invalidation_path":
                continue
            claim["support_ids"] = [
                support_id
                for support_id in claim["support_ids"]
                if not support_id.startswith("claim_counter_")
            ]
        result = self.evaluate_reasoning_candidate(
            evidence,
            project(sibling_candidate),
        )
        self.assertTrue(result.passed, [(item.code, item.path) for item in result.defects])

        missing_regime = self.reasoning(evidence)
        main_invalidation = next(
            item
            for item in missing_regime["claims"]
            if item["claim_type"] == "invalidation_path"
            and item["account"] == "main"
        )
        main_invalidation["support_ids"] = ["claim_chart"]
        result = self.evaluate_reasoning_candidate(evidence, project(missing_regime))
        self.assertIn("claim.layer_missing", {item.code for item in result.defects})

        missing_counter_closure = self.reasoning(evidence)
        maker_invalidation = next(
            item
            for item in missing_counter_closure["claims"]
            if item["claim_type"] == "invalidation_path"
            and item["account"] == "maker"
        )
        maker_invalidation["support_ids"] = [
            support_id
            for support_id in maker_invalidation["support_ids"]
            if support_id != "claim_counter_maker"
        ]
        cannot_do = next(
            item
            for item in missing_counter_closure["claims"]
            if item["claim_type"] == "cannot_do"
        )
        cannot_do["support_ids"] = [
            support_id
            for support_id in cannot_do["support_ids"]
            if support_id != "claim_counter_maker"
        ]
        result = self.evaluate_reasoning_candidate(
            evidence,
            project(missing_counter_closure),
        )
        self.assertIn(
            (
                "claim.layer_missing",
                "claims.claim_cannot.support_ids",
            ),
            {(item.code, item.path) for item in result.defects},
        )

    def test_reasoning_accepts_fine_grained_orderflow_scores_through_60(self):
        self.controller.accept_evidence(
            self.run_root,
            self.evidence(),
            evidence_files_root=self.root,
        )
        evidence = self.controller.store.load_stage_payload(self.run_root, "evidence", "evidence")

        for score in (0, 1, 52, 57, 59, 60):
            with self.subTest(score=score):
                payload = self.reasoning(evidence)
                orderflow = next(
                    item for item in payload["claims"] if item["id"] == "claim_orderflow"
                )
                orderflow["score_assessment"]["score"] = score
                result = self.evaluate_reasoning_candidate(evidence, payload)
                self.assertNotIn(
                    "orderflow.score_invalid",
                    {item.code for item in result.defects},
                )

    def test_reasoning_rejects_orderflow_score_gap_and_invalid_types(self):
        self.controller.accept_evidence(
            self.run_root,
            self.evidence(),
            evidence_files_root=self.root,
        )
        evidence = self.controller.store.load_stage_payload(self.run_root, "evidence", "evidence")

        for score in (-1, 61, 65, 69, 71, 57.5, True, "57"):
            with self.subTest(score=score):
                payload = self.reasoning(evidence)
                orderflow = next(
                    item for item in payload["claims"] if item["id"] == "claim_orderflow"
                )
                orderflow["score_assessment"]["score"] = score
                result = self.evaluate_reasoning_candidate(evidence, payload)
                self.assertIn(
                    "orderflow.score_invalid",
                    {item.code for item in result.defects},
                )

    def test_reasoning_reserves_70_for_proven_extreme_orderflow(self):
        self.controller.accept_evidence(
            self.run_root,
            self.evidence(),
            evidence_files_root=self.root,
        )
        evidence = self.controller.store.load_stage_payload(self.run_root, "evidence", "evidence")
        payload = self.reasoning(evidence)
        orderflow = next(
            item for item in payload["claims"] if item["id"] == "claim_orderflow"
        )
        orderflow["score_assessment"]["score"] = 70
        orderflow["score_assessment"]["extreme_confirmed"] = False

        result = self.evaluate_reasoning_candidate(evidence, payload)
        codes = {item.code for item in result.defects}
        self.assertNotIn("orderflow.score_invalid", codes)
        self.assertIn("orderflow.extreme_unproven", codes)

    def test_reasoning_rejects_cross_account_dependencies_and_scenarios(self):
        self.controller.accept_evidence(
            self.run_root,
            self.evidence(),
            evidence_files_root=self.root,
        )
        evidence = self.controller.store.load_stage_payload(self.run_root, "evidence", "evidence")
        payload = self.reasoning(evidence)
        maker = next(item for item in payload["claims"] if item["id"] == "claim_maker")
        maker["support_ids"].append("claim_main")
        maker_scenario = next(
            item
            for item in payload["scenario_tree"]
            if item["account"] == "maker" and item["scenario_type"] == "base"
        )
        maker_scenario["owner_claim_id"] = "claim_main"
        methodology = json.loads(
            (self.run_root / "methodology_manifest.json").read_text(encoding="utf-8")
        )
        result = evaluate_reasoning(
            payload,
            evidence=evidence,
                reasoning_authority_sha256=methodology["phases"]["reasoning"]["phase_sha256"],
            evidence_root=self.root,
            methodology_root=self.root,
        )
        codes = {item.code for item in result.defects}
        self.assertIn("claim.cross_account_dependency", codes)
        self.assertIn("scenario.owner_claim_binding", codes)

    def test_reasoning_rejects_cross_account_causal_claim_text(self):
        self.controller.accept_evidence(
            self.run_root,
            self.evidence(),
            evidence_files_root=self.root,
        )
        evidence = self.controller.store.load_stage_payload(
            self.run_root, "evidence", "evidence"
        )
        cases = (
            ("claim_main", "conclusion", "因为Maker偏空，所以主账户维持做空判断。"),
            ("claim_maker", "conclusion", "Maker据此沿用主账户方向并计划做空。"),
            ("claim_main", "invalidation", "Maker决定转多时主账户判断失效。"),
            ("claim_maker", "invalidation", "主账户方向同步转强时Maker判断失效。"),
        )
        for claim_id, field, value in cases:
            with self.subTest(claim_id=claim_id, field=field):
                payload = self.reasoning(evidence)
                claim = next(
                    item for item in payload["claims"] if item["id"] == claim_id
                )
                claim[field] = value
                result = self.evaluate_reasoning_candidate(evidence, payload)
                self.assertIn(
                    "claim.cross_account_causal_text",
                    {item.code for item in result.defects},
                )

    def test_reasoning_v3_rejects_legacy_report_sections(self):
        self.controller.accept_evidence(
            self.run_root,
            self.evidence(),
            evidence_files_root=self.root,
        )
        evidence = self.controller.store.load_stage_payload(
            self.run_root, "evidence", "evidence"
        )
        payload = self.reasoning(evidence)
        payload["report_sections"] = {
            "strategy": {
                "text": "因为Maker偏空，所以主账户继续执行做空计划。",
                "claim_ids": ["claim_main"],
            }
        }
        result = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertIn("reasoning.schema_fields", {item.code for item in result.defects})

    def test_reasoning_allows_non_causal_two_account_comparison(self):
        self.controller.accept_evidence(
            self.run_root,
            self.evidence(),
            evidence_files_root=self.root,
        )
        evidence = self.controller.store.load_stage_payload(
            self.run_root, "evidence", "evidence"
        )
        payload = self.reasoning(evidence)
        claims = {item["id"]: item for item in payload["claims"]}
        claims["claim_main"]["conclusion"] = (
            "主账户与Maker方向可以相同，但两套判断独立且不可互推。"
        )
        claims["claim_main"]["invalidation"] = (
            "即使Maker转强也不决定主账户失效，主账户只按自身条件重评。"
        )
        claims["claim_maker"]["conclusion"] = (
            "Maker与主账户方向可以相同，但两套判断独立且不互相引用。"
        )
        claims["claim_maker"]["invalidation"] = (
            "主账户转强不影响Maker失效条件，Maker只按自身链重评。"
        )
        result = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertTrue(result.passed, result.to_dict())

    def test_reasoning_requires_pre_risk_structural_noise_buffer_owner(self):
        self.controller.accept_evidence(
            self.run_root,
            self.evidence(),
            evidence_files_root=self.root,
        )
        evidence = self.controller.store.load_stage_payload(
            self.run_root, "evidence", "evidence"
        )
        cases = (
            (
                "claim_invalidation_main",
                lambda claim: claim.pop("structural_noise_buffer"),
                "claim.structural_noise_buffer_schema",
            ),
            (
                "claim_invalidation_maker",
                lambda claim: claim["structural_noise_buffer"].update(
                    {"observation_id": "obs_cg"}
                ),
                "claim.structural_noise_buffer_owner",
            ),
            (
                "claim_invalidation_maker",
                lambda claim: claim["structural_noise_buffer"].update(
                    {"risk_budget_input_used": True}
                ),
                "claim.structural_noise_buffer_method",
            ),
            (
                "claim_invalidation_maker",
                lambda claim: claim["structural_noise_buffer"].update(
                    {"noise_outer_boundary": 100.35}
                ),
                "claim.structural_noise_buffer_economic_insufficiency",
            ),
        )
        for claim_id, mutate, expected_code in cases:
            with self.subTest(claim_id=claim_id, expected_code=expected_code):
                payload = self.reasoning(evidence)
                claim = next(
                    item for item in payload["claims"] if item["id"] == claim_id
                )
                mutate(claim)
                result = self.evaluate_reasoning_candidate(evidence, payload)
                self.assertIn(
                    expected_code,
                    {item.code for item in result.defects},
                )

    def test_reasoning_accepts_honest_insufficient_noise_envelope(self):
        self.controller.accept_evidence(
            self.run_root,
            self.evidence(),
            evidence_files_root=self.root,
        )
        evidence = self.controller.store.load_stage_payload(
            self.run_root, "evidence", "evidence"
        )
        payload = self.reasoning(evidence)
        claim = next(
            item
            for item in payload["claims"]
            if item["id"] == "claim_invalidation_maker"
        )
        claim["structural_noise_buffer"].update(
            {
                "status": "insufficient",
                "anchor_kind": None,
                "anchor_source_field": None,
                "anchor_price": None,
                "noise_outer_boundary": None,
                "price_distance": None,
                "insufficiency_reason_code": "visual_noise_envelope_not_readable",
            }
        )
        payload["pipeline_units"] = build_pipeline_units(payload)
        result = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertTrue(result.passed, result.to_dict())

    def test_reasoning_accepts_closed_non_directional_theses(self):
        self.controller.accept_evidence(
            self.run_root,
            self.evidence(),
            evidence_files_root=self.root,
        )
        evidence = self.controller.store.load_stage_payload(
            self.run_root, "evidence", "evidence"
        )
        for claim_id, direction, conclusion, invalidation_id in (
            (
                "claim_main",
                "neutral",
                "主账户当前证据冲突，保持中性观察并等待自身条件闭合",
                "claim_invalidation_main",
            ),
            (
                "claim_maker",
                "observe",
                "Maker当前没有方向性执行结论，只保持观察",
                "claim_invalidation_maker",
            ),
        ):
            with self.subTest(claim_id=claim_id, direction=direction):
                payload = self.reasoning(evidence)
                claims = {item["id"]: item for item in payload["claims"]}
                thesis = claims[claim_id]
                thesis["direction"] = direction
                thesis["conclusion"] = conclusion
                thesis["invalidation"] = "出现一个闭合且一致的方向性替代证据后重新评估"
                invalidation = claims[invalidation_id]
                invalidation["structural_noise_buffer"].update(
                    {
                        "status": "insufficient",
                        "anchor_kind": None,
                        "anchor_source_field": None,
                        "anchor_price": None,
                        "noise_outer_boundary": None,
                        "price_distance": None,
                        "insufficiency_reason_code": "not_applicable_non_directional_thesis",
                    }
                )
                if direction == "observe":
                    claims["claim_cannot"].update(
                        {
                            "prohibition": "追多空",
                            "conclusion": "Maker本轮不能追多或追空，只能保持观察",
                        }
                    )
                payload["pipeline_units"] = build_pipeline_units(payload)
                result = self.evaluate_reasoning_candidate(evidence, payload)
                self.assertTrue(result.passed, result.to_dict())

    def test_non_directional_future_triggers_require_one_matching_direction(self):
        self.controller.accept_evidence(
            self.run_root,
            self.evidence(),
            evidence_files_root=self.root,
        )
        evidence = self.controller.store.load_stage_payload(
            self.run_root, "evidence", "evidence"
        )

        def non_directional_payload(account):
            payload = self.reasoning(evidence)
            claims = {item["id"]: item for item in payload["claims"]}
            if account == "main":
                claims["claim_main"].update(
                    {
                        "direction": "neutral",
                        "conclusion": "当前证据冲突，主账户保持中性观察并等待闭合的替代方向证据",
                        "invalidation": "出现一组闭合且一致的方向性替代证据后重新评估",
                    }
                )
                invalidation = claims["claim_invalidation_main"]
            else:
                claims["claim_maker"].update(
                    {
                        "direction": "observe",
                        "conclusion": "Maker 当前没有方向性执行结论，只保持观察",
                        "invalidation": "出现一组闭合且一致的方向性替代证据后重新评估",
                    }
                )
                claims["claim_cannot"].update(
                    {
                        "prohibition": "追多空",
                        "conclusion": "Maker 本轮不能追多或追空，只能保持观察",
                    }
                )
                invalidation = claims["claim_invalidation_maker"]
            invalidation["structural_noise_buffer"].update(
                {
                    "status": "insufficient",
                    "anchor_kind": None,
                    "anchor_source_field": None,
                    "anchor_price": None,
                    "noise_outer_boundary": None,
                    "price_distance": None,
                    "insufficiency_reason_code": "not_applicable_non_directional_thesis",
                }
            )
            return payload, claims

        payload, claims = non_directional_payload("main")
        trigger = claims["claim_counter_main"]["trigger_logic"]
        trigger["clauses"][0]["value"] = "range"
        trigger["clauses"][1]["value"] = "flat"
        payload["pipeline_units"] = build_pipeline_units(payload)
        result = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertIn(
            "claim.trigger_non_directional_alternative_incoherent",
            {item.code for item in result.defects},
        )

        payload, claims = non_directional_payload("maker")
        trigger = claims["claim_invalidation_maker"]["trigger_logic"]
        trigger["clauses"][0]["value"] = "range"
        trigger["clauses"][2]["value"] = "neutral"
        payload["pipeline_units"] = build_pipeline_units(payload)
        result = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertIn(
            "claim.trigger_non_directional_alternative_incoherent",
            {item.code for item in result.defects},
        )

        payload, claims = non_directional_payload("maker")
        trigger = claims["claim_counter_maker"]["trigger_logic"]
        trigger_clause = trigger["clauses"][0]
        trigger_clause.clear()
        trigger_clause.update(
            {
                "owner_type": "observation",
                "owner_id": "obs_tv",
                "field": "timeframes.1h.structure",
                "operator": "one_of_at_trigger",
                "values": ["bearish"],
            }
        )
        trigger["clauses"][1].update(
            {
                "operator": "equals_at_trigger",
                "value": "bearish",
            }
        )
        payload["pipeline_units"] = build_pipeline_units(payload)
        result = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertIn(
            "claim.trigger_non_directional_counter_direction_drift",
            {item.code for item in result.defects},
        )

    def test_non_directional_thesis_rejects_padding_mixed_counter_and_stop(self):
        self.controller.accept_evidence(
            self.run_root,
            self.evidence(),
            evidence_files_root=self.root,
        )
        evidence = self.controller.store.load_stage_payload(
            self.run_root, "evidence", "evidence"
        )

        payload = self.reasoning(evidence)
        claims = {item["id"]: item for item in payload["claims"]}
        claims["claim_main"].update(
            {
                "direction": "neutral",
                "conclusion": "主账户当前证据冲突，保持中性观察",
                "invalidation": "出现一个闭合且一致的方向性替代证据后重新评估",
            }
        )
        claims["claim_counter_main"]["current_basis"]["clauses"].append(
            {
                "owner_type": "observation",
                "owner_id": "obs_tv",
                "field": "timeframes.1d.structure",
                "operator": "equals",
                "value": "bearish",
            }
        )
        payload["pipeline_units"] = build_pipeline_units(payload)
        result = self.evaluate_reasoning_candidate(evidence, payload)
        codes = {item.code for item in result.defects}
        self.assertIn("claim.current_basis_counter_direction_incoherent", codes)
        self.assertIn("claim.structural_noise_buffer_direction_applicability", codes)

        payload = self.reasoning(evidence)
        claims = {item["id"]: item for item in payload["claims"]}
        claims["claim_main"].update(
            {
                "direction": "neutral",
                "conclusion": "主账户当前证据冲突，保持中性观察",
                "invalidation": "出现一个闭合且一致的方向性替代证据后重新评估",
            }
        )
        claims["claim_counter_main"]["current_basis"]["clauses"].append(
            {
                "owner_type": "claim",
                "owner_id": "claim_realization",
                "field": "realization_state",
                "operator": "equals",
                "value": "partially_realized",
            }
        )
        claims["claim_invalidation_main"]["structural_noise_buffer"].update(
            {
                "status": "insufficient",
                "anchor_kind": None,
                "anchor_source_field": None,
                "anchor_price": None,
                "noise_outer_boundary": None,
                "price_distance": None,
                "insufficiency_reason_code": "not_applicable_non_directional_thesis",
            }
        )
        payload["pipeline_units"] = build_pipeline_units(payload)
        result = self.evaluate_reasoning_candidate(evidence, payload)
        codes = {item.code for item in result.defects}
        self.assertIn("claim.current_basis_polarity", codes)
        self.assertIn(
            "fundamental.event_observation_only_current_basis",
            codes,
        )

    def test_reasoning_rejects_supportive_padding_in_strongest_counter(self):
        self.controller.accept_evidence(
            self.run_root,
            self.evidence(),
            evidence_files_root=self.root,
        )
        evidence = self.controller.store.load_stage_payload(
            self.run_root, "evidence", "evidence"
        )
        cases = (
            {
                "owner_type": "observation",
                "owner_id": "obs_cg",
                "field": "final_direction",
                "operator": "equals",
                "value": "bearish",
            },
            {
                "owner_type": "observation",
                "owner_id": "obs_exo",
                "field": "cross_check_result",
                "operator": "equals",
                "value": "confirm",
            },
        )
        for clause in cases:
            with self.subTest(owner_id=clause["owner_id"]):
                payload = self.reasoning(evidence)
                counter = next(
                    item
                    for item in payload["claims"]
                    if item["id"] == "claim_counter_maker"
                )
                counter["current_basis"] = {
                    "mode": "all",
                    "clauses": [clause],
                }
                payload["pipeline_units"] = build_pipeline_units(payload)
                result = self.evaluate_reasoning_candidate(evidence, payload)
                self.assertIn(
                    "claim.current_basis_polarity",
                    {item.code for item in result.defects},
                )

    def test_decision_rejects_main_claim_in_maker_basis(self):
        _, reasoning = self.prepare_through_reasoning()
        payload = self.decision(reasoning)
        payload["maker"]["winrate_rubric"]["anchor_claim_ids"].append("claim_main")
        result = evaluate_decision(
            payload,
            reasoning=reasoning,
            run=self.controller.store.load_run(self.run_root),
            pretrade_gate=self.gate,
            root=self.root,
        )
        self.assertIn(
            "decision.cross_account_claim",
            {item.code for item in result.defects},
        )

    def test_shadow_decision_never_loads_pretrade_and_keeps_full_qualified_plan(self):
        _, reasoning = self.prepare_through_reasoning()
        payload = self.decision(reasoning)
        run = self.controller.store.load_run(self.run_root)
        baseline = evaluate_decision(
            payload,
            reasoning=reasoning,
            run=run,
            pretrade_gate=None,
            root=self.root,
        )
        self.assertTrue(baseline.passed, baseline.to_dict())
        self.assertEqual(payload["maker"]["plan_state"], "qualified")
        self.assertEqual(payload["maker"]["execution_action"], "not_attempted")
        self.assertEqual(len(payload["maker"]["risk_plan"]["entries"]), 2)

        without_tp2 = copy.deepcopy(payload)
        without_tp2["maker"]["risk_plan"].pop("tp2")
        rejected = evaluate_decision(
            without_tp2,
            reasoning=reasoning,
            run=run,
            pretrade_gate=None,
            root=self.root,
        )
        self.assertIn("risk.schema_fields", {item.code for item in rejected.defects})

        supplied_personal_gate = build_pretrade_gate_contract(
            self.date,
            source_reference="38efda35-a098-810c-b9c3-cdf448a9d226",
            source_observed_at=f"{self.date}T06:00:00+08:00",
            subjective_conclusion="可交易",
            emotion_stable=True,
            rhythm_consistent=True,
            result_dependency=False,
            continuous_stop_loss_count=0,
            physical_condition="normal",
        )
        rejected = evaluate_decision(
            payload,
            reasoning=reasoning,
            run=run,
            pretrade_gate=supplied_personal_gate,
            root=self.root,
        )
        self.assertIn(
            "execution_authorization.shadow_pretrade_forbidden",
            {item.code for item in rejected.defects},
        )

        boundary_cases = (
            (
                "execution_authorization.shadow_boundary",
                lambda item: item["execution_authorization"].__setitem__(
                    "live_execution_allowed", True
                ),
            ),
            (
                "maker.execution_action_drift",
                lambda item: item["maker"].__setitem__(
                    "execution_action", "place_order"
                ),
            ),
            (
                "continuity.shadow_boundary",
                lambda item: item["continuity_contract"].__setitem__(
                    "live_state_read", True
                ),
            ),
            (
                "continuity.shadow_boundary",
                lambda item: item["continuity_contract"].__setitem__(
                    "order_mutation_attempted", True
                ),
            ),
        )
        for expected_code, mutate in boundary_cases:
            with self.subTest(expected_code=expected_code):
                candidate = copy.deepcopy(payload)
                mutate(candidate)
                result = evaluate_decision(
                    candidate,
                    reasoning=reasoning,
                    run=run,
                    pretrade_gate=None,
                    root=self.root,
                )
                self.assertIn(expected_code, {item.code for item in result.defects})

        with patch.object(
            self.controller.store,
            "load_pretrade_gate",
            side_effect=AssertionError("shadow must not load pretrade"),
        ) as load_gate:
            self.controller.accept_decision(self.run_root, payload)
        load_gate.assert_not_called()
        self.assertFalse(
            (self.root / "runtime_state_vnext" / self.date / "pretrade_gate.json").exists()
        )

    def test_shadow_capture_has_no_pretrade_or_personal_state_dependency(self):
        with patch.object(
            self.controller.store,
            "load_pretrade_gate",
            side_effect=AssertionError("capture must not load pretrade"),
        ) as load_gate, patch(
            "runtime_vnext.controller.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=["node", "capture_all.js"],
                returncode=1,
                stdout="",
                stderr="capture failed before manifest",
            ),
        ):
            with self.assertRaises(WorkflowFailure):
                self.controller.capture(self.run_root)
        load_gate.assert_not_called()
        self.assertFalse(
            (self.root / "runtime_state_vnext" / self.date / "pretrade_gate.json").exists()
        )

    def test_production_gate_changes_execution_only_not_the_certified_plan(self):
        _, reasoning = self.prepare_through_reasoning()
        run = self.controller.store.load_run(self.run_root)
        allowed_payload = self.decision(reasoning)
        allowed_result = evaluate_decision(
            allowed_payload,
            reasoning=reasoning,
            run=run,
            pretrade_gate=self.gate,
            root=self.root,
        )
        self.assertTrue(allowed_result.passed, allowed_result.to_dict())

        blocked_gate = build_pretrade_gate_contract(
            self.date,
            source_reference="48efda35-a098-810c-b9c3-cdf448a9d227",
            source_observed_at=f"{self.date}T06:05:00+08:00",
            subjective_conclusion="不可交易",
            emotion_stable=False,
            rhythm_consistent=True,
            result_dependency=False,
            continuous_stop_loss_count=0,
            physical_condition="normal",
        )
        blocked_payload = copy.deepcopy(allowed_payload)
        blocked_payload["execution_authorization"] = {
            "source_kind": "notion_pretrade_gate",
            "source_sha256": blocked_gate["manifest_sha256"],
            "live_execution_allowed": False,
            "reason_code": "pretrade_gate_blocks_live_execution",
        }
        blocked_payload["maker"]["execution_action"] = "blocked"
        blocked_payload["maker"]["order_transition_action"] = "observe"
        blocked_payload["continuity_contract"]["current_plan"].update(
            {
                "action": "observe",
                "new_order_created": False,
                "executable_order_count_after": 0,
                "reason": "个人执行资格本轮关闭，因此不创建订单，但不得改写已经认证的候选计划。",
            }
        )
        blocked_result = evaluate_decision(
            blocked_payload,
            reasoning=reasoning,
            run=run,
            pretrade_gate=blocked_gate,
            root=self.root,
        )
        self.assertTrue(blocked_result.passed, blocked_result.to_dict())

        allowed_plan = copy.deepcopy(allowed_payload["maker"])
        blocked_plan = copy.deepcopy(blocked_payload["maker"])
        allowed_plan.pop("execution_action")
        blocked_plan.pop("execution_action")
        allowed_plan.pop("order_transition_action")
        blocked_plan.pop("order_transition_action")
        self.assertEqual(blocked_plan, allowed_plan)
        self.assertEqual(blocked_payload["main_account"], allowed_payload["main_account"])
        self.assertEqual(
            blocked_result.facts["expected_plan_state"],
            allowed_result.facts["expected_plan_state"],
        )

        evidence = self.controller.store.load_stage_payload(
            self.run_root, "evidence", "evidence"
        )
        methodology = json.loads(
            (self.run_root / "methodology_manifest.json").read_text(encoding="utf-8")
        )
        contract, contract_sha256 = _load_report_presentation_contract(self.root)

        def compile_candidate(decision: dict):
            certified_decision = copy.deepcopy(decision)
            certified_decision["decision_sha256"] = decision_model_sha256(
                certified_decision
            )
            source = certify_report_projection_input(
                evidence=evidence,
                reasoning=reasoning,
                decision=certified_decision,
                blockbeats_rows=_load_blockbeats_rows(self.root, evidence),
                presentation_contract=contract,
                presentation_contract_sha256=contract_sha256,
                methodology_sha256=methodology["phases"]["reasoning"]["phase_sha256"],
                report_contract_sha256=methodology["phases"]["report"]["phase_sha256"],
            )
            return compile_projected_report(source, contract)

        allowed_report = compile_candidate(allowed_payload)
        blocked_report = compile_candidate(blocked_payload)
        allowed_model = to_plain(allowed_report.model)
        blocked_model = to_plain(blocked_report.model)
        self.assertEqual(
            allowed_model["frontstage"]["maker_execution"],
            blocked_model["frontstage"]["maker_execution"],
        )
        self.assertEqual(
            allowed_model["maker_summary"]["risk_plan"],
            blocked_model["maker_summary"]["risk_plan"],
        )
        self.assertEqual(
            allowed_model["audit"]["risk_scenarios"],
            blocked_model["audit"]["risk_scenarios"],
        )
        self.assertNotEqual(
            allowed_model["frontstage"]["maker_authorization"],
            blocked_model["frontstage"]["maker_authorization"],
        )
        self.assertNotEqual(
            allowed_model["frontstage"]["maker_execution_status"],
            blocked_model["frontstage"]["maker_execution_status"],
        )
        for report in (allowed_report, blocked_report):
            self.assertIn("候选计划已通过认证；计划结论成立", report.markdown)
            self.assertIn("Maker风险计划：入场区间", report.markdown)

        missing_gate_result = evaluate_decision(
            allowed_payload,
            reasoning=reasoning,
            run=run,
            pretrade_gate=None,
            root=self.root,
        )
        self.assertIn(
            "binding.pretrade_gate",
            {item.code for item in missing_gate_result.defects},
        )

    def test_decision_v6_rejects_execution_and_continuity_drift(self):
        _, reasoning = self.prepare_through_reasoning()
        baseline = self.decision(reasoning)
        self.assertTrue(
            evaluate_decision(
                baseline,
                reasoning=reasoning,
                run=self.controller.store.load_run(self.run_root),
                pretrade_gate=self.gate,
                root=self.root,
            ).passed
        )
        cases = (
            ("maker.exchange_drift", lambda item: item["maker"].__setitem__("exchange", "Binance")),
            ("maker.position_notional_invalid", lambda item: item["maker"].__setitem__("position_notional_usdt", 100)),
            ("risk.leverage_drift", lambda item: item["maker"]["risk_plan"].__setitem__("leverage", 3)),
            ("main.position_notional_invalid", lambda item: item["main_account"].__setitem__("position_notional_usdt", 100)),
            ("continuity.analysis_mutation", lambda item: item["continuity_contract"]["current_plan"].__setitem__("independent_analysis_changed_after_lock", True)),
            ("continuity.daily_trade_limit", lambda item: item["continuity_contract"]["current_plan"].__setitem__("daily_trade_count_after", 4)),
        )
        for expected_code, mutate in cases:
            with self.subTest(expected_code=expected_code):
                candidate = copy.deepcopy(baseline)
                mutate(candidate)
                result = evaluate_decision(
                    candidate,
                    reasoning=reasoning,
                    run=self.controller.store.load_run(self.run_root),
                    pretrade_gate=self.gate,
                    root=self.root,
                )
                self.assertFalse(result.passed)
                self.assertIn(expected_code, {item.code for item in result.defects})

        right_candidate = copy.deepcopy(baseline)
        right_candidate["maker"]["entry_type"] = "right"
        right_result = evaluate_decision(
            right_candidate,
            reasoning=reasoning,
            run=self.controller.store.load_run(self.run_root),
            pretrade_gate=self.gate,
            root=self.root,
        )
        self.assertFalse(right_result.passed)
        self.assertEqual(
            right_result.facts["maker_candidate_failure_codes"],
            ["entry_semantics_invalid", "cannot_do_conflict"],
        )

    def test_decision_v4_binds_prior_plan_to_standardized_snapshot(self):
        _, reasoning = self.prepare_through_reasoning()
        snapshot = {
            "schema_version": "prior-plan-snapshot-vnext-v1",
            "source_reference": "notion-readonly:maker-plan-page",
            "observed_at": f"{self.date}T09:00:00+08:00",
            "status": "pending",
            "executed_pct": 0,
            "executable_order_count": 1,
            "daily_trade_count": 0,
            "summary": "前序Maker区间计划仍未成交且保留一个有效挂单。",
        }
        snapshot_path = self.root / "continuity" / "prior_plan.json"
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        payload = self.decision(reasoning)
        payload["continuity_contract"]["prior_plan"] = {
            "source_kind": "local_artifact",
            "reference": snapshot_path.relative_to(self.root).as_posix(),
            "source_sha256": sha256_file(snapshot_path),
            "observed_at": snapshot["observed_at"],
            "status": "pending",
            "executed_pct": 0,
            "executable_order_count_before": 1,
            "daily_trade_count_before": 0,
            "summary": snapshot["summary"],
        }
        payload["continuity_contract"]["current_plan"].update(
            {
                "action": "keep",
                "new_order_created": False,
                "executable_order_count_after": 1,
                "reason": "前序订单与锁定后的本轮独立计划完全一致，因此沿用原挂单。",
            }
        )
        payload["maker"]["order_transition_action"] = "keep"
        accepted = evaluate_decision(
            payload,
            reasoning=reasoning,
            run=self.controller.store.load_run(self.run_root),
            pretrade_gate=self.gate,
            root=self.root,
        )
        self.assertTrue(accepted.passed, accepted.to_dict())
        payload["continuity_contract"]["prior_plan"]["summary"] = "模型自行改写了前序计划摘要。"
        rejected = evaluate_decision(
            payload,
            reasoning=reasoning,
            run=self.controller.store.load_run(self.run_root),
            pretrade_gate=self.gate,
            root=self.root,
        )
        self.assertIn(
            "continuity.snapshot_binding_invalid",
            {item.code for item in rejected.defects},
        )

    def test_reasoning_rejects_actual_position_before_seal(self):
        self.controller.accept_evidence(
            self.run_root,
            self.evidence(),
            evidence_files_root=self.root,
        )
        evidence = self.controller.store.load_stage_payload(self.run_root, "evidence", "evidence")
        payload = self.reasoning(evidence)
        claim = next(item for item in payload["claims"] if item["id"] == "claim_main")
        claim["conclusion"] = "Maker账户当前已有空单，因此主账户继续等待。"
        methodology = json.loads(
            (self.run_root / "methodology_manifest.json").read_text(encoding="utf-8")
        )
        result = evaluate_reasoning(
            payload,
            evidence=evidence,
            reasoning_authority_sha256=methodology["phases"]["reasoning"]["phase_sha256"],
            evidence_root=self.root,
            methodology_root=self.root,
        )
        self.assertIn(
            "reasoning.actual_position_coupling",
            {item.code for item in result.defects},
        )

    def test_winrate_rubric_must_recompute_to_the_final_value(self):
        _, reasoning = self.prepare_through_reasoning()
        payload = self.decision(reasoning)
        payload["maker"]["winrate_rubric"]["adjustments"][0]["delta"] = -3
        with self.assertRaises(WorkflowFailure) as caught:
            self.controller.accept_decision(self.run_root, payload)
        self.assertEqual(caught.exception.failure_class, FailureClass.RISK_EXECUTION)
        self.assertTrue(
            any(item["code"] == "winrate.rubric_final" for item in caught.exception.defects)
        )

    def test_winrate_closed_counter_and_adjustment_contract_rejects_bypasses(self):
        _, reasoning = self.prepare_through_reasoning()
        run = self.controller.store.load_run(self.run_root)

        def defect_codes(payload: dict) -> set[str]:
            result = evaluate_decision(
                payload,
                reasoning=reasoning,
                run=run,
                pretrade_gate=self.gate,
                root=self.root,
            )
            return {item.code for item in result.defects}

        payload = self.decision(reasoning)
        payload["maker"]["winrate_rubric"]["adjustments"] = "not-an-array"
        self.assertIn("winrate.adjustments_invalid", defect_codes(payload))

        payload = self.decision(reasoning)
        rubric = payload["maker"]["winrate_rubric"]
        rubric["adjustments"] = []
        rubric["counter_resolution"] = {
            "counter_claim_id": "claim_counter_maker",
            "disposition": "resolved_no_adjustment",
            "adjustment_reason_code": None,
            "residual_clause_indexes": [],
            "resolution_claim_ids": ["claim_maker"],
        }
        rubric["final"] = rubric["anchor"]
        payload["maker"]["win_rate"] = rubric["anchor"]
        self.assertIn("winrate.counter_resolution_disposition", defect_codes(payload))

        payload = self.decision(reasoning)
        payload["maker"]["winrate_rubric"]["counter_resolution"][
            "residual_clause_indexes"
        ] = []
        self.assertIn("winrate.counter_residual_coverage", defect_codes(payload))

        payload = self.decision(reasoning)
        payload["maker"]["winrate_rubric"]["anchor_claim_ids"].append(
            "claim_maker"
        )
        self.assertIn("winrate.anchor_claim_forbidden", defect_codes(payload))

        payload = self.decision(reasoning)
        rubric = payload["maker"]["winrate_rubric"]
        duplicate = copy.deepcopy(rubric["adjustments"][0])
        duplicate["delta"] = -1
        rubric["adjustments"].append(duplicate)
        rubric["final"] -= 1
        payload["maker"]["win_rate"] -= 1
        self.assertIn("winrate.reason_code_duplicate", defect_codes(payload))

        payload = self.decision(reasoning)
        payload["maker"]["winrate_rubric"]["adjustments"][0][
            "claim_ids"
        ] = ["claim_counter_maker", "claim_counter_maker"]
        self.assertIn("winrate.adjustment_claim_duplicate", defect_codes(payload))

        payload = self.decision(reasoning)
        payload["maker"]["winrate_rubric"]["adjustments"][0].update(
            {
                "reason_code": "fedwatch_event_uncertainty",
                "claim_ids": ["claim_fundamental"],
            }
        )
        self.assertIn("winrate.reason_code_invalid", defect_codes(payload))

        payload = self.decision(reasoning)
        payload["maker"]["winrate_rubric"]["anchor_rationale"] = (
            "机构现货持续买入且鲸鱼托底，因此采用更高基准锚。"
        )
        self.assertIn(
            "winrate.anchor_rationale_not_canonical", defect_codes(payload)
        )

        payload = self.decision(reasoning)
        rubric = payload["maker"]["winrate_rubric"]
        rubric["adjustments"].insert(
            0,
            {
                "reason_code": "etf_confirm",
                "label": "ETF现货确认",
                "delta": 1,
                "claim_ids": ["claim_etf"],
                "rationale": "ETF与当前价格方向形成现货侧确认，但不能单变量翻向。",
            },
        )
        rubric["final"] += 1
        payload["maker"]["win_rate"] += 1
        self.assertIn("winrate.counter_adjustment_order", defect_codes(payload))

    def test_fundamental_event_v1_is_observation_only_in_winrate(self):
        _, reasoning = self.prepare_through_reasoning()
        run = self.controller.store.load_run(self.run_root)

        def defect_codes(payload: dict) -> set[str]:
            result = evaluate_decision(
                payload,
                reasoning=reasoning,
                run=run,
                pretrade_gate=self.gate,
                root=self.root,
            )
            return {item.code for item in result.defects}

        legacy_reason = self.decision(reasoning)
        legacy_disposition = next(
            item
            for item in legacy_reason["maker"]["winrate_rubric"][
                "signal_dispositions"
            ]
            if item["signal_type"] == "fundamental_price_realization"
        )
        legacy_disposition[
            "no_adjustment_reason_code"
        ] = "reviewed_no_independent_incremental_effect"
        self.assertIn(
            "winrate.signal_no_adjustment_invalid",
            defect_codes(legacy_reason),
        )

        legacy_adjustment = self.decision(reasoning)
        maker = legacy_adjustment["maker"]
        rubric = maker["winrate_rubric"]
        rubric["adjustments"].append(
            {
                "reason_code": "fundamental_weaken",
                "label": "legacy fundamental adjustment",
                "delta": -1,
                "claim_ids": ["claim_realization"],
                "rationale": "legacy event-v1 load-bearing path",
            }
        )
        disposition = next(
            item
            for item in rubric["signal_dispositions"]
            if item["signal_type"] == "fundamental_price_realization"
        )
        disposition.update(
            {
                "disposition": "adjusted",
                "adjustment_reason_code": "fundamental_weaken",
                "no_adjustment_reason_code": None,
            }
        )
        rubric["final"] -= 1
        maker["win_rate"] -= 1
        codes = defect_codes(legacy_adjustment)
        self.assertIn("winrate.signal_observation_only", codes)
        self.assertIn("winrate.signal_adjustment_mismatch", codes)

    def test_decision_cannot_change_reasoning_sealed_stop_buffer(self):
        _, reasoning = self.prepare_through_reasoning()
        run = self.controller.store.load_run(self.run_root)

        def seal_as_self_reported_observe(
            payload,
            *,
            failure_codes=("structural_stop_invalid",),
        ):
            maker = payload["maker"]
            maker["plan_constructible"] = False
            maker["plan_state"] = "observe"
            maker["execution_action"] = "observe"
            maker["order_transition_action"] = "observe"
            maker["plan_constructibility"].update(
                {
                    "status": "not_constructible",
                    "primary_reason_code": failure_codes[0],
                    "failure_codes": list(failure_codes),
                }
            )
            payload["continuity_contract"]["current_plan"].update(
                {
                    "action": "observe",
                    "new_order_created": False,
                    "executable_order_count_after": 0,
                    "reason": "候选结构止损未通过认证，因此保持观察且不创建订单。",
                }
            )

        def assert_hard_owner_drift(
            payload,
            expected_code="structural_stop.buffer_reasoning_binding",
            *,
            failure_codes=("structural_stop_invalid",),
        ):
            seal_as_self_reported_observe(
                payload,
                failure_codes=failure_codes,
            )
            result = evaluate_decision(
                payload,
                reasoning=reasoning,
                run=run,
                pretrade_gate=self.gate,
                root=self.root,
            )
            self.assertFalse(result.passed, result.to_dict())
            self.assertIn(
                expected_code,
                {item.code for item in result.defects},
            )

        maker_payload = self.decision(reasoning)
        maker_basis = maker_payload["maker"]["risk_plan"]["stop_basis"]
        maker_basis["outward_buffer_price"] = 0.01
        maker_basis["derived_stop"] = 100.21
        maker_payload["maker"]["risk_plan"]["stop"] = 100.21
        maker_payload["maker"]["defense_plan"] = self.exact_prefill_defense_plan(
            [99.8, 100.0], [50, 50], 100.21
        )
        assert_hard_owner_drift(maker_payload)

        near_equal_payload = self.decision(reasoning)
        near_equal_basis = near_equal_payload["maker"]["risk_plan"]["stop_basis"]
        near_equal_basis["outward_buffer_price"] = 0.150000001
        near_equal_basis["derived_stop"] = 100.350000001
        near_equal_payload["maker"]["risk_plan"]["stop"] = 100.350000001
        near_equal_payload["maker"]["defense_plan"] = self.exact_prefill_defense_plan(
            [99.8, 100.0], [50, 50], 100.350000001
        )
        assert_hard_owner_drift(near_equal_payload)

        for field, drifted_value in (
            ("observation_id", "obs_cg"),
            ("timeframe", "4h"),
        ):
            with self.subTest(field=field):
                drifted_payload = self.decision(reasoning)
                drifted_payload["maker"]["risk_plan"]["stop_basis"][field] = (
                    drifted_value
                )
                assert_hard_owner_drift(drifted_payload)

        cross_timeframe_payload = self.decision(reasoning)
        cross_timeframe_basis = cross_timeframe_payload["maker"]["risk_plan"][
            "stop_basis"
        ]
        cross_timeframe_basis.update(
            {
                "timeframe": "4h",
                "anchor_source_field": (
                    "metrics.chart_basis.structure_zones[1].upper_bound"
                ),
                "anchor_price": 100.5,
                "derived_stop": 100.65,
            }
        )
        cross_timeframe_payload["maker"]["risk_plan"]["stop"] = 100.65
        cross_timeframe_payload["maker"]["defense_plan"] = (
            {}
        )
        assert_hard_owner_drift(
            cross_timeframe_payload,
            failure_codes=("structural_stop_invalid", "risk_math_invalid"),
        )

        for field, drifted_value, expected_code in (
            (
                "buffer_claim_id",
                "claim_counter_maker",
                "structural_stop.buffer_claim_binding",
            ),
            (
                "buffer_basis_code",
                "bogus",
                "structural_stop.buffer_basis_code",
            ),
            (
                "buffer_backsolved_from_risk",
                True,
                "structural_stop.buffer_backsolve_forbidden",
            ),
        ):
            with self.subTest(field=field):
                drifted_payload = self.decision(reasoning)
                drifted_payload["maker"]["risk_plan"]["stop_basis"][field] = (
                    drifted_value
                )
                assert_hard_owner_drift(
                    drifted_payload,
                    expected_code,
                )

        observation_payload = self.decision(reasoning)
        observation_payload["maker"]["risk_plan"]["stop_basis"][
            "observation_id"
        ] = "obs_cg"
        assert_hard_owner_drift(
            observation_payload,
            "structural_stop.observation_binding",
        )

        cross_account_payload = self.decision(reasoning)
        cross_account_payload["maker"]["risk_plan"]["stop_basis"] = copy.deepcopy(
            cross_account_payload["main_account"]["stop_basis"]
        )
        cross_account_payload["maker"]["risk_plan"]["stop"] = 101.0
        cross_account_payload["maker"]["defense_plan"] = {}
        assert_hard_owner_drift(
            cross_account_payload,
            "structural_stop.claim_binding",
            failure_codes=("structural_stop_invalid", "risk_math_invalid"),
        )

        main_payload = self.decision(reasoning)
        main_basis = main_payload["main_account"]["stop_basis"]
        main_basis["outward_buffer_price"] = 0.1
        main_basis["derived_stop"] = 100.6
        main_payload["main_account"]["stop"] = 100.6
        main_result = evaluate_decision(
            main_payload,
            reasoning=reasoning,
            run=run,
            pretrade_gate=self.gate,
            root=self.root,
        )
        self.assertIn(
            "structural_stop.buffer_reasoning_binding",
            {item.code for item in main_result.defects},
        )

    def test_directional_thesis_can_retain_constructibility_diagnostics_without_risk_input(self):
        _, reasoning = self.prepare_through_reasoning()
        payload = self.decision(reasoning)
        maker = payload["maker"]
        maker["risk_plan"] = {}
        maker["defense_plan"] = {}
        maker["position_notional_usdt"] = None
        maker["entry_type"] = "not_applicable"
        maker["entry_reach_probability"] = None
        maker["entry_reach_probability_basis"].update(
            {
                "applicability": "not_applicable_no_certified_entry_geometry",
                "reference_entry": None,
                "entry_distance": None,
                "reach_direction": None,
            }
        )
        maker["order_lifecycle"] = {
            "schema_version": "maker-order-lifecycle-v1",
            "state": "not_applicable_no_candidate_geometry",
            "legal_fill_path_exists": False,
            "legal_cancel_path_exists": False,
            "fill_probability": None,
            "fill_probability_applicability": "not_applicable_no_candidate_geometry",
            "reason_code": "not_applicable_no_candidate_geometry",
        }
        maker["plan_constructible"] = False
        maker["plan_state"] = "observe"
        maker["execution_action"] = "observe"
        maker["order_transition_action"] = "observe"
        maker["plan_constructibility"].update(
            {
                "status": "not_constructible",
                "primary_reason_code": "structural_stop_invalid",
                "failure_codes": [
                    "structural_stop_invalid",
                    "risk_math_invalid",
                ],
            }
        )
        payload["continuity_contract"]["current_plan"].update(
            {
                "action": "observe",
                "new_order_created": False,
                "executable_order_count_after": 0,
                "reason": "密封周期没有合法外部锚，保持观察且不提交风险候选。",
            }
        )
        result = evaluate_decision(
            payload,
            reasoning=reasoning,
            run=self.controller.store.load_run(self.run_root),
            pretrade_gate=self.gate,
            root=self.root,
        )
        self.assertTrue(result.passed, result.to_dict())
        self.assertEqual(
            result.facts["maker_candidate_failure_codes"],
            [
                "structural_stop_invalid",
                "risk_math_invalid",
            ],
        )

    def test_directional_thesis_with_structure_zones_is_not_forced_into_candidate_fields(self):
        _, reasoning = self.prepare_through_reasoning()
        payload = self.decision(reasoning)
        maker = payload["maker"]
        maker["risk_plan"] = {}
        maker["defense_plan"] = {}
        maker["position_notional_usdt"] = None
        maker["entry_type"] = "not_applicable"
        maker["entry_reach_probability"] = None
        maker["entry_reach_probability_basis"].update(
            {
                "applicability": "not_applicable_no_certified_entry_geometry",
                "reference_entry": None,
                "entry_distance": None,
                "reach_direction": None,
            }
        )
        maker["order_lifecycle"] = {
            "schema_version": "maker-order-lifecycle-v1",
            "state": "not_applicable_no_candidate_geometry",
            "legal_fill_path_exists": False,
            "legal_cancel_path_exists": False,
            "fill_probability": None,
            "fill_probability_applicability": "not_applicable_no_candidate_geometry",
            "reason_code": "not_applicable_no_candidate_geometry",
        }
        maker["plan_constructible"] = False
        maker["plan_state"] = "observe"
        maker["execution_action"] = "observe"
        maker["order_transition_action"] = "observe"
        maker["plan_constructibility"].update(
            {
                "status": "not_constructible",
                "primary_reason_code": "entry_zone_binding_invalid",
                "failure_codes": [
                    "entry_zone_binding_invalid",
                    "structural_stop_invalid",
                    "risk_math_invalid",
                ],
                "entry_zone_basis": None,
            }
        )
        payload["continuity_contract"]["current_plan"].update(
            {
                "action": "observe",
                "new_order_created": False,
                "executable_order_count_after": 0,
            }
        )

        result = evaluate_decision(
            payload,
            reasoning=reasoning,
            run=self.controller.store.load_run(self.run_root),
            pretrade_gate=self.gate,
            root=self.root,
        )

        self.assertTrue(result.passed, result.to_dict())
        self.assertEqual(
            result.facts["maker_candidate_failure_codes"],
            [
                "entry_zone_binding_invalid",
                "structural_stop_invalid",
                "risk_math_invalid",
            ],
        )

    def test_submitted_candidate_still_requires_entry_zone_basis(self):
        _, reasoning = self.prepare_through_reasoning()
        payload = self.decision(reasoning)
        payload["maker"]["plan_constructibility"]["entry_zone_basis"] = None

        result = evaluate_decision(
            payload,
            reasoning=reasoning,
            run=self.controller.store.load_run(self.run_root),
            pretrade_gate=self.gate,
            root=self.root,
        )

        self.assertFalse(result.passed, result.to_dict())
        self.assertIn(
            "maker.entry_zone_basis_schema",
            {item.code for item in result.defects},
        )

    def test_chart_score_component_must_trace_to_tradingview(self):
        _, reasoning = self.prepare_through_reasoning()
        payload = self.decision(reasoning)
        payload["maker"]["chart_scorecard"]["chart.support_resistance"]["claim_ids"] = ["claim_etf"]
        with self.assertRaises(WorkflowFailure) as caught:
            self.controller.accept_decision(self.run_root, payload)
        self.assertTrue(
            any(item["code"] == "decision.claim_source_missing" for item in caught.exception.defects)
        )

    def test_entry_reach_probability_distance_must_match_certified_price(self):
        _, reasoning = self.prepare_through_reasoning()
        payload = self.decision(reasoning)
        payload["maker"]["entry_reach_probability_basis"]["entry_distance"] = 2.5
        with self.assertRaises(WorkflowFailure) as caught:
            self.controller.accept_decision(self.run_root, payload)
        self.assertTrue(
            any(
                item["code"] == "entry_reach_probability.entry_distance"
                for item in caught.exception.defects
            )
        )

    def test_applicable_entry_reach_probability_preserves_real_zero(self):
        _, reasoning = self.prepare_through_reasoning()
        payload = self.decision(reasoning)
        payload["maker"]["entry_reach_probability"] = 0
        result = evaluate_decision(
            payload,
            reasoning=reasoning,
            run=self.controller.store.load_run(self.run_root),
            pretrade_gate=self.gate,
            root=self.root,
        )
        self.assertTrue(result.passed, result.to_dict())

    def test_entry_reach_probability_applicability_is_derived_from_certified_candidate_geometry(self):
        _, reasoning = self.prepare_through_reasoning()
        run = self.controller.store.load_run(self.run_root)
        cases = {
            "unresolved_zone": lambda maker: maker["plan_constructibility"][
                "entry_zone_basis"
            ].__setitem__("zone_index", 999),
            "missing_entry_geometry": lambda maker: (
                maker["risk_plan"].__setitem__("entries", []),
                maker["risk_plan"].__setitem__("entry_allocations_pct", []),
            ),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                payload = self.decision(reasoning)
                mutate(payload["maker"])
                numeric_result = evaluate_decision(
                    payload,
                    reasoning=reasoning,
                    run=run,
                    pretrade_gate=self.gate,
                    root=self.root,
                )
                numeric_codes = {item.code for item in numeric_result.defects}
                self.assertIn(
                    "entry_reach_probability.applicability_drift", numeric_codes
                )
                self.assertIn(
                    "entry_reach_probability.not_applicable_value", numeric_codes
                )

                typed_na = copy.deepcopy(payload)
                typed_na["maker"]["entry_reach_probability"] = None
                typed_na["maker"]["entry_reach_probability_basis"].update(
                    {
                        "applicability": "not_applicable_no_certified_entry_geometry",
                        "reference_entry": None,
                        "entry_distance": None,
                        "reach_direction": None,
                    }
                )
                na_result = evaluate_decision(
                    typed_na,
                    reasoning=reasoning,
                    run=run,
                    pretrade_gate=self.gate,
                    root=self.root,
                )
                self.assertFalse(
                    any(
                        item.code.startswith("entry_reach_probability.")
                        for item in na_result.defects
                    ),
                    na_result.to_dict(),
                )

        malformed_non_geometry = self.decision(reasoning)
        malformed_non_geometry["maker"]["risk_plan"].pop("tp2")
        malformed_result = evaluate_decision(
            malformed_non_geometry,
            reasoning=reasoning,
            run=run,
            pretrade_gate=self.gate,
            root=self.root,
        )
        self.assertFalse(
            any(
                item.code.startswith("entry_reach_probability.")
                for item in malformed_result.defects
            ),
            malformed_result.to_dict(),
        )

    def test_capture_infrastructure_failure_retries_evidence_only(self):
        failed = subprocess.CompletedProcess(
            args=["node"],
            returncode=3,
            stdout="",
            stderr="browser unavailable",
        )
        with patch("runtime_vnext.controller.subprocess.run", return_value=failed):
            with self.assertRaises(WorkflowFailure) as caught:
                self.controller.capture(self.run_root)
        self.assertEqual(caught.exception.failure_class, FailureClass.INFRASTRUCTURE_TRANSIENT)
        status = self.controller.status(self.run_root)
        self.assertEqual(status["next_stage"], "evidence")
        self.assertEqual(status["attempt_counts"]["evidence"], 1)

    def test_capture_preserves_safe_exocharts_leaf_failure_code(self):
        capture_id = "00000000-0000-4000-8000-000000000001"
        manifest_path = (
            self.root
            / "runtime_state"
            / self.date
            / "captures"
            / self.slot
            / f"full_base_{capture_id}.json"
        )
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "date": self.date,
                    "slot": self.slot,
                    "mode": "full_base",
                    "run_id": capture_id,
                    "vnext_active_run_id": "run-test",
                    "results": {"capture_exo.js": 2},
                    "source_failures": {
                        "capture_exo.js": {
                            "defect_code": "capture.exocharts.vwap_unconfirmed"
                        }
                    },
                    "success": False,
                }
            ),
            encoding="utf-8",
        )
        failed = subprocess.CompletedProcess(
            args=["node"],
            returncode=2,
            stdout=f"FULL_CAPTURE_MANIFEST={manifest_path}\n",
            stderr="collector failed with unrestricted implementation detail",
        )
        with patch("runtime_vnext.controller.uuid.uuid4", return_value=uuid.UUID(capture_id)):
            with patch(
                "runtime_vnext.controller.subprocess.run",
                return_value=failed,
            ) as capture_run:
                with self.assertRaises(WorkflowFailure) as caught:
                    self.controller.capture(self.run_root)
        self.assertEqual(
            caught.exception.defects[0]["code"],
            "capture.exocharts.vwap_unconfirmed",
        )
        self.assertEqual(caught.exception.defects[0]["path"], "evidence.Exocharts")
        attempt_root = Path(
            capture_run.call_args.kwargs["env"]["VNEXT_CAPTURE_ATTEMPT_ROOT"]
        )
        self.assertEqual(attempt_root.parent, self.run_root / "evidence")
        self.assertRegex(attempt_root.name, r"^attempt-\d{3}$")
        self.assertEqual(
            capture_run.call_args.kwargs["env"]["VNEXT_PYTHON_EXECUTABLE"],
            sys.executable,
        )

    def test_capture_rejects_unstructured_exocharts_failure_marker(self):
        capture_id = "00000000-0000-4000-8000-000000000002"
        manifest_path = (
            self.root
            / "runtime_state"
            / self.date
            / "captures"
            / self.slot
            / f"full_base_{capture_id}.json"
        )
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "date": self.date,
                    "slot": self.slot,
                    "run_id": capture_id,
                    "vnext_active_run_id": "run-test",
                    "results": {"capture_exo.js": 2},
                    "source_failures": {
                        "capture_exo.js": {
                            "defect_code": "vWap failed: user token=should-not-propagate"
                        }
                    },
                    "success": False,
                }
            ),
            encoding="utf-8",
        )
        failed = subprocess.CompletedProcess(
            args=["node"],
            returncode=2,
            stdout=f"FULL_CAPTURE_MANIFEST={manifest_path}\n",
            stderr="",
        )
        with patch("runtime_vnext.controller.uuid.uuid4", return_value=uuid.UUID(capture_id)):
            with patch("runtime_vnext.controller.subprocess.run", return_value=failed):
                with self.assertRaises(WorkflowFailure) as caught:
                    self.controller.capture(self.run_root)
        self.assertEqual(caught.exception.defects[0]["code"], "capture.failed")

    def test_second_capture_failure_requires_manual_review(self):
        failed = subprocess.CompletedProcess(
            args=["node"],
            returncode=3,
            stdout="",
            stderr="browser unavailable",
        )
        with patch("runtime_vnext.controller.subprocess.run", return_value=failed):
            with self.assertRaises(WorkflowFailure) as first:
                self.controller.capture(self.run_root)
            with self.assertRaises(WorkflowFailure) as second:
                self.controller.capture(self.run_root)
        self.assertEqual(first.exception.failure_class, FailureClass.INFRASTRUCTURE_TRANSIENT)
        self.assertEqual(second.exception.failure_class, FailureClass.MANUAL_REVIEW)
        self.assertEqual(self.controller.status(self.run_root)["status"], "needs_review")

    def test_legacy_capture_adapter_verifies_and_maps_all_six_sources(self):
        capture_run_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        profile_nonce = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        snapshot = (
            self.root
            / "runtime_state"
            / self.date
            / "evidence"
            / self.slot
            / capture_run_id
        )
        snapshot.mkdir(parents=True)
        contents = {
            "blockbeats.json": {
                "important_only": True,
                "capture_window_hours": 12,
                "window_covered": True,
                "selected_count_required": 3,
                "selected_rows": [
                    {"selected_rank": index, "time": f"7/13 0{index}:00", "title": f"事件{index}", "body": f"事件{index}正文"}
                    for index in range(1, 4)
                ],
            },
            "blockbeats.png": b"png",
            "coinglass.png": b"png",
            "exocharts.png": b"png",
            "fedwatch.png": b"png",
            "farside_btc_etf.json": {
                "latest": {
                    "date_iso": "2026-07-10",
                    "total_usd_m": -10.5,
                    "funds": {"IBIT": -10.5},
                }
            },
            "farside_btc_etf.png": b"png",
            "liqheatmap_48h.png": b"png",
            "liqheatmap_24h.png": b"png",
            "tradingview_btc_1d.png": b"png",
            "tradingview_btc_4h.png": b"png",
            "tradingview_btc_1h.png": b"png",
            "tradingview_btc_15m.png": b"png",
            "tradingview_profile_state.json": {
                "schema_version": "tradingview-profile-state-v2",
                "capture_run_id": capture_run_id,
                "capture_nonce": profile_nonce,
                "source_mode": "user_drawn_manual_only",
                "platform_indicator_policy": "hide_and_never_use",
                "aggregate_state": "hidden",
                "timeframes": {
                    frame: {
                        "initial_state": "hidden",
                        "final_state": "hidden",
                        "correction_attempted": False,
                        "certification_basis": "profile_control",
                    }
                    for frame in ("1d", "4h", "1h", "15m")
                },
            },
        }
        records = []
        for name, content in contents.items():
            path = snapshot / name
            if isinstance(content, dict):
                path.write_text(json.dumps(content), encoding="utf-8")
            else:
                path.write_bytes(self.valid_png_bytes())
            records.append({"path": name, "sha256": sha256_file(path), "size": path.stat().st_size})
        capture_dir = self.root / "runtime_state" / self.date / "captures" / self.slot
        capture_dir.mkdir(parents=True)
        manifest_path = capture_dir / "full_base_test.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "date": self.date,
                    "slot": self.slot,
                    "mode": "full_base",
                    "run_id": capture_run_id,
                    "evidence_capture_run_id": capture_run_id,
                    "tradingview_profile_binding": {
                        "schema_version": "tradingview-profile-capture-binding-v1",
                        "capture_run_id": capture_run_id,
                        "capture_nonce": profile_nonce,
                        "sidecar_filename": "tradingview_profile_state.json",
                        "sidecar_schema_version": "tradingview-profile-state-v2",
                    },
                    "workflow_lease_id": "lease-test",
                    "completed_at": "2026-07-13T00:37:54.555Z",
                    "results": {"capture_all.js": 0},
                    "evidence_snapshot": {
                        "root": f"evidence/{self.slot}/{capture_run_id}",
                        "created_at": "2026-07-13T00:37:54.555Z",
                        "files": records,
                    },
                    "success": True,
                }
            ),
            encoding="utf-8",
        )
        adapted = adapt_legacy_capture(manifest_path, root=self.root)
        self.assertEqual(adapted["capture_mode"], "full_base")
        self.assertEqual(set(adapted["sources"]), set(REQUIRED_SOURCES))
        self.assertEqual(adapted["sources"]["TradingView"]["timeframes"], ["1D", "4H", "1H", "15m"])
        self.assertEqual(adapted["capture_run_id"], capture_run_id)
        self.assertEqual(
            adapted["tradingview_profile_binding"]["capture_nonce"],
            profile_nonce,
        )
        self.assertRegex(adapted["snapshot_sha256"], r"^[0-9a-f]{64}$")

        original_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        cross_run = copy.deepcopy(original_manifest)
        cross_run["evidence_capture_run_id"] = (
            "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
        )
        manifest_path.write_text(json.dumps(cross_run), encoding="utf-8")
        with self.assertRaisesRegex(
            ValueError,
            "profile binding differs from current evidence run",
        ):
            adapt_legacy_capture(manifest_path, root=self.root)

        path_drift = copy.deepcopy(original_manifest)
        path_drift["evidence_capture_run_id"] = (
            "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
        )
        path_drift["tradingview_profile_binding"]["capture_run_id"] = (
            "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
        )
        manifest_path.write_text(json.dumps(path_drift), encoding="utf-8")
        with self.assertRaisesRegex(
            ValueError,
            "snapshot root differs from evidence_capture_run_id",
        ):
            adapt_legacy_capture(manifest_path, root=self.root)

        manifest_path.write_text(json.dumps(original_manifest), encoding="utf-8")

    def test_legacy_adapter_closes_plan_c_provenance_before_meta_projection(self):
        evidence = self.plan_c_evidence()
        records = evidence["sources"]["FedWatch"]["artifacts"]
        snapshot_root = (self.root / records[0]["path"]).parent
        schema, meta = _rate_expectation_meta(
            snapshot_root=snapshot_root,
            grouped_records=records,
            capture_run_id=evidence["capture_run_id"],
            root=self.root,
        )
        self.assertEqual(schema, "evidence-snapshot-v2")
        self.assertEqual(meta, evidence["sources"]["FedWatch"]["meta"])

        provenance_path = snapshot_root / "rate_expectation_provenance.json"
        original = json.loads(provenance_path.read_text(encoding="utf-8"))
        mutated = copy.deepcopy(original)
        mutated["provider_id"] = "cme_fedwatch_ui"
        provenance_path.write_text(json.dumps(mutated), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "identity or hash"):
            _rate_expectation_meta(
                snapshot_root=snapshot_root,
                grouped_records=records,
                capture_run_id=evidence["capture_run_id"],
                root=self.root,
            )

        provenance_path.write_text(json.dumps(original), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "not closed"):
            _rate_expectation_meta(
                snapshot_root=snapshot_root,
                grouped_records=[*records, {"path": "fedwatch.png"}],
                capture_run_id=evidence["capture_run_id"],
                root=self.root,
            )

        unknown = copy.deepcopy(original)
        unknown["fallback_reason_code"] = "cme_unknown_failure"
        unknown["provenance_sha256"] = rate_canonical_sha256(
            unknown, exclude="provenance_sha256"
        )
        provenance_path.write_text(json.dumps(unknown), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "not closed"):
            _rate_expectation_meta(
                snapshot_root=snapshot_root,
                grouped_records=records,
                capture_run_id=evidence["capture_run_id"],
                root=self.root,
            )

    def test_legacy_capture_adapter_preserves_verified_fallback_identity(self):
        self.test_legacy_capture_adapter_verifies_and_maps_all_six_sources()
        capture_dir = self.root / "runtime_state" / self.date / "captures" / self.slot
        base_path = capture_dir / "full_base_test.json"
        fallback = json.loads(base_path.read_text(encoding="utf-8"))
        evidence_run_id = fallback["evidence_capture_run_id"]
        fallback["mode"] = "full_recollection"
        fallback_path = capture_dir / f"full_recollection_{evidence_run_id}.json"
        fallback_path.write_text(json.dumps(fallback), encoding="utf-8")

        outer_run_id = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
        state_root = self.root / "runtime_state" / self.date
        outer = {
            **copy.deepcopy(fallback),
            "mode": "conservative_delta",
            "run_id": outer_run_id,
            "results": {"capture_tv.js": 2},
            "full_fallback_used": True,
            "fallback_code": 0,
            "fallback_manifest": {
                "path": fallback_path.relative_to(state_root).as_posix(),
                "sha256": sha256_file(fallback_path),
            },
        }
        outer_path = capture_dir / f"conservative_delta_{outer_run_id}.json"
        outer_path.write_text(json.dumps(outer), encoding="utf-8")
        adapted = adapt_legacy_capture(outer_path, root=self.root)
        self.assertEqual(adapted["capture_run_id"], evidence_run_id)
        self.assertEqual(
            adapted["tradingview_profile_binding"]["capture_run_id"],
            evidence_run_id,
        )

        fallback["evidence_capture_run_id"] = (
            "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
        )
        fallback_path.write_text(json.dumps(fallback), encoding="utf-8")
        outer["fallback_manifest"]["sha256"] = sha256_file(fallback_path)
        outer_path.write_text(json.dumps(outer), encoding="utf-8")
        with self.assertRaisesRegex(
            ValueError,
            "fallback manifest does not bind",
        ):
            adapt_legacy_capture(outer_path, root=self.root)

    def test_complete_flow_compiles_from_model_and_finishes(self):
        self.prepare_through_decision()
        report_manifest = self.controller.compile_report(self.run_root)
        status = self.controller.status(self.run_root)
        self.assertEqual(status["next_stage"], "delivery")
        report = self.controller.store.load_stage_payload(self.run_root, "report", "canonical_report")
        self.assertEqual(report["schema_version"], "canonical-report-model-v11")
        report_outputs = self.controller.store.load_checkpoint(self.run_root)["completed"]["report"]["outputs"]
        report_bindings = self.controller.store.load_stage_payload(
            self.run_root,
            "report",
            "report_bindings",
        )
        combined = report_outputs["combined"]
        self.assertEqual(len(report["blockbeats_cards"]), 3)
        self.assertEqual(
            tuple(
                (item["section_id"], tuple(item["model_path"]))
                for item in report_bindings["sections"]
            ),
            REGISTRY.report_binding_section_model_paths,
        )
        self.assertEqual(
            report_manifest["gate"]["facts"]["report_bindings_sha256"],
            report_outputs["report_bindings"]["sha256"],
        )
        for name in (
            "report_bindings",
            "cards_spec",
            "card_1",
            "card_2",
            "card_3",
        ):
            self.assertTrue((self.root / report_outputs[name]["path"]).is_file())
        text = (self.root / combined["path"]).read_text(encoding="utf-8")
        self.assertIn("## ③ 后附", text)
        self.assertIn("Farside", text)
        self.assertIn("事件窗口（小时）", text)
        self.assertIn("主账户与 Maker 分离", text)
        self.assertIn("基准情景", text)
        self.assertIn("计划时置信度推导链（非回测命中率）", text)
        self.assertIn("持仓750 USDT", text)
        self.assertIn("OKX BTCUSDT", text)
        self.assertIn("左侧", text)
        self.assertIn("杠杆5x", text)
        self.assertIn("已执行0%", text)
        for timeframe in ("1D价格", "4H价格", "1H价格", "15m价格"):
            self.assertIn(timeframe, text)
        decision_outputs = self.controller.store.load_checkpoint(self.run_root)["completed"]["decision"]["outputs"]
        self.assertIn("continuity", decision_outputs)
        self.assertTrue((self.root / decision_outputs["continuity"]["path"]).is_file())
        self.assertIn("### C. 人类可读推理证明链", text)
        proof_section = text.split("### C. 人类可读推理证明链", 1)[1].split(
            "### D. 风险、情景与机械校验",
            1,
        )[0]
        for marker in (
            "**主账户基准情景**：触发条件为",
            "**主账户反证情景**：触发条件为",
            "**主账户失效情景**：触发条件为",
            "**Maker基准情景**：触发条件为",
            "**Maker反证情景**：触发条件为",
            "**Maker失效情景**：触发条件为",
        ):
            self.assertEqual(text.count(marker), 1)
            self.assertNotIn(marker, proof_section)
        for marker in (
            "**主账户当前最强反证**：",
            "**主账户未来反证触发条件**：",
            "**主账户当前失效路径基线**：",
            "**主账户未来失效触发条件**：",
            "**Maker当前最强反证**：",
            "**Maker未来反证触发条件**：",
            "**Maker当前失效路径基线**：",
            "**Maker未来失效触发条件**：",
        ):
            self.assertEqual(text.count(marker), 1)
        self.assertNotIn("event_window_hours", text)
        self.assertNotIn("main_account_thesis", text)
        self.assertNotIn("补充指标（", text)
        self.assertNotRegex(text, r"\b[0-9a-f]{64}\b")
        self.assertNotIn("#### ", text)
        self.assertNotIn("。。", text)
        self.assertNotIn(".。", text)
        gate_facts = self.controller.store.load_checkpoint(self.run_root)["completed"]["report"]
        manifest = json.loads((self.root / gate_facts["manifest_path"]).read_text(encoding="utf-8"))
        self.assertTrue(manifest["gate"]["facts"]["human_reasoning_depth"]["passed"])
        self.assertTrue(manifest["gate"]["facts"]["gold_template_fidelity"]["passed"])
        self.controller.accept_delivery(self.run_root, self.delivery())
        self.assertEqual(self.controller.status(self.run_root)["status"], "complete")

    def test_delivery_reopens_report_bindings_integrity_record(self):
        self.prepare_through_decision()
        self.controller.compile_report(self.run_root)
        bindings_record = self.controller.store.load_stage_output_record(
            self.run_root,
            "report",
            "report_bindings",
        )
        bindings_path = self.root / bindings_record["path"]
        bindings_path.write_text(
            bindings_path.read_text(encoding="utf-8") + " ",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "stage output changed"):
            self.controller.accept_delivery(
                self.run_root,
                self.delivery(),
            )
        self.assertEqual(
            self.controller.store.attempt_count(self.run_root, "delivery"),
            0,
        )

    def test_liquidation_fact_projects_certified_timeframes_for_compatibility_lint(self):
        raw_evidence = self.evidence()
        self.controller.accept_evidence(
            self.run_root,
            raw_evidence,
            evidence_files_root=self.root,
        )
        evidence = self.controller.store.load_stage_payload(
            self.run_root,
            "evidence",
            "evidence",
        )
        reasoning = self.reasoning(evidence)
        coinglass = next(
            item for item in reasoning["observations"] if item.get("source") == "Coinglass"
        )
        coinglass["fact"] = (
            "Coinglass同一一小时主腿价格上行，上方65000与下方63000存在清算密集区。"
        )
        self.controller.accept_reasoning(self.run_root, reasoning)
        certified = self.controller.store.load_stage_payload(
            self.run_root,
            "reasoning",
            "reasoning",
        )
        self.controller.accept_decision(self.run_root, self.decision(certified))

        self.controller.compile_report(self.run_root)

        combined = self.controller.store.load_stage_output_record(
            self.run_root,
            "report",
            "combined",
        )
        text = (self.root / combined["path"]).read_text(encoding="utf-8")
        self.assertIn("清算图周期：48H、24H", text)

    def test_report_compiles_when_optional_15m_sma20_is_absent(self):
        raw_evidence = self.evidence()
        self.controller.accept_evidence(
            self.run_root,
            raw_evidence,
            evidence_files_root=self.root,
        )
        evidence = self.controller.store.load_stage_payload(
            self.run_root, "evidence", "evidence"
        )
        reasoning = self.reasoning(evidence)
        tradingview = next(
            item for item in reasoning["observations"] if item["source"] == "TradingView"
        )
        tradingview["metrics"]["timeframes"]["15m"]["sma20"] = None
        tradingview["visual_review"]["metrics_sha256"] = canonical_sha256(
            tradingview["metrics"]
        )
        self.controller.accept_reasoning(self.run_root, reasoning)
        reasoning = self.controller.store.load_stage_payload(
            self.run_root, "reasoning", "reasoning"
        )
        self.controller.accept_decision(self.run_root, self.decision(reasoning))

        self.controller.compile_report(self.run_root)

        outputs = self.controller.store.load_checkpoint(self.run_root)["completed"]["report"]["outputs"]
        text = (self.root / outputs["combined"]["path"]).read_text(encoding="utf-8")
        self.assertIn("15m价格", text)
        self.assertIn("SMA20 未采集（15m非必需）", text)

    def test_observe_report_compiles_without_defense_trigger_formula(self):
        _, reasoning = self.prepare_through_reasoning()
        decision = self.decision(reasoning)
        decision["maker"]["plan_state"] = "observe"
        decision["maker"]["threshold_eligible"] = False
        decision["maker"]["execution_action"] = "observe"
        decision["maker"]["order_transition_action"] = "observe"
        decision["maker"]["win_rate"] = 56
        decision["maker"]["winrate_rubric"]["adjustments"][0]["delta"] = -12
        decision["maker"]["winrate_rubric"]["final"] = 56
        decision["continuity_contract"]["current_plan"].update(
            {
                "action": "observe",
                "new_order_created": False,
                "executable_order_count_after": 0,
                "daily_trade_count_after": 0,
                "reason": "当前评分与胜率未同时达标，因此不创建订单并继续观察。",
            }
        )
        self.controller.accept_decision(self.run_root, decision)

        self.controller.compile_report(self.run_root)

        combined = self.controller.store.load_stage_output_record(
            self.run_root,
            "report",
            "combined",
        )
        text = (self.root / combined["path"]).read_text(encoding="utf-8")
        self.assertIn("被拒候选机械结论（不可执行，不得用于下单）", text)
        self.assertIn("已提交候选未通过认证，不可执行", text)
        self.assertIn("第一层：", text)
        self.assertIn("第二层：", text)
        self.assertIn("### BTC（未通过认证）", text)
        self.assertNotIn("### BTC（被拒候选审计）", text)
        self.assertTrue(
            all(len(line.removeprefix("### ")) <= 70 for line in text.splitlines() if line.startswith("### "))
        )
        self.assertNotIn("双门槛", text)
        self.assertNotIn("### BTC（候选策略）", text)
        self.assertNotIn("first_trigger_formula", text)
        self.assertNotIn("实际加权成交价", text)
        frontstage, appendix_d = text.split("### D. 风险、情景与机械校验", maxsplit=1)
        self.assertNotIn("订单生命周期：", frontstage)
        self.assertNotIn("候选名义持仓750", frontstage)
        self.assertIn("被拒候选参数审计（不可执行，不得用于下单）", appendix_d)
        self.assertIn("被拒候选订单生命周期审计（不可执行，不得用于下单）", appendix_d)

    def test_shadow_observe_report_compiles_without_defense_trigger_formula(self):
        _, reasoning = self.prepare_through_reasoning()
        decision = self.decision(reasoning)
        decision["maker"]["plan_state"] = "observe"
        decision["maker"]["threshold_eligible"] = False
        decision["maker"]["execution_action"] = "not_attempted"
        decision["maker"]["order_transition_action"] = "not_attempted"
        decision["maker"]["win_rate"] = 56
        decision["maker"]["winrate_rubric"]["adjustments"][0]["delta"] = -12
        decision["maker"]["winrate_rubric"]["final"] = 56
        self.controller.accept_decision(self.run_root, decision)

        self.controller.compile_report(self.run_root)

        combined = self.controller.store.load_stage_output_record(
            self.run_root,
            "report",
            "combined",
        )
        text = (self.root / combined["path"]).read_text(encoding="utf-8")
        self.assertIn("被拒候选机械结论（不可执行，不得用于下单）", text)
        self.assertIn("### BTC（未通过认证）", text)
        self.assertNotIn("### BTC（被拒候选审计）", text)
        self.assertIn("真实执行状态：未尝试真实执行", text)
        self.assertIn("第一层：无可执行 Maker 计划，第一层防守暂不触发。", text)
        self.assertIn("第二层：无可执行 Maker 计划，第二层防守暂不触发。", text)
        self.assertNotIn("first_trigger_formula", text)
        self.assertNotIn("实际加权成交价", text)
        frontstage, appendix_d = text.split("### D. 风险、情景与机械校验", maxsplit=1)
        self.assertNotIn("订单生命周期：", frontstage)
        self.assertNotIn("候选名义持仓750", frontstage)
        self.assertIn("被拒候选参数审计（不可执行，不得用于下单）", appendix_d)
        self.assertIn("被拒候选订单生命周期审计（不可执行，不得用于下单）", appendix_d)

    def test_report_projection_moves_audit_meta_and_owns_defense_triggers_once(self):
        raw_evidence = self.evidence()
        self.controller.accept_evidence(
            self.run_root,
            raw_evidence,
            evidence_files_root=self.root,
        )
        evidence = self.controller.store.load_stage_payload(self.run_root, "evidence", "evidence")
        reasoning = self.reasoning(evidence)
        self.controller.accept_reasoning(self.run_root, reasoning)
        certified_reasoning = self.controller.store.load_stage_payload(
            self.run_root,
            "reasoning",
            "reasoning",
        )
        self.controller.accept_decision(self.run_root, self.decision(certified_reasoning))
        self.controller.compile_report(self.run_root)
        combined = self.controller.store.load_stage_output_record(
            self.run_root,
            "report",
            "combined",
        )
        text = (self.root / combined["path"]).read_text(encoding="utf-8")
        frontstage, appendix = text.split("## ③ 后附", maxsplit=1)
        self.assertNotIn("C80", frontstage)
        self.assertNotIn("盘口60", frontstage)
        self.assertNotIn("盘面机会质量23/30", frontstage)
        self.assertIn("C80", appendix)
        self.assertIn(
            "第一层：触及99.225后，完整分档的预成交加权锚为99.9（不是实际成交价，也不是单档价），第一层预成交投影价为99.225；实际成交后按实际加权成交价重新计算并替换该投影。只有随后形成并确认新的4H结构极点",
            frontstage,
        )
        self.assertIn(
            "第二层：触及99后，完整分档的第二层预成交投影价为99；实际成交后按实际加权成交价重新计算并替换该投影。第二层只把剩余仓位止损移至实际加权成交价对应的保本损位置",
            frontstage,
        )

    def test_compatibility_lint_certifies_the_in_memory_projection(self):
        self.prepare_through_decision()
        self.controller.compile_report(self.run_root)
        combined = self.controller.store.load_stage_output_record(
            self.run_root, "report", "combined"
        )
        markdown = (self.root / combined["path"]).read_text(encoding="utf-8")
        result = run_compatibility_lint(
            markdown,
            report_filename=f"{self.date}_{self.slot}_combined.md",
            trading_date=self.date,
            slot=self.slot,
        )
        self.assertTrue(result["passed"])
        self.assertEqual(result["exit_code"], 0)

    def test_vnext_certified_report_renders_without_legacy_analysis_lock(self):
        self.prepare_through_decision()
        self.controller.compile_report(self.run_root)
        combined = self.controller.store.load_stage_output_record(
            self.run_root,
            "report",
            "combined",
        )
        result = render_canonical(
            self.root / combined["path"],
            self.date,
            self.slot,
            root=self.root,
            vnext_run_root=self.run_root,
        )
        self.assertEqual(result["status"], "success")
        docx_path = Path(result["docx_path"])
        self.assertTrue(docx_path.is_file())
        docx_path.relative_to(self.run_root / "delivery_assets")
        self.assertFalse(
            (self.root / "runtime_state" / self.date / f"render_{self.slot}.json").exists()
        )
        self.assertGreater(result["colored_runs"], 0)

    def test_shadow_compile_to_word_qa_export_auto_renders(self):
        self.prepare_through_decision()
        self.controller.compile_report(self.run_root)
        combined = self.controller.store.load_stage_output_record(
            self.run_root,
            "report",
            "combined",
        )
        self.assertFalse((self.run_root / "delivery_assets").exists())
        renderer = self.root / "pdftoppm.exe"
        renderer.write_bytes(b"binary")

        def fake_export(docx: Path, pdf: Path, **_kwargs) -> str:
            self.assertTrue(docx.is_file())
            pdf.write_bytes(
                b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\nstartxref\n0\n%%EOF\n"
            )
            return "word_com"

        def fake_pdf_render(
            pdf: Path,
            prefix: Path,
            _renderer: Path,
        ) -> list[Path]:
            self.assertTrue(pdf.is_file())
            page = prefix.parent / f"{prefix.name}-1.png"
            page.write_bytes(b"\x89PNG\r\n\x1a\npage")
            return [page]

        with patch(
            "runtime_vnext.delivery_renderer.canonical_word_qa._export_word",
            side_effect=fake_export,
        ), patch(
            "runtime_vnext.delivery_renderer.canonical_word_qa._find_pdftoppm",
            return_value=renderer,
        ), patch(
            "runtime_vnext.delivery_renderer.canonical_word_qa._render_pdf",
            side_effect=fake_pdf_render,
        ):
            prepared = prepare_run_qa(self.root, self.run_root)

        render_manifest = json.loads(
            (
                self.run_root / "delivery_assets" / "render_manifest.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(render_manifest["status"], "success")
        self.assertEqual(render_manifest["source_sha256"], combined["sha256"])
        self.assertEqual(prepared["status"], "prepared")
        self.assertEqual(prepared["report_sha256"], combined["sha256"])
        self.assertEqual(prepared["attempts"], 1)
        attempts = list(
            (self.run_root / "delivery_assets" / "word_qa").glob("attempt-*")
        )
        self.assertEqual(len(attempts), 1)

    def test_user_visible_reasoning_must_be_chinese_readable(self):
        self.controller.accept_evidence(self.run_root, self.evidence(), evidence_files_root=self.root)
        evidence = self.controller.store.load_stage_payload(self.run_root, "evidence", "evidence")
        payload = self.reasoning(evidence)
        main_claim = next(item for item in payload["claims"] if item["id"] == "claim_main")
        main_claim["conclusion"] = "wait for confirmation before execution"
        with self.assertRaises(WorkflowFailure) as caught:
            self.controller.accept_reasoning(self.run_root, payload)
        self.assertTrue(
            any(item["code"] == "claim.language" for item in caught.exception.defects)
        )

    def test_blockbeats_reasoning_count_must_match_certified_evidence(self):
        self.controller.accept_evidence(self.run_root, self.evidence(), evidence_files_root=self.root)
        evidence = self.controller.store.load_stage_payload(self.run_root, "evidence", "evidence")
        payload = self.reasoning(evidence)
        blockbeats = next(
            item for item in payload["observations"] if item["source"] == "BlockBeats"
        )
        blockbeats["metrics"]["selected_event_count"] = "1"
        with self.assertRaises(WorkflowFailure) as caught:
            self.controller.accept_reasoning(self.run_root, payload)
        self.assertTrue(
            any(
                item["code"] == "blockbeats.selected_count_drift"
                for item in caught.exception.defects
            )
        )

    def test_non_png_visual_evidence_is_rejected_before_reasoning(self):
        payload = self.evidence()
        record = payload["sources"]["Exocharts"]["artifacts"][0]
        target = self.root / record["path"]
        target.write_bytes(b"not-a-png")
        record["sha256"] = sha256_file(target)
        record["bytes"] = target.stat().st_size
        result = evaluate_evidence(payload, root=self.root)
        self.assertFalse(result.passed)
        self.assertIn("artifact.visual_invalid", {item.code for item in result.defects})

    def test_fabricated_c999_is_rejected_by_deterministic_combination(self):
        self.controller.accept_evidence(self.run_root, self.evidence(), evidence_files_root=self.root)
        evidence = self.controller.store.load_stage_payload(self.run_root, "evidence", "evidence")
        payload = self.reasoning(evidence)
        coinglass = next(item for item in payload["observations"] if item["source"] == "Coinglass")
        coinglass["metrics"]["combination_id"] = "C999"
        coinglass["visual_review"]["metrics_sha256"] = canonical_sha256(coinglass["metrics"])
        result = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertFalse(result.passed)
        self.assertIn("coinglass.combination_mismatch", {item.code for item in result.defects})

    def test_fedwatch_probability_hallucination_is_rejected(self):
        self.controller.accept_evidence(self.run_root, self.evidence(), evidence_files_root=self.root)
        evidence = self.controller.store.load_stage_payload(self.run_root, "evidence", "evidence")
        payload = self.reasoning(evidence)
        fedwatch = next(item for item in payload["observations"] if item["source"] == "FedWatch")
        fedwatch["metrics"]["current_probabilities"] = {"hold": 70, "hike_25bp": 20}
        fedwatch["visual_review"]["metrics_sha256"] = canonical_sha256(fedwatch["metrics"])
        result = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertFalse(result.passed)
        self.assertIn("fedwatch.probability_sum", {item.code for item in result.defects})

    def test_plan_c_evidence_v2_replays_raw_and_uses_structured_reasoning(self):
        evidence = self.plan_c_evidence()
        gate = evaluate_evidence(evidence, root=self.root)
        self.assertTrue(gate.passed, [(item.code, item.message) for item in gate.defects])
        self.controller.accept_evidence(
            self.run_root, evidence, evidence_files_root=self.root
        )
        certified = self.controller.store.load_stage_payload(
            self.run_root, "evidence", "evidence"
        )
        payload = self.reasoning(certified)
        fedwatch = next(
            item for item in payload["observations"] if item["source"] == "FedWatch"
        )
        fedwatch_record = next(
            record
            for record in certified["sources"]["FedWatch"]["artifacts"]
            if Path(record["path"]).name == "fedwatch.json"
        )
        normalized = json.loads(
            (self.root / fedwatch_record["path"]).read_text(encoding="utf-8")
        )
        fedwatch.clear()
        fedwatch.update(
            {
                "id": "obs_fw",
                "source": "FedWatch",
                "kind": "structured_observation",
                "observed_at": certified["sources"]["FedWatch"]["observed_at"],
                "fact": "Kalshi 仅作为 CME 技术不可用后的非等价宏观观察，不直接产生交易方向。",
                "uncertainty": "独立事件合约价格不是 CME FedWatch，也不是客观概率或交易方向。",
                "metrics": normalized["metrics"],
                "evidence_refs": [
                    record["path"]
                    for record in certified["sources"]["FedWatch"]["artifacts"]
                ],
                "structured_binding": {
                    "artifact_path": fedwatch_record["path"],
                    "artifact_sha256": fedwatch_record["sha256"],
                    "metrics_sha256": canonical_sha256(normalized["metrics"]),
                },
            }
        )
        result = self.evaluate_reasoning_candidate(certified, payload)
        self.assertTrue(result.passed, [(item.code, item.message) for item in result.defects])

    def test_cme_primary_evidence_v2_keeps_visual_reasoning_and_no_fallback(self):
        evidence = self.cme_primary_evidence()
        gate = evaluate_evidence(evidence, root=self.root)
        self.assertTrue(gate.passed, [(item.code, item.message) for item in gate.defects])
        self.controller.accept_evidence(
            self.run_root, evidence, evidence_files_root=self.root
        )
        certified = self.controller.store.load_stage_payload(
            self.run_root, "evidence", "evidence"
        )
        payload = self.reasoning(certified)
        fedwatch = next(
            item for item in payload["observations"] if item["source"] == "FedWatch"
        )
        self.assertEqual(fedwatch["kind"], "visual_judgment")
        result = self.evaluate_reasoning_candidate(certified, payload)
        self.assertTrue(result.passed, [(item.code, item.message) for item in result.defects])

    def test_plan_c_normalized_artifact_mutation_fails_independent_replay(self):
        evidence = self.plan_c_evidence()
        record = next(
            item
            for item in evidence["sources"]["FedWatch"]["artifacts"]
            if Path(item["path"]).name == "fedwatch.json"
        )
        target = self.root / record["path"]
        normalized = json.loads(target.read_text(encoding="utf-8"))
        normalized["metrics"]["current_probabilities"]["hold"] = "0.000"
        target.write_text(
            json.dumps(normalized, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        record["sha256"] = sha256_file(target)
        record["bytes"] = target.stat().st_size
        evidence["snapshot_sha256"] = evidence_snapshot_sha256(evidence)
        result = evaluate_evidence(evidence, root=self.root)
        self.assertFalse(result.passed)
        self.assertIn("fedwatch.provider_integrity", {item.code for item in result.defects})

    def test_fedwatch_outcome_key_is_closed_before_report_projection(self):
        evidence = self.evidence()
        payload = self.reasoning(evidence)
        fedwatch = next(
            item for item in payload["observations"] if item["source"] == "FedWatch"
        )
        malicious_key = "Maker委托价63960"
        fedwatch["metrics"].update(
            {
                "current_probabilities": {malicious_key: 100},
                "change_1d": {malicious_key: 0},
                "change_1w": {malicious_key: 0},
                "change_1m": {malicious_key: 0},
            }
        )
        fedwatch["visual_review"]["metrics_sha256"] = canonical_sha256(
            fedwatch["metrics"]
        )
        result = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertIn(
            "fedwatch.outcome_key_invalid",
            {item.code for item in result.defects},
        )

    def test_fedwatch_display_time_is_not_compared_with_host_clock(self):
        self.controller.accept_evidence(self.run_root, self.evidence(), evidence_files_root=self.root)
        evidence = self.controller.store.load_stage_payload(self.run_root, "evidence", "evidence")
        payload = self.reasoning(evidence)
        fedwatch = next(item for item in payload["observations"] if item["source"] == "FedWatch")
        fedwatch["metrics"]["data_as_of"] = "2026-07-14T12:50:54-05:00"
        fedwatch["visual_review"]["metrics_sha256"] = canonical_sha256(fedwatch["metrics"])
        result = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertTrue(result.passed, [item.to_dict() for item in result.defects])

    def test_farside_sign_cannot_disagree_with_certified_json(self):
        self.controller.accept_evidence(self.run_root, self.evidence(), evidence_files_root=self.root)
        evidence = self.controller.store.load_stage_payload(self.run_root, "evidence", "evidence")
        payload = self.reasoning(evidence)
        farside = next(item for item in payload["observations"] if item["source"] == "Farside")
        farside["metrics"]["flow_direction"] = "inflow"
        farside["structured_binding"]["metrics_sha256"] = canonical_sha256(farside["metrics"])
        result = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertFalse(result.passed)
        self.assertIn("farside.structured_mismatch", {item.code for item in result.defects})

    def test_exocharts_one_hour_cannot_masquerade_as_daily_baseline(self):
        self.controller.accept_evidence(self.run_root, self.evidence(), evidence_files_root=self.root)
        evidence = self.controller.store.load_stage_payload(self.run_root, "evidence", "evidence")
        payload = self.reasoning(evidence)
        exocharts = next(item for item in payload["observations"] if item["source"] == "Exocharts")
        exocharts["timeframe"] = "1H"
        result = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertFalse(result.passed)
        self.assertIn("exocharts.timeframe_drift", {item.code for item in result.defects})

    def test_exocharts_capture_profile_cannot_drift_from_user_gold(self):
        self.controller.accept_evidence(self.run_root, self.evidence(), evidence_files_root=self.root)
        evidence = self.controller.store.load_stage_payload(self.run_root, "evidence", "evidence")
        payload = self.reasoning(evidence)
        exocharts = next(item for item in payload["observations"] if item["source"] == "Exocharts")
        exocharts["metrics"]["capture_profile"]["text_type"] = "Volume"
        exocharts["visual_review"]["metrics_sha256"] = canonical_sha256(exocharts["metrics"])
        result = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertFalse(result.passed)
        self.assertIn("exocharts.capture_profile_drift", {item.code for item in result.defects})

    def test_decision_rejects_non_4h_first_defense_semantics(self):
        _, reasoning = self.prepare_through_reasoning()
        payload = self.decision(reasoning)
        payload["maker"]["defense_plan"]["first_stop_rule"] = (
            "confirmed_post_fill_1h_structural_extreme"
        )
        result = evaluate_decision(
            payload,
            reasoning=reasoning,
            run=self.controller.store.load_run(self.run_root),
            pretrade_gate=self.gate,
            root=self.root,
        )
        self.assertFalse(result.passed)
        self.assertIn(
            "defense_trigger_invalid",
            result.facts["maker_candidate_failure_codes"],
        )

    def test_decision_rejects_second_defense_without_breakeven_only_rule(self):
        _, reasoning = self.prepare_through_reasoning()
        payload = self.decision(reasoning)
        payload["maker"]["defense_plan"]["second_action"] = "reduce_position_half"
        result = evaluate_decision(
            payload,
            reasoning=reasoning,
            run=self.controller.store.load_run(self.run_root),
            pretrade_gate=self.gate,
            root=self.root,
        )
        self.assertFalse(result.passed)
        self.assertIn(
            "defense_trigger_invalid",
            result.facts["maker_candidate_failure_codes"],
        )

    def test_visual_metrics_changed_after_review_are_rejected(self):
        self.controller.accept_evidence(self.run_root, self.evidence(), evidence_files_root=self.root)
        evidence = self.controller.store.load_stage_payload(self.run_root, "evidence", "evidence")
        payload = self.reasoning(evidence)
        exocharts = next(item for item in payload["observations"] if item["source"] == "Exocharts")
        exocharts["metrics"]["delta"] = 999999
        result = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertFalse(result.passed)
        self.assertIn("visual.review_metrics_drift", {item.code for item in result.defects})

    def test_visual_parent_metric_path_cannot_cover_uncited_leaf_metrics(self):
        self.controller.accept_evidence(self.run_root, self.evidence(), evidence_files_root=self.root)
        evidence = self.controller.store.load_stage_payload(self.run_root, "evidence", "evidence")
        payload = self.reasoning(evidence)
        tradingview = next(item for item in payload["observations"] if item["source"] == "TradingView")
        tradingview["visual_citations"][0]["metric_paths"] = ["timeframes"]
        result = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertFalse(result.passed)
        codes = {item.code for item in result.defects}
        self.assertIn("visual.metric_path_unknown", codes)
        self.assertIn("visual.metric_uncited", codes)

    def test_tradingview_timeframe_metric_requires_matching_screenshot(self):
        self.controller.accept_evidence(self.run_root, self.evidence(), evidence_files_root=self.root)
        evidence = self.controller.store.load_stage_payload(self.run_root, "evidence", "evidence")
        payload = self.reasoning(evidence)
        tradingview = next(item for item in payload["observations"] if item["source"] == "TradingView")
        citation = next(
            item
            for item in tradingview["visual_citations"]
            if any(path.startswith("timeframes.1d.") for path in item["metric_paths"])
        )
        citation["evidence_ref"] = next(
            record["path"]
            for record in evidence["sources"]["TradingView"]["artifacts"]
            if str(record.get("timeframe", "")).lower() == "4h"
        )
        result = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertFalse(result.passed)
        self.assertIn(
            "visual.timeframe_citation_mismatch",
            {item.code for item in result.defects},
        )

    def test_chart_score_control_uses_typed_basis_not_rationale_keywords(self):
        self.controller.accept_evidence(self.run_root, self.evidence(), evidence_files_root=self.root)
        evidence = self.controller.store.load_stage_payload(self.run_root, "evidence", "evidence")
        payload = self.reasoning(evidence)
        tradingview = next(item for item in payload["observations"] if item["source"] == "TradingView")
        tradingview["metrics"]["chart_component_rationales"]["chart.support_resistance"] = (
            "十五分钟只用于入场精度，不参与前三周期的支撑压力评分。"
        )
        tradingview["visual_review"]["metrics_sha256"] = canonical_sha256(tradingview["metrics"])
        result = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertTrue(result.passed, [(item.code, item.path) for item in result.defects])

        tradingview["metrics"]["chart_scoring_basis"]["included_timeframes"].append(
            "15m"
        )
        tradingview["visual_review"]["metrics_sha256"] = canonical_sha256(
            tradingview["metrics"]
        )
        result = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertFalse(result.passed)
        self.assertIn(
            "tradingview.chart_scoring_basis",
            {item.code for item in result.defects},
        )

    def test_decision_cannot_rewrite_certified_semantic_scores(self):
        _, reasoning = self.prepare_through_reasoning()
        payload = self.decision(reasoning)
        payload["maker"]["orderflow_score"] = 55
        payload["maker"]["orderflow_scorecard"]["score"] = 55
        payload["maker"]["total_score"] = 78
        with self.assertRaises(WorkflowFailure) as caught:
            self.controller.accept_decision(self.run_root, payload)
        self.assertTrue(
            any(
                item["code"] == "score.orderflow_semantic_drift"
                for item in caught.exception.defects
            )
        )

    def test_decision_rejects_single_entry_maker_plan(self):
        _, reasoning = self.prepare_through_reasoning()
        payload = self.decision(reasoning)
        payload["maker"]["risk_plan"]["entries"] = [100.0]
        payload["maker"]["risk_plan"]["entry_allocations_pct"] = [100]
        with self.assertRaises(WorkflowFailure) as caught:
            self.controller.accept_decision(self.run_root, payload)
        self.assertTrue(
            any(
                item["code"] == "risk.entry_range_required"
                for item in caught.exception.defects
            )
        )

    def test_decision_rejects_numerically_duplicate_entry_levels(self):
        _, reasoning = self.prepare_through_reasoning()
        payload = self.decision(reasoning)
        payload["maker"]["risk_plan"]["entries"] = [100, 100.0]
        payload["maker"]["entry_reach_probability_basis"]["reference_entry"] = 100
        payload["maker"]["entry_reach_probability_basis"]["entry_distance"] = 3
        with self.assertRaises(WorkflowFailure) as caught:
            self.controller.accept_decision(self.run_root, payload)
        self.assertIn(
            "risk.entry_levels_duplicate",
            {item["code"] for item in caught.exception.defects},
        )

    def test_decision_rejects_missing_tp2_and_wrong_position_ledger(self):
        _, reasoning = self.prepare_through_reasoning()
        payload = self.decision(reasoning)
        payload["maker"]["risk_plan"].pop("tp2")
        payload["maker"]["risk_plan"]["tp1_close_pct"] = 100
        with self.assertRaises(WorkflowFailure) as caught:
            self.controller.accept_decision(self.run_root, payload)
        codes = {item["code"] for item in caught.exception.defects}
        self.assertIn("risk.schema_fields", codes)
        self.assertIn("risk.tp1_close_pct", codes)
        self.assertIn("risk.values_invalid", codes)

    def test_decision_separates_pre_fill_cancel_from_post_fill_stop(self):
        _, reasoning = self.prepare_through_reasoning()
        payload = self.decision(reasoning)
        payload["maker"]["risk_plan"]["cancel_before_fill"] = 100.35
        payload["maker"]["order_lifecycle"] = {
            "schema_version": "maker-order-lifecycle-v1",
            "state": "entry_before_cancel",
            "legal_fill_path_exists": True,
            "legal_cancel_path_exists": False,
            "fill_probability": None,
            "fill_probability_applicability": "not_applicable_invalid_prefill_cancel",
            "reason_code": "entry_before_cancel",
        }
        payload["maker"]["plan_constructible"] = False
        payload["maker"]["plan_constructibility"].update(
            {
                "status": "not_constructible",
                "primary_reason_code": "order_lifecycle_invalid",
                "failure_codes": ["order_lifecycle_invalid"],
            }
        )
        payload["maker"]["plan_state"] = "observe"
        payload["maker"]["execution_action"] = "observe"
        payload["maker"]["order_transition_action"] = "observe"
        payload["continuity_contract"]["current_plan"].update(
            {
                "action": "observe",
                "new_order_created": False,
                "executable_order_count_after": 0,
                "reason": "撤单价只有在入场成交后才会触达，因此候选只观察。",
            }
        )
        result = evaluate_decision(
            payload,
            reasoning=reasoning,
            run=self.controller.store.load_run(self.run_root),
            pretrade_gate=self.gate,
            root=self.root,
        )
        self.assertTrue(result.passed, result.to_dict())
        self.assertEqual(
            result.facts["maker_candidate_failure_codes"],
            ["order_lifecycle_invalid"],
        )

    def test_decision_gate_rejects_cancel_that_preempts_every_entry(self):
        _, reasoning = self.prepare_through_reasoning()
        payload = self.decision(reasoning)
        payload["maker"]["risk_plan"]["cancel_before_fill"] = 98
        payload["maker"]["order_lifecycle"] = {
            "schema_version": "maker-order-lifecycle-v1",
            "state": "cancel_blocks_all_entries",
            "legal_fill_path_exists": False,
            "legal_cancel_path_exists": True,
            "fill_probability": None,
            "fill_probability_applicability": "not_applicable_no_legal_fill_path",
            "reason_code": "cancel_blocks_all_entries",
        }
        payload["maker"]["plan_constructible"] = False
        payload["maker"]["plan_constructibility"].update(
            {
                "status": "not_constructible",
                "primary_reason_code": "order_lifecycle_invalid",
                "failure_codes": ["order_lifecycle_invalid"],
            }
        )
        payload["maker"]["plan_state"] = "observe"
        payload["maker"]["execution_action"] = "observe"
        payload["maker"]["order_transition_action"] = "observe"
        payload["continuity_contract"]["current_plan"].update(
            {
                "action": "observe",
                "new_order_created": False,
                "executable_order_count_after": 0,
                "reason": "撤单价会先于所有入场档触发，候选没有可成交路径。",
            }
        )
        result = evaluate_decision(
            payload,
            reasoning=reasoning,
            run=self.controller.store.load_run(self.run_root),
            pretrade_gate=self.gate,
            root=self.root,
        )
        self.assertTrue(result.passed, result.to_dict())
        self.assertEqual(
            result.facts["maker_candidate_failure_codes"],
            ["order_lifecycle_invalid"],
        )

    def test_ladder_defense_uses_weighted_fill_formulas_and_compiles(self):
        _, reasoning = self.prepare_through_reasoning()
        payload = self.decision(reasoning)
        payload["maker"]["risk_plan"].update({
            "entries": [100.0, 99.8],
            "entry_allocations_pct": [50, 50],
            "stop": 100.35,
            "tp1": 98.0,
            "tp2": 97.0,
            "tp1_close_pct": 50,
            "tp2_close_pct": 50,
            "leverage": 5,
            "cancel_before_fill": 96.5,
        })
        payload["maker"]["defense_plan"] = self.exact_prefill_defense_plan(
            [100.0, 99.8], [50, 50], 100.35
        )
        self.controller.accept_decision(self.run_root, payload)
        self.controller.compile_report(self.run_root)
        combined = self.controller.store.load_stage_output_record(
            self.run_root,
            "report",
            "combined",
        )
        text = (self.root / combined["path"]).read_text(encoding="utf-8")
        self.assertIn("入场区间99.8–100分档做空", text)
        self.assertEqual(text.count("**Maker成交情景**"), 3)
        self.assertIn("第一层：触及99.225后", text)
        self.assertIn("第二层：触及99后", text)
        self.assertIn("完整分档的预成交加权锚为99.9", text)

    def test_compiled_risk_scenarios_round_weighted_entry_for_humans_only(self):
        _, reasoning = self.prepare_through_reasoning()
        payload = self.decision(reasoning)
        payload["maker"]["risk_plan"].update({
            "entries": [100.0, 99.95, 99.83],
            "entry_allocations_pct": [30, 40, 30],
            "stop": 100.35,
            "tp1": 97.5,
            "tp2": 96.5,
            "tp1_close_pct": 50,
            "tp2_close_pct": 50,
            "leverage": 5,
            "cancel_before_fill": 96.0,
        })
        payload["maker"]["defense_plan"] = self.exact_prefill_defense_plan(
            [100.0, 99.95, 99.83], [30, 40, 30], 100.35
        )
        payload["maker"]["entry_reach_probability_basis"].update(
            {
                "reference_entry": 99.83,
                "entry_distance": 2.83,
            }
        )
        self.controller.accept_decision(self.run_root, payload)
        self.controller.compile_report(self.run_root)
        combined = self.controller.store.load_stage_output_record(
            self.run_root,
            "report",
            "combined",
        )
        text = (self.root / combined["path"]).read_text(encoding="utf-8")
        self.assertIn("加权入场99.93", text)
        risk_scenario_text = "\n".join(
            line
            for line in text.splitlines()
            if line.startswith("**Maker成交情景**")
        )
        self.assertNotIn("99.885714", risk_scenario_text)
        self.assertEqual(text.count("**Maker成交情景**"), 7)

    def test_stale_source_time_is_rejected_at_evidence_gate(self):
        payload = self.evidence()
        payload["sources"]["Coinglass"]["observed_at"] = "2026-07-13T01:00:00+08:00"
        result = evaluate_evidence(payload, root=self.root)
        self.assertFalse(result.passed)
        self.assertIn("source.capture_time_drift", {item.code for item in result.defects})

    def test_evidence_file_drift_blocks_reasoning_without_recapture_loop(self):
        self.controller.accept_evidence(self.run_root, self.evidence(), evidence_files_root=self.root)
        evidence = self.controller.store.load_stage_payload(self.run_root, "evidence", "evidence")
        payload = self.reasoning(evidence)
        blockbeats = self.root / evidence["sources"]["BlockBeats"]["artifacts"][0]["path"]
        blockbeats.write_text("changed", encoding="utf-8")
        with self.assertRaises(WorkflowFailure) as caught:
            self.controller.accept_reasoning(self.run_root, payload)
        self.assertEqual(caught.exception.failure_class, FailureClass.EVIDENCE_INTEGRITY)
        self.assertTrue(any(item["code"] == "binding.evidence_drift" for item in caught.exception.defects))
        self.assertEqual(self.controller.status(self.run_root)["next_stage"], "evidence")

    def test_delivery_retry_does_not_invalidate_reasoning_or_report(self):
        self.prepare_through_decision()
        self.controller.compile_report(self.run_root)
        before = copy.deepcopy(self.controller.store.load_checkpoint(self.run_root)["completed"])
        broken = self.delivery(unique_page_count=2)
        with self.assertRaises(WorkflowFailure) as caught:
            self.controller.accept_delivery(self.run_root, broken)
        self.assertEqual(caught.exception.failure_class, FailureClass.DELIVERY_INTEGRITY)
        status = self.controller.status(self.run_root)
        self.assertEqual(status["next_stage"], "delivery")
        after = self.controller.store.load_checkpoint(self.run_root)["completed"]
        for stage in ("evidence", "reasoning", "decision", "report"):
            self.assertEqual(after[stage], before[stage])
        self.controller.accept_delivery(self.run_root, self.delivery())
        status = self.controller.status(self.run_root)
        self.assertEqual(status["attempt_counts"]["delivery"], 2)
        self.assertEqual(status["status"], "complete")

    def test_shadow_delivery_rejects_missing_local_qa(self):
        self.prepare_through_decision()
        self.controller.compile_report(self.run_root)
        payload = self.shadow_delivery()
        payload["render"].pop("word_qa")
        with self.assertRaises(WorkflowFailure) as caught:
            self.controller.accept_shadow_delivery(self.run_root, payload)
        self.assertEqual(caught.exception.failure_class, FailureClass.DELIVERY_INTEGRITY)
        self.assertTrue(
            any(item["code"] == "delivery.artifact_missing" for item in caught.exception.defects)
        )
        self.assertEqual(self.controller.status(self.run_root)["next_stage"], "delivery")

    def test_shadow_delivery_rejects_notion_publish_claim(self):
        self.prepare_through_decision()
        self.controller.compile_report(self.run_root)
        payload = self.shadow_delivery()
        payload["publish"]["manifest"] = self.delivery()["publish"]["manifest"]
        expected_report = self.controller.store.load_checkpoint(self.run_root)["completed"]["report"]["outputs"]["combined"]
        result = evaluate_shadow_delivery(
            payload,
            root=self.root,
            run=self.controller.store.load_run(self.run_root),
            expected_report=expected_report,
        )
        self.assertFalse(result.passed)
        self.assertIn("delivery.shadow_publish_claim", {item.code for item in result.defects})

    def test_shadow_run_rejects_production_delivery_before_attempt(self):
        with self.assertRaisesRegex(
            WorkflowFailure,
            "production delivery is forbidden",
        ):
            self.controller.accept_delivery(self.run_root, {})
        self.assertEqual(self.controller.store.attempt_count(self.run_root, "delivery"), 0)

    def test_production_run_rejects_local_only_delivery_before_attempt(self):
        with self.assertRaisesRegex(
            WorkflowFailure,
            "shadow delivery is forbidden",
        ):
            self.controller.accept_shadow_delivery(self.run_root, {})
        self.assertEqual(self.controller.store.attempt_count(self.run_root, "delivery"), 0)

    def test_shadow_delivery_malformed_sections_return_complete_defect_set(self):
        result = evaluate_shadow_delivery(
            {
                "schema_version": "shadow-delivery-model-v1",
                "render": [],
                "cards": [],
                "publish": [],
            },
            root=self.root,
            run=self.controller.store.load_run(self.run_root),
        )
        self.assertFalse(result.passed)
        codes = {item.code for item in result.defects}
        self.assertIn("delivery.artifact_missing", codes)
        self.assertIn("delivery.cards_missing", codes)
        self.assertIn("delivery.shadow_publish_boundary", codes)

    def test_production_delivery_still_requires_notion_publish_and_readback(self):
        self.prepare_through_decision()
        self.controller.compile_report(self.run_root)
        payload = self.shadow_delivery()
        payload["schema_version"] = "delivery-model-v1"
        expected_report = self.controller.store.load_checkpoint(self.run_root)["completed"]["report"]["outputs"]["combined"]
        result = evaluate_delivery(
            payload,
            root=self.root,
            run=self.controller.store.load_run(self.run_root),
            expected_report=expected_report,
        )
        self.assertFalse(result.passed)
        self.assertIn("delivery.artifact_missing", {item.code for item in result.defects})
        self.assertIn("delivery.publish_manifest", {item.code for item in result.defects})
        self.assertIn("delivery.notion_verification", {item.code for item in result.defects})

    def test_delivery_cannot_switch_to_an_uncertified_report(self):
        self.prepare_through_decision()
        self.controller.compile_report(self.run_root)
        delivery = self.delivery()
        delivery["report"] = delivery["render"]["docx"]
        with self.assertRaises(WorkflowFailure) as caught:
            self.controller.accept_delivery(self.run_root, delivery)
        self.assertEqual(caught.exception.failure_class, FailureClass.DELIVERY_INTEGRITY)
        self.assertTrue(any(item["code"] == "delivery.report_record_drift" for item in caught.exception.defects))

    def test_delivery_cannot_switch_to_uncertified_blockbeats_cards(self):
        self.prepare_through_decision()
        self.controller.compile_report(self.run_root)
        delivery = self.delivery()
        delivery["cards"]["images"][0] = delivery["cards"]["images"][1]
        with self.assertRaises(WorkflowFailure) as caught:
            self.controller.accept_delivery(self.run_root, delivery)
        self.assertTrue(any(item["code"] == "delivery.cards_drift" for item in caught.exception.defects))

    def test_delivery_word_qa_v2_rejects_wrong_identity_and_cross_run_reuse(self):
        self.prepare_through_decision()
        self.controller.compile_report(self.run_root)
        run = self.controller.store.load_run(self.run_root)
        report_outputs = self.controller.store.load_checkpoint(self.run_root)["completed"]["report"]["outputs"]
        expected_cards = {
            name: report_outputs[name]
            for name in ("cards_spec", "card_1", "card_2", "card_3")
        }
        cases = (
            ("wrong_run", lambda qa: qa.__setitem__("run_id", "run-wrong-owner")),
            ("wrong_date", lambda qa: qa.__setitem__("trading_date", "2026-07-14")),
            ("wrong_slot", lambda qa: qa.__setitem__("slot", "evening")),
            (
                "cross_run_reuse",
                lambda qa: qa.update(
                    {"run_id": "run-foreign-sample", "run_sha256": "b" * 64}
                ),
            ),
        )
        for label, mutate in cases:
            with self.subTest(label=label):
                delivery = self.delivery()
                self.rewrite_delivery_word_qa(delivery, mutate)
                result = evaluate_delivery(
                    delivery,
                    root=self.root,
                    run=run,
                    expected_report=report_outputs["combined"],
                    expected_cards=expected_cards,
                )
                self.assertFalse(result.passed)
                self.assertIn(
                    "delivery.word_identity",
                    {item.code for item in result.defects},
                )

    def test_delivery_gate_rejects_cross_run_word_qa_page_evidence(self):
        self.prepare_through_decision()
        self.controller.compile_report(self.run_root)
        run = self.controller.store.load_run(self.run_root)
        report_outputs = self.controller.store.load_checkpoint(self.run_root)[
            "completed"
        ]["report"]["outputs"]
        expected_cards = {
            name: report_outputs[name]
            for name in ("cards_spec", "card_1", "card_2", "card_3")
        }
        delivery = self.delivery()
        qa_record = delivery["render"]["word_qa"]
        qa_path = self.root / qa_record["path"]
        qa = json.loads(qa_path.read_text(encoding="utf-8"))
        foreign_attempt = (
            self.root
            / "runtime_state_vnext"
            / self.date
            / self.slot
            / "run-foreign-sample"
            / "delivery_assets"
            / "word_qa"
            / "attempt-001-deadbeef"
        )
        foreign_attempt.mkdir(parents=True)
        source_pdf = self.root / qa["pdf"]["path"]
        foreign_pdf = foreign_attempt / f"{self.date}_{self.slot}_render.pdf"
        foreign_pdf.write_bytes(source_pdf.read_bytes())
        qa["pdf"] = self.file_record(
            foreign_pdf.relative_to(self.root).as_posix(),
            foreign_pdf.read_bytes(),
        )
        qa["pdf_sha256"] = qa["pdf"]["sha256"]
        delivery["render"]["pdf"] = qa["pdf"]
        foreign_pages = []
        for page in qa["page_images"]:
            source_page = self.root / page["path"]
            foreign_page = foreign_attempt / source_page.name
            foreign_page.write_bytes(source_page.read_bytes())
            record = self.file_record(
                foreign_page.relative_to(self.root).as_posix(),
                foreign_page.read_bytes(),
            )
            record["page"] = page["page"]
            foreign_pages.append(record)
        qa["page_images"] = foreign_pages
        qa_path.write_text(
            json.dumps(qa, ensure_ascii=False),
            encoding="utf-8",
        )
        qa_record["sha256"] = sha256_file(qa_path)
        qa_record["bytes"] = qa_path.stat().st_size

        result = evaluate_delivery(
            delivery,
            root=self.root,
            run=run,
            expected_report=report_outputs["combined"],
            expected_cards=expected_cards,
        )
        self.assertFalse(result.passed)
        self.assertIn(
            "delivery.word_run_locality",
            {item.code for item in result.defects},
        )

    def test_delivery_word_qa_v2_requires_review_backend_and_full_page_confirmation(self):
        self.prepare_through_decision()
        self.controller.compile_report(self.run_root)
        run = self.controller.store.load_run(self.run_root)
        report_outputs = self.controller.store.load_checkpoint(self.run_root)["completed"]["report"]["outputs"]
        expected_cards = {
            name: report_outputs[name]
            for name in ("cards_spec", "card_1", "card_2", "card_3")
        }
        cases = (
            ("missing_reviewer", "delivery.word_review", lambda qa: qa.pop("reviewer")),
            ("missing_reviewed_at", "delivery.word_review", lambda qa: qa.pop("reviewed_at")),
            (
                "naive_reviewed_at",
                "delivery.word_review",
                lambda qa: qa.__setitem__("reviewed_at", "2026-07-13T08:27:00"),
            ),
            (
                "unapproved_backend",
                "delivery.word_backend",
                lambda qa: qa.__setitem__("backend", "libreoffice"),
            ),
            (
                "partial_page_review",
                "delivery.word_pages",
                lambda qa: qa.__setitem__("inspected_pages", []),
            ),
            (
                "legacy_schema",
                "delivery.word_manifest",
                lambda qa: qa.__setitem__("schema_version", "word-qa-vnext-v1"),
            ),
            (
                "wrong_review_checklist_version",
                "delivery.word_review_checklist",
                lambda qa: qa.__setitem__(
                    "review_checklist_version", "word-qa-semantic-review-v0"
                ),
            ),
            (
                "missing_review_checklist_key",
                "delivery.word_review_checklist",
                lambda qa: qa["review_checklist"].pop(
                    "arabic_price_digits_preserved"
                ),
            ),
            (
                "false_review_checklist_value",
                "delivery.word_review_checklist",
                lambda qa: qa["review_checklist"].__setitem__(
                    "critical_price_blocks_not_split", False
                ),
            ),
        )
        for label, expected_code, mutate in cases:
            with self.subTest(label=label):
                delivery = self.delivery()
                self.rewrite_delivery_word_qa(delivery, mutate)
                result = evaluate_delivery(
                    delivery,
                    root=self.root,
                    run=run,
                    expected_report=report_outputs["combined"],
                    expected_cards=expected_cards,
                )
                self.assertFalse(result.passed)
                self.assertIn(expected_code, {item.code for item in result.defects})

    def test_delivery_rejects_hash_valid_non_png_page_evidence(self):
        self.prepare_through_decision()
        self.controller.compile_report(self.run_root)
        delivery = self.delivery()
        qa_record = delivery["render"]["word_qa"]
        qa_path = self.root / qa_record["path"]
        qa_payload = json.loads(qa_path.read_text(encoding="utf-8"))
        page_record = qa_payload["page_images"][0]
        page_path = self.root / page_record["path"]
        page_path.write_bytes(b"not-a-png")
        page_record["sha256"] = sha256_file(page_path)
        page_record["bytes"] = page_path.stat().st_size
        qa_path.write_text(json.dumps(qa_payload), encoding="utf-8")
        qa_record["sha256"] = sha256_file(qa_path)
        qa_record["bytes"] = qa_path.stat().st_size
        expected_report = self.controller.store.load_checkpoint(self.run_root)["completed"]["report"]["outputs"]["combined"]
        result = evaluate_delivery(
            delivery,
            root=self.root,
            run=self.controller.store.load_run(self.run_root),
            expected_report=expected_report,
        )
        self.assertFalse(result.passed)
        self.assertIn("delivery.page_image_format", {item.code for item in result.defects})

    def test_report_failure_retries_report_only(self):
        self.prepare_through_decision()
        before = copy.deepcopy(self.controller.store.load_checkpoint(self.run_root)["completed"])
        with patch("runtime_vnext.controller.compile_projected_report", side_effect=ValueError("format defect")):
            with self.assertRaises(WorkflowFailure) as caught:
                self.controller.compile_report(self.run_root)
        self.assertEqual(caught.exception.failure_class, FailureClass.COMPILATION)
        status = self.controller.status(self.run_root)
        self.assertEqual(status["next_stage"], "report")
        after = self.controller.store.load_checkpoint(self.run_root)["completed"]
        for stage in ("evidence", "reasoning", "decision"):
            self.assertEqual(after[stage], before[stage])
        self.controller.compile_report(self.run_root)
        self.assertEqual(self.controller.status(self.run_root)["attempt_counts"]["report"], 2)

    def test_second_report_failure_requires_manual_review(self):
        self.prepare_through_decision()
        with patch("runtime_vnext.controller.compile_projected_report", side_effect=ValueError("format defect")):
            with self.assertRaises(WorkflowFailure) as first:
                self.controller.compile_report(self.run_root)
            with self.assertRaises(WorkflowFailure) as second:
                self.controller.compile_report(self.run_root)
        self.assertEqual(first.exception.failure_class, FailureClass.COMPILATION)
        self.assertEqual(second.exception.failure_class, FailureClass.MANUAL_REVIEW)
        self.assertEqual(self.controller.status(self.run_root)["status"], "needs_review")

    def test_second_delivery_failure_requires_manual_review(self):
        self.prepare_through_decision()
        self.controller.compile_report(self.run_root)
        broken = self.delivery(unique_page_count=2)
        with self.assertRaises(WorkflowFailure) as first:
            self.controller.accept_delivery(self.run_root, broken)
        with self.assertRaises(WorkflowFailure) as second:
            self.controller.accept_delivery(self.run_root, broken)
        self.assertEqual(first.exception.failure_class, FailureClass.DELIVERY_INTEGRITY)
        self.assertEqual(second.exception.failure_class, FailureClass.MANUAL_REVIEW)
        self.assertEqual(self.controller.status(self.run_root)["status"], "needs_review")

    def test_fresh_controller_can_compile_from_sealed_artifacts_only(self):
        self.prepare_through_decision()
        fresh_controller = RunController(self.root)
        fresh_controller.compile_report(self.run_root)
        report = fresh_controller.store.load_stage_payload(
            self.run_root,
            "report",
            "canonical_report",
        )
        contract = load_presentation_contract(self.root)
        depth = evaluate_human_reasoning_depth(report, contract=contract)
        combined = fresh_controller.store.load_stage_output_record(
            self.run_root,
            "report",
            "combined",
        )
        markdown = (self.root / combined["path"]).read_text(encoding="utf-8")
        template = evaluate_gold_template_fidelity(markdown, contract=contract)
        self.assertTrue(depth["passed"])
        self.assertTrue(template["passed"])
        self.assertEqual(depth["facts"]["proof_block_count"], 10)

    def test_report_product_gates_return_complete_defect_sets(self):
        self.prepare_through_decision()
        fresh_controller = RunController(self.root)
        fresh_controller.compile_report(self.run_root)
        report = fresh_controller.store.load_stage_payload(self.run_root, "report", "canonical_report")
        contract = load_presentation_contract(self.root)
        broken = copy.deepcopy(report)
        broken["audit"]["reasoning_proof_blocks"] = {}
        broken["audit"]["sources"].pop("Farside")
        depth = evaluate_human_reasoning_depth(broken, contract=contract)
        self.assertFalse(depth["passed"])
        self.assertGreaterEqual(len(depth["defects"]), 2)
        template = evaluate_gold_template_fidelity(
            "## ① 正文\n#### 补充判断｜主账户\nraw_metric_key abc_def " + "a" * 64,
            contract=contract,
        )
        self.assertFalse(template["passed"])
        self.assertGreaterEqual(len(template["defects"]), 3)

    def test_display_contract_rejects_deleted_business_mirrors(self):
        contract = load_presentation_contract(self.root)
        contract["retry_policy"] = {"maximum_failed_attempts": 2}
        with self.assertRaisesRegex(ValueError, "business mirrors"):
            certify_presentation_contract(contract)

    def test_third_reasoning_failure_requires_manual_review(self):
        self.assertEqual(DEFAULT_AUTOMATIC_ATTEMPT_LIMIT, 2)
        self.assertEqual(AUTOMATIC_ATTEMPT_LIMIT_BY_STAGE, {"reasoning": 3})
        self.controller.accept_evidence(self.run_root, self.evidence(), evidence_files_root=self.root)
        evidence = self.controller.store.load_stage_payload(self.run_root, "evidence", "evidence")
        broken = self.reasoning(evidence)
        broken["claims"][-1]["support_ids"] = ["future_claim"]
        with self.assertRaises(WorkflowFailure) as first:
            self.controller.accept_reasoning(self.run_root, broken)
        self.assertEqual(first.exception.failure_class, FailureClass.REASONING_CONSISTENCY)
        with self.assertRaises(WorkflowFailure) as second:
            self.controller.accept_reasoning(self.run_root, broken)
        self.assertEqual(second.exception.failure_class, FailureClass.REASONING_CONSISTENCY)
        self.assertEqual(self.controller.status(self.run_root)["status"], "retryable_failure")
        self.assertEqual(self.controller.status(self.run_root)["next_stage"], "reasoning")
        with self.assertRaises(WorkflowFailure) as third:
            self.controller.accept_reasoning(self.run_root, broken)
        self.assertEqual(third.exception.failure_class, FailureClass.MANUAL_REVIEW)
        self.assertEqual(self.controller.status(self.run_root)["status"], "needs_review")
        with self.assertRaisesRegex(RuntimeError, "manual review authorization"):
            self.controller.accept_reasoning(self.run_root, broken)
        authorization = {
            "schema_version": "manual-review-authorization-v1",
            "approved": True,
            "run_id": "run-test",
            "trading_date": self.date,
            "slot": self.slot,
            "retry_stage": "reasoning",
            "reason": "人工确认可在相同证据和方法合同下修正推理结构",
            "reviewer_reference": "user",
            "approval_reference": "codex-task-test",
            "reviewed_at": "2026-07-13T08:00:00+08:00",
        }
        authorization["manifest_sha256"] = canonical_sha256(authorization)
        self.controller.authorize_manual_review(self.run_root, authorization)
        status = self.controller.status(self.run_root)
        self.assertEqual(status["status"], "running")
        self.assertEqual(status["next_stage"], "reasoning")

    def test_second_decision_failure_requires_manual_review(self):
        _, reasoning = self.prepare_through_reasoning()
        broken = self.decision(reasoning)
        broken["maker"]["winrate_rubric"]["adjustments"][0]["delta"] = -3
        with self.assertRaises(WorkflowFailure) as first:
            self.controller.accept_decision(self.run_root, broken)
        with self.assertRaises(WorkflowFailure) as second:
            self.controller.accept_decision(self.run_root, broken)
        self.assertEqual(first.exception.failure_class, FailureClass.RISK_EXECUTION)
        self.assertEqual(second.exception.failure_class, FailureClass.MANUAL_REVIEW)
        self.assertEqual(self.controller.status(self.run_root)["status"], "needs_review")

    def test_tampered_failure_record_cannot_drive_manual_review_count(self):
        self.controller.accept_evidence(self.run_root, self.evidence(), evidence_files_root=self.root)
        evidence = self.controller.store.load_stage_payload(self.run_root, "evidence", "evidence")
        broken = self.reasoning(evidence)
        broken["claims"][-1]["support_ids"] = ["future_claim"]
        with self.assertRaises(WorkflowFailure):
            self.controller.accept_reasoning(self.run_root, broken)
        failure_path = self.run_root / "reasoning" / "attempt-001" / "failure.json"
        failure = json.loads(failure_path.read_text(encoding="utf-8"))
        failure["failure_class"] = FailureClass.COMPILATION.value
        failure_path.write_text(json.dumps(failure), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "failure record is invalid"):
            self.controller.store.failure_count(
                self.run_root,
                "reasoning",
                failure_class=FailureClass.REASONING_CONSISTENCY.value,
            )

    def test_hash_valid_failure_record_with_wrong_stage_is_rejected(self):
        self.controller.accept_evidence(self.run_root, self.evidence(), evidence_files_root=self.root)
        evidence = self.controller.store.load_stage_payload(self.run_root, "evidence", "evidence")
        broken = self.reasoning(evidence)
        broken["claims"][-1]["support_ids"] = ["future_claim"]
        with self.assertRaises(WorkflowFailure):
            self.controller.accept_reasoning(self.run_root, broken)
        failure_path = self.run_root / "reasoning" / "attempt-001" / "failure.json"
        failure = json.loads(failure_path.read_text(encoding="utf-8"))
        failure["stage"] = "decision"
        failure.pop("failure_sha256")
        failure["failure_sha256"] = canonical_sha256(failure)
        failure_path.write_text(json.dumps(failure), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "failure record is invalid"):
            self.controller.store.failure_count(self.run_root, "reasoning")

    def test_a4r2_seventy_requires_native_presealed_proof_not_self_attestation(self):
        evidence = self.evidence()
        payload = self.reasoning(evidence)
        observations = {item["source"]: item for item in payload["observations"]}
        coinglass = observations["Coinglass"]["metrics"]
        coinglass.update(
            {
                "price_direction": "down",
                "cvd_direction": "up",
                "oi_direction": "up",
                "funding_direction": "up",
                "funding_sign": "positive",
                "combination_id": "C19",
                "effect_divergence": {
                    "cvd_break": "higher_high",
                    "price_confirmation": "not_confirmed",
                    "interpretation": "bearish",
                },
                "price_break_status": "new_low_or_breakdown",
                "oi_price_context": "new_short_expansion",
                "main_triad_direction": "bearish",
                "main_triad_rationale": "价格下破而CVD创新高且OI扩张，形成同一枢轴的看跌背离主判。",
                "funding_effect": "strengthen",
                "final_direction": "bearish",
            }
        )
        observations["Coinglass"]["visual_review"]["metrics_sha256"] = canonical_sha256(
            coinglass
        )
        orderflow = next(
            item
            for item in payload["claims"]
            if item["claim_type"] == "orderflow_interpretation"
        )
        orderflow["score_assessment"] = {
            "score": 70,
            "extreme_confirmed": True,
            "rationale": "C19同锚背离、OI语义、资金费率修正、足迹确认、Maker反证与失效路径全部闭环。",
        }

        self_attested = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertIn(
            "orderflow.extreme_unproven",
            {item.code for item in self_attested.defects},
        )

        conservative = copy.deepcopy(payload)
        conservative_orderflow = next(
            item
            for item in conservative["claims"]
            if item["claim_type"] == "orderflow_interpretation"
        )
        conservative_orderflow["score_assessment"].update(
            {"score": 60, "extreme_confirmed": False}
        )
        conservative_result = self.evaluate_reasoning_candidate(evidence, conservative)
        self.assertTrue(conservative_result.passed, conservative_result.to_dict())

        unproven = copy.deepcopy(payload)
        next(
            item
            for item in unproven["observations"]
            if item["source"] == "Exocharts"
        )["metrics"]["cross_check_result"] = "weaken"
        unproven["methodology"]["footprint_cross_check"]["relationship"] = "weaken"
        rejected = self.evaluate_reasoning_candidate(evidence, unproven)
        self.assertIn(
            "orderflow.extreme_unproven",
            {item.code for item in rejected.defects},
        )

    def test_a4r2_seventy_cannot_be_enabled_by_policy_flag_alone(self):
        policy = copy.deepcopy(
            load_scoring_policy(root=self.root)["maker_score"]["orderflow"]
        )
        policy["extreme_confirmation"]["production_enabled"] = True
        self.assertEqual(
            [
                "native structured extreme proof validator is not implemented; cap at 60"
            ],
            _extreme_proof_failures(orderflow_policy=policy),
        )

    def test_a4r2_exocharts_contradiction_cannot_flip_coinglass_direction(self):
        evidence = self.evidence()
        payload = self.reasoning(evidence)
        next(
            item
            for item in payload["observations"]
            if item["source"] == "Exocharts"
        )["metrics"]["cross_check_result"] = "contradict"
        payload["methodology"]["footprint_cross_check"]["relationship"] = "contradict"
        orderflow = next(
            item
            for item in payload["claims"]
            if item["claim_type"] == "orderflow_interpretation"
        )
        orderflow["direction"] = "long"
        orderflow["conclusion"] = "足迹出现反证后把Coinglass偏空主判直接翻为做多"
        rejected = self.evaluate_reasoning_candidate(evidence, payload)
        codes = {item.code for item in rejected.defects}
        self.assertIn("orderflow.direction_drift", codes)

    def test_a4r2_cannot_do_cannot_be_reused_as_scenario_input(self):
        evidence = self.evidence()
        payload = self.reasoning(evidence)
        maker_invalidation = next(
            item
            for item in payload["scenario_tree"]
            if item["id"] == "scenario_maker_invalidation"
        )
        maker_invalidation["owner_claim_id"] = "claim_cannot"
        rejected = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertIn(
            "cannot_do.used_as_scenario_input",
            {item.code for item in rejected.defects},
        )

    def test_a4r2_honest_risk_math_failure_is_business_observe(self):
        _, reasoning = self.prepare_through_reasoning()
        payload = self.decision(reasoning)
        payload["maker"]["risk_plan"]["entries"] = [100.0, 100.0]
        payload["maker"]["entry_reach_probability_basis"].update(
            {
                "reference_entry": 100.0,
                "entry_distance": 3.0,
                "reach_direction": "up_to_entry",
            }
        )
        payload["maker"]["defense_plan"] = {}
        payload["maker"]["plan_constructible"] = False
        payload["maker"]["plan_constructibility"].update(
            {
                "status": "not_constructible",
                "primary_reason_code": "risk_math_invalid",
                "failure_codes": ["risk_math_invalid"],
            }
        )
        payload["maker"]["plan_state"] = "observe"
        payload["maker"]["execution_action"] = "observe"
        payload["maker"]["order_transition_action"] = "observe"
        payload["continuity_contract"]["current_plan"].update(
            {
                "action": "observe",
                "new_order_created": False,
                "executable_order_count_after": 0,
                "reason": "候选风险数学未通过全部成交组合校验，因此保持观察且不创建订单。",
            }
        )
        result = evaluate_decision(
            payload,
            reasoning=reasoning,
            run=self.controller.store.load_run(self.run_root),
            pretrade_gate=self.gate,
            root=self.root,
        )
        self.assertTrue(result.passed, result.to_dict())
        self.assertEqual(result.facts["expected_plan_state"], "observe")

    def test_a5r1_unrecalculable_rejected_risk_still_compiles_observe_report(self):
        _, reasoning = self.prepare_through_reasoning()
        payload = self.decision(reasoning)
        maker = payload["maker"]
        maker["risk_plan"]["tp1"] = maker["risk_plan"]["entries"][0]
        maker["defense_plan"] = {}
        maker["plan_constructible"] = False
        maker["plan_constructibility"].update(
            {
                "status": "not_constructible",
                "primary_reason_code": "risk_math_invalid",
                "failure_codes": ["risk_math_invalid"],
            }
        )
        maker["plan_state"] = "observe"
        maker["execution_action"] = "observe"
        maker["order_transition_action"] = "observe"
        payload["continuity_contract"]["current_plan"].update(
            {
                "action": "observe",
                "new_order_created": False,
                "executable_order_count_after": 0,
                "reason": "候选风险几何不可复算，因此保持观察且不创建订单。",
            }
        )

        self.controller.accept_decision(self.run_root, payload)
        self.controller.compile_report(self.run_root)
        canonical_record = self.controller.store.load_stage_output_record(
            self.run_root,
            "report",
            "canonical_report",
        )
        canonical = json.loads(
            (self.root / canonical_record["path"]).read_text(encoding="utf-8")
        )
        combined_record = self.controller.store.load_stage_output_record(
            self.run_root,
            "report",
            "combined",
        )
        combined = (self.root / combined_record["path"]).read_text(
            encoding="utf-8"
        )

        self.assertEqual(
            canonical["audit"]["rejected_candidate_risk_recalculation"],
            {
                "status": "not_recalculable",
                "reason_code": "candidate_risk_input_failed_recalculation",
            },
        )
        self.assertEqual(
            canonical["audit"]["rejected_candidate_risk_scenarios"],
            [],
        )
        self.assertIn("候选风险输入未满足确定性复算前提", combined)

    def test_a5r1_six_level_rejected_risk_is_not_enumerated(self):
        _, reasoning = self.prepare_through_reasoning()
        payload = self.decision(reasoning)
        maker = payload["maker"]
        maker["risk_plan"]["entries"] = [
            99.75,
            99.8,
            99.85,
            99.9,
            99.95,
            100.0,
        ]
        maker["risk_plan"]["entry_allocations_pct"] = [10, 10, 20, 20, 20, 20]
        maker["defense_plan"] = {}
        maker["plan_constructible"] = False
        maker["plan_constructibility"].update(
            {
                "status": "not_constructible",
                "primary_reason_code": "risk_math_invalid",
                "failure_codes": ["risk_math_invalid"],
            }
        )
        maker["plan_state"] = "observe"
        maker["execution_action"] = "observe"
        maker["order_transition_action"] = "observe"
        payload["continuity_contract"]["current_plan"].update(
            {
                "action": "observe",
                "new_order_created": False,
                "executable_order_count_after": 0,
                "reason": "候选分档数量超出风险合同上限，因此保持观察且不创建订单。",
            }
        )

        decision_result = evaluate_decision(
            payload,
            reasoning=reasoning,
            run=self.controller.store.load_run(self.run_root),
            pretrade_gate=self.gate,
            root=self.root,
        )
        self.assertTrue(decision_result.passed, decision_result.to_dict())
        self.controller.accept_decision(self.run_root, payload)
        self.controller.compile_report(self.run_root)
        canonical_record = self.controller.store.load_stage_output_record(
            self.run_root,
            "report",
            "canonical_report",
        )
        canonical = json.loads(
            (self.root / canonical_record["path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(
            canonical["audit"]["rejected_candidate_risk_recalculation"]["status"],
            "not_recalculable",
        )
        self.assertEqual(
            canonical["audit"]["rejected_candidate_risk_scenarios"],
            [],
        )

    def test_a5r1_nonconstructible_observe_rejects_untyped_candidate_fields(self):
        _, reasoning = self.prepare_through_reasoning()
        payload = self.decision(reasoning)
        sentinel = "OBSERVE-RISK-SECOND-TRUTH"
        payload["maker"]["risk_plan"]["entries"] = [100.0, 100.0]
        payload["maker"]["risk_plan"]["fake_price"] = 63960
        payload["maker"]["risk_plan"]["extra_narrative"] = sentinel
        payload["maker"]["defense_plan"] = {"extra_narrative": sentinel}
        payload["maker"]["entry_reach_probability_basis"]["extra_narrative"] = sentinel
        payload["maker"]["plan_constructible"] = False
        payload["maker"]["plan_constructibility"].update(
            {
                "status": "not_constructible",
                "primary_reason_code": "entry_semantics_invalid",
                "failure_codes": ["entry_semantics_invalid", "risk_math_invalid"],
            }
        )
        payload["maker"]["plan_state"] = "observe"
        payload["maker"]["execution_action"] = "observe"
        payload["maker"]["order_transition_action"] = "observe"
        payload["continuity_contract"]["current_plan"].update(
            {
                "action": "observe",
                "new_order_created": False,
                "executable_order_count_after": 0,
                "reason": "候选风险数学未通过，因此保持观察。",
            }
        )
        result = evaluate_decision(
            payload,
            reasoning=reasoning,
            run=self.controller.store.load_run(self.run_root),
            pretrade_gate=self.gate,
            root=self.root,
        )
        codes = {item.code for item in result.defects}
        self.assertIn("risk.schema_fields", codes)
        self.assertIn("defense.schema", codes)
        self.assertIn("entry_reach_probability.schema_fields", codes)

    def test_a5r2_shadow_non_directional_observe_has_no_ghost_candidate(self):
        self.controller.accept_evidence(
            self.run_root,
            self.evidence(),
            evidence_files_root=self.root,
        )
        evidence = self.controller.store.load_stage_payload(
            self.run_root, "evidence", "evidence"
        )
        reasoning_payload = self.reasoning(evidence)
        reasoning_claims = {
            item["id"]: item for item in reasoning_payload["claims"]
        }
        reasoning_claims["claim_maker"].update(
            {
                "direction": "observe",
                "conclusion": "Maker 当前没有方向性执行结论，只保持观察",
                "invalidation": "出现一组闭合且一致的方向性替代证据后重新评估",
            }
        )
        reasoning_claims["claim_cannot"].update(
            {
                "prohibition": "追多空",
                "conclusion": "Maker 本轮不能追多或追空，只能保持观察",
            }
        )
        reasoning_claims["claim_invalidation_maker"][
            "structural_noise_buffer"
        ].update(
            {
                "status": "insufficient",
                "anchor_kind": None,
                "anchor_source_field": None,
                "anchor_price": None,
                "noise_outer_boundary": None,
                "price_distance": None,
                "insufficiency_reason_code": "not_applicable_non_directional_thesis",
            }
        )
        reasoning_payload["pipeline_units"] = build_pipeline_units(
            reasoning_payload
        )
        self.controller.accept_reasoning(self.run_root, reasoning_payload)
        reasoning = self.controller.store.load_stage_payload(
            self.run_root, "reasoning", "reasoning"
        )

        payload = self.decision(reasoning)
        maker = payload["maker"]
        maker.update(
            {
                "direction": "observe",
                "plan_state": "observe",
                "plan_constructible": False,
                "strategy_type": "观望",
                "entry_type": "not_applicable",
                "position_notional_usdt": None,
                "cannot_do_code": "追多空",
                "entry_reach_probability": None,
                "risk_plan": {},
                "defense_plan": {},
            }
        )
        maker["plan_constructibility"].update(
            {
                "status": "not_constructible",
                "primary_reason_code": "non_directional_thesis",
                "failure_codes": ["non_directional_thesis"],
                "entry_zone_basis": None,
            }
        )
        maker["entry_reach_probability_basis"].update(
            {
                "applicability": "not_applicable_no_certified_entry_geometry",
                "reference_entry": None,
                "entry_distance": None,
                "reach_direction": None,
            }
        )
        maker["order_lifecycle"] = {
            "schema_version": "maker-order-lifecycle-v1",
            "state": "not_applicable_no_candidate_geometry",
            "legal_fill_path_exists": False,
            "legal_cancel_path_exists": False,
            "fill_probability": None,
            "fill_probability_applicability": "not_applicable_no_candidate_geometry",
            "reason_code": "not_applicable_no_candidate_geometry",
        }

        decision_result = evaluate_decision(
            payload,
            reasoning=reasoning,
            run=self.controller.store.load_run(self.run_root),
            pretrade_gate=self.gate,
            root=self.root,
        )
        self.assertTrue(decision_result.passed, decision_result.to_dict())
        self.controller.accept_decision(self.run_root, payload)
        self.controller.compile_report(self.run_root)
        canonical_record = self.controller.store.load_stage_output_record(
            self.run_root, "report", "canonical_report"
        )
        canonical = json.loads(
            (self.root / canonical_record["path"]).read_text(encoding="utf-8")
        )
        combined_record = self.controller.store.load_stage_output_record(
            self.run_root, "report", "combined"
        )
        combined = (self.root / combined_record["path"]).read_text(
            encoding="utf-8"
        )
        maker_execution = canonical["audit"]["maker_execution"]
        self.assertEqual(canonical["maker_summary"]["direction"], "observe")
        self.assertEqual(
            canonical["maker_summary"]["semantic_state"],
            "non_directional_observation",
        )
        self.assertEqual(
            canonical["maker_summary"]["constructibility_reason"],
            "non_directional_thesis",
        )
        self.assertIsNone(maker_execution["position_notional_usdt"])
        self.assertEqual(maker_execution["entry_type"], "not_applicable")
        self.assertIsNone(
            maker_execution["plan_constructibility"]["entry_zone_basis"]
        )
        self.assertEqual(canonical["audit"]["risk_plan"], {})
        self.assertEqual(canonical["audit"]["defense_plan"], {})
        self.assertEqual(
            canonical["audit"]["order_lifecycle"]["state"],
            "not_applicable_no_candidate_geometry",
        )
        self.assertIn(
            "本轮无方向观察（未提交候选计划，风险与执行均不适用）",
            combined,
        )
        self.assertIn("影子无方向观察状态；未读取个人持仓/订单状态；未创建、撤销或挂出真实订单", combined)
        self.assertIn("BTC（无方向观察）", combined)
        self.assertNotIn("被拒候选", combined)
        self.assertNotIn("候选已被否决", combined)
        self.assertNotIn("本轮候选计划未同时通过", combined)
        self.assertNotIn("影子候选计划", combined)
        self.assertNotIn("候选判断有效至", combined)
        self.assertNotIn("BTC（候选策略）", combined)
        self.assertNotIn("候选计划结论", combined)
        self.assertNotIn("候选减仓规则", combined)
        poisoned = copy.deepcopy(canonical)
        poisoned["frontstage"]["maker_continuity"] += (
            "；影子候选计划；候选判断有效至2099-01-01T00:00:00+08:00"
        )
        depth = evaluate_human_reasoning_depth(
            poisoned,
            contract=load_presentation_contract(self.root),
        )
        self.assertFalse(depth["passed"])
        self.assertIn(
            "report_projection.shadow_semantic_state_conflict",
            {item["code"] for item in depth["defects"]},
        )

    def test_a5r2_shadow_nonpositive_order_prices_fail_closed(self):
        _, reasoning = self.prepare_through_reasoning()
        cases = (
            ("cancel", 0),
            ("cancel", -1),
            ("entry", 0),
            ("entry", -1),
        )
        for field, invalid_value in cases:
            with self.subTest(field=field, invalid_value=invalid_value):
                payload = self.decision(reasoning)
                maker = payload["maker"]
                risk = maker["risk_plan"]
                if field == "cancel":
                    risk["cancel_before_fill"] = invalid_value
                    failure_codes = ["order_lifecycle_invalid"]
                else:
                    risk["entries"][0] = invalid_value
                    maker["defense_plan"] = {}
                    failure_codes = [
                        "maker_order_marketable",
                        "entry_semantics_invalid",
                        "cannot_do_conflict",
                        "order_lifecycle_invalid",
                        "risk_math_invalid",
                    ]
                lifecycle = assess_order_lifecycle(
                    reference_price=Decimal(
                        str(
                            maker["entry_reach_probability_basis"][
                                "reference_price"
                            ]
                        )
                    ),
                    cancel_price=Decimal(str(risk["cancel_before_fill"])),
                    entries=tuple(Decimal(str(value)) for value in risk["entries"]),
                )
                maker["order_lifecycle"] = lifecycle.as_dict()
                maker["plan_constructible"] = False
                maker["plan_constructibility"].update(
                    {
                        "status": "not_constructible",
                        "primary_reason_code": failure_codes[0],
                        "failure_codes": failure_codes,
                    }
                )
                maker["plan_state"] = "observe"

                result = evaluate_decision(
                    payload,
                    reasoning=reasoning,
                    run=self.controller.store.load_run(self.run_root),
                    pretrade_gate=self.gate,
                    root=self.root,
                )
                codes = {item.code for item in result.defects}
                self.assertEqual(lifecycle.state, "invalid_geometry")
                if field == "cancel":
                    self.assertIn("risk.cancel_before_fill_invalid", codes)
                else:
                    self.assertIn("risk.entry_invalid", codes)

    def test_a5r2_shadow_long_reasoning_decision_and_report_are_symmetric(self):
        self.controller.accept_evidence(
            self.run_root,
            self.evidence(),
            evidence_files_root=self.root,
        )
        evidence = self.controller.store.load_stage_payload(
            self.run_root, "evidence", "evidence"
        )
        reasoning_payload = self.reasoning(evidence)
        observations = {
            item["id"]: item for item in reasoning_payload["observations"]
        }

        coinglass = observations["obs_cg"]
        coinglass["metrics"].update(
            {
                "pivot": {
                    "timeframe": "1h",
                    "start_price": 100,
                    "end_price": 103,
                    "dominant_leg": "up",
                    "trendline_status": "intact",
                    "anchor_reset": False,
                },
                "price_direction": "up",
                "cvd_direction": "up",
                "oi_direction": "up",
                "funding_direction": "up",
                "funding_sign": "positive",
                "combination_id": "C01",
                "effect_divergence": {
                    "cvd_break": "higher_high",
                    "price_confirmation": "confirmed",
                    "interpretation": "none",
                },
                "price_break_status": "new_high_or_breakout",
                "oi_price_context": "new_long_expansion",
                "main_triad_direction": "bullish",
                "main_triad_rationale": "CVD与价格在同一主腿同步上行，OI上升体现新多参与而非资金费率单变量翻向。",
                "funding_effect": "weaken",
                "final_direction": "bullish",
                "funding_single_variable_flip": False,
                "liquidation_map": {
                    "role": "auxiliary_only",
                    "threshold": 0.85,
                    "captured_timeframes": ["48h", "24h"],
                    "current_price": 103,
                    "levels": [
                        {
                            "side": "above",
                            "price": 105,
                            "timeframe": "48h",
                            "strength": "strong",
                        },
                        {
                            "side": "below",
                            "price": 100,
                            "timeframe": "24h",
                            "strength": "medium",
                        },
                    ],
                },
            }
        )
        coinglass["fact"] = "同一一小时枢轴内价格、CVD与OI共同偏多，资金费率只修正强度。"

        exocharts = observations["obs_exo"]
        exocharts["metrics"].update(
            {
                "ohlc": {"open": 100, "high": 104, "low": 99, "close": 103},
                "poc": 102,
                "delta": 12,
                "cvd": 24,
                "volume": 1200,
                "cross_check_result": "confirm",
            }
        )
        exocharts["fact"] = "日线足迹确认主动买入占优，但不替代一小时订单流主判。"

        tradingview = observations["obs_tv"]
        tradingview["metrics"].update(
            {
                "timeframes": {
                    "1d": {"price": 103, "sma20": 97, "structure": "bullish"},
                    "4h": {"price": 103, "sma20": 99, "structure": "bullish"},
                    "1h": {"price": 103, "sma20": 101, "structure": "bullish"},
                    "15m": {"price": 103, "sma20": 103.5, "structure": "bearish"},
                },
                "volume_profile": {
                    "source_mode": "user_drawn_manual_only",
                    "status": "readable",
                    "platform_indicator_state": "hidden",
                    "platform_vrvp_used": False,
                    "automated_values_used": False,
                    "zones": [
                        {
                            "lower_bound": 100,
                            "upper_bound": 102,
                            "timeframe": "1h",
                            "role": "value_area",
                        }
                    ],
                    "reason": "",
                },
                "chart_basis": {
                    "support_levels": [100, 102],
                    "resistance_levels": [104, 105],
                    "swing_highs": [105.2, 105.5],
                    "swing_lows": [99.8, 99.5],
                    "structure_zones": [
                        {
                            "lower_bound": 100,
                            "upper_bound": 102,
                            "timeframe": "1h",
                            "role": "support",
                        },
                        {
                            "lower_bound": 99.5,
                            "upper_bound": 99.8,
                            "timeframe": "4h",
                            "role": "support",
                        },
                        {
                            "lower_bound": 99.8,
                            "upper_bound": 99.9,
                            "timeframe": "1h",
                            "role": "support",
                        },
                    ],
                    "volume_price_state": "confirm",
                    "fibonacci_levels": [100, 102],
                    "trendline_status": "intact",
                },
            }
        )
        tradingview["metrics"]["chart_component_rationales"][
            "chart.sma20_interaction"
        ] = "日线、四小时与一小时均位于各自SMA20上方。"
        tradingview["fact"] = "日线、四小时与一小时偏多，十五分钟回踩只承担短线反证。"

        for observation in (coinglass, exocharts, tradingview):
            observation["visual_review"]["metrics_sha256"] = canonical_sha256(
                observation["metrics"]
            )

        claims = {item["id"]: item for item in reasoning_payload["claims"]}
        claims["claim_orderflow"].update(
            {
                "direction": "long",
                "conclusion": "同一一小时枢轴的订单流主腿偏多并得到足迹确认",
                "invalidation": "价格与主动成交共同转弱且形成新锚点后当前盘口解释失效",
            }
        )
        claims["claim_orderflow"]["score_assessment"][
            "rationale"
        ] = "价格、CVD与OI在同一主腿偏多且足迹确认，但组合未进入宪法定义的极端集合。"
        claims["claim_chart"][
            "invalidation"
        ] = "一小时与四小时结构共同翻空后当前盘面解释失效"
        claims["claim_etf"].update(
            {
                "price_relation": "weaken",
                "conclusion": "ETF净流出与同锚价格上行相背，类型化为削弱但不能单独翻转方向",
                "invalidation": "后续持续净流入或同锚价格方向改变后重新评估",
            }
        )
        claims["claim_liq"].update(
            {
                "conclusion": "用户手绘价值区下沿附近存在回踩后的流动性猎杀概率",
                "invalidation": "一小时有效跌破下沿后猎杀假设失效",
            }
        )
        claims["claim_regime_main"].update(
            {
                "conclusion": "基本面部分兑现且中期结构偏强，主账户市场阶段保持谨慎偏多",
                "invalidation": "四小时与基本面兑现关系共同翻空时主账户阶段失效",
            }
        )
        claims["claim_regime_maker"].update(
            {
                "conclusion": "盘口与盘面偏多但短周期存在回踩，Maker阶段等待高质量支撑边缘",
                "invalidation": "订单流与一小时结构共同翻空时Maker阶段失效",
            }
        )
        claims["claim_counter_main"].update(
            {
                "conclusion": "十五分钟结构已转弱，是当前对主账户偏多判断最直接的反证",
                "invalidation": "若短线回踩未延续且中期结构保持偏多，则该反证减弱",
            }
        )
        claims["claim_counter_main"]["current_basis"]["clauses"][0][
            "value"
        ] = "bearish"
        claims["claim_counter_main"]["trigger_logic"]["clauses"] = [
            {
                "owner_type": "observation",
                "owner_id": "obs_tv",
                "field": "timeframes.1d.structure",
                "operator": "becomes",
                "value": "bearish",
            },
            {
                "owner_type": "observation",
                "owner_id": "obs_fs",
                "field": "flow_direction",
                "operator": "equals_at_trigger",
                "value": "outflow",
            },
        ]
        claims["claim_counter_maker"].update(
            {
                "conclusion": "十五分钟结构已转弱，显示Maker多头入场前仍可能出现更深回踩",
                "invalidation": "若回踩未延续且盘口维持偏多，则该反证自然减弱",
            }
        )
        claims["claim_counter_maker"]["current_basis"]["clauses"][0][
            "value"
        ] = "bearish"
        claims["claim_counter_maker"]["trigger_logic"]["clauses"] = [
            {
                "owner_type": "observation",
                "owner_id": "obs_tv",
                "field": "timeframes.1h.structure",
                "operator": "becomes",
                "value": "bearish",
            },
            {
                "owner_type": "observation",
                "owner_id": "obs_cg",
                "field": "final_direction",
                "operator": "becomes",
                "value": "bearish",
            },
            {
                "owner_type": "observation",
                "owner_id": "obs_exo",
                "field": "cross_check_result",
                "operator": "equals_at_trigger",
                "value": "confirm",
            },
        ]
        main_invalidation = claims["claim_invalidation_main"]
        main_invalidation.update(
            {
                "conclusion": "若日线重新跌破关键结构且现货承接转弱，则主账户判断失效",
                "invalidation": "该条件本身就是主账户偏多判断的失效路径",
            }
        )
        main_invalidation["current_basis"]["clauses"][0]["value"] = "bullish"
        main_invalidation["trigger_logic"]["clauses"] = [
            {
                "owner_type": "observation",
                "owner_id": "obs_tv",
                "field": "timeframes.1d.structure",
                "operator": "becomes",
                "value": "bearish",
            },
            {
                "owner_type": "observation",
                "owner_id": "obs_tv",
                "field": "timeframes.4h.structure",
                "operator": "becomes",
                "value": "bearish",
            },
            {
                "owner_type": "observation",
                "owner_id": "obs_fs",
                "field": "flow_direction",
                "operator": "equals_at_trigger",
                "value": "outflow",
            },
        ]
        main_invalidation["structural_noise_buffer"].update(
            {
                "observation_id": "obs_tv",
                "timeframe": "4h",
                "anchor_kind": "structure_zone_outer_boundary",
                "anchor_source_field": "metrics.chart_basis.structure_zones[1].lower_bound",
                "anchor_price": 99.5,
                "noise_outer_boundary": 99.2,
                "price_distance": 0.5,
            }
        )
        maker_invalidation = claims["claim_invalidation_maker"]
        maker_invalidation.update(
            {
                "conclusion": "若一小时跌破价值区下沿且订单流同步转弱，则Maker判断失效",
                "invalidation": "该条件本身就是Maker偏多判断的失效路径",
            }
        )
        maker_invalidation["current_basis"]["clauses"][0]["value"] = "bullish"
        maker_invalidation["current_basis"]["clauses"][1]["value"] = "bullish"
        maker_invalidation["trigger_logic"]["clauses"] = [
            {
                "owner_type": "observation",
                "owner_id": "obs_tv",
                "field": "timeframes.1h.structure",
                "operator": "becomes",
                "value": "bearish",
            },
            {
                "owner_type": "observation",
                "owner_id": "obs_cg",
                "field": "pivot.anchor_reset",
                "operator": "becomes",
                "value": True,
            },
            {
                "owner_type": "observation",
                "owner_id": "obs_cg",
                "field": "final_direction",
                "operator": "becomes",
                "value": "bearish",
            },
            {
                "owner_type": "observation",
                "owner_id": "obs_exo",
                "field": "cross_check_result",
                "operator": "equals_at_trigger",
                "value": "confirm",
            },
        ]
        maker_invalidation["structural_noise_buffer"].update(
            {
                "observation_id": "obs_tv",
                "timeframe": "1h",
                "anchor_kind": "structure_zone_outer_boundary",
                "anchor_source_field": "metrics.chart_basis.structure_zones[2].lower_bound",
                "anchor_price": 99.8,
                "noise_outer_boundary": 99.7,
                "price_distance": 0.15,
            }
        )
        claims["claim_main"].update(
            {
                "direction": "long",
                "conclusion": "中期结构偏强且主账户认证链保持完整，主账户维持谨慎偏多",
                "invalidation": "日线跌破关键结构且现货承接同步转弱",
            }
        )
        claims["claim_maker"].update(
            {
                "direction": "long",
                "conclusion": "同一小时订单流与Maker阶段偏多，回踩至高质量支撑边缘后计划做多",
                "invalidation": "一小时价格与主动成交共同转弱并跌破下沿",
            }
        )
        claims["claim_cannot"].update(
            {
                "prohibition": "追多",
                "conclusion": "Maker不能在高位右侧追多或在计划支撑边缘外临时成交",
                "invalidation": "只有Maker既定失效路径成立后才允许重建判断",
            }
        )
        reasoning_payload["methodology"]["independent_synthesis"][
            "dominant_leg"
        ] = "up"
        reasoning_payload["methodology"]["multi_timeframe_transition"][
            "transition_summary"
        ] = "日线、四小时与一小时偏多，十五分钟仅保留回踩反证。"
        reasoning_payload["methodology"]["etf_flow_relation"][
            "price_relation"
        ] = "weaken"
        reasoning_payload["pipeline_units"] = build_pipeline_units(
            reasoning_payload
        )
        reasoning_result = self.evaluate_reasoning_candidate(
            evidence, reasoning_payload
        )
        self.assertTrue(reasoning_result.passed, reasoning_result.to_dict())
        self.controller.accept_reasoning(self.run_root, reasoning_payload)
        reasoning = self.controller.store.load_stage_payload(
            self.run_root, "reasoning", "reasoning"
        )

        decision_payload = self.decision(reasoning)
        main = decision_payload["main_account"]
        main.update(
            {
                "direction": "long",
                "entry_zone_basis": {
                    "observation_id": "obs_tv",
                    "zone_kind": "manual_profile",
                    "zone_index": 0,
                },
                "entries": [100, 100.1, 100.2, 100.3],
                "entry_allocations_pct": [25, 25, 25, 25],
                "stop": 99,
                "tp1": 104,
                "final_take_profit": 106,
            }
        )
        main["stop_basis"].update(
            {
                "observation_id": "obs_tv",
                "claim_id": "claim_invalidation_main",
                "timeframe": "4h",
                "anchor_kind": "structure_zone_outer_boundary",
                "anchor_source_field": "metrics.chart_basis.structure_zones[1].lower_bound",
                "anchor_price": 99.5,
                "buffer_claim_id": "claim_invalidation_main",
                "outward_buffer_price": 0.5,
                "derived_stop": 99,
            }
        )

        maker = decision_payload["maker"]
        maker.update(
            {
                "direction": "long",
                "combination_id": "C01",
                "strategy_type": "低多",
                "entry_type": "left",
                "cannot_do_code": "追多",
                "entry_reach_probability": 58,
            }
        )
        maker["chart_scorecard"]["chart.sma20_interaction"][
            "timeframe_relations"
        ] = {"1d": "above", "4h": "above", "1h": "above"}
        maker["entry_reach_probability_basis"].update(
            {
                "applicability": "applicable",
                "reference_source": "TradingView",
                "reference_timeframe": "1h",
                "reference_price": 103,
                "reference_entry": 100.2,
                "entry_distance": 2.8,
                "reach_direction": "down_to_entry",
            }
        )
        maker["risk_plan"].update(
            {
                "entries": [100.2, 100],
                "entry_allocations_pct": [50, 50],
                "stop": 99.65,
                "tp1": 102,
                "tp2": 104,
                "cancel_before_fill": 104.5,
            }
        )
        maker["risk_plan"]["stop_basis"].update(
            {
                "observation_id": "obs_tv",
                "claim_id": "claim_invalidation_maker",
                "timeframe": "1h",
                "anchor_kind": "structure_zone_outer_boundary",
                "anchor_source_field": "metrics.chart_basis.structure_zones[2].lower_bound",
                "anchor_price": 99.8,
                "buffer_claim_id": "claim_invalidation_maker",
                "outward_buffer_price": 0.15,
                "derived_stop": 99.65,
            }
        )
        maker["order_lifecycle"] = assess_order_lifecycle(
            reference_price=Decimal("103"),
            cancel_price=Decimal("104.5"),
            entries=(Decimal("100.2"), Decimal("100")),
        ).as_dict()
        maker["defense_plan"] = self.exact_prefill_defense_plan(
            [100.2, 100],
            [50, 50],
            99.65,
            direction="long",
        )

        decision_result = evaluate_decision(
            decision_payload,
            reasoning=reasoning,
            run=self.controller.store.load_run(self.run_root),
            pretrade_gate=self.gate,
            root=self.root,
        )
        self.assertTrue(decision_result.passed, decision_result.to_dict())
        self.controller.accept_decision(self.run_root, decision_payload)
        self.controller.compile_report(self.run_root)
        canonical_record = self.controller.store.load_stage_output_record(
            self.run_root, "report", "canonical_report"
        )
        canonical = json.loads(
            (self.root / canonical_record["path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(canonical["main_summary"]["direction"], "long")
        self.assertEqual(canonical["maker_summary"]["direction"], "long")
        self.assertEqual(canonical["maker_summary"]["plan_state"], "qualified")
        self.assertEqual(
            canonical["audit"]["order_lifecycle"]["state"], "fillable"
        )
        self.assertTrue(canonical["audit"]["order_lifecycle"]["legal_fill_path_exists"])
        self.assertIsNone(canonical["audit"]["order_lifecycle"]["fill_probability"])

    def test_structural_stop_failure_reason_reaches_canonical_frontstage(self):
        _, reasoning = self.prepare_through_reasoning()
        payload = self.decision(reasoning)
        payload["maker"]["risk_plan"]["stop_basis"]["derived_stop"] = 100.36
        payload["maker"]["plan_constructible"] = False
        payload["maker"]["plan_constructibility"].update(
            {
                "status": "not_constructible",
                "primary_reason_code": "structural_stop_invalid",
                "failure_codes": ["structural_stop_invalid"],
            }
        )
        payload["maker"]["plan_state"] = "observe"
        payload["maker"]["execution_action"] = "observe"
        payload["maker"]["order_transition_action"] = "observe"
        payload["continuity_contract"]["current_plan"].update(
            {
                "action": "observe",
                "new_order_created": False,
                "executable_order_count_after": 0,
                "reason": "候选结构止损未通过认证，因此保持观察。",
            }
        )

        self.controller.accept_decision(self.run_root, payload)
        self.controller.compile_report(self.run_root)
        canonical_record = self.controller.store.load_stage_output_record(
            self.run_root,
            "report",
            "canonical_report",
        )
        canonical = json.loads(
            (self.root / canonical_record["path"]).read_text(encoding="utf-8")
        )
        combined_record = self.controller.store.load_stage_output_record(
            self.run_root,
            "report",
            "combined",
        )
        markdown = (self.root / combined_record["path"]).read_text(encoding="utf-8")
        expected_text = (
            "候选初始止损未绑定本轮认证结构与推理阶段预先密封的外扩缓冲"
        )
        self.assertEqual(
            canonical["maker_summary"]["constructibility_reason"],
            "structural_stop_invalid",
        )
        self.assertEqual(
            canonical["frontstage"]["maker_execution"],
            f"已提交候选未通过认证，不可执行；全部原因=1.{expected_text}",
        )
        self.assertIn(expected_text, markdown)
        self.assertNotIn("计划条件未完成认证", markdown)
        self.assertEqual(
            canonical["audit"]["risk_plan"]["candidate_status"],
            "rejected_not_executable",
        )
        self.assertEqual(
            canonical["audit"]["defense_plan"]["candidate_status"],
            "rejected_not_executable",
        )

    def test_defense_failure_reason_reaches_canonical_frontstage(self):
        _, reasoning = self.prepare_through_reasoning()
        payload = self.decision(reasoning)
        payload["maker"]["defense_plan"]["second_action"] = "reduce_position_half"
        payload["maker"]["plan_constructible"] = False
        payload["maker"]["plan_constructibility"].update(
            {
                "status": "not_constructible",
                "primary_reason_code": "defense_trigger_invalid",
                "failure_codes": ["defense_trigger_invalid"],
            }
        )
        payload["maker"]["plan_state"] = "observe"
        payload["maker"]["execution_action"] = "observe"
        payload["maker"]["order_transition_action"] = "observe"
        payload["continuity_contract"]["current_plan"].update(
            {
                "action": "observe",
                "new_order_created": False,
                "executable_order_count_after": 0,
                "reason": "候选防守触发价未通过确定性计算，因此保持观察。",
            }
        )

        self.controller.accept_decision(self.run_root, payload)
        self.controller.compile_report(self.run_root)
        canonical_record = self.controller.store.load_stage_output_record(
            self.run_root,
            "report",
            "canonical_report",
        )
        canonical = json.loads(
            (self.root / canonical_record["path"]).read_text(encoding="utf-8")
        )
        combined_record = self.controller.store.load_stage_output_record(
            self.run_root,
            "report",
            "combined",
        )
        markdown = (self.root / combined_record["path"]).read_text(encoding="utf-8")
        expected_text = "候选防守触发价未通过完整分档情景的确定性计算"
        self.assertEqual(
            canonical["maker_summary"]["constructibility_reason"],
            "defense_trigger_invalid",
        )
        self.assertEqual(
            canonical["frontstage"]["maker_execution"],
            f"已提交候选未通过认证，不可执行；全部原因=1.{expected_text}",
        )
        self.assertIn(expected_text, markdown)
        self.assertNotIn("计划条件未完成认证", markdown)
        self.assertEqual(
            canonical["audit"]["risk_plan"]["candidate_status"],
            "rejected_not_executable",
        )
        self.assertEqual(
            canonical["audit"]["defense_plan"]["candidate_status"],
            "rejected_not_executable",
        )

    def test_a4r2_manual_entry_zone_has_priority_and_entries_must_stay_inside(self):
        _, reasoning = self.prepare_through_reasoning()
        payload = self.decision(reasoning)
        payload["maker"]["plan_constructibility"]["entry_zone_basis"] = {
            "observation_id": "obs_tv",
            "zone_kind": "structure",
            "zone_index": 0,
        }
        result = evaluate_decision(
            payload,
            reasoning=reasoning,
            run=self.controller.store.load_run(self.run_root),
            pretrade_gate=self.gate,
            root=self.root,
        )
        self.assertIn(
            "entry_zone_binding_invalid",
            result.facts["maker_candidate_failure_codes"],
        )

        tradingview = next(
            item for item in reasoning["observations"] if item["source"] == "TradingView"
        )
        tradingview["metrics"]["chart_basis"]["structure_zones"][0][
            "role"
        ] = "support"
        role_result = evaluate_decision(
            payload,
            reasoning=reasoning,
            run=self.controller.store.load_run(self.run_root),
            pretrade_gate=self.gate,
            root=self.root,
        )
        self.assertEqual(
            role_result.facts["maker_candidate_failure_codes"][:2],
            ["entry_zone_binding_invalid", "entry_zone_role_invalid"],
        )

        outside = self.decision(reasoning)
        outside["maker"]["risk_plan"]["entries"] = [100.1, 100.2]
        outside_result = evaluate_decision(
            outside,
            reasoning=reasoning,
            run=self.controller.store.load_run(self.run_root),
            pretrade_gate=self.gate,
            root=self.root,
        )
        self.assertIn(
            "risk.entries_outside_certified_zone",
            {item.code for item in outside_result.defects},
        )

    def test_a5r1_no_certified_zone_allows_price_free_business_observe(self):
        _, reasoning = self.prepare_through_reasoning()
        tradingview = next(
            item for item in reasoning["observations"] if item["source"] == "TradingView"
        )
        tradingview["metrics"]["volume_profile"].update(
            {
                "status": "insufficient",
                "zones": [],
                "reason": "本轮没有可读的用户手绘入场区间。",
            }
        )
        tradingview["metrics"]["chart_basis"]["structure_zones"] = []
        reasoning["reasoning_sha256"] = reasoning_model_sha256(reasoning)
        payload = self.decision(reasoning)
        payload["main_account"].update(
            {
                "plan_state": "observe",
                "action": "observe",
                "position_notional_usdt": None,
                "leverage": None,
                "entry_mode": None,
                "entry_zone_basis": None,
                "entries": [],
                "entry_allocations_pct": [],
                "stop_basis": None,
                "stop": None,
                "tp1": None,
                "final_take_profit": None,
                "tp1_close_pct": None,
                "plan_state_reason_code": "no_typed_plan",
            }
        )
        payload["maker"]["risk_plan"] = {}
        payload["maker"]["defense_plan"] = {}
        payload["maker"]["position_notional_usdt"] = None
        payload["maker"]["entry_type"] = "not_applicable"
        payload["maker"]["entry_reach_probability"] = None
        payload["maker"]["entry_reach_probability_basis"].update(
            {
                "applicability": "not_applicable_no_certified_entry_geometry",
                "reference_entry": None,
                "entry_distance": None,
                "reach_direction": None,
            }
        )
        payload["maker"]["order_lifecycle"] = {
            "schema_version": "maker-order-lifecycle-v1",
            "state": "not_applicable_no_candidate_geometry",
            "legal_fill_path_exists": False,
            "legal_cancel_path_exists": False,
            "fill_probability": None,
            "fill_probability_applicability": "not_applicable_no_candidate_geometry",
            "reason_code": "not_applicable_no_candidate_geometry",
        }
        payload["maker"]["plan_constructible"] = False
        payload["maker"]["plan_constructibility"].update(
            {
                "status": "not_constructible",
                "primary_reason_code": "no_certified_entry_zone",
                "failure_codes": ["no_certified_entry_zone"],
            }
        )
        payload["maker"]["plan_state"] = "observe"
        payload["maker"]["execution_action"] = "observe"
        payload["maker"]["order_transition_action"] = "observe"
        payload["continuity_contract"]["current_plan"].update(
            {
                "action": "observe",
                "new_order_created": False,
                "executable_order_count_after": 0,
                "reason": "当前没有认证入场区间，因此不生成候选价格或名义持仓。",
            }
        )
        result = evaluate_decision(
            payload,
            reasoning=reasoning,
            run=self.controller.store.load_run(self.run_root),
            pretrade_gate=self.gate,
            root=self.root,
        )
        self.assertTrue(result.passed, result.to_dict())
        self.assertEqual(
            result.facts["maker_candidate_failure_codes"],
            ["no_certified_entry_zone"],
        )

        zero_sentinel = copy.deepcopy(payload)
        zero_sentinel["maker"]["entry_reach_probability"] = 0
        zero_result = evaluate_decision(
            zero_sentinel,
            reasoning=reasoning,
            run=self.controller.store.load_run(self.run_root),
            pretrade_gate=self.gate,
            root=self.root,
        )
        self.assertIn(
            "entry_reach_probability.not_applicable_value",
            {item.code for item in zero_result.defects},
        )
        for field, value, expected_code in (
            ("reference_source", "Unknown", "entry_reach_probability.reference_contract"),
            ("reference_timeframe", "4h", "entry_reach_probability.reference_contract"),
            ("reference_price", 12345, "entry_reach_probability.reference_price"),
        ):
            with self.subTest(field=field):
                poisoned = copy.deepcopy(payload)
                poisoned["maker"]["entry_reach_probability_basis"][field] = value
                poisoned_result = evaluate_decision(
                    poisoned,
                    reasoning=reasoning,
                    run=self.controller.store.load_run(self.run_root),
                    pretrade_gate=self.gate,
                    root=self.root,
                )
                self.assertIn(
                    expected_code,
                    {item.code for item in poisoned_result.defects},
                )

    def test_a4r2_main_plan_rejects_free_text_second_truth_channel(self):
        _, reasoning = self.prepare_through_reasoning()
        payload = self.decision(reasoning)
        payload["main_account"]["plan_text"] = "用自由文本另写一套主账户价格与方向"
        result = evaluate_decision(
            payload,
            reasoning=reasoning,
            run=self.controller.store.load_run(self.run_root),
            pretrade_gate=self.gate,
            root=self.root,
        )
        self.assertIn("main.schema_fields", {item.code for item in result.defects})

    def test_a4r2_observe_cannot_silently_erase_active_order(self):
        _, reasoning = self.prepare_through_reasoning()
        snapshot = {
            "schema_version": "prior-plan-snapshot-vnext-v1",
            "source_reference": "notion-readonly:maker-plan-page",
            "observed_at": f"{self.date}T09:00:00+08:00",
            "status": "pending",
            "executed_pct": 0,
            "executable_order_count": 1,
            "daily_trade_count": 0,
            "summary": "前序Maker区间计划仍未成交且保留一个有效挂单。",
        }
        snapshot_path = self.root / "continuity" / "prior_plan.json"
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        payload = self.decision(reasoning)
        payload["maker"]["threshold_eligible"] = False
        payload["maker"]["plan_state"] = "observe"
        payload["maker"]["execution_action"] = "observe"
        payload["maker"]["order_transition_action"] = "observe"
        payload["maker"]["win_rate"] = 56
        payload["maker"]["winrate_rubric"]["adjustments"][0]["delta"] = -12
        payload["maker"]["winrate_rubric"]["final"] = 56
        payload["continuity_contract"]["prior_plan"] = {
            "source_kind": "local_artifact",
            "reference": snapshot_path.relative_to(self.root).as_posix(),
            "source_sha256": sha256_file(snapshot_path),
            "observed_at": snapshot["observed_at"],
            "status": "pending",
            "executed_pct": 0,
            "executable_order_count_before": 1,
            "daily_trade_count_before": 0,
            "summary": snapshot["summary"],
        }
        payload["continuity_contract"]["current_plan"].update(
            {
                "action": "observe",
                "old_order_cancelled": False,
                "new_order_created": False,
                "executable_order_count_after": 0,
                "reason": "当前计划不执行，但故意没有声明撤销前序有效挂单。",
            }
        )
        result = evaluate_decision(
            payload,
            reasoning=reasoning,
            run=self.controller.store.load_run(self.run_root),
            pretrade_gate=self.gate,
            root=self.root,
        )
        self.assertIn(
            "continuity.observe_invalid",
            {item.code for item in result.defects},
        )

    def test_a4r2_source_role_text_cannot_issue_account_orders(self):
        evidence = self.evidence()
        payload = self.reasoning(evidence)
        etf = next(
            item for item in payload["claims"] if item["claim_type"] == "etf_confirmation"
        )
        etf["conclusion"] = "ETF净流出直接决定Maker做多并要求立即开仓"
        claim_result = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertIn(
            "claim.source_role_action_leak",
            {item.code for item in claim_result.defects},
        )

        legacy_section_payload = self.reasoning(evidence)
        legacy_section_payload["report_sections"] = {
            "fundamentals": {
                "text": "基本面直接决定Maker做多并要求立即开仓，主账户也同步转多",
                "claim_ids": ["claim_fundamental"],
            }
        }
        section_result = self.evaluate_reasoning_candidate(
            evidence, legacy_section_payload
        )
        self.assertIn(
            "reasoning.schema_fields",
            {item.code for item in section_result.defects},
        )

    def test_a4r2_maker_rejects_free_text_and_single_price_second_truths(self):
        _, reasoning = self.prepare_through_reasoning()
        payload = self.decision(reasoning)
        payload["maker"]["plan_text"] = "Maker改为做多，单价入场1并使用100x"
        payload["maker"]["entry_price"] = 1
        result = evaluate_decision(
            payload,
            reasoning=reasoning,
            run=self.controller.store.load_run(self.run_root),
            pretrade_gate=self.gate,
            root=self.root,
        )
        self.assertIn("maker.schema_fields", {item.code for item in result.defects})

    def test_a4r2_methodology_scenario_cannot_consume_final_cannot_do(self):
        evidence = self.evidence()
        payload = self.reasoning(evidence)
        maker_base = next(
            item
            for item in payload["methodology"]["scenario_tree"]
            if item.get("account") == "maker" and item.get("kind") == "base"
        )
        maker_base["trigger_claim_ids"].append("claim_cannot")
        result = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertIn(
            "methodology.scenario_trigger_projection",
            {item.code for item in result.defects},
        )
        self.assertIn(
            "cannot_do.used_as_methodology_scenario_input",
            {item.code for item in result.defects},
        )

    def test_empty_visual_metric_collection_requires_explicit_citation(self):
        evidence = self.evidence()
        payload = self.reasoning(evidence)
        tradingview = next(
            item
            for item in payload["observations"]
            if item["source"] == "TradingView"
        )
        tradingview["metrics"]["chart_basis"]["fibonacci_levels"] = []
        for citation in tradingview["visual_citations"]:
            citation["metric_paths"] = [
                path
                for path in citation["metric_paths"]
                if not path.startswith("chart_basis.fibonacci_levels[")
            ]
        tradingview["visual_citations"] = [
            citation
            for citation in tradingview["visual_citations"]
            if citation["metric_paths"]
        ]
        tradingview["visual_review"]["metrics_sha256"] = canonical_sha256(
            tradingview["metrics"]
        )

        uncited = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertIn(
            (
                "visual.metric_uncited",
                "observations.obs_tv.metrics.chart_basis.fibonacci_levels",
            ),
            {(item.code, item.path) for item in uncited.defects},
        )

        target = next(
            citation
            for citation in tradingview["visual_citations"]
            if len(citation["metric_paths"]) < 6
        )
        target["metric_paths"].append("chart_basis.fibonacci_levels")
        cited = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertTrue(cited.passed, cited.to_dict())

    def test_a4r2_etf_relation_is_derived_from_price_and_flow(self):
        evidence = self.evidence()
        payload = self.reasoning(evidence)
        etf = next(
            item for item in payload["claims"] if item["claim_type"] == "etf_confirmation"
        )
        etf["price_relation"] = "weaken"
        etf["conclusion"] = "ETF净流出与价格背离，只能削弱现货侧确认"
        payload["methodology"]["etf_flow_relation"]["price_relation"] = "weaken"
        result = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertIn("etf.price_relation_drift", {item.code for item in result.defects})

    def test_a4r2_cross_source_realization_cannot_be_owned_by_blockbeats(self):
        evidence = self.evidence()
        payload = self.reasoning(evidence)
        blockbeats = next(
            item for item in payload["observations"] if item["source"] == "BlockBeats"
        )
        blockbeats["metrics"]["realization_state"] = "realized"
        blockbeats["structured_binding"]["metrics_sha256"] = canonical_sha256(
            blockbeats["metrics"]
        )
        result = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertIn(
            "blockbeats.metric_ownership",
            {item.code for item in result.defects},
        )

    def test_a4r2_pivot_geometry_owns_price_direction(self):
        evidence = self.evidence()
        payload = self.reasoning(evidence)
        coinglass = next(
            item for item in payload["observations"] if item["source"] == "Coinglass"
        )
        coinglass["metrics"]["pivot"].update(
            {"end_price": 110, "dominant_leg": "up"}
        )
        coinglass["visual_review"]["metrics_sha256"] = canonical_sha256(
            coinglass["metrics"]
        )
        payload["methodology"]["independent_synthesis"]["dominant_leg"] = "up"
        result = self.evaluate_reasoning_candidate(evidence, payload)
        codes = {item.code for item in result.defects}
        self.assertIn("coinglass.pivot_price_direction_drift", codes)

    def test_a4r2_open_partial_order_cannot_reconcile_without_cancellation(self):
        _, reasoning = self.prepare_through_reasoning()
        snapshot = {
            "schema_version": "prior-plan-snapshot-vnext-v1",
            "source_reference": "notion-readonly:maker-plan-page",
            "observed_at": f"{self.date}T09:00:00+08:00",
            "status": "open",
            "executed_pct": 50,
            "executable_order_count": 1,
            "daily_trade_count": 0,
            "summary": "前序Maker订单已经部分成交百分之五十，剩余挂单仍然有效。",
        }
        snapshot_path = self.root / "continuity" / "prior_plan.json"
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        payload = self.decision(reasoning)
        payload["maker"]["threshold_eligible"] = False
        payload["maker"]["plan_state"] = "observe"
        payload["maker"]["strategy_type"] = "观望"
        payload["maker"]["execution_action"] = "observe"
        payload["maker"]["order_transition_action"] = "reconcile_filled"
        payload["maker"]["win_rate"] = 56
        payload["maker"]["winrate_rubric"]["adjustments"][0]["delta"] = -12
        payload["maker"]["winrate_rubric"]["final"] = 56
        payload["continuity_contract"]["prior_plan"] = {
            "source_kind": "local_artifact",
            "reference": snapshot_path.relative_to(self.root).as_posix(),
            "source_sha256": sha256_file(snapshot_path),
            "observed_at": snapshot["observed_at"],
            "status": "open",
            "executed_pct": 50,
            "executable_order_count_before": 1,
            "daily_trade_count_before": 0,
            "summary": snapshot["summary"],
        }
        payload["continuity_contract"]["current_plan"].update(
            {
                "action": "reconcile_filled",
                "old_order_cancelled": False,
                "new_order_created": False,
                "executable_order_count_after": 0,
                "executed_pct": 50,
                "reason": "错误地把部分成交计划当成全部成交并清除剩余有效挂单。",
            }
        )
        result = evaluate_decision(
            payload,
            reasoning=reasoning,
            run=self.controller.store.load_run(self.run_root),
            pretrade_gate=self.gate,
            root=self.root,
        )
        self.assertIn("continuity.reconcile_invalid", {item.code for item in result.defects})

    def test_a4r2_source_claim_action_leak_needs_no_causal_keyword(self):
        evidence = self.evidence()
        payload = self.reasoning(evidence)
        etf = next(
            item for item in payload["claims"] if item["claim_type"] == "etf_confirmation"
        )
        etf["conclusion"] = "ETF净流出与价格同向形成确认；Maker立即开仓做多。"
        result = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertIn(
            "claim.source_role_action_leak",
            {item.code for item in result.defects},
        )

    def test_a4r2_cannot_do_cannot_reenter_either_scenario_owner(self):
        evidence = self.evidence()
        payload = self.reasoning(evidence)
        maker_base = next(
            item
            for item in payload["scenario_tree"]
            if item["account"] == "maker" and item["scenario_type"] == "base"
        )
        maker_base["owner_claim_id"] = "claim_cannot"
        methodology_base = next(
            item
            for item in payload["methodology"]["scenario_tree"]
            if item["account"] == "maker" and item["kind"] == "base"
        )
        methodology_base["claim_id"] = "claim_cannot"
        result = self.evaluate_reasoning_candidate(evidence, payload)
        codes = {item.code for item in result.defects}
        self.assertIn("cannot_do.used_as_scenario_input", codes)
        self.assertIn("cannot_do.used_as_methodology_scenario_input", codes)

    def test_a4r2_methodology_scenarios_require_both_account_closures(self):
        evidence = self.evidence()
        payload = self.reasoning(evidence)
        for item in payload["methodology"]["scenario_tree"]:
            item.pop("account")
        result = self.evaluate_reasoning_candidate(evidence, payload)
        codes = {item.code for item in result.defects}
        self.assertIn("methodology.scenario_schema_fields", codes)
        self.assertIn("methodology.scenario_account_coverage", codes)

    def test_a4r2_counter_and_invalidation_require_typed_trigger_owners(self):
        evidence = self.evidence()

        payload = self.reasoning(evidence)
        maker_counter = next(
            item
            for item in payload["claims"]
            if item["claim_type"] == "strongest_counterevidence"
            and item["account"] == "maker"
        )
        maker_counter.pop("trigger_logic")
        result = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertIn("claim.trigger_logic_missing", {item.code for item in result.defects})

        payload = self.reasoning(evidence)
        main_invalidation = next(
            item
            for item in payload["claims"]
            if item["claim_type"] == "invalidation_path"
            and item["account"] == "main"
        )
        main_invalidation["trigger_logic"]["mode"] = "any"
        result = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertIn("claim.invalidation_trigger_mode", {item.code for item in result.defects})

        for claim_type in ("strongest_counterevidence", "invalidation_path"):
            with self.subTest(claim_type=claim_type):
                payload = self.reasoning(evidence)
                current_direction = next(
                    item
                    for item in payload["observations"]
                    if item["source"] == "Coinglass"
                )["metrics"]["final_direction"]
                maker_owner = next(
                    item
                    for item in payload["claims"]
                    if item["claim_type"] == claim_type
                    and item["account"] == "maker"
                )
                direction_clause = next(
                    item
                    for item in maker_owner["trigger_logic"]["clauses"]
                    if item["field"] == "final_direction"
                )
                self.assertEqual(direction_clause["operator"], "becomes")
                direction_clause["value"] = current_direction
                result = self.evaluate_reasoning_candidate(evidence, payload)
                codes = {item.code for item in result.defects}
                self.assertIn("claim.trigger_no_state_change", codes)

    def test_a4r2_validation_owns_incomplete_or_weakened_typed_triggers(self):
        evidence = self.evidence()
        payload = self.reasoning(evidence)
        compiler_source = (
            self.root / "runtime_vnext" / "report_compiler.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("_typed_account_controls", compiler_source)
        self.assertNotIn("trigger_policy", compiler_source)

        one_clause = copy.deepcopy(payload)
        main_counter = next(
            item
            for item in one_clause["claims"]
            if item["claim_type"] == "strongest_counterevidence"
            and item["account"] == "main"
        )
        main_counter["trigger_logic"]["clauses"] = main_counter["trigger_logic"][
            "clauses"
        ][:1]
        self.assertFalse(self.evaluate_reasoning_candidate(evidence, one_clause).passed)

        weakened = copy.deepcopy(payload)
        main_invalidation = next(
            item
            for item in weakened["claims"]
            if item["claim_type"] == "invalidation_path"
            and item["account"] == "main"
        )
        main_invalidation["trigger_logic"]["mode"] = "any"
        self.assertFalse(self.evaluate_reasoning_candidate(evidence, weakened).passed)

    def test_a4r2_claims_cannot_add_execution_or_score_second_truths(self):
        evidence = self.evidence()
        cases = (
            "在12345单一价格开仓，并在13000止损。",
            "在六万三千九百六十价位开仓，并在六万四千一百二十止损。",
            "Maker委托价固定为63960，保护价64120。",
            "挂单价63960，目标价65000。",
        )
        for injected in cases:
            with self.subTest(injected=injected):
                payload = self.reasoning(evidence)
                maker_claim = next(
                    item for item in payload["claims"] if item["claim_type"] == "maker_thesis"
                )
                maker_claim["conclusion"] += injected
                result = self.evaluate_reasoning_candidate(evidence, payload)
                self.assertIn(
                    "claim.execution_parameter_second_truth",
                    {item.code for item in result.defects},
                )

        for injected_score in (
            "本轮盘口评分70分且无需极值证明。",
            "本轮盘口评分六十分且无需结构化分项。",
        ):
            with self.subTest(injected_score=injected_score):
                payload = self.reasoning(evidence)
                orderflow = next(
                    item
                    for item in payload["claims"]
                    if item["claim_type"] == "orderflow_interpretation"
                )
                orderflow["conclusion"] += injected_score
                result = self.evaluate_reasoning_candidate(evidence, payload)
                self.assertIn(
                    "claim.score_second_truth",
                    {item.code for item in result.defects},
                )

    def test_a4r2_final_direction_reversal_cannot_hide_behind_both_direction_words(self):
        evidence = self.evidence()
        payload = self.reasoning(evidence)
        maker_claim = next(
            item for item in payload["claims"] if item["claim_type"] == "maker_thesis"
        )
        maker_claim["conclusion"] = (
            "Maker不再做空而是立即做多，原偏空结论全部取消并转为多头方向。"
        )
        result = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertIn(
            "claim.typed_direction_text_conflict",
            {item.code for item in result.defects},
        )

    def test_a5r2a_typed_direction_parser_is_clause_and_claim_owner_aware(self):
        passing_cases = (
            (
                "orderflow_interpretation",
                "long",
                "同锚点盘口方向为多头，但上涨主要由空头回补驱动且日线足迹偏空只削弱确认。",
            ),
            (
                "orderflow_interpretation",
                "short",
                "同锚点盘口方向为空头，但下跌主要由多头清算驱动，强度有限。",
            ),
            (
                "main_account_thesis",
                "long",
                "主账户维持偏多，15m偏空仅作局部反证，不替代中线主判。",
            ),
            (
                "main_account_thesis",
                "long",
                "若订单流转空则重新评估，当前主判维持偏多。",
            ),
            (
                "maker_thesis",
                "short",
                "并非转多，Maker仍计划做空。",
            ),
            (
                "main_account_thesis",
                "long",
                "原偏空结论已取消，当前方向为多头。",
            ),
            (
                "main_account_thesis",
                "long",
                "主账户等待下跌回调后再做多，不把价格路径误写成最终空头主判。",
            ),
            (
                "main_account_thesis",
                "neutral",
                "看多与看空证据冲突，当前保持中性。",
            ),
            (
                "maker_thesis",
                "observe",
                "Maker不做多也不做空，只保持观察。",
            ),
        )
        for claim_type, direction, conclusion in passing_cases:
            with self.subTest(expected="pass", conclusion=conclusion):
                self.assertIsNone(
                    _typed_direction_prose_issue(
                        conclusion,
                        direction,
                        claim_type=claim_type,
                    )
                )

        failing_cases = (
            (
                "maker_thesis",
                "short",
                "Maker不再做空而是立即做多，原偏空结论全部取消并转为多头方向。",
                "opposite_bullish_marker",
            ),
            (
                "maker_thesis",
                "long",
                "Maker不再做多而是立即做空，最终转为空头方向。",
                "opposite_bearish_marker",
            ),
            (
                "main_account_thesis",
                "long",
                "方向先为多头，但最终结论转为空头方向。",
                "opposite_bearish_marker",
            ),
            (
                "maker_thesis",
                "short",
                "Maker先维持偏空，但最终立即做多。",
                "opposite_bullish_marker",
            ),
            (
                "main_account_thesis",
                "neutral",
                "最终方向改为多头。",
                "direction_marker_for_non_directional_owner",
            ),
            (
                "maker_thesis",
                "observe",
                "Maker最终计划做空。",
                "direction_marker_for_non_directional_owner",
            ),
            (
                "main_account_thesis",
                "long",
                "主账户最终结论转为下跌方向。",
                "opposite_bearish_marker",
            ),
            (
                "main_account_thesis",
                "short",
                "主账户最终看涨，多方占优。",
                "opposite_bullish_marker",
            ),
            (
                "main_account_thesis",
                "neutral",
                "主账户最终转为多方。",
                "direction_marker_for_non_directional_owner",
            ),
            (
                "maker_thesis",
                "observe",
                "Maker最终看跌，空方占优。",
                "direction_marker_for_non_directional_owner",
            ),
        )
        for claim_type, direction, conclusion, expected in failing_cases:
            with self.subTest(expected=expected, conclusion=conclusion):
                self.assertEqual(
                    _typed_direction_prose_issue(
                        conclusion,
                        direction,
                        claim_type=claim_type,
                    ),
                    expected,
                )

    def test_a5r2a_score_rationale_uses_the_same_owner_aware_direction_parser(self):
        evidence = self.evidence()
        payload = self.reasoning(evidence)
        orderflow = next(
            item
            for item in payload["claims"]
            if item["claim_type"] == "orderflow_interpretation"
        )
        orderflow["score_assessment"]["rationale"] = (
            "早前偏空判断已经取消；同锚点盘口当前最终看涨，多方占优。"
        )
        payload["pipeline_units"] = build_pipeline_units(payload)

        result = self.evaluate_reasoning_candidate(evidence, payload)

        self.assertIn(
            "claim.score_rationale_direction_conflict",
            {item.code for item in result.defects},
        )

    def test_a5r2a_historical_any_trigger_rejects_a_neutral_independent_branch(self):
        evidence = self.evidence()
        payload = self.reasoning(evidence)
        claims = {item["id"]: item for item in payload["claims"]}
        claims["claim_main"].update(
            {
                "direction": "neutral",
                "conclusion": "当前证据冲突，主账户保持中性观察并等待闭合的替代方向证据",
                "invalidation": "出现一组闭合且一致的方向性替代证据后重新评估",
            }
        )
        claims["claim_invalidation_main"]["structural_noise_buffer"].update(
            {
                "status": "insufficient",
                "anchor_kind": None,
                "anchor_source_field": None,
                "anchor_price": None,
                "noise_outer_boundary": None,
                "price_distance": None,
                "insufficiency_reason_code": "not_applicable_non_directional_thesis",
            }
        )
        trigger = claims["claim_counter_main"]["trigger_logic"]
        trigger["mode"] = "any"
        trigger["clauses"] = [
            {
                "owner_type": "observation",
                "owner_id": "obs_tv",
                "field": "timeframes.1h.structure",
                "operator": "becomes",
                "value": "bullish",
            },
            {
                "owner_type": "claim",
                "owner_id": "claim_realization",
                "field": "realization_state",
                "operator": "becomes",
                "value": "realized",
            },
        ]
        payload["pipeline_units"] = build_pipeline_units(payload)

        result = self.evaluate_reasoning_candidate(evidence, payload)
        matching = [
            item
            for item in result.defects
            if item.code == "claim.trigger_any_clause_not_counter"
        ]
        self.assertEqual(
            [item.path for item in matching],
            ["claims.claim_counter_main.trigger_logic.clauses[1]"],
        )
        self.assertIn(
            "fundamental.event_observation_only_trigger",
            {item.code for item in result.defects},
        )

    def test_a5r2a_any_direct_counters_pass_but_mixed_one_of_is_rejected(self):
        evidence = self.evidence()
        payload = self.reasoning(evidence)
        claims = {item["id"]: item for item in payload["claims"]}
        maker_trigger = claims["claim_counter_maker"]["trigger_logic"]
        maker_trigger["mode"] = "any"
        maker_trigger["clauses"] = [
            {
                "owner_type": "observation",
                "owner_id": "obs_tv",
                "field": "timeframes.1h.structure",
                "operator": "becomes",
                "value": "bullish",
            },
            {
                "owner_type": "observation",
                "owner_id": "obs_cg",
                "field": "final_direction",
                "operator": "becomes",
                "value": "bullish",
            },
        ]
        payload["pipeline_units"] = build_pipeline_units(payload)
        accepted = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertTrue(accepted.passed, accepted.defects)

        payload = self.reasoning(evidence)
        claims = {item["id"]: item for item in payload["claims"]}
        mixed_clause = claims["claim_counter_main"]["trigger_logic"]["clauses"][0]
        mixed_clause.pop("value")
        mixed_clause.update(
            {
                "operator": "one_of_at_trigger",
                "values": ["bullish", "range"],
            }
        )
        payload["pipeline_units"] = build_pipeline_units(payload)
        rejected = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertIn(
            "claim.trigger_direction_incoherent",
            {item.code for item in rejected.defects},
        )

    def test_a5r2g5_any_future_rejects_one_already_satisfied_clause(self):
        evidence = self.evidence()
        payload = self.reasoning(evidence)
        claims = {item["id"]: item for item in payload["claims"]}
        maker_trigger = claims["claim_counter_maker"]["trigger_logic"]
        maker_trigger["mode"] = "any"
        maker_trigger["clauses"] = [
            {
                "owner_type": "observation",
                "owner_id": "obs_tv",
                "field": "timeframes.15m.structure",
                "operator": "equals_at_trigger",
                "value": "bullish",
            },
            {
                "owner_type": "observation",
                "owner_id": "obs_cg",
                "field": "final_direction",
                "operator": "becomes",
                "value": "bullish",
            },
        ]
        payload["pipeline_units"] = build_pipeline_units(payload)

        rejected = self.evaluate_reasoning_candidate(evidence, payload)

        self.assertIn(
            "claim.trigger_already_satisfied",
            {item.code for item in rejected.defects},
        )

    def test_a5r2g5_all_future_allows_one_satisfied_clause(self):
        evidence = self.evidence()
        payload = self.reasoning(evidence)
        claims = {item["id"]: item for item in payload["claims"]}
        maker_trigger = claims["claim_counter_maker"]["trigger_logic"]
        maker_trigger["mode"] = "all"
        maker_trigger["clauses"] = [
            {
                "owner_type": "observation",
                "owner_id": "obs_tv",
                "field": "timeframes.15m.structure",
                "operator": "equals_at_trigger",
                "value": "bullish",
            },
            {
                "owner_type": "observation",
                "owner_id": "obs_cg",
                "field": "final_direction",
                "operator": "becomes",
                "value": "bullish",
            },
        ]
        payload["pipeline_units"] = build_pipeline_units(payload)

        accepted = self.evaluate_reasoning_candidate(evidence, payload)

        self.assertTrue(accepted.passed, accepted.defects)

    def test_a5r2a_all_trigger_allows_neutral_aux_but_rejects_support(self):
        evidence = self.evidence()
        payload = self.reasoning(evidence)
        accepted = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertTrue(accepted.passed, accepted.defects)

        claims = {item["id"]: item for item in payload["claims"]}
        claims["claim_counter_main"]["trigger_logic"]["clauses"].append(
            {
                "owner_type": "observation",
                "owner_id": "obs_tv",
                "field": "timeframes.4h.structure",
                "operator": "equals_at_trigger",
                "value": "bearish",
            }
        )
        payload["pipeline_units"] = build_pipeline_units(payload)
        rejected = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertIn(
            "claim.trigger_direction_incoherent",
            {item.code for item in rejected.defects},
        )

    def test_a5r2a_relative_exocharts_must_bind_and_match_the_counter(self):
        evidence = self.evidence()

        payload = self.reasoning(evidence)
        claims = {item["id"]: item for item in payload["claims"]}
        exocharts_clause = claims["claim_counter_maker"]["trigger_logic"][
            "clauses"
        ][2]
        exocharts_clause["value"] = "contradict"
        payload["pipeline_units"] = build_pipeline_units(payload)
        contradictory = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertIn(
            "claim.trigger_direction_incoherent",
            {item.code for item in contradictory.defects},
        )

        payload = self.reasoning(evidence)
        claims = {item["id"]: item for item in payload["claims"]}
        exocharts_clause = claims["claim_counter_maker"]["trigger_logic"][
            "clauses"
        ][2]
        exocharts_clause.pop("value")
        exocharts_clause.update(
            {
                "operator": "one_of_at_trigger",
                "values": ["confirm", "weaken"],
            }
        )
        payload["pipeline_units"] = build_pipeline_units(payload)
        mixed_relative_targets = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertIn(
            "claim.exocharts_counter_polarity",
            {item.code for item in mixed_relative_targets.defects},
        )

        payload = self.reasoning(evidence)
        claims = {item["id"]: item for item in payload["claims"]}
        trigger = claims["claim_counter_maker"]["trigger_logic"]
        trigger["mode"] = "any"
        trigger["clauses"] = [trigger["clauses"][0], trigger["clauses"][2]]
        payload["pipeline_units"] = build_pipeline_units(payload)
        unbound = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertIn(
            "claim.exocharts_counter_polarity",
            {item.code for item in unbound.defects},
        )

    def test_exocharts_reference_requires_one_current_aware_canonical_clause(self):
        evidence = self.evidence()

        payload = self.reasoning(evidence)
        claims = {item["id"]: item for item in payload["claims"]}
        trigger = claims["claim_counter_maker"]["trigger_logic"]
        reference = next(
            item for item in trigger["clauses"] if item["field"] == "final_direction"
        )
        reference["operator"] = "equals_at_trigger"
        payload["pipeline_units"] = build_pipeline_units(payload)
        wrong_operator = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertIn(
            "claim.exocharts_counter_polarity",
            {item.code for item in wrong_operator.defects},
        )

        payload = self.reasoning(evidence)
        claims = {item["id"]: item for item in payload["claims"]}
        trigger = claims["claim_counter_maker"]["trigger_logic"]
        trigger["clauses"].append(
            {
                "owner_type": "observation",
                "owner_id": "obs_cg",
                "field": "final_direction",
                "operator": "one_of_at_trigger",
                "values": ["bullish"],
            }
        )
        payload["pipeline_units"] = build_pipeline_units(payload)
        ambiguous_reference = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertIn(
            "claim.exocharts_counter_polarity",
            {item.code for item in ambiguous_reference.defects},
        )

    def test_a5r2a_trigger_targets_require_closed_shape_and_exact_json_types(self):
        evidence = self.evidence()
        cases = (
            ("bool_as_int", 1),
            ("object", {"value": True}),
            ("array", [True]),
        )
        for label, invalid_target in cases:
            with self.subTest(label=label):
                payload = self.reasoning(evidence)
                claims = {item["id"]: item for item in payload["claims"]}
                clause = next(
                    item
                    for item in claims["claim_invalidation_maker"]["trigger_logic"][
                        "clauses"
                    ]
                    if item["field"] == "pivot.anchor_reset"
                )
                clause["value"] = invalid_target
                payload["pipeline_units"] = build_pipeline_units(payload)
                result = self.evaluate_reasoning_candidate(evidence, payload)
                self.assertIn(
                    "claim.trigger_target_invalid",
                    {item.code for item in result.defects},
                )

        for label, invalid_values in (
            ("string_not_array", "bullish"),
            ("nested_array", [["bullish"]]),
        ):
            with self.subTest(label=label):
                payload = self.reasoning(evidence)
                claims = {item["id"]: item for item in payload["claims"]}
                clause = next(
                    item
                    for item in claims["claim_counter_maker"]["trigger_logic"][
                        "clauses"
                    ]
                    if item["field"] == "final_direction"
                )
                clause.pop("value")
                clause.update(
                    {
                        "operator": "one_of_at_trigger",
                        "values": invalid_values,
                    }
                )
                payload["pipeline_units"] = build_pipeline_units(payload)
                result = self.evaluate_reasoning_candidate(evidence, payload)
                self.assertIn(
                    "claim.trigger_target_invalid",
                    {item.code for item in result.defects},
                )

        payload = self.reasoning(evidence)
        claims = {item["id"]: item for item in payload["claims"]}
        claims["claim_invalidation_maker"]["current_basis"]["clauses"].append(
            {
                "owner_type": "observation",
                "owner_id": "obs_cg",
                "field": "pivot.anchor_reset",
                "operator": "equals",
                "value": 0,
            }
        )
        payload["pipeline_units"] = build_pipeline_units(payload)
        current_basis_bool_as_int = self.evaluate_reasoning_candidate(
            evidence, payload
        )
        self.assertIn(
            "claim.current_basis_value_domain",
            {item.code for item in current_basis_bool_as_int.defects},
        )

    def test_a5r2a_all_trigger_same_field_targets_must_be_jointly_reachable(self):
        evidence = self.evidence()
        payload = self.reasoning(evidence)
        claims = {item["id"]: item for item in payload["claims"]}
        trigger = claims["claim_counter_maker"]["trigger_logic"]
        trigger["clauses"].append(
            {
                "owner_type": "observation",
                "owner_id": "obs_cg",
                "field": "final_direction",
                "operator": "equals_at_trigger",
                "value": "bearish",
            }
        )
        payload["pipeline_units"] = build_pipeline_units(payload)

        impossible = self.evaluate_reasoning_candidate(evidence, payload)
        matching = [
            item
            for item in impossible.defects
            if item.code == "claim.trigger_all_clause_unsatisfiable"
        ]
        self.assertEqual(
            [item.path for item in matching],
            ["claims.claim_counter_maker.trigger_logic.clauses[3]"],
        )

        payload = self.reasoning(evidence)
        claims = {item["id"]: item for item in payload["claims"]}
        trigger = claims["claim_counter_maker"]["trigger_logic"]
        trigger["clauses"].append(
            {
                "owner_type": "observation",
                "owner_id": "obs_cg",
                "field": "final_direction",
                "operator": "equals_at_trigger",
                "value": "bullish",
            }
        )
        payload["pipeline_units"] = build_pipeline_units(payload)
        overlap = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertNotIn(
            "claim.trigger_all_clause_unsatisfiable",
            {item.code for item in overlap.defects},
        )

    def test_a5r2a_closed_trigger_and_scenario_identifiers_reject_padding(self):
        evidence = self.evidence()

        def padded_mode(payload):
            claims = {item["id"]: item for item in payload["claims"]}
            claims["claim_counter_maker"]["trigger_logic"]["mode"] = " all "

        def padded_operator(payload):
            claims = {item["id"]: item for item in payload["claims"]}
            claims["claim_counter_maker"]["trigger_logic"]["clauses"][0][
                "operator"
            ] = " becomes "

        def padded_owner(payload):
            claims = {item["id"]: item for item in payload["claims"]}
            claims["claim_counter_maker"]["trigger_logic"]["clauses"][0][
                "owner_id"
            ] = " obs_tv "

        def padded_current_basis_mode(payload):
            claims = {item["id"]: item for item in payload["claims"]}
            claims["claim_counter_maker"]["current_basis"]["mode"] = " all "

        def padded_scenario_type(payload):
            scenario = next(
                item
                for item in payload["scenario_tree"]
                if item["id"] == "scenario_main_counter"
            )
            scenario["scenario_type"] = " counter "

        def padded_scenario_owner_claim_id(payload):
            scenario = next(
                item
                for item in payload["scenario_tree"]
                if item["id"] == "scenario_main_counter"
            )
            scenario["owner_claim_id"] = f" {scenario['owner_claim_id']} "

        for label, mutator, expected_code in (
            ("mode", padded_mode, "claim.trigger_mode_invalid"),
            ("operator", padded_operator, "claim.trigger_clause_schema"),
            ("owner", padded_owner, "claim.trigger_identifier_noncanonical"),
            (
                "current_basis_mode",
                padded_current_basis_mode,
                "claim.current_basis_mode",
            ),
            ("scenario_type", padded_scenario_type, "scenario.identifier_noncanonical"),
            (
                "scenario_owner_claim_id",
                padded_scenario_owner_claim_id,
                "scenario.identifier_noncanonical",
            ),
        ):
            with self.subTest(label=label):
                payload = self.reasoning(evidence)
                mutator(payload)
                if label not in {"owner", "scenario_owner_claim_id"}:
                    payload["pipeline_units"] = build_pipeline_units(payload)
                result = self.evaluate_reasoning_candidate(evidence, payload)
                self.assertIn(expected_code, {item.code for item in result.defects})

    def test_a5r2f_scenario_ownership_matrix_and_methodology_parity(self):
        evidence = self.evidence()
        payload = self.reasoning(evidence)
        expected = {
            ("main", "base"): ("scenario_main_base", "claim_main"),
            ("main", "counter"): (
                "scenario_main_counter",
                "claim_counter_main",
            ),
            ("main", "invalidation"): (
                "scenario_main_invalidation",
                "claim_invalidation_main",
            ),
            ("maker", "base"): ("scenario_maker_base", "claim_maker"),
            ("maker", "counter"): (
                "scenario_maker_counter",
                "claim_counter_maker",
            ),
            ("maker", "invalidation"): (
                "scenario_maker_invalidation",
                "claim_invalidation_maker",
            ),
        }
        transitions = {
            "base": "retain_certified_assessment",
            "counter": "reassess_on_typed_counter",
            "invalidation": "invalidate_and_recollect_evidence",
        }
        scenarios = {
            (item["account"], item["scenario_type"]): item
            for item in payload["scenario_tree"]
        }
        methodology = {
            (item["account"], item["kind"]): item
            for item in payload["methodology"]["scenario_tree"]
        }
        self.assertEqual(set(scenarios), set(expected))
        self.assertEqual(set(methodology), set(expected))
        for key, (scenario_id, owner_claim_id) in expected.items():
            with self.subTest(account=key[0], scenario_type=key[1]):
                scenario = scenarios[key]
                methodology_item = methodology[key]
                self.assertEqual(
                    set(scenario),
                    {"id", "account", "scenario_type", "owner_claim_id"},
                )
                self.assertEqual(scenario["id"], scenario_id)
                self.assertEqual(scenario["owner_claim_id"], owner_claim_id)
                self.assertEqual(methodology_item["claim_id"], owner_claim_id)
                self.assertEqual(
                    methodology_item["action"],
                    transitions[key[1]],
                )
        accepted = self.evaluate_reasoning_candidate(evidence, payload)
        self.assertTrue(accepted.passed, accepted.defects)

    def test_a5r2f_scenario_unknown_fields_and_owner_drift_fail_closed(self):
        evidence = self.evidence()

        def unknown_prose_field(payload):
            payload["scenario_tree"][0]["condition"] = (
                "自由文本不得重新成为情景条件真相"
            )

        def wrong_top_level_owner(payload):
            scenario = next(
                item
                for item in payload["scenario_tree"]
                if item["id"] == "scenario_main_counter"
            )
            scenario["owner_claim_id"] = "claim_counter_maker"

        def wrong_methodology_owner(payload):
            scenario = next(
                item
                for item in payload["methodology"]["scenario_tree"]
                if item["account"] == "main" and item["kind"] == "counter"
            )
            scenario["claim_id"] = "claim_main"

        def wrong_transition_code(payload):
            scenario = next(
                item
                for item in payload["methodology"]["scenario_tree"]
                if item["account"] == "maker" and item["kind"] == "invalidation"
            )
            scenario["action"] = "retain_certified_assessment"

        for label, mutator, expected_codes in (
            (
                "unknown_top_level_prose",
                unknown_prose_field,
                {"scenario.schema_fields"},
            ),
            (
                "wrong_top_level_owner",
                wrong_top_level_owner,
                {
                    "scenario.owner_claim_binding",
                    "methodology.scenario_owner_drift",
                },
            ),
            (
                "wrong_methodology_owner",
                wrong_methodology_owner,
                {"methodology.scenario_owner_drift"},
            ),
            (
                "wrong_transition_code",
                wrong_transition_code,
                {"methodology.scenario_transition_code"},
            ),
        ):
            with self.subTest(label=label):
                payload = self.reasoning(evidence)
                mutator(payload)
                result = self.evaluate_reasoning_candidate(evidence, payload)
                self.assertTrue(expected_codes.issubset(
                    {item.code for item in result.defects}
                ), result.to_dict())

    def test_a4r2_user_visible_report_never_renders_model_narrative_second_truths(self):
        raw_evidence = self.evidence()
        self.controller.accept_evidence(
            self.run_root, raw_evidence, evidence_files_root=self.root
        )
        evidence = self.controller.store.load_stage_payload(
            self.run_root, "evidence", "evidence"
        )
        reasoning = self.reasoning(evidence)
        coinglass_observation = next(
            item for item in reasoning["observations"] if item["source"] == "Coinglass"
        )
        coinglass_observation["fact"] += "【FACT-SECOND】63971为唯一观察锚。"
        coinglass_observation["metrics"]["main_triad_rationale"] += (
            "【METRIC-SECOND】63971为唯一方向锚。"
        )
        coinglass_observation["metrics"]["pivot"]["extra_narrative"] = "NESTED-SECOND"
        coinglass_observation["metrics"]["liquidation_map"]["levels"][0][
            "extra_narrative"
        ] = "NESTED-SECOND"
        coinglass_observation["visual_review"]["metrics_sha256"] = canonical_sha256(
            coinglass_observation["metrics"]
        )
        tradingview_observation = next(
            item for item in reasoning["observations"] if item["source"] == "TradingView"
        )
        tradingview_observation["metrics"]["chart_component_rationales"][
            "chart.support_resistance"
        ] += "【TV-METRIC-SECOND】63971为唯一盘面锚。"
        tradingview_observation["metrics"]["timeframes"]["1h"][
            "extra_narrative"
        ] = "NESTED-SECOND"
        tradingview_observation["metrics"]["volume_profile"]["zones"][0][
            "extra_narrative"
        ] = "NESTED-SECOND"
        tradingview_observation["visual_review"]["metrics_sha256"] = canonical_sha256(
            tradingview_observation["metrics"]
        )
        maker_claim = next(
            item for item in reasoning["claims"] if item["claim_type"] == "maker_thesis"
        )
        maker_claim["conclusion"] += "委托价固定为63960，保护价64120。"
        maker_claim.setdefault("method_tags", []).append("TAG-SECOND")
        poisoned_result = self.evaluate_reasoning_candidate(evidence, reasoning)
        self.assertFalse(poisoned_result.passed)
        self.assertTrue(poisoned_result.defects)

        # The reasoning gate must reject the poisoned candidate.  The compiler
        # is exercised only with certified reasoning; its recursive closed
        # projection is covered independently by report-compiler semantics.
        reasoning = self.reasoning(evidence)
        self.controller.accept_reasoning(self.run_root, reasoning)
        certified = self.controller.store.load_stage_payload(
            self.run_root, "reasoning", "reasoning"
        )
        poisoned_decision = self.decision(certified)
        injected = "委托价固定为63960，保护价64120；盘口判定为七十分；综合结论改为多方。"
        poisoned_decision["maker"]["orderflow_scorecard"]["rationale"] = injected
        first_chart = next(iter(poisoned_decision["maker"]["chart_scorecard"].values()))
        first_chart["rationale"] = injected
        poisoned_decision["maker"]["winrate_rubric"]["adjustments"][0]["rationale"] += injected
        poisoned_decision_result = evaluate_decision(
            poisoned_decision,
            reasoning=certified,
            run=self.controller.store.load_run(self.run_root),
            pretrade_gate=self.gate,
            root=self.root,
        )
        self.assertFalse(poisoned_decision_result.passed)
        self.assertIn(
            "decision.narrative_execution_second_truth",
            {item.code for item in poisoned_decision_result.defects},
        )

        closed_schema_probe = self.decision(certified)
        closed_schema_probe["main_account"]["rationale"] = "【MAIN-SECOND】"
        closed_schema_probe["maker"]["orderflow_scorecard"]["rationale"] = (
            "【ORDERFLOW-NARRATIVE-SECOND】"
        )
        closed_schema_probe["maker"]["entry_reach_probability_basis"][
            "extra_narrative"
        ] = "BASIS-SECOND"
        first_chart = next(
            iter(closed_schema_probe["maker"]["chart_scorecard"].values())
        )
        first_chart["rationale"] = "【CHART-NARRATIVE-SECOND】"
        decision_result = evaluate_decision(
            closed_schema_probe,
            reasoning=certified,
            run=self.controller.store.load_run(self.run_root),
            pretrade_gate=self.gate,
            root=self.root,
        )
        self.assertFalse(decision_result.passed)

        decision = self.decision(certified)
        self.controller.accept_decision(self.run_root, decision)
        self.controller.compile_report(self.run_root)
        combined = self.controller.store.load_stage_output_record(
            self.run_root, "report", "combined"
        )
        text = (self.root / combined["path"]).read_text(encoding="utf-8")
        canonical = self.controller.store.load_stage_output_record(
            self.run_root, "report", "canonical_report"
        )
        canonical_text = (self.root / canonical["path"]).read_text(encoding="utf-8")
        for forbidden in (
            "委托价固定为63960",
            "保护价64120",
            "七十分",
            "改为多方",
            "FACT-SECOND",
            "METRIC-SECOND",
            "TV-METRIC-SECOND",
            "MAIN-SECOND",
            "CONT-SECOND",
            "ORDERFLOW-NARRATIVE-SECOND",
            "CHART-NARRATIVE-SECOND",
            "WINRATE-NARRATIVE-SECOND",
            "NESTED-SECOND",
            "TAG-SECOND",
            "BASIS-SECOND",
        ):
            self.assertNotIn(forbidden, text)
            self.assertNotIn(forbidden, canonical_text)
        self.assertIn("**盘口 60／60**", text)
        self.assertIn("TradingView 1D结构当前为偏空，转为偏多", text)
        self.assertIn("Farside ETF流向当前为净流出，转为净流入", text)
        self.assertIn("TradingView15m结构=偏多", text)
        self.assertIn("Coinglass最终主判当前为偏空，转为偏多", text)
        self.assertIn("组合C80", text)
        self.assertIn("当前认证支撑=95、96", text)
        self.assertIn("因此类型化调整=-4个百分点", text)

    def test_a4r2_main_observe_projection_never_says_execute_directional_plan(self):
        _, reasoning = self.prepare_through_reasoning()
        decision = self.decision(reasoning)
        main = decision["main_account"]
        main.update(
            {
                "plan_state": "observe",
                "action": "observe",
                "position_notional_usdt": None,
                "leverage": None,
                "entry_mode": None,
                "entry_zone_basis": None,
                "entries": [],
                "entry_allocations_pct": [],
                "stop_basis": None,
                "stop": None,
                "tp1": None,
                "final_take_profit": None,
                "tp1_close_pct": None,
                "plan_state_reason_code": "no_typed_plan",
            }
        )
        result = evaluate_decision(
            decision,
            reasoning=reasoning,
            run=self.controller.store.load_run(self.run_root),
            pretrade_gate=self.gate,
            root=self.root,
        )
        self.assertTrue(result.passed, result.to_dict())
        self.controller.accept_decision(self.run_root, decision)
        self.controller.compile_report(self.run_root)
        combined = self.controller.store.load_stage_output_record(
            self.run_root, "report", "combined"
        )
        text = (self.root / combined["path"]).read_text(encoding="utf-8")
        self.assertIn("主账户保留做空中线判断，但本轮计划状态为观察", text)
        self.assertNotIn("执行做空中线计划", text)

    def test_attempt_artifacts_are_immutable(self):
        attempt, attempt_root = self.controller.store.begin_attempt(self.run_root, "evidence")
        self.controller.store.write_payload(attempt_root, "evidence.json", {"one": 1})
        with self.assertRaises(FileExistsError):
            self.controller.store.write_payload(attempt_root, "evidence.json", {"two": 2})
        self.assertEqual(attempt, 1)


if __name__ == "__main__":
    unittest.main()
