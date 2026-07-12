"""Validate hash-bound observations, reasoning graph, scoring and conviction.

The contract intentionally separates facts from visual judgments and blocks a
conclusion from becoming report authority unless every load-bearing claim is
traceable to the current immutable evidence snapshot.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from runtime.golden_methodology import (
    normalize_methodology,
    normalize_report_projection,
)


ROOT = Path(__file__).resolve().parents[1]
SCORING_CONTRACT = ROOT / "scoring" / "scoring_contract.json"
SOURCES = {
    "blockbeats",
    "coinglass",
    "exocharts",
    "fedwatch",
    "farside_btc_etf",
    "tradingview",
}
OBSERVATION_KINDS = {"structured_observation", "visual_judgment"}
CONFIDENCE_BANDS = {"low", "medium", "high"}
REQUIRED_CLAIM_TYPES = {
    "market_regime",
    "orderflow_interpretation",
    "chart_interpretation",
    "main_account_thesis",
    "maker_thesis",
    "strongest_counterevidence",
    "invalidation_path",
    "cannot_do",
}
HIGH_IMPACT_CLAIM_TYPES = {
    "market_regime",
    "main_account_thesis",
    "maker_thesis",
    "strongest_counterevidence",
    "invalidation_path",
}
ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{2,79}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SOURCE_EVIDENCE_PREFIXES = {
    "blockbeats": ("blockbeats.",),
    "coinglass": ("coinglass.", "liqheatmap_"),
    "exocharts": ("exocharts.",),
    "fedwatch": ("fedwatch.",),
    "farside_btc_etf": ("farside_btc_etf.",),
    "tradingview": ("tradingview_",),
}


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest_hash(payload: dict[str, Any]) -> str:
    clean = dict(payload)
    clean.pop("contract_sha256", None)
    return hashlib.sha256(
        json.dumps(
            clean,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _decimal(value: Any, field: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not number.is_finite():
        raise ValueError(f"{field} must be finite")
    return number


def _plain(value: Decimal) -> int | float:
    number = float(value)
    return int(number) if number.is_integer() else number


def _text(value: Any, field: str, minimum: int = 1) -> str:
    normalized = str(value or "").strip()
    if len(normalized) < minimum:
        raise ValueError(f"{field} must contain at least {minimum} characters")
    return normalized


def _id(value: Any, field: str) -> str:
    normalized = _text(value, field)
    if not ID_RE.fullmatch(normalized):
        raise ValueError(f"{field} has invalid identifier syntax")
    return normalized


def _timestamp(value: Any, field: str) -> str:
    normalized = _text(value, field)
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include timezone")
    return parsed.isoformat(timespec="seconds")


def _inside(path: Path, root: Path, field: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{field} escapes repository root") from exc
    return resolved


def _load_scoring_contract(root: Path) -> tuple[dict[str, Any], Path]:
    path = root / "scoring" / "scoring_contract.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "trading-scoring-contract-v2":
        raise ValueError("unsupported scoring contract version")
    return payload, path


def _capture_evidence(
    capture_manifest_path: Path,
    trading_date: str,
    slot: str,
    root: Path,
) -> tuple[dict[str, str], dict[str, Any]]:
    capture = _inside(capture_manifest_path, root, "capture manifest")
    allowed_capture_root = (
        root / "runtime_state" / trading_date / "captures" / slot
    ).resolve()
    try:
        capture.relative_to(allowed_capture_root)
    except ValueError as exc:
        raise ValueError("capture manifest is outside current date/slot capture root") from exc
    payload = json.loads(capture.read_text(encoding="utf-8"))
    checks = {
        "date": payload.get("date") == trading_date,
        "slot": payload.get("slot") == slot,
        "success": payload.get("success") is True,
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    if failed:
        raise ValueError("invalid capture manifest: " + ", ".join(failed))
    snapshot = payload.get("evidence_snapshot") or {}
    snapshot_root = (capture.parent.parent.parent / str(snapshot.get("root", ""))).resolve()
    date_root = (root / "runtime_state" / trading_date).resolve()
    try:
        snapshot_root.relative_to(date_root)
    except ValueError as exc:
        raise ValueError("capture evidence snapshot escapes date runtime state") from exc
    evidence: dict[str, str] = {}
    for index, item in enumerate(snapshot.get("files") or []):
        if not isinstance(item, dict):
            raise ValueError(f"capture evidence files[{index}] must be an object")
        relative = str(item.get("path", ""))
        if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError(f"invalid capture evidence path: {relative!r}")
        expected = str(item.get("sha256", ""))
        file_path = (snapshot_root / relative).resolve()
        try:
            file_path.relative_to(snapshot_root)
        except ValueError as exc:
            raise ValueError(f"capture evidence path escapes snapshot: {relative}") from exc
        if not file_path.is_file() or not SHA256_RE.fullmatch(expected):
            raise ValueError(f"capture evidence is missing or invalid: {relative}")
        if _sha256_file(file_path) != expected:
            raise ValueError(f"capture evidence hash mismatch: {relative}")
        evidence[relative] = expected
    if not evidence:
        raise ValueError("capture evidence snapshot is empty")
    return evidence, {
        "path": capture.relative_to(root).as_posix(),
        "sha256": _sha256_file(capture),
    }


def _normalize_observations(
    items: Any,
    evidence: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    if not isinstance(items, list):
        raise ValueError("observations must be an array")
    normalized: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    sources_seen: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"observations[{index}] must be an object")
        item_id = _id(item.get("id"), f"observations[{index}].id")
        if item_id in by_id:
            raise ValueError(f"duplicate observation id: {item_id}")
        source = str(item.get("source", "")).lower()
        if source not in SOURCES:
            raise ValueError(f"observation {item_id} has unsupported source")
        kind = str(item.get("kind", ""))
        if kind not in OBSERVATION_KINDS:
            raise ValueError(f"observation {item_id} has invalid kind")
        refs = item.get("evidence_refs")
        if not isinstance(refs, list) or not refs:
            raise ValueError(f"observation {item_id} requires evidence_refs")
        clean_refs: list[str] = []
        for ref in refs:
            relative = str(ref)
            if relative not in evidence:
                raise ValueError(
                    f"observation {item_id} references evidence outside capture: {relative}"
                )
            if not relative.lower().startswith(SOURCE_EVIDENCE_PREFIXES[source]):
                raise ValueError(
                    f"observation {item_id} source/evidence mismatch: {relative}"
                )
            if relative not in clean_refs:
                clean_refs.append(relative)
        values = item.get("values")
        if kind == "structured_observation" and (
            not isinstance(values, dict) or not values
        ):
            raise ValueError(
                f"structured observation {item_id} requires a non-empty values object"
            )
        uncertainty = _text(item.get("uncertainty"), f"observation {item_id}.uncertainty", 4)
        alternate = item.get("alternate_interpretation")
        if kind == "visual_judgment":
            alternate = _text(
                alternate,
                f"visual observation {item_id}.alternate_interpretation",
                8,
            )
        elif alternate is not None:
            alternate = _text(alternate, f"observation {item_id}.alternate_interpretation", 4)
        if item.get("freshness_status") != "current_slot_valid":
            raise ValueError(
                f"observation {item_id}.freshness_status must be current_slot_valid"
            )
        record = {
            "id": item_id,
            "source": source,
            "kind": kind,
            "observed_at": _timestamp(
                item.get("observed_at"), f"observation {item_id}.observed_at"
            ),
            "window": _text(item.get("window"), f"observation {item_id}.window", 2),
            "freshness_status": "current_slot_valid",
            "statement": _text(
                item.get("statement"), f"observation {item_id}.statement", 8
            ),
            "values": values if isinstance(values, dict) else None,
            "uncertainty": uncertainty,
            "alternate_interpretation": alternate,
            "evidence_refs": clean_refs,
        }
        normalized.append(record)
        by_id[item_id] = record
        sources_seen.add(source)
    missing_sources = sorted(SOURCES - sources_seen)
    if missing_sources:
        raise ValueError("observations missing required sources: " + ", ".join(missing_sources))
    return normalized, by_id


def _normalize_claims(
    items: Any,
    observations: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    if not isinstance(items, list):
        raise ValueError("claims must be an array")
    normalized: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    types_seen: set[str] = set()
    known = set(observations)
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"claims[{index}] must be an object")
        item_id = _id(item.get("id"), f"claims[{index}].id")
        if item_id in known:
            raise ValueError(f"duplicate reasoning node id: {item_id}")
        claim_type = _text(item.get("claim_type"), f"claim {item_id}.claim_type")
        support = item.get("support_ids")
        if not isinstance(support, list) or not support:
            raise ValueError(f"claim {item_id} requires support_ids")
        clean_support = []
        for ref in support:
            ref_id = str(ref)
            if ref_id not in known:
                raise ValueError(
                    f"claim {item_id} references missing or forward support node: {ref_id}"
                )
            if ref_id not in clean_support:
                clean_support.append(ref_id)
        counter = item.get("counter_ids")
        if not isinstance(counter, list):
            raise ValueError(f"claim {item_id}.counter_ids must be an array")
        clean_counter = []
        for ref in counter:
            ref_id = str(ref)
            if ref_id not in known:
                raise ValueError(
                    f"claim {item_id} references missing or forward counter node: {ref_id}"
                )
            if ref_id not in clean_counter:
                clean_counter.append(ref_id)
        confidence = str(item.get("confidence_band", ""))
        if confidence not in CONFIDENCE_BANDS:
            raise ValueError(f"claim {item_id} has invalid confidence_band")
        record = {
            "id": item_id,
            "claim_type": claim_type,
            "statement": _text(item.get("statement"), f"claim {item_id}.statement", 12),
            "support_ids": clean_support,
            "counter_ids": clean_counter,
            "inference": _text(item.get("inference"), f"claim {item_id}.inference", 12),
            "confidence_band": confidence,
            "invalidation": _text(
                item.get("invalidation"), f"claim {item_id}.invalidation", 8
            ),
        }
        normalized.append(record)
        by_id[item_id] = record
        known.add(item_id)
        types_seen.add(claim_type)
    missing_types = sorted(REQUIRED_CLAIM_TYPES - types_seen)
    if missing_types:
        raise ValueError("claims missing required types: " + ", ".join(missing_types))
    for claim in normalized:
        if claim["claim_type"] in HIGH_IMPACT_CLAIM_TYPES and not claim["counter_ids"]:
            raise ValueError(
                f"high-impact claim {claim['id']} requires explicit counter evidence"
            )
    return normalized, by_id


def _claim_sources(
    claim_ids: list[str],
    observations: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
) -> set[str]:
    sources: set[str] = set()
    pending = list(claim_ids)
    seen: set[str] = set()
    while pending:
        node_id = pending.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        if node_id in observations:
            sources.add(observations[node_id]["source"])
        elif node_id in claims:
            pending.extend(claims[node_id]["support_ids"])
    return sources


def _normalize_score(
    score: Any,
    observations: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    policy: dict[str, Any],
    methodology: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(score, dict):
        raise ValueError("score must be an object")
    maker = policy["maker_score"]
    orderflow = score.get("orderflow")
    if not isinstance(orderflow, dict):
        raise ValueError("score.orderflow must be an object")
    value = _decimal(orderflow.get("value"), "score.orderflow.value")
    orderflow_policy = maker["orderflow"]
    minimum_score = Decimal(str(orderflow_policy["minimum_score"]))
    maximum_score = Decimal(str(orderflow_policy["maximum_score"]))
    if value < minimum_score or value > maximum_score:
        raise ValueError("orderflow score is outside the 0..70 policy range")
    if orderflow_policy.get("integer_only") is True and value != value.to_integral_value():
        raise ValueError("orderflow score must be an integer")
    extreme = orderflow.get("extreme_confirmed") is True
    extreme_score = Decimal(str(orderflow_policy["extreme_score"]))
    combination_id = str(methodology["same_pivot_orderflow"]["combination_id"])
    extreme_candidates = {
        str(item) for item in orderflow_policy["extreme_candidate_combinations"]
    }
    is_extreme_candidate = combination_id in extreme_candidates
    if value == extreme_score and not extreme:
        raise ValueError("orderflow 70 requires extreme_confirmed=true")
    if extreme and value != extreme_score:
        raise ValueError("extreme_confirmed=true is valid only for orderflow score 70")
    if extreme and not is_extreme_candidate:
        raise ValueError(
            f"orderflow 70 requires one of {sorted(extreme_candidates)}, got {combination_id}"
        )
    if not extreme and value > Decimal(str(orderflow_policy["non_extreme_max"])):
        raise ValueError("non-extreme orderflow score exceeds policy maximum")
    if orderflow.get("extreme_signature") not in (None, {}):
        raise ValueError("extreme_signature is retired; C01-C81 is derived from methodology")
    dimensions = orderflow.get("dimensions")
    if not isinstance(dimensions, dict):
        raise ValueError("score.orderflow.dimensions must be an object")
    normalized_dimensions: dict[str, list[str]] = {}
    for dimension in maker["orderflow"]["required_dimensions"]:
        refs = dimensions.get(dimension)
        if not isinstance(refs, list) or not refs:
            raise ValueError(f"orderflow score missing dimension: {dimension}")
        clean = []
        for ref in refs:
            ref_id = str(ref)
            if ref_id not in claims:
                raise ValueError(
                    f"orderflow dimension {dimension} must reference claim ids"
                )
            if ref_id not in clean:
                clean.append(ref_id)
        normalized_dimensions[dimension] = clean
    orderflow_claim_ids = [
        claim_id for refs in normalized_dimensions.values() for claim_id in refs
    ]
    orderflow_sources = _claim_sources(orderflow_claim_ids, observations, claims)
    if orderflow_sources != {"coinglass", "exocharts"}:
        raise ValueError(
            "orderflow score requires Coinglass+Exocharts-only provenance"
        )
    chart = score.get("chart")
    if not isinstance(chart, dict):
        raise ValueError("score.chart must be an object")
    components = chart.get("components")
    if not isinstance(components, dict):
        raise ValueError("score.chart.components must be an object")
    normalized_components: dict[str, dict[str, Any]] = {}
    chart_total = Decimal("0")
    expected_components = maker["chart"]["components"]
    if set(components) != set(expected_components):
        raise ValueError("chart score component set differs from scoring contract")
    for factor_id, maximum in expected_components.items():
        item = components[factor_id]
        if not isinstance(item, dict):
            raise ValueError(f"chart component {factor_id} must be an object")
        points = _decimal(item.get("points"), f"chart component {factor_id}.points")
        if points < 0 or points > Decimal(str(maximum)):
            raise ValueError(f"chart component {factor_id} exceeds allowed range")
        if maker["chart"].get("integer_only") is True and points != points.to_integral_value():
            raise ValueError(f"chart component {factor_id} points must be an integer")
        refs = item.get("claim_ids")
        if not isinstance(refs, list) or not refs:
            raise ValueError(f"chart component {factor_id} requires claim_ids")
        clean_refs = []
        for ref in refs:
            ref_id = str(ref)
            if ref_id not in claims:
                raise ValueError(f"chart component {factor_id} references missing claim")
            if ref_id not in clean_refs:
                clean_refs.append(ref_id)
        chart_sources = _claim_sources(clean_refs, observations, claims)
        if chart_sources != {"tradingview"}:
            raise ValueError(
                f"chart component {factor_id} must use TradingView-only provenance"
            )
        if item.get("directional_use") is not False:
            raise ValueError(
                f"chart component {factor_id} must set directional_use=false"
            )
        normalized_components[factor_id] = {
            "points": _plain(points),
            "max_points": maximum,
            "claim_ids": clean_refs,
            "rationale": _text(
                item.get("rationale"), f"chart component {factor_id}.rationale", 12
            ),
            "directional_use": False,
        }
        chart_total += points
    if chart.get("score_semantics") != maker["chart"]["score_semantics"]:
        raise ValueError(
            "chart score must be opportunity_quality_not_direction"
        )
    claimed_chart = _decimal(chart.get("total"), "score.chart.total")
    if claimed_chart != chart_total:
        raise ValueError("chart total does not equal component sum")
    total = value + chart_total
    claimed_total = _decimal(score.get("total"), "score.total")
    if claimed_total != total:
        raise ValueError("score total does not equal orderflow + chart")
    return {
        "orderflow": {
            "value": _plain(value),
            "extreme_confirmed": extreme,
            "combination_id": combination_id,
            "extreme_candidate": is_extreme_candidate,
            "dimensions": normalized_dimensions,
            "holistic_rationale": _text(
                orderflow.get("holistic_rationale"),
                "score.orderflow.holistic_rationale",
                20,
            ),
        },
        "chart": {
            "components": normalized_components,
            "total": _plain(chart_total),
            "score_semantics": maker["chart"]["score_semantics"],
            "directional_use": False,
        },
        "total": _plain(total),
        "formula": maker["formula"],
    }


def _normalize_conviction(
    payload: Any,
    claims: dict[str, dict[str, Any]],
    policy: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("conviction must be an object")
    expected = policy["conviction"]
    if payload.get("metric_kind") != expected["metric_kind"]:
        raise ValueError("conviction metric_kind must be plan_time_conviction")
    if payload.get("calibrated_probability") is not False:
        raise ValueError("conviction must not claim calibrated probability")
    anchor = _decimal(payload.get("anchor"), "conviction.anchor")
    adjustments = payload.get("adjustments")
    if not isinstance(adjustments, list):
        raise ValueError("conviction.adjustments must be an array")
    normalized = []
    total_delta = Decimal("0")
    ids: set[str] = set()
    for index, item in enumerate(adjustments):
        if not isinstance(item, dict):
            raise ValueError(f"conviction.adjustments[{index}] must be an object")
        item_id = _id(item.get("id"), f"conviction.adjustments[{index}].id")
        if item_id in ids:
            raise ValueError(f"duplicate conviction adjustment id: {item_id}")
        ids.add(item_id)
        delta = _decimal(item.get("delta"), f"conviction adjustment {item_id}.delta")
        refs = item.get("claim_ids")
        if not isinstance(refs, list) or not refs:
            raise ValueError(f"conviction adjustment {item_id} requires claim_ids")
        clean_refs = []
        for ref in refs:
            ref_id = str(ref)
            if ref_id not in claims:
                raise ValueError(
                    f"conviction adjustment {item_id} references missing claim"
                )
            if ref_id not in clean_refs:
                clean_refs.append(ref_id)
        normalized.append(
            {
                "id": item_id,
                "delta": _plain(delta),
                "claim_ids": clean_refs,
                "rationale": _text(
                    item.get("rationale"),
                    f"conviction adjustment {item_id}.rationale",
                    8,
                ),
            }
        )
        total_delta += delta
    final = anchor + total_delta
    if final < 0 or final > 100:
        raise ValueError("conviction final must be between 0 and 100")
    claimed = _decimal(payload.get("final"), "conviction.final")
    if claimed != final:
        raise ValueError("conviction final does not equal anchor + adjustments")
    return {
        "metric_kind": expected["metric_kind"],
        "calibrated_probability": False,
        "report_label": expected["report_label"],
        "anchor": _plain(anchor),
        "adjustments": normalized,
        "adjustment_total": _plain(total_delta),
        "final": _plain(final),
    }


def build_reasoning_contract(
    payload: dict[str, Any],
    *,
    capture_manifest_path: Path,
    root: Path = ROOT,
) -> dict[str, Any]:
    trading_date = _text(payload.get("trading_date"), "trading_date")
    slot = str(payload.get("slot", ""))
    if slot not in {"morning", "midday", "evening"}:
        raise ValueError("slot must be morning, midday or evening")
    evidence, capture_record = _capture_evidence(
        capture_manifest_path, trading_date, slot, root
    )
    policy, policy_path = _load_scoring_contract(root)
    observations, observations_by_id = _normalize_observations(
        payload.get("observations"), evidence
    )
    claims, claims_by_id = _normalize_claims(
        payload.get("claims"), observations_by_id
    )
    methodology_policy = policy.get("gold_methodology")
    if not isinstance(methodology_policy, dict):
        raise ValueError("scoring contract is missing gold_methodology policy")
    methodology = normalize_methodology(
        payload.get("methodology"), observations_by_id, claims_by_id,
        methodology_policy,
    )
    report_projection = normalize_report_projection(
        payload.get("report_projection"), observations_by_id, claims_by_id,
        methodology_policy,
    )
    score = _normalize_score(
        payload.get("score"), observations_by_id, claims_by_id, policy, methodology
    )
    conviction = _normalize_conviction(payload.get("conviction"), claims_by_id, policy)
    decision = payload.get("decision")
    if not isinstance(decision, dict):
        raise ValueError("decision must be an object")
    primary = str(decision.get("primary_claim_id", ""))
    strongest_counter = str(decision.get("strongest_counter_claim_id", ""))
    invalidation = str(decision.get("invalidation_claim_id", ""))
    if primary not in claims_by_id:
        raise ValueError("decision primary_claim_id is missing")
    if strongest_counter not in claims_by_id or claims_by_id[strongest_counter]["claim_type"] != "strongest_counterevidence":
        raise ValueError("decision strongest counter claim is invalid")
    if invalidation not in claims_by_id or claims_by_id[invalidation]["claim_type"] != "invalidation_path":
        raise ValueError("decision invalidation claim is invalid")
    competing = decision.get("competing_claim_ids")
    if not isinstance(competing, list) or not competing:
        raise ValueError("decision requires competing_claim_ids")
    clean_competing = []
    for ref in competing:
        ref_id = str(ref)
        if ref_id not in claims_by_id or ref_id == primary:
            raise ValueError("decision competing claim is invalid")
        if ref_id not in clean_competing:
            clean_competing.append(ref_id)
    normalized: dict[str, Any] = {
        "schema_version": "trading-reasoning-contract-v2",
        "trading_date": trading_date,
        "slot": slot,
        "capture_manifest": capture_record,
        "scoring_contract": {
            "path": policy_path.relative_to(root).as_posix(),
            "sha256": _sha256_file(policy_path),
            "schema_version": policy["schema_version"],
        },
        "observations": observations,
        "claims": claims,
        "methodology": methodology,
        "report_projection": report_projection,
        "score": score,
        "conviction": conviction,
        "decision": {
            "primary_claim_id": primary,
            "competing_claim_ids": clean_competing,
            "strongest_counter_claim_id": strongest_counter,
            "invalidation_claim_id": invalidation,
            "residual_uncertainty": _text(
                decision.get("residual_uncertainty"),
                "decision.residual_uncertainty",
                8,
            ),
        },
    }
    normalized["contract_sha256"] = _manifest_hash(normalized)
    return normalized


def validate_reasoning_contract_file(
    path: Path,
    trading_date: str,
    slot: str,
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    resolved = _inside(path, root, "reasoning contract")
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "trading-reasoning-contract-v2":
        raise ValueError("unsupported reasoning contract version")
    if payload.get("trading_date") != trading_date or payload.get("slot") != slot:
        raise ValueError("reasoning contract date/slot mismatch")
    if payload.get("contract_sha256") != _manifest_hash(payload):
        raise ValueError("reasoning contract hash mismatch")
    capture = root / str((payload.get("capture_manifest") or {}).get("path", ""))
    rebuilt = build_reasoning_contract(
        {
            "trading_date": trading_date,
            "slot": slot,
            "observations": payload.get("observations"),
            "claims": payload.get("claims"),
            "methodology": payload.get("methodology"),
            "report_projection": payload.get("report_projection"),
            "score": payload.get("score"),
            "conviction": payload.get("conviction"),
            "decision": payload.get("decision"),
        },
        capture_manifest_path=capture,
        root=root,
    )
    if rebuilt != payload:
        raise ValueError("reasoning contract differs from deterministic rebuild")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--capture-manifest", required=True, type=Path)
    parser.add_argument("--date", required=True)
    parser.add_argument("--slot", required=True, choices=("morning", "midday", "evening"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if payload.get("trading_date") != args.date or payload.get("slot") != args.slot:
        raise SystemExit("input date/slot mismatch")
    contract = build_reasoning_contract(
        payload,
        capture_manifest_path=args.capture_manifest,
        root=ROOT,
    )
    target = args.output or (
        ROOT / "runtime_state" / args.date / f"reasoning_contract_{args.slot}.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)
    print(
        json.dumps(
            {"status": "VALID", "output": str(target), "sha256": contract["contract_sha256"]},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
