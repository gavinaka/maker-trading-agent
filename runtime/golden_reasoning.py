"""Pre-write golden reasoning contract checks for daily reports."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from runtime.state_store import atomic_json_write


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_RELATIVE = "scoring/golden_report_reasoning_alignment.md"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")


def _file_record(path: Path, root: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"required file is missing: {path}")
    return {
        "path": _relative(path, root),
        "sha256": _sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _manifest_path(trading_date: str, slot: str, root: Path) -> Path:
    return root / "runtime_state" / trading_date / f"golden_reasoning_{slot}.json"


def build_golden_reasoning_manifest(
    trading_date: str,
    slot: str,
    *,
    capture_manifest_path: Path,
    transition_path: Path,
    root: Path = ROOT,
) -> tuple[dict[str, Any], Path]:
    """Record that the compact learned reasoning contract is active pre-write.

    This intentionally does not read or hash historical Word reports. The old
    local reports have already been distilled into CONTRACT_RELATIVE.
    """

    contract = root / CONTRACT_RELATIVE
    capture = capture_manifest_path.resolve()
    transition = transition_path.resolve()
    target = _manifest_path(trading_date, slot, root)
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "ready",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "trading_date": trading_date,
        "slot": slot,
        "policy": "pre_write_reasoning_alignment_not_posthoc_output_padding",
        "historical_sample_runtime_use": "forbidden",
        "historical_sample_policy": (
            "pre-2026-06-26 local Word reports are learned once into the compact "
            "contract and are not runtime inputs for daily reports"
        ),
        "format_alignment_policy": (
            "reasoning_style_depth_and_dimensions_are_hard_aligned; "
            "format_only_needs_near_100_percent_alignment_plus_mechanical_gates"
        ),
        "phase_order": [
            "six_source_capture_manifest_ready",
            "prepare_transition_ready",
            "golden_reasoning_contract_active",
            "pre_md_reasoning_readiness",
            "combined_report_drafting",
            "analysis_lock",
        ],
        "contract": _file_record(contract, root),
        "capture_manifest": _file_record(capture, root),
        "transition": _file_record(transition, root),
        "required_dimensions": [
            "six_source_validation_and_transcription",
            "farside_btc_etf_flow_consistency",
            "sample_derived_reasoning_order_from_june_word_reports",
            "blockbeats_tier_and_price_realization",
            "fedwatch_probability_delta",
            "coinglass_phase_pivot_price_cvd_funding_oi",
            "orderflow_anchor_three_question_check",
            "exocharts_ohlc_poc_delta_cvd_self_consistency",
            "tradingview_1d_4h_1h_15m_sma20_vrvp_trendline",
            "liquidity_period_labels_with_heatmap_auxiliary_only",
            "main_account_fundamentals_before_chart_before_orderflow",
            "maker_orderflow_before_chart_before_fundamentals",
            "account_separation_and_conflict_resolution",
            "absolute_70_30_score_before_threshold_comparison",
            "winrate_rubric_anchor_then_adjustment_then_threshold",
            "execution_probability_separate_from_winrate",
            "risk_reward_and_leverage_math",
            "scenario_refutation_and_invalidation",
            "cannot_do_filled_last",
            "maker_order_lifecycle_cancel_replace",
            "embedded_numeric_evidence_not_anchor_dump",
            "floating_defense_first_layer_4h_extreme",
            "post_lock_prior_plan_and_position_reconciliation_only",
        ],
        "forbidden_alignment_modes": [
            "reading_historical_word_reports_each_run",
            "posthoc_length_padding",
            "posthoc_price_reference_padding",
            "posthoc_rubric_word_stuffing",
            "posthoc_reasoning_backfill",
            "numeric_anchor_dump_as_quality_proxy",
            "copying_prior_direction_scores_winrate_or_risk",
            "reading_actual_positions_before_analysis_lock",
            "sacrificing_reasoning_depth_for_exact_format_clone",
        ],
    }
    atomic_json_write(target, payload)
    return payload, target


def validate_golden_reasoning_manifest(
    trading_date: str,
    slot: str,
    report_path: Path,
    *,
    root: Path = ROOT,
) -> tuple[dict[str, Any], Path]:
    """Block analysis lock unless the reasoning contract existed before the report."""

    target = _manifest_path(trading_date, slot, root)
    if not target.is_file():
        raise ValueError(
            "missing pre-write golden reasoning manifest; rerun prepare before drafting"
        )
    payload = json.loads(target.read_text(encoding="utf-8"))
    if payload.get("status") != "ready":
        raise ValueError("golden reasoning manifest is not ready")
    if payload.get("policy") != "pre_write_reasoning_alignment_not_posthoc_output_padding":
        raise ValueError("golden reasoning manifest policy mismatch")
    if payload.get("historical_sample_runtime_use") != "forbidden":
        raise ValueError("golden reasoning manifest allows historical sample runtime use")

    contract = root / CONTRACT_RELATIVE
    contract_record = payload.get("contract") or {}
    if contract_record.get("sha256") != _sha256_file(contract):
        raise ValueError("golden reasoning contract changed after prepare; rerun prepare")

    for key in ("capture_manifest", "transition"):
        record = payload.get(key) or {}
        path_text = record.get("path")
        if not path_text:
            raise ValueError(f"golden reasoning manifest missing {key} path")
        path = root / path_text
        if record.get("sha256") != _sha256_file(path):
            raise ValueError(f"{key} changed after golden reasoning prepare")

    report = report_path.resolve()
    if not report.is_file():
        raise ValueError(f"report not found for golden reasoning validation: {report}")
    created_at = datetime.fromisoformat(str(payload["created_at"]))
    report_mtime = datetime.fromtimestamp(
        report.stat().st_mtime,
        tz=created_at.tzinfo,
    )
    if created_at.timestamp() > report_mtime.timestamp() + 1:
        raise ValueError(
            "golden reasoning manifest was created after the report; "
            "alignment must happen before drafting, not after MD output"
        )
    return payload, target
