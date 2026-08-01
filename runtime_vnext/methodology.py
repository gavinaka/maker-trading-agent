"""Versioned methodology manifest without runtime document concatenation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .reasoning_submission import (
    load_reasoning_submission_contract,
    validate_contract_runtime_compatibility,
)


ROOT = Path(__file__).resolve().parents[1]

PHASE_FILES: dict[str, tuple[str, ...]] = {
    "evidence": (
        "data_sources/required_sources.md",
        "data_sources/source_rules.md",
        "data_sources/freshness_rules.md",
        "data_sources/blockbeats_rules.md",
        "data_sources/collectors/blockbeats.md",
        "data_sources/collectors/coinglass.md",
        "data_sources/collectors/exocharts.md",
        "data_sources/collectors/farside_btc_etf.md",
        "data_sources/collectors/fedwatch.md",
        "data_sources/rate_expectation_provider_contract.json",
        "data_sources/collectors/tradingview.md",
        "scoring/scoring_contract.json",
    ),
    "reasoning": (
        "constitution/trading_constitution.md",
        "constitution/cannot_do_mapping.md",
        "constitution/maker_principles.md",
        "execution/main_account.md",
        "execution/maker_execution.md",
        "execution/entry_models.md",
        "scoring/reasoning_submission_contract.json",
        "scoring/golden_report_reasoning_alignment.md",
        "scoring/scoring_contract.json",
        "scoring/orderflow_methodology.md",
        "scoring/orderflow_scoring.md",
        "scoring/chart_methodology.md",
        "scoring/chart_scoring.md",
        "scoring/reasoning_depth_checklist.md",
        "scoring/score_thresholds.md",
        "scoring/winrate_methodology.md",
        "risk/risk_checklist.md",
        "risk/entry_exit_rules.md",
        "risk/floating_defense.md",
    ),
    "report": (
        "governance/vnext_golden_sample_contract.json",
        "governance/vnext_report_presentation_contract.json",
        "governance/vnext_report_language_contract.md",
    ),
}

CONTROL_PLANE_FILES: tuple[str, ...] = (
    "AGENTS.md",
    ".agents/skills/daily-report/SKILL.md",
    "runtime_vnext/artifacts.py",
    "runtime_vnext/cli.py",
    "runtime_vnext/controller.py",
    "runtime_vnext/delivery_renderer.py",
    "runtime_vnext/effort_policy.py",
    "runtime_vnext/errors.py",
    "runtime_vnext/gates.py",
    "runtime_vnext/golden_samples.py",
    "runtime_vnext/legacy_capture_adapter.py",
    "runtime_vnext/methodology.py",
    "runtime_vnext/plan_semantics.py",
    "runtime_vnext/pretrade_gate.py",
    "runtime_vnext/rate_expectation.py",
    "runtime_vnext/report_compiler.py",
    "runtime_vnext/reasoning_pipeline.py",
    "runtime_vnext/reasoning_submission.py",
    "runtime_vnext/sample_outcome.py",
    "runtime_vnext/semantic_validation.py",
    "governance/vnext_daily_workflow.md",
    "governance/vnext_sample_outcome_contract.json",
    "runtime/golden_methodology.py",
    "runtime/host_capability.py",
    "tools/browser_capture/capture_all.js",
    "tools/browser_capture/capture_delta.js",
    "tools/browser_capture/capture_blockbeats.js",
    "tools/browser_capture/blockbeats_priority.js",
    "tools/browser_capture/capture_coinglass.js",
    "tools/browser_capture/capture_exo.js",
    "tools/browser_capture/exocharts_ui_state.js",
    "tools/browser_capture/capture_farside_btc_etf.js",
    "tools/browser_capture/capture_fedwatch.js",
    "tools/browser_capture/capture_kalshi_feddecision.js",
    "tools/browser_capture/capture_rate_expectation.js",
    "tools/browser_capture/capture_liqheatmap.js",
    "tools/browser_capture/capture_lock.js",
    "tools/browser_capture/capture_tv.js",
    "tools/browser_capture/rate_expectation_state.js",
    "tools/browser_capture/tradingview_profile_state.js",
    "tools/browser_capture/cleanup.js",
    "tools/browser_capture/farside_row_policy.js",
    "tools/browser_capture/package.json",
    "tools/browser_capture/package-lock.json",
    "schemas/capture_run_manifest_schema.json",
    "outputs/daily_publish_contract.py",
    "outputs/daily_payload_builder.py",
    "outputs/blockbeats_card.py",
    "outputs/report_structure_gate.py",
    "outputs/report_lint.py",
    "outputs/word_qa.py",
    "outputs/render_from_combined.py",
)

ADDITIVE_METHOD_MARKERS = {
    "scoring/chart_methodology.md": ("VRVP", "流动性猎杀"),
    "scoring/scoring_contract.json": ("liquidation", "etf"),
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_sha256(payload: dict[str, Any]) -> str:
    clean = dict(payload)
    clean.pop("manifest_sha256", None)
    return sha256_bytes(
        json.dumps(
            clean,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def build_methodology_manifest(*, root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    phases: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    marker_failures: list[str] = []
    for phase, relatives in PHASE_FILES.items():
        records = []
        for relative in relatives:
            path = (root / relative).resolve()
            path.relative_to(root)
            if not path.is_file():
                missing.append(relative)
                continue
            text = path.read_text(encoding="utf-8")
            for marker in ADDITIVE_METHOD_MARKERS.get(relative, ()):
                if marker.lower() not in text.lower():
                    marker_failures.append(f"{relative}:{marker}")
            records.append(
                {
                    "path": relative,
                    "sha256": sha256_file(path),
                    "bytes": path.stat().st_size,
                }
            )
        phase_payload = {"files": records}
        phase_payload["phase_sha256"] = canonical_sha256(phase_payload)
        phases[phase] = phase_payload
    if missing:
        raise ValueError("methodology files missing: " + ", ".join(sorted(missing)))
    if marker_failures:
        raise ValueError(
            "additive methodology markers missing: "
            + ", ".join(sorted(marker_failures))
        )
    full_policy = load_scoring_policy(root=root)
    submission_contract = load_reasoning_submission_contract(root=root)
    contract_issues = validate_contract_runtime_compatibility(
        submission_contract,
        full_policy=full_policy,
    )
    if contract_issues:
        raise ValueError(
            "reasoning submission contract is incompatible: "
            + "; ".join(
                f"{item.code}@{item.path}:{item.message}"
                for item in contract_issues
            )
        )
    control_records = []
    for relative in CONTROL_PLANE_FILES:
        path = (root / relative).resolve()
        path.relative_to(root)
        if not path.is_file():
            raise ValueError(f"control-plane file missing: {relative}")
        control_records.append(
            {
                "path": relative,
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
    control_plane: dict[str, Any] = {"files": control_records}
    control_plane["control_sha256"] = canonical_sha256(control_plane)
    payload: dict[str, Any] = {
        "schema_version": "methodology-manifest-v2",
        "policy": "phase-scoped-authority-plus-hashed-control-plane-no-concatenated-transport",
        "phases": phases,
        "control_plane": control_plane,
    }
    payload["manifest_sha256"] = canonical_sha256(payload)
    return payload


def load_scoring_policy(*, root: Path = ROOT) -> dict[str, Any]:
    path = root / "scoring" / "scoring_contract.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "maker_score" not in payload:
        raise ValueError("scoring contract is invalid")
    maker = payload.get("maker_score") or {}
    chart = (maker.get("chart") or {}).get("components")
    if (
        not isinstance(maker.get("threshold"), int)
        or not isinstance(chart, dict)
        or not chart
        or any(not isinstance(value, int) or value <= 0 for value in chart.values())
    ):
        raise ValueError("scoring contract maker score is invalid")
    source_roles = ((payload.get("gold_methodology") or {}).get("source_roles") or {})
    required_roles = {
        "blockbeats",
        "coinglass",
        "exocharts",
        "fedwatch",
        "farside_btc_etf",
        "tradingview",
    }
    if set(source_roles) != required_roles:
        raise ValueError("scoring contract source role set is invalid")
    for name, role in source_roles.items():
        paths = role.get("required_value_paths") if isinstance(role, dict) else None
        if not isinstance(paths, list) or not paths:
            raise ValueError(f"scoring contract source role is incomplete: {name}")
    profile_policy = payload.get("tradingview_profile_policy") or {}
    if (
        profile_policy.get("source_mode") != "user_drawn_manual_only"
        or profile_policy.get("platform_indicator_policy") != "hide_and_never_use"
        or profile_policy.get("automated_numeric_values_allowed") is not False
        or profile_policy.get("coinglass_substitution_allowed") is not False
        or profile_policy.get("directional_use") is not False
        or profile_policy.get("insufficient_liquidity_hunt_score") != 0
        or profile_policy.get("state_sidecar_filename") != "tradingview_profile_state.json"
        or profile_policy.get("state_sidecar_schema_version") != "tradingview-profile-state-v2"
        or profile_policy.get("state_sidecar_binding_schema_version")
        != "tradingview-profile-capture-binding-v1"
        or profile_policy.get("state_sidecar_identity_fields")
        != ["capture_run_id", "capture_nonce"]
        or set(profile_policy.get("allowed_certification_bases") or [])
        != {"profile_control", "certified_legend_inventory", "unverified"}
        or profile_policy.get("certified_absence_basis")
        != "certified_legend_inventory"
        or profile_policy.get("state_sidecar_write_failure_behavior")
        != "profile_dimension_insufficient_non_blocking"
        or profile_policy.get("uncertified_platform_indicator_behavior")
        != "profile_dimension_insufficient"
        or set(profile_policy.get("allowed_statuses") or []) != {"readable", "insufficient"}
        or set(profile_policy.get("allowed_platform_indicator_states") or [])
        != {"hidden", "absent", "visible", "unknown"}
        or set(profile_policy.get("readable_platform_indicator_states") or []) != {"hidden", "absent"}
        or set(profile_policy.get("allowed_zone_timeframes") or [])
        != {"1d", "4h", "1h", "15m"}
        or set(profile_policy.get("allowed_zone_roles") or [])
        != {"value_area", "poc_zone", "hvn_zone", "lvn_zone"}
        or profile_policy.get("unreadable_manual_profile_behavior")
        != "profile_dimension_insufficient_no_inference"
    ):
        raise ValueError("TradingView manual profile policy is invalid")
    risk = payload.get("risk_execution") or {}
    instruments = risk.get("maker_instruments")
    right_entry_policy = risk.get("right_entry_confirmation_policy") or {}
    entry_reach_probability_policy = (
        risk.get("entry_reach_probability_applicability") or {}
    )
    if (
        risk.get("maker_exchange") != "OKX"
        or risk.get("maker_order_method") != "Maker"
        or risk.get("maker_fixed_leverage") != 5
        or risk.get("maker_entry_types") != ["left", "right"]
        or risk.get("maker_non_directional_entry_type") != "not_applicable"
        or right_entry_policy
        != {
            "status": "fail_closed_until_typed_confirmation_basis",
            "constructible_in_decision_model_v7": False,
            "authority": "execution/entry_models.md",
        }
        or entry_reach_probability_policy
        != {
            "allowed_statuses": [
                "applicable",
                "not_applicable_no_certified_entry_geometry",
            ],
            "applicable_requires": [
                "certified_tradingview_entry_zone",
                "at_least_one_typed_candidate_entry_within_zone",
                "complete_tradingview_1h_reach_geometry",
            ],
            "not_applicable_probability_value": None,
            "not_applicable_geometry_fields_must_be_null": [
                "reference_entry",
                "entry_distance",
                "reach_direction",
            ],
            "numeric_zero_is_not_a_null_sentinel": True,
            "compiler_may_infer_or_coerce": False,
        }
        or not isinstance(instruments, dict)
        or set(instruments) != {"BTCUSDT", "ETHUSDT"}
        or set(risk.get("cannot_do_codes") or []) != {"做多", "追多", "做空", "追空", "追多空"}
    ):
        raise ValueError("scoring contract Maker execution policy is invalid")
    lifecycle_policy = risk.get("maker_order_lifecycle") or {}
    if (
        lifecycle_policy.get("schema_version") != "maker-order-lifecycle-v1"
        or lifecycle_policy.get("gate_derives_exact_object") is not True
        or lifecycle_policy.get("actual_fill_probability_is_not_estimated") is not True
        or lifecycle_policy.get("compiler_may_infer_or_rewrite") is not False
    ):
        raise ValueError("scoring contract Maker order lifecycle policy is invalid")
    for instrument, limits in instruments.items():
        if (
            not isinstance(limits, dict)
            or not isinstance(limits.get("minimum_position_notional_usdt"), (int, float))
            or not isinstance(limits.get("maximum_position_notional_usdt"), (int, float))
            or limits["minimum_position_notional_usdt"] > limits["maximum_position_notional_usdt"]
        ):
            raise ValueError(f"scoring contract Maker notional range is invalid: {instrument}")
    liquidation_ownership = (
        (payload.get("gold_methodology") or {}).get(
            "liquidation_confirmation_ownership"
        )
        or {}
    )
    if liquidation_ownership != {
        "raw_liquidation_map_owner": "Coinglass observation",
        "confirmation_result_owner": "liquidation_confirmation claim",
        "required_direct_observation_sources": ["Coinglass"],
        "required_direct_claim_types": ["chart_interpretation"],
        "raw_tradingview_observation_bypass_forbidden": True,
        "insufficient_manual_profile_result": "neutral",
    }:
        raise ValueError("scoring contract liquidation ownership policy is invalid")
    return payload
