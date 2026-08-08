"""Evidence-stage production validation owner."""

from __future__ import annotations

import json
import re
import struct
import zipfile
import zlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from itertools import combinations
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from runtime.golden_methodology import (
    derive_combination_id,
    validate_effect_divergence,
    validate_oi_price_context,
)

from ..methodology import canonical_sha256, load_scoring_policy, sha256_file
from ..domain_ir.projection import (
    account_current_basis_projection,
    account_trigger_logic_projection,
)
from ..domain_ir.registry import (
    ACCOUNT_CURRENT_BASIS_POLICY_FIELDS,
    ACCOUNT_LOOP_CLAIM_TYPES,
    CANNOT_DO_CODES,
    CLAIM_ACCOUNT_SCOPES,
    CLAIM_TYPES as REQUIRED_CLAIM_TYPES,
    CONTINUITY_ACTIONS,
    CONTINUITY_PRIOR_STATUSES,
    EVIDENCE_SOURCE_ORDER as REQUIRED_SOURCES,
    HIGH_IMPACT_CLAIMS,
    MINIMUM_OBSERVATION_METRICS,
    NON_ACTION_REPORT_SECTIONS,
    NON_TRACEABLE_REPORT_SECTIONS,
    POLICY_SOURCE_KEYS,
    REPORT_SECTIONS as REQUIRED_REPORT_SECTIONS,
    SCENARIO_TYPES as REQUIRED_SCENARIO_TYPES,
    SECTION_REQUIRED_CLAIM_TYPES,
    SOURCE_ROLES,
    SOURCE_ROLE_CLAIM_OWNER,
    STRUCTURED_EVIDENCE_SOURCES,
    TRADINGVIEW_TIMEFRAMES,
    TRIGGER_CONTROL_CLAIM_TYPES,
    TRIGGER_EFFECT_BY_CLAIM_TYPE,
    VISUAL_EVIDENCE_SOURCES,
)
from ..plan_semantics import (
    assess_candidate,
    assess_order_lifecycle,
    classify_evidence_polarity,
    classify_maker_semantic_state,
    cannot_do_conflicts,
    expected_reach_direction,
    resting_maker_order_valid,
    structural_noise_stop_is_outside,
    structure_zone_role_valid,
)
from ..pretrade_gate import validate_pretrade_gate_contract
from ..rate_expectation import (
    RateExpectationError,
    canonical_json_sha256 as rate_canonical_sha256,
    normalize_kalshi_payload,
    validate_cme_result,
    validate_rate_provenance,
)
from ..reasoning_pipeline import validate_reasoning_pipeline
from ..reasoning_submission import (
    derive_methodology_trigger_claim_ids,
    load_reasoning_submission_contract,
    project_observation_mechanical_fields,
)
from ..delivery_renderer import (
    ALLOWED_BACKENDS as WORD_QA_ALLOWED_BACKENDS,
    PASSED_WORD_QA_FIELDS,
    WORD_QA_SCHEMA,
    passed_word_qa_checklist_is_valid,
    passed_word_qa_run_paths_are_valid,
)
from outputs.report_lint import coupling_check

from .common import (
    Defect, GateResult, _canonical_closed_string,
    _canonical_positive_decimal_string, _contains_cjk, _decimal_matches,
    _json_number, _matches_policy_path, _nested_value, _number,
    _parse_iso_datetime, _reachable_trigger_owners, _record_paths,
    _resolve_concrete_value_path, _round_to_step, _text,
    _typed_domain_contains, _typed_domain_intersection,
    _valid_png_dimensions, _validate_file_record, gate_result as _result,
    maker_fill_scenarios,
)

@dataclass(frozen=True)
class SemanticIssue:
    code: str
    message: str
    path: str


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _fedwatch_is_plan_c(evidence: dict[str, Any]) -> bool:
    source = ((evidence.get("sources") or {}).get("FedWatch") or {})
    meta = source.get("meta") if isinstance(source.get("meta"), dict) else {}
    return meta.get("selection_mode") == "kalshi_plan_c_fallback"


def _contains_cjk(value: Any) -> bool:
    return bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", _text(value)))


def _metric_leaf_paths(value: Any, prefix: str = "") -> set[str]:
    if isinstance(value, dict):
        if not value:
            return {prefix} if prefix else set()
        result: set[str] = set()
        for key, item in value.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            result.update(_metric_leaf_paths(item, child))
        return result
    if isinstance(value, list):
        if not value:
            return {prefix} if prefix else set()
        result: set[str] = set()
        for index, item in enumerate(value):
            result.update(_metric_leaf_paths(item, f"{prefix}[{index}]"))
        return result
    return {prefix} if prefix else set()


def _semantic_number(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def _iso_datetime(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(_text(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else None


def _iso_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(_text(value))
    except (TypeError, ValueError):
        return None


def _png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("invalid PNG signature")
    offset = 8
    width = height = 0
    saw_ihdr = saw_idat = saw_iend = False
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        data_start = offset + 8
        data_end = data_start + length
        crc_end = data_end + 4
        if crc_end > len(data):
            raise ValueError("truncated PNG chunk")
        payload = data[data_start:data_end]
        expected_crc = struct.unpack(">I", data[data_end:crc_end])[0]
        actual_crc = zlib.crc32(payload, zlib.crc32(kind)) & 0xFFFFFFFF
        if expected_crc != actual_crc:
            raise ValueError("invalid PNG CRC")
        if kind == b"IHDR":
            if saw_ihdr or length != 13 or offset != 8:
                raise ValueError("invalid PNG IHDR")
            width, height = struct.unpack(">II", payload[:8])
            saw_ihdr = True
        elif kind == b"IDAT":
            saw_idat = True
        elif kind == b"IEND":
            if length != 0:
                raise ValueError("invalid PNG IEND")
            saw_iend = True
            offset = crc_end
            break
        offset = crc_end
    if not (saw_ihdr and saw_idat and saw_iend and width >= 800 and height >= 450):
        raise ValueError("PNG must be complete and at least 800x450")
    if any(byte not in b"\x00\t\n\r " for byte in data[offset:]):
        raise ValueError("unexpected data after PNG IEND")
    return width, height


def _record_map(evidence: dict[str, Any], source: str) -> dict[str, dict[str, Any]]:
    payload = ((evidence.get("sources") or {}).get(source) or {})
    records = payload.get("artifacts")
    if not isinstance(records, list):
        return {}
    return {
        _text(item.get("path")): item
        for item in records
        if isinstance(item, dict) and _text(item.get("path"))
    }


def _validate_observation_server_projection(
    item: dict[str, Any],
    *,
    source: str,
    evidence: dict[str, Any],
    submission_contract: dict[str, Any],
    issues: list[SemanticIssue],
) -> None:
    expected = project_observation_mechanical_fields(
        item,
        source=source,
        evidence=evidence,
        contract=submission_contract,
    )
    observation_id = _text(item.get("id"))
    base_path = f"observations.{observation_id}"
    if item.get("evidence_refs") != expected.get("evidence_refs"):
        issues.append(
            SemanticIssue(
                "observation.server_projection_drift",
                "evidence_refs must equal the sealed same-source artifact inventory",
                f"{base_path}.evidence_refs",
            )
        )

    ownership = submission_contract["server_projection"][
        "observation_mechanical_ownership"
    ]
    contract_source = (
        "FedWatchPlanC"
        if source == "FedWatch" and _fedwatch_is_plan_c(evidence)
        else source
    )
    if contract_source in ownership[
        "structured_artifact_filename_by_contract_source"
    ] and item.get("structured_binding") != expected.get("structured_binding"):
        issues.append(
            SemanticIssue(
                "observation.server_projection_drift",
                "structured_binding must equal its deterministic artifact and metrics binding",
                f"{base_path}.structured_binding",
            )
        )

    if "visual_review" not in item:
        return
    actual_review = (
        item.get("visual_review")
        if isinstance(item.get("visual_review"), dict)
        else {}
    )
    expected_review = (
        expected.get("visual_review")
        if isinstance(expected.get("visual_review"), dict)
        else {}
    )
    for field in ownership["visual_review_hash_fields"]:
        if actual_review.get(field) != expected_review.get(field):
            issues.append(
                SemanticIssue(
                    "observation.server_projection_drift",
                    f"visual_review.{field} must equal its deterministic projection",
                    f"{base_path}.visual_review.{field}",
                )
            )


def _load_bound_json(
    root: Path,
    records: dict[str, dict[str, Any]],
    filename: str,
) -> tuple[str, dict[str, Any], dict[str, Any]] | None:
    matches = [
        (relative, record)
        for relative, record in records.items()
        if Path(relative).name.lower() == filename.lower()
    ]
    if len(matches) != 1:
        return None
    relative, record = matches[0]
    try:
        payload = json.loads((root / relative).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return relative, record, payload


def _extreme_proof_failures(
    *,
    orderflow_policy: dict[str, Any],
) -> list[str]:
    """Keep 70 unavailable until a native structured validator exists.

    Ordinary 0..60 reasoning is unaffected.  Flipping a policy flag alone
    must never revive the retired visual-transcription/self-attestation path.
    Enabling 70 later therefore requires an implemented native-series
    validator plus its own regression suite, not a configuration-only change.
    """

    confirmation = orderflow_policy.get("extreme_confirmation") or {}
    if confirmation.get("production_enabled") is not True:
        return [
            "native structured extreme proof capability is not production-enabled; cap at 60"
        ]
    return [
        "native structured extreme proof validator is not implemented; cap at 60"
    ]


def _enum(
    value: Any,
    allowed: set[str],
    *,
    code: str,
    path: str,
    issues: list[SemanticIssue],
) -> str:
    normalized = _text(value)
    if normalized not in allowed:
        issues.append(
            SemanticIssue(code, f"value must be one of {sorted(allowed)}", path)
        )
    return normalized


def _require_number(
    value: Any,
    *,
    code: str,
    path: str,
    issues: list[SemanticIssue],
    positive: bool = False,
) -> Decimal | None:
    result = _semantic_number(value)
    if result is None or (positive and result <= 0):
        qualifier = "positive " if positive else ""
        issues.append(SemanticIssue(code, f"value must be a finite {qualifier}number", path))
        return None
    return result


def validate_tradingview_profile_capture_binding(
    evidence: dict[str, Any],
) -> list[SemanticIssue]:
    """Validate current-run profile lineage at the existing evidence gate."""

    issues: list[SemanticIssue] = []
    capture_run_id = _text(evidence.get("capture_run_id"))
    identity_pattern = r"[0-9a-f-]{16,64}"
    if not re.fullmatch(identity_pattern, capture_run_id, re.I):
        issues.append(
            SemanticIssue(
                "tradingview.profile_capture_run_invalid",
                "evidence capture_run_id must be a current-run capture identity",
                "capture_run_id",
            )
        )
    binding = evidence.get("tradingview_profile_binding")
    expected_keys = {
        "schema_version",
        "capture_run_id",
        "capture_nonce",
        "sidecar_filename",
        "sidecar_schema_version",
    }
    if not isinstance(binding, dict) or set(binding) != expected_keys:
        issues.append(
            SemanticIssue(
                "tradingview.profile_binding_invalid",
                "TradingView profile binding must contain the exact current-run identity fields",
                "tradingview_profile_binding",
            )
        )
        return issues
    filename = _text(binding.get("sidecar_filename"))
    nonce = _text(binding.get("capture_nonce"))
    if (
        binding.get("schema_version")
        != "tradingview-profile-capture-binding-v1"
        or _text(binding.get("capture_run_id")) != capture_run_id
        or not re.fullmatch(identity_pattern, nonce, re.I)
        or filename != "tradingview_profile_state.json"
        or Path(filename).name != filename
        or binding.get("sidecar_schema_version")
        != "tradingview-profile-state-v2"
    ):
        issues.append(
            SemanticIssue(
                "tradingview.profile_binding_mismatch",
                "TradingView profile binding must match this evidence capture_run_id and a valid nonce",
                "tradingview_profile_binding",
            )
        )
    return issues


def validate_visual_artifacts(
    evidence: dict[str, Any],
    *,
    root: Path,
) -> list[SemanticIssue]:
    """Reject non-PNG or implausibly small screenshot evidence at gate one."""

    issues = validate_tradingview_profile_capture_binding(evidence)
    for source in sorted(VISUAL_EVIDENCE_SOURCES):
        if source == "FedWatch" and _fedwatch_is_plan_c(evidence):
            continue
        png_count = 0
        for relative in _record_map(evidence, source):
            path = f"sources.{source}.artifacts.{Path(relative).name}"
            if Path(relative).suffix.lower() != ".png":
                if Path(relative).suffix.lower() == ".json":
                    continue
                issues.append(
                    SemanticIssue(
                        "artifact.visual_not_png",
                        f"{source} visual evidence must be PNG",
                        path,
                    )
                )
                continue
            png_count += 1
            try:
                _png_dimensions(root / relative)
            except (OSError, ValueError) as exc:
                issues.append(
                    SemanticIssue(
                        "artifact.visual_invalid",
                        f"{source} visual evidence is not a valid production screenshot: {exc}",
                        path,
                    )
                )
        if png_count == 0:
            issues.append(
                SemanticIssue(
                    "artifact.visual_missing",
                    f"{source} requires at least one certified PNG screenshot",
                    f"sources.{source}.artifacts",
                )
            )
    return issues


def _validate_common_observation(
    item: dict[str, Any],
    *,
    source: str,
    evidence: dict[str, Any],
    root: Path,
    structured_artifact_filename: str | None,
    visual_review_not_after: datetime | None,
    issues: list[SemanticIssue],
) -> None:
    path = f"observations.{_text(item.get('id')) or source}"
    is_structured = source in STRUCTURED_EVIDENCE_SOURCES or (
        source == "FedWatch" and _fedwatch_is_plan_c(evidence)
    )
    expected_kind = "structured_observation" if is_structured else "visual_judgment"
    if item.get("kind") != expected_kind:
        issues.append(
            SemanticIssue(
                "observation.kind_mismatch",
                f"{source} must use {expected_kind}",
                f"{path}.kind",
            )
        )
    evidence_source = ((evidence.get("sources") or {}).get(source) or {})
    if item.get("observed_at") != evidence_source.get("observed_at"):
        issues.append(
            SemanticIssue(
                "observation.time_binding",
                f"{source} observed_at must equal its certified capture time",
                f"{path}.observed_at",
            )
        )
    uncertainty = _text(item.get("uncertainty"))
    if len(uncertainty) < 8 or not _contains_cjk(uncertainty):
        issues.append(
            SemanticIssue(
                "observation.uncertainty_missing",
                f"{source} requires a Chinese-readable uncertainty boundary",
                f"{path}.uncertainty",
            )
        )
    metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
    records = _record_map(evidence, source)
    refs = item.get("evidence_refs") if isinstance(item.get("evidence_refs"), list) else []
    ref_set = {_text(value) for value in refs if _text(value)}

    if is_structured:
        filename = structured_artifact_filename
        if not isinstance(filename, str) or not filename:
            issues.append(
                SemanticIssue(
                    "structured.artifact_policy_missing",
                    f"{source} structured artifact filename is absent from the submission contract",
                    f"{path}.structured_binding",
                )
            )
            return
        bound = _load_bound_json(root, records, filename)
        binding = (
            item.get("structured_binding")
            if isinstance(item.get("structured_binding"), dict)
            else {}
        )
        if bound is None:
            issues.append(
                SemanticIssue(
                    "structured.artifact_missing",
                    f"{source} requires exactly one readable {filename}",
                    f"{path}.structured_binding",
                )
            )
        else:
            relative, record, _ = bound
            expected = {
                "artifact_path": relative,
                "artifact_sha256": record.get("sha256"),
                "metrics_sha256": canonical_sha256(metrics),
            }
            for key, value in expected.items():
                if binding.get(key) != value:
                    issues.append(
                        SemanticIssue(
                            "structured.binding_mismatch",
                            f"{source} {key} differs from the certified artifact/metrics",
                            f"{path}.structured_binding.{key}",
                        )
                    )
            if relative not in ref_set:
                issues.append(
                    SemanticIssue(
                        "structured.reference_missing",
                        f"{source} JSON binding must also be an evidence_ref",
                        f"{path}.evidence_refs",
                    )
                )
        return

    alternate = _text(item.get("alternate_interpretation"))
    if len(alternate) < 8 or not _contains_cjk(alternate):
        issues.append(
            SemanticIssue(
                "visual.alternative_missing",
                f"{source} visual judgment requires a Chinese alternate interpretation",
                f"{path}.alternate_interpretation",
            )
        )
    citations = item.get("visual_citations")
    if not isinstance(citations, list) or not citations:
        issues.append(
            SemanticIssue(
                "visual.citations_missing",
                f"{source} requires bounded visual citations",
                f"{path}.visual_citations",
            )
        )
        citations = []
    metric_leaf_paths = _metric_leaf_paths(metrics)
    covered: set[str] = set()
    cited_hashes: list[str] = []
    for index, citation in enumerate(citations):
        citation_path = f"{path}.visual_citations[{index}]"
        if not isinstance(citation, dict):
            issues.append(
                SemanticIssue("visual.citation_invalid", "citation must be an object", citation_path)
            )
            continue
        relative = _text(citation.get("evidence_ref"))
        record = records.get(relative)
        if record is None or relative not in ref_set:
            issues.append(
                SemanticIssue(
                    "visual.citation_unbound",
                    "citation must reference a same-source certified PNG in evidence_refs",
                    f"{citation_path}.evidence_ref",
                )
            )
            continue
        metric_paths = citation.get("metric_paths")
        if not isinstance(metric_paths, list) or not metric_paths or len(metric_paths) > 6:
            issues.append(
                SemanticIssue(
                    "visual.metric_paths_invalid",
                    "each visual citation must cover 1..6 metric paths",
                    f"{citation_path}.metric_paths",
                )
            )
            metric_paths = []
        for metric_path in metric_paths:
            exact_path = _text(metric_path)
            if exact_path not in metric_leaf_paths:
                issues.append(
                    SemanticIssue(
                        "visual.metric_path_unknown",
                        f"visual citation references unknown metric: {metric_path}",
                        f"{citation_path}.metric_paths",
                    )
                )
            elif exact_path:
                covered.add(exact_path)
                timeframe_match = re.fullmatch(
                    r"timeframes\.(1d|4h|1h|15m)\.(?:price|sma20|structure)",
                    exact_path,
                )
                if source == "TradingView" and timeframe_match:
                    expected_name = f"tradingview_btc_{timeframe_match.group(1)}.png"
                    if Path(relative).name.lower() != expected_name:
                        issues.append(
                            SemanticIssue(
                                "visual.timeframe_citation_mismatch",
                                f"{exact_path} must cite {expected_name}",
                                f"{citation_path}.evidence_ref",
                            )
                        )
        crop = citation.get("crop")
        try:
            width, height = _png_dimensions(root / relative)
        except (OSError, ValueError):
            continue
        if (
            not isinstance(crop, list)
            or len(crop) != 4
            or any(not isinstance(value, int) or isinstance(value, bool) for value in crop)
        ):
            issues.append(
                SemanticIssue(
                    "visual.crop_invalid",
                    "crop must be [x,y,width,height] integers",
                    f"{citation_path}.crop",
                )
            )
        else:
            x, y, crop_width, crop_height = crop
            if (
                x < 0
                or y < 0
                or crop_width < 32
                or crop_height < 32
                or x + crop_width > width
                or y + crop_height > height
            ):
                issues.append(
                    SemanticIssue(
                        "visual.crop_outside_image",
                        "crop must be a non-trivial rectangle inside the cited PNG",
                        f"{citation_path}.crop",
                    )
                )
        cited_hashes.append(_text(record.get("sha256")))
    for key in sorted(metric_leaf_paths - covered):
        issues.append(
            SemanticIssue(
                "visual.metric_uncited",
                f"{source} metric lacks a bounded screenshot citation: {key}",
                f"{path}.metrics.{key}",
            )
        )

    review = item.get("visual_review") if isinstance(item.get("visual_review"), dict) else {}
    if review.get("status") != "confirmed":
        issues.append(
            SemanticIssue(
                "visual.review_unconfirmed",
                f"{source} requires a completed second-pass visual review",
                f"{path}.visual_review.status",
            )
        )
    primary = _text(review.get("primary_reader"))
    reviewer = _text(review.get("reviewer"))
    if not primary or not reviewer or primary.casefold() == reviewer.casefold():
        issues.append(
            SemanticIssue(
                "visual.review_not_separate",
                "primary_reader and reviewer must identify separate review passes",
                f"{path}.visual_review",
            )
        )
    reviewed_at = _iso_datetime(review.get("reviewed_at"))
    observed_at = _iso_datetime(item.get("observed_at"))
    if reviewed_at is None or (observed_at is not None and reviewed_at < observed_at):
        issues.append(
            SemanticIssue(
                "visual.review_time_invalid",
                "reviewed_at must be a timezone-aware time at or after observation",
                f"{path}.visual_review.reviewed_at",
            )
        )
    elif (
        visual_review_not_after is not None
        and reviewed_at > visual_review_not_after
    ):
        issues.append(
            SemanticIssue(
                "visual.review_time_after_attempt_start",
                "reviewed_at cannot be later than the sealed reasoning-attempt start time",
                f"{path}.visual_review.reviewed_at",
            )
        )
    if review.get("metrics_sha256") != canonical_sha256(metrics):
        issues.append(
            SemanticIssue(
                "visual.review_metrics_drift",
                "visual review is not bound to the current metrics",
                f"{path}.visual_review.metrics_sha256",
            )
        )
    expected_evidence_hash = canonical_sha256(
        {"artifact_sha256s": sorted(set(cited_hashes))}
    )
    if review.get("evidence_sha256") != expected_evidence_hash:
        issues.append(
            SemanticIssue(
                "visual.review_evidence_drift",
                "visual review is not bound to the cited screenshot hashes",
                f"{path}.visual_review.evidence_sha256",
            )
        )
    notes = _text(review.get("notes"))
    if len(notes) < 8 or not _contains_cjk(notes):
        issues.append(
            SemanticIssue(
                "visual.review_notes_missing",
                "visual review requires Chinese-readable review notes",
                f"{path}.visual_review.notes",
            )
        )


def _validate_blockbeats(
    item: dict[str, Any],
    evidence: dict[str, Any],
    root: Path,
    policy: dict[str, Any],
    issues: list[SemanticIssue],
) -> None:
    path = f"observations.{_text(item.get('id'))}.metrics"
    metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
    bound = _load_bound_json(root, _record_map(evidence, "BlockBeats"), "blockbeats.json")
    if bound is None:
        return
    _, _, payload = bound
    selected = payload.get("selected_rows")
    if not isinstance(selected, list):
        selected = []
    tiers: list[int] = []
    for row in selected:
        raw = _text(((row or {}).get("analysis_priority") or {}).get("tier")) if isinstance(row, dict) else ""
        match = re.match(r"T([123])", raw)
        if match:
            tiers.append(int(match.group(1)))
    expected_tier = min(tiers) if tiers else None
    expected = {
        "tier": expected_tier,
        "event_window_hours": payload.get("capture_window_hours"),
        "selected_event_count": len(selected),
        "selected_event_sha256": [canonical_sha256(row) for row in selected],
    }
    configured_fields = set(
        ((policy.get("source_roles") or {}).get("blockbeats") or {}).get(
            "vnext_observation_metric_fields"
        )
        or []
    )
    if configured_fields != set(expected):
        issues.append(
            SemanticIssue(
                "blockbeats.metric_contract_invalid",
                "vNext BlockBeats metric-field contract must own the exact artifact-derived field set",
                "scoring.gold_methodology.source_roles.blockbeats.vnext_observation_metric_fields",
            )
        )
    if set(metrics) != configured_fields:
        issues.append(
            SemanticIssue(
                "blockbeats.metric_ownership",
                "BlockBeats observation may contain only artifact-derived event fields; price realization belongs to the cross-source synthesis claim",
                path,
            )
        )
    for key, value in expected.items():
        if metrics.get(key) != value:
            issues.append(
                SemanticIssue(
                    "blockbeats.structured_mismatch",
                    f"BlockBeats {key} must be derived exactly from selected_rows",
                    f"{path}.{key}",
                )
            )


def _validate_farside(
    item: dict[str, Any],
    evidence: dict[str, Any],
    root: Path,
    policy: dict[str, Any],
    issues: list[SemanticIssue],
) -> None:
    path = f"observations.{_text(item.get('id'))}.metrics"
    metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
    bound = _load_bound_json(root, _record_map(evidence, "Farside"), "farside_btc_etf.json")
    if bound is None:
        return
    _, _, payload = bound
    latest = payload.get("latest") if isinstance(payload.get("latest"), dict) else {}
    total = _semantic_number(latest.get("total_usd_m"))
    expected_direction = (
        "inflow" if total is not None and total > 0 else
        "outflow" if total is not None and total < 0 else "flat"
    )
    expected = {
        "latest_complete_date": latest.get("date_iso") or latest.get("date"),
        "latest_total_usd_m": latest.get("total_usd_m"),
        "flow_direction": expected_direction,
    }
    if set(metrics) != set(expected):
        issues.append(
            SemanticIssue(
                "farside.metric_ownership",
                "Farside observation may contain only artifact-derived flow fields; price relation belongs to the cross-source ETF claim",
                path,
            )
        )
    for key, value in expected.items():
        actual = metrics.get(key)
        matches = _semantic_number(actual) == _semantic_number(value) if key == "latest_total_usd_m" else actual == value
        if not matches:
            issues.append(
                SemanticIssue(
                    "farside.structured_mismatch",
                    f"Farside {key} must equal the latest certified row",
                    f"{path}.{key}",
                )
            )
    del policy


def _validate_fedwatch(
    item: dict[str, Any],
    policy: dict[str, Any],
    evidence: dict[str, Any],
    root: Path,
    issues: list[SemanticIssue],
) -> None:
    path = f"observations.{_text(item.get('id'))}.metrics"
    values = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
    if _fedwatch_is_plan_c(evidence):
        bound = _load_bound_json(root, _record_map(evidence, "FedWatch"), "fedwatch.json")
        normalized = bound[2] if bound is not None else {}
        expected_metrics = (
            normalized.get("metrics")
            if isinstance(normalized.get("metrics"), dict)
            else None
        )
        if expected_metrics is None:
            issues.append(
                SemanticIssue(
                    "fedwatch.structured_artifact_invalid",
                    "Plan C fedwatch.json must contain exact normalized metrics",
                    path,
                )
            )
        else:
            if set(values) != set(expected_metrics):
                issues.append(
                    SemanticIssue(
                        "fedwatch.metric_ownership",
                        "Plan C FedWatch observation may contain only normalized artifact metrics",
                        path,
                    )
                )
            for key, expected in expected_metrics.items():
                actual = values.get(key)
                if isinstance(expected, dict) and isinstance(actual, dict):
                    matches = set(actual) == set(expected) and all(
                        _semantic_number(actual.get(bucket)) == _semantic_number(expected.get(bucket))
                        for bucket in expected
                    )
                else:
                    matches = actual == expected
                if not matches:
                    issues.append(
                        SemanticIssue(
                            "fedwatch.structured_mismatch",
                            f"Plan C {key} must equal the independently replayed artifact",
                            f"{path}.{key}",
                        )
                    )
    outcome_pattern_text = _text(policy.get("fedwatch_outcome_key_pattern"))
    outcome_step_bp = policy.get("fedwatch_outcome_step_bp")
    try:
        outcome_pattern = re.compile(outcome_pattern_text)
    except re.error:
        outcome_pattern = None
        issues.append(
            SemanticIssue(
                "fedwatch.outcome_policy_invalid",
                "FedWatch outcome-key policy must be a valid closed regex",
                "scoring.gold_methodology.fedwatch_outcome_key_pattern",
            )
        )
    if not isinstance(outcome_step_bp, int) or isinstance(outcome_step_bp, bool) or outcome_step_bp <= 0:
        issues.append(
            SemanticIssue(
                "fedwatch.outcome_policy_invalid",
                "FedWatch outcome step must be a positive integer",
                "scoring.gold_methodology.fedwatch_outcome_step_bp",
            )
        )
        outcome_step_bp = None
    current = values.get("current_probabilities")
    if not isinstance(current, dict) or not current:
        issues.append(SemanticIssue("fedwatch.current_invalid", "current_probabilities must be a non-empty numeric object", f"{path}.current_probabilities"))
        current = {}
    current_numbers: dict[str, Decimal] = {}
    for key, value in current.items():
        outcome_key = str(key)
        if outcome_pattern is None or outcome_pattern.fullmatch(outcome_key) is None:
            issues.append(
                SemanticIssue(
                    "fedwatch.outcome_key_invalid",
                    "FedWatch outcome key must be hold or a typed cut/hike basis-point bucket",
                    f"{path}.current_probabilities.{outcome_key}",
                )
            )
        elif outcome_key not in {
            "hold",
            "other_unlisted",
            "cut_gt_25bp",
            "hike_gt_25bp",
        } and outcome_step_bp is not None:
            basis_point_match = re.search(r"_([1-9][0-9]*)bp$", outcome_key)
            if (
                basis_point_match is None
                or int(basis_point_match.group(1)) % outcome_step_bp != 0
            ):
                issues.append(
                    SemanticIssue(
                        "fedwatch.outcome_key_invalid",
                        f"FedWatch cut/hike buckets must use {outcome_step_bp}bp increments",
                        f"{path}.current_probabilities.{outcome_key}",
                    )
                )
        number = _require_number(value, code="fedwatch.probability_invalid", path=f"{path}.current_probabilities.{key}", issues=issues)
        if number is not None:
            if not 0 <= number <= 100:
                issues.append(SemanticIssue("fedwatch.probability_range", "probability must be within 0..100", f"{path}.current_probabilities.{key}"))
            current_numbers[str(key)] = number
    if current_numbers and not Decimal("99.8") <= sum(current_numbers.values()) <= Decimal("100.2"):
        issues.append(SemanticIssue("fedwatch.probability_sum", "current probabilities must sum to approximately 100", f"{path}.current_probabilities"))
    for window in ("change_1d", "change_1w", "change_1m"):
        delta = values.get(window)
        if not isinstance(delta, dict) or set(delta) != set(current):
            issues.append(SemanticIssue("fedwatch.delta_keys", f"{window} must contain the same outcomes as current_probabilities", f"{path}.{window}"))
            continue
        total = Decimal("0")
        valid = True
        for key, value in delta.items():
            number = _require_number(value, code="fedwatch.delta_invalid", path=f"{path}.{window}.{key}", issues=issues)
            if number is None:
                valid = False
            else:
                total += number
        if valid and abs(total) > Decimal("0.2"):
            issues.append(SemanticIssue("fedwatch.delta_sum", f"{window} deltas must net to approximately zero", f"{path}.{window}"))
    as_of = _iso_datetime(values.get("data_as_of"))
    fomc = _iso_date(values.get("next_fomc_date"))
    observed = _iso_datetime(item.get("observed_at"))
    if as_of is None:
        issues.append(SemanticIssue("fedwatch.data_as_of_invalid", "data_as_of must be timezone-aware ISO-8601", f"{path}.data_as_of"))
    if fomc is None or (observed is not None and fomc < observed.date()):
        issues.append(SemanticIssue("fedwatch.fomc_date_invalid", "next_fomc_date must be a real date not earlier than the observation", f"{path}.next_fomc_date"))


def _validate_coinglass(
    item: dict[str, Any],
    evidence: dict[str, Any],
    full_policy: dict[str, Any],
    issues: list[SemanticIssue],
) -> None:
    policy = full_policy["gold_methodology"]
    path = f"observations.{_text(item.get('id'))}.metrics"
    values = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
    pivot = values.get("pivot")
    if not isinstance(pivot, dict):
        issues.append(SemanticIssue("coinglass.pivot_invalid", "pivot must be a structured object", f"{path}.pivot"))
        pivot = {}
    _enum(pivot.get("timeframe"), {"1h"}, code="coinglass.pivot_timeframe", path=f"{path}.pivot.timeframe", issues=issues)
    start_price = _require_number(pivot.get("start_price"), code="coinglass.pivot_price", path=f"{path}.pivot.start_price", issues=issues, positive=True)
    end_price = _require_number(pivot.get("end_price"), code="coinglass.pivot_price", path=f"{path}.pivot.end_price", issues=issues, positive=True)
    dominant_leg = _enum(pivot.get("dominant_leg"), set(policy["dominant_legs"]), code="coinglass.dominant_leg", path=f"{path}.pivot.dominant_leg", issues=issues)
    _enum(pivot.get("trendline_status"), set(policy["trendline_statuses"]), code="coinglass.trendline_status", path=f"{path}.pivot.trendline_status", issues=issues)
    if not isinstance(pivot.get("anchor_reset"), bool):
        issues.append(SemanticIssue("coinglass.anchor_reset_type", "anchor_reset must be boolean", f"{path}.pivot.anchor_reset"))
    directions = set(policy["directions"])
    price = _enum(values.get("price_direction"), directions, code="coinglass.price_direction", path=f"{path}.price_direction", issues=issues)
    cvd = _enum(values.get("cvd_direction"), directions, code="coinglass.cvd_direction", path=f"{path}.cvd_direction", issues=issues)
    oi = _enum(values.get("oi_direction"), directions, code="coinglass.oi_direction", path=f"{path}.oi_direction", issues=issues)
    _enum(values.get("funding_direction"), directions, code="coinglass.funding_direction", path=f"{path}.funding_direction", issues=issues)
    funding_sign = _enum(values.get("funding_sign"), set(policy["funding_signs"]), code="coinglass.funding_sign", path=f"{path}.funding_sign", issues=issues)
    if start_price is not None and end_price is not None:
        geometric_price = (
            "up" if end_price > start_price else "down" if end_price < start_price else "flat"
        )
        geometric_leg = {"up": "up", "down": "down", "flat": "range"}[
            geometric_price
        ]
        if price != geometric_price:
            issues.append(
                SemanticIssue(
                    "coinglass.pivot_price_direction_drift",
                    "price_direction must be derived from pivot start/end geometry",
                    f"{path}.price_direction",
                )
            )
        if dominant_leg != geometric_leg:
            issues.append(
                SemanticIssue(
                    "coinglass.pivot_dominant_leg_drift",
                    "dominant_leg must be derived from pivot start/end geometry",
                    f"{path}.pivot.dominant_leg",
                )
            )
    try:
        expected_combination = derive_combination_id(cvd, price, oi, funding_sign, policy)
        if values.get("combination_id") != expected_combination:
            issues.append(SemanticIssue("coinglass.combination_mismatch", f"combination_id must be {expected_combination}", f"{path}.combination_id"))
    except (KeyError, ValueError) as exc:
        issues.append(SemanticIssue("coinglass.combination_invalid", str(exc), f"{path}.combination_id"))
    try:
        validate_effect_divergence(values.get("effect_divergence"), cvd_direction=cvd, price_direction=price, policy=policy)
    except ValueError as exc:
        issues.append(SemanticIssue("coinglass.effect_divergence", str(exc), f"{path}.effect_divergence"))
    price_break = _enum(values.get("price_break_status"), set(policy["price_break_statuses"]), code="coinglass.price_break_status", path=f"{path}.price_break_status", issues=issues)
    if (
        price_break == "new_high_or_breakout" and price != "up"
    ) or (
        price_break == "new_low_or_breakdown" and price != "down"
    ):
        issues.append(
            SemanticIssue(
                "coinglass.price_break_direction_drift",
                "price_break_status conflicts with price_direction",
                f"{path}.price_break_status",
            )
        )
    try:
        validate_oi_price_context(values.get("oi_price_context"), price_direction=price, oi_direction=oi, price_break_status=price_break, policy=policy)
    except ValueError as exc:
        issues.append(SemanticIssue("coinglass.oi_price_context", str(exc), f"{path}.oi_price_context"))
    triad = _enum(values.get("main_triad_direction"), set(policy["triad_directions"]), code="coinglass.triad_direction", path=f"{path}.main_triad_direction", issues=issues)
    if len(_text(values.get("main_triad_rationale"))) < 20 or not _contains_cjk(values.get("main_triad_rationale")):
        issues.append(SemanticIssue("coinglass.triad_rationale", "main_triad_rationale requires at least 20 Chinese-readable characters", f"{path}.main_triad_rationale"))
    _enum(values.get("funding_effect"), set(policy["funding_effects"]), code="coinglass.funding_effect", path=f"{path}.funding_effect", issues=issues)
    final_direction = _enum(values.get("final_direction"), set(policy["triad_directions"]), code="coinglass.final_direction", path=f"{path}.final_direction", issues=issues)
    if values.get("funding_single_variable_flip") is not False:
        issues.append(SemanticIssue("coinglass.funding_flip", "funding_single_variable_flip must be boolean false", f"{path}.funding_single_variable_flip"))
    if final_direction and triad and final_direction != triad:
        issues.append(SemanticIssue("coinglass.final_direction_drift", "funding may change strength but cannot flip the main triad", f"{path}.final_direction"))

    heatmap = values.get("liquidation_map")
    if not isinstance(heatmap, dict):
        issues.append(SemanticIssue("liquidation.map_invalid", "liquidation_map must be an object", f"{path}.liquidation_map"))
        heatmap = {}
    if heatmap.get("role") != policy["liquidation_map_role"]:
        issues.append(SemanticIssue("liquidation.role_drift", "liquidation map must remain auxiliary_only", f"{path}.liquidation_map.role"))
    threshold = _semantic_number(heatmap.get("threshold"))
    if threshold != _semantic_number(policy["liquidation_map_threshold"]):
        issues.append(SemanticIssue("liquidation.threshold_drift", "liquidation threshold must equal the scoring contract", f"{path}.liquidation_map.threshold"))
    observed = _iso_datetime(item.get("observed_at"))
    window_kind = "weekend" if observed is not None and observed.date().weekday() >= 5 else "weekday"
    expected_windows = [str(value).lower() for value in policy["liquidation_capture_windows"][window_kind]]
    actual_windows = heatmap.get("captured_timeframes")
    if actual_windows != expected_windows:
        issues.append(SemanticIssue("liquidation.window_drift", f"captured_timeframes must be {expected_windows} on {window_kind}", f"{path}.liquidation_map.captured_timeframes"))
    records = _record_map(evidence, "Coinglass")
    refs = {_text(value) for value in item.get("evidence_refs", [])} if isinstance(item.get("evidence_refs"), list) else set()
    for window in expected_windows:
        matches = [relative for relative in records if Path(relative).name.lower() == f"liqheatmap_{window}.png"]
        if len(matches) != 1 or matches[0] not in refs:
            issues.append(SemanticIssue("liquidation.artifact_missing", f"fresh hash-bound liqheatmap_{window}.png is required", f"{path}.liquidation_map.captured_timeframes"))
    current_price = _require_number(heatmap.get("current_price"), code="liquidation.current_price", path=f"{path}.liquidation_map.current_price", issues=issues, positive=True)
    levels = heatmap.get("levels")
    if not isinstance(levels, list) or not levels:
        issues.append(SemanticIssue("liquidation.levels_missing", "liquidation map requires at least one evidenced level", f"{path}.liquidation_map.levels"))
        levels = []
    for index, level in enumerate(levels):
        level_path = f"{path}.liquidation_map.levels[{index}]"
        if not isinstance(level, dict):
            issues.append(SemanticIssue("liquidation.level_invalid", "level must be an object", level_path))
            continue
        side = _enum(level.get("side"), {"above", "below"}, code="liquidation.side", path=f"{level_path}.side", issues=issues)
        price_value = _require_number(level.get("price"), code="liquidation.price", path=f"{level_path}.price", issues=issues, positive=True)
        _enum(_text(level.get("timeframe")).lower(), set(expected_windows), code="liquidation.timeframe", path=f"{level_path}.timeframe", issues=issues)
        _enum(level.get("strength"), {"strong", "medium", "weak"}, code="liquidation.strength", path=f"{level_path}.strength", issues=issues)
        if current_price is not None and price_value is not None and ((side == "above" and price_value <= current_price) or (side == "below" and price_value >= current_price)):
            issues.append(SemanticIssue("liquidation.side_price_conflict", "level side conflicts with current_price", level_path))
    if "liquidation_confirmation_result" in values:
        issues.append(
            SemanticIssue(
                "liquidation.metric_ownership",
                "Coinglass owns the raw liquidation map; its relation to the TradingView manual profile belongs only to the cross-source liquidation_confirmation claim",
                f"{path}.liquidation_confirmation_result",
            )
        )


def _validate_exocharts(
    item: dict[str, Any],
    policy: dict[str, Any],
    issues: list[SemanticIssue],
) -> None:
    path = f"observations.{_text(item.get('id'))}.metrics"
    values = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
    if _text(item.get("timeframe")) != "D":
        issues.append(SemanticIssue("exocharts.timeframe_drift", "Exocharts observation must use the certified Daily footprint baseline", f"observations.{_text(item.get('id'))}.timeframe"))
    expected_profile = {
        "exchange": "Bybit",
        "symbol": "BTCUSD",
        "timeframe": "D",
        "tick_multiplier": 120,
        "cluster_type": "Bid-Ask Profile",
        "text_type": "Imbalance",
        "candle_type": "None",
        "fpbs_enabled": True,
        "vwap_enabled": True,
    }
    profile = values.get("capture_profile")
    if not isinstance(profile, dict) or set(profile) != set(expected_profile):
        issues.append(SemanticIssue("exocharts.capture_profile_invalid", "Exocharts capture_profile must contain the complete user-gold configuration", f"{path}.capture_profile"))
    else:
        for key, expected in expected_profile.items():
            if profile.get(key) != expected:
                issues.append(SemanticIssue("exocharts.capture_profile_drift", f"Exocharts {key} must equal {expected!r}", f"{path}.capture_profile.{key}"))
    ohlc = values.get("ohlc")
    if not isinstance(ohlc, dict) or set(ohlc) != {"open", "high", "low", "close"}:
        issues.append(SemanticIssue("exocharts.ohlc_invalid", "OHLC must contain exactly open/high/low/close", f"{path}.ohlc"))
        ohlc = {}
    numbers = {key: _require_number(ohlc.get(key), code="exocharts.ohlc_number", path=f"{path}.ohlc.{key}", issues=issues, positive=True) for key in ("open", "high", "low", "close")}
    if all(value is not None for value in numbers.values()):
        if not numbers["low"] <= min(numbers["open"], numbers["close"]) <= max(numbers["open"], numbers["close"]) <= numbers["high"]:
            issues.append(SemanticIssue("exocharts.ohlc_geometry", "OHLC geometry is internally inconsistent", f"{path}.ohlc"))
    poc = _require_number(values.get("poc"), code="exocharts.poc", path=f"{path}.poc", issues=issues, positive=True)
    if poc is not None and numbers.get("low") is not None and numbers.get("high") is not None and not numbers["low"] <= poc <= numbers["high"]:
        issues.append(SemanticIssue("exocharts.poc_outside", "POC must lie inside the captured OHLC range", f"{path}.poc"))
    for key in ("delta", "cvd", "volume"):
        _require_number(values.get(key), code=f"exocharts.{key}", path=f"{path}.{key}", issues=issues, positive=key == "volume")
    _enum(values.get("cross_check_result"), set(policy["cross_check_results"]), code="exocharts.cross_check", path=f"{path}.cross_check_result", issues=issues)


def _validate_tradingview(
    item: dict[str, Any],
    full_policy: dict[str, Any],
    issues: list[SemanticIssue],
) -> None:
    policy = full_policy["gold_methodology"]
    profile_policy = full_policy["tradingview_profile_policy"]
    path = f"observations.{_text(item.get('id'))}.metrics"
    values = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
    frames = values.get("timeframes")
    expected_frames = set(policy["timeframes"])
    if not isinstance(frames, dict) or set(frames) != expected_frames:
        issues.append(SemanticIssue("tradingview.timeframes_invalid", f"timeframes must contain exactly {sorted(expected_frames)}", f"{path}.timeframes"))
        frames = {}
    for timeframe in policy["timeframes"]:
        frame = frames.get(timeframe)
        frame_path = f"{path}.timeframes.{timeframe}"
        if not isinstance(frame, dict):
            continue
        _require_number(frame.get("price"), code="tradingview.price", path=f"{frame_path}.price", issues=issues, positive=True)
        _enum(frame.get("structure"), {"bullish", "bearish", "range"}, code="tradingview.structure", path=f"{frame_path}.structure", issues=issues)
        if timeframe != "15m" or frame.get("sma20") is not None:
            _require_number(frame.get("sma20"), code="tradingview.sma20", path=f"{frame_path}.sma20", issues=issues, positive=True)
    profile = values.get("volume_profile")
    if not isinstance(profile, dict):
        issues.append(SemanticIssue("tradingview.volume_profile_invalid", "volume_profile must be a structured object", f"{path}.volume_profile"))
        profile = {}
    source_mode = _text(profile.get("source_mode"))
    status = _text(profile.get("status"))
    platform_state = _text(profile.get("platform_indicator_state"))
    if source_mode != profile_policy["source_mode"]:
        issues.append(SemanticIssue("tradingview.profile_source_drift", "volume_profile source_mode must be user_drawn_manual_only", f"{path}.volume_profile.source_mode"))
    _enum(status, set(profile_policy["allowed_statuses"]), code="tradingview.profile_status", path=f"{path}.volume_profile.status", issues=issues)
    _enum(platform_state, set(profile_policy["allowed_platform_indicator_states"]), code="tradingview.platform_profile_state", path=f"{path}.volume_profile.platform_indicator_state", issues=issues)
    if profile.get("platform_vrvp_used") is not False:
        issues.append(SemanticIssue("tradingview.platform_vrvp_forbidden", "platform VRVP must be hidden and never used as evidence", f"{path}.volume_profile.platform_vrvp_used"))
    if profile.get("automated_values_used") is not False:
        issues.append(SemanticIssue("tradingview.automated_profile_values_forbidden", "automated volume-profile values are forbidden in user_drawn_manual_only mode", f"{path}.volume_profile.automated_values_used"))
    forbidden_fields = {
        "poc", "vah", "val", "hvn", "lvn", "hvn_levels", "lvn_levels",
        "value_area_position", "automated_poc", "automated_vah", "automated_val",
    }
    for key in sorted(forbidden_fields & set(profile)):
        issues.append(SemanticIssue("tradingview.profile_point_value_forbidden", f"{key} is forbidden; use a user-drawn price zone instead of a platform/point value", f"{path}.volume_profile.{key}"))
    zones = profile.get("zones")
    if not isinstance(zones, list):
        issues.append(SemanticIssue("tradingview.profile_zones_invalid", "volume_profile.zones must be an array", f"{path}.volume_profile.zones"))
        zones = []
    if status == "readable":
        if platform_state not in set(profile_policy["readable_platform_indicator_states"]):
            issues.append(SemanticIssue("tradingview.profile_contaminated", "readable manual profile requires the platform indicator to be hidden or absent", f"{path}.volume_profile.platform_indicator_state"))
        if not zones:
            issues.append(SemanticIssue("tradingview.manual_profile_zone_missing", "readable manual profile requires at least one user-drawn price zone", f"{path}.volume_profile.zones"))
    elif status == "insufficient":
        if zones:
            issues.append(SemanticIssue("tradingview.insufficient_profile_has_zones", "insufficient manual profile must use zones=[] and must not infer locations", f"{path}.volume_profile.zones"))
        reason = _text(profile.get("reason"))
        if len(reason) < 8 or not _contains_cjk(reason):
            issues.append(SemanticIssue("tradingview.insufficient_profile_reason", "insufficient manual profile requires a Chinese-readable reason", f"{path}.volume_profile.reason"))
    for index, zone in enumerate(zones):
        zone_path = f"{path}.volume_profile.zones[{index}]"
        if not isinstance(zone, dict):
            issues.append(SemanticIssue("tradingview.manual_profile_zone_invalid", "manual profile zone must be an object", zone_path))
            continue
        lower = _require_number(zone.get("lower_bound"), code="tradingview.manual_profile_zone_bound", path=f"{zone_path}.lower_bound", issues=issues, positive=True)
        upper = _require_number(zone.get("upper_bound"), code="tradingview.manual_profile_zone_bound", path=f"{zone_path}.upper_bound", issues=issues, positive=True)
        if lower is not None and upper is not None and lower >= upper:
            issues.append(SemanticIssue("tradingview.manual_profile_zone_geometry", "manual profile zone lower_bound must be below upper_bound", zone_path))
        _enum(_text(zone.get("timeframe")).lower(), set(profile_policy["allowed_zone_timeframes"]), code="tradingview.manual_profile_zone_timeframe", path=f"{zone_path}.timeframe", issues=issues)
        _enum(zone.get("role"), set(profile_policy["allowed_zone_roles"]), code="tradingview.manual_profile_zone_role", path=f"{zone_path}.role", issues=issues)
    basis = values.get("chart_basis")
    if not isinstance(basis, dict):
        issues.append(SemanticIssue("tradingview.chart_basis_missing", "chart_basis must expose the inputs behind all five chart components", f"{path}.chart_basis"))
        basis = {}
    for key in ("support_levels", "resistance_levels"):
        levels = basis.get(key)
        if not isinstance(levels, list) or not levels:
            issues.append(SemanticIssue("tradingview.levels_missing", f"{key} must be a non-empty numeric list", f"{path}.chart_basis.{key}"))
        else:
            for index, value in enumerate(levels):
                _require_number(value, code="tradingview.level_invalid", path=f"{path}.chart_basis.{key}[{index}]", issues=issues, positive=True)
    structure_zones = basis.get("structure_zones")
    if not isinstance(structure_zones, list):
        issues.append(
            SemanticIssue(
                "tradingview.structure_zones_invalid",
                "structure_zones must be an array; use [] when no certified multitimeframe entry zone exists",
                f"{path}.chart_basis.structure_zones",
            )
        )
        structure_zones = []
    for index, zone in enumerate(structure_zones):
        zone_path = f"{path}.chart_basis.structure_zones[{index}]"
        if not isinstance(zone, dict):
            issues.append(
                SemanticIssue(
                    "tradingview.structure_zone_invalid",
                    "structure zone must be an object",
                    zone_path,
                )
            )
            continue
        expected_zone_fields = {"lower_bound", "upper_bound", "timeframe", "role"}
        if set(zone) != expected_zone_fields:
            issues.append(
                SemanticIssue(
                    "tradingview.structure_zone_schema",
                    "structure zone must contain only lower_bound, upper_bound, timeframe and role",
                    zone_path,
                )
            )
        lower = _require_number(
            zone.get("lower_bound"),
            code="tradingview.structure_zone_bound",
            path=f"{zone_path}.lower_bound",
            issues=issues,
            positive=True,
        )
        upper = _require_number(
            zone.get("upper_bound"),
            code="tradingview.structure_zone_bound",
            path=f"{zone_path}.upper_bound",
            issues=issues,
            positive=True,
        )
        if lower is not None and upper is not None and lower >= upper:
            issues.append(
                SemanticIssue(
                    "tradingview.structure_zone_geometry",
                    "structure zone lower_bound must be below upper_bound",
                    zone_path,
                )
            )
        _enum(
            _text(zone.get("timeframe")).lower(),
            set(profile_policy["allowed_zone_timeframes"]),
            code="tradingview.structure_zone_timeframe",
            path=f"{zone_path}.timeframe",
            issues=issues,
        )
        _enum(
            zone.get("role"),
            set(profile_policy["allowed_structure_zone_roles"]),
            code="tradingview.structure_zone_role",
            path=f"{zone_path}.role",
            issues=issues,
        )
    _enum(basis.get("volume_price_state"), {"confirm", "weaken", "neutral", "conflicted", "not_available"}, code="tradingview.volume_price_state", path=f"{path}.chart_basis.volume_price_state", issues=issues)
    _enum(basis.get("trendline_status"), {"intact", "broken", "ambiguous", "not_available"}, code="tradingview.trendline_status", path=f"{path}.chart_basis.trendline_status", issues=issues)
    fib = basis.get("fibonacci_levels")
    if not isinstance(fib, list):
        issues.append(SemanticIssue("tradingview.fibonacci_invalid", "fibonacci_levels must be an array; use [] when unavailable", f"{path}.chart_basis.fibonacci_levels"))
        fib = []
    for index, value in enumerate(fib):
        _require_number(value, code="tradingview.fibonacci_level", path=f"{path}.chart_basis.fibonacci_levels[{index}]", issues=issues, positive=True)
    components = values.get("chart_component_scores")
    maxima = full_policy["maker_score"]["chart"]["components"]
    if not isinstance(components, dict) or set(components) != set(maxima):
        issues.append(SemanticIssue("tradingview.component_set", "chart_component_scores must exactly match the scoring contract", f"{path}.chart_component_scores"))
        components = {}
    for name, maximum in maxima.items():
        value = components.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= maximum:
            issues.append(SemanticIssue("tradingview.component_score", f"{name} must be an integer within 0..{maximum}", f"{path}.chart_component_scores.{name}"))
    if (
        status == "insufficient"
        and components.get("chart.liquidity_hunt")
        != profile_policy["insufficient_liquidity_hunt_score"]
    ):
        issues.append(SemanticIssue("tradingview.insufficient_liquidity_score", "manual profile insufficiency requires chart.liquidity_hunt=0", f"{path}.chart_component_scores.chart.liquidity_hunt"))
    rationales = values.get("chart_component_rationales")
    if not isinstance(rationales, dict) or set(rationales) != set(maxima):
        issues.append(SemanticIssue("tradingview.component_rationales", "chart_component_rationales must cover every chart component", f"{path}.chart_component_rationales"))
        rationales = {}
    for name in maxima:
        rationale = _text(rationales.get(name))
        if len(rationale) < 8 or not _contains_cjk(rationale):
            issues.append(SemanticIssue("tradingview.component_rationale", f"{name} requires a Chinese-readable rationale", f"{path}.chart_component_rationales.{name}"))
    scoring_basis = values.get("chart_scoring_basis")
    expected_scoring_basis = {
        "included_timeframes": ["1d", "4h", "1h"],
        "excluded_timeframes": ["15m"],
        "fifteen_minute_role": "maker_entry_only",
    }
    if scoring_basis != expected_scoring_basis:
        issues.append(SemanticIssue("tradingview.chart_scoring_basis", "chart scoring must use 1d/4h/1h and reserve 15m for Maker entry precision", f"{path}.chart_scoring_basis"))
    fib_points = components.get("chart.fibonacci_trendline")
    if isinstance(fib_points, int) and fib_points > 0 and not fib and basis.get("trendline_status") == "not_available":
        issues.append(SemanticIssue("tradingview.fibonacci_score_ungrounded", "fibonacci/trendline points require an available Fibonacci level or trendline", f"{path}.chart_component_scores.chart.fibonacci_trendline"))


def _validated_tradingview_profile_sidecar(
    evidence: dict[str, Any],
    root: Path,
    profile_policy: dict[str, Any],
) -> tuple[str | None, str | None]:
    """Return the deterministic aggregate state, or unavailable for any invalid sidecar."""

    filename = str(profile_policy["state_sidecar_filename"])
    bound = _load_bound_json(root, _record_map(evidence, "TradingView"), filename)
    if bound is None:
        return None, None
    relative, record, payload = bound
    try:
        target = (root / relative).resolve()
        target.relative_to(root.resolve())
        if (
            not target.is_file()
            or target.stat().st_size != record.get("bytes")
            or sha256_file(target) != record.get("sha256")
        ):
            return None, None
    except (OSError, ValueError):
        return None, None
    binding = evidence.get("tradingview_profile_binding")
    expected_binding_keys = {
        "schema_version",
        "capture_run_id",
        "capture_nonce",
        "sidecar_filename",
        "sidecar_schema_version",
    }
    if not isinstance(binding, dict) or set(binding) != expected_binding_keys:
        return None, None
    capture_run_id = _text(evidence.get("capture_run_id"))
    capture_nonce = _text(binding.get("capture_nonce"))
    identity_pattern = r"[0-9a-f-]{16,64}"
    if (
        binding.get("schema_version")
        != profile_policy["state_sidecar_binding_schema_version"]
        or binding.get("sidecar_filename") != filename
        or binding.get("sidecar_schema_version")
        != profile_policy["state_sidecar_schema_version"]
        or _text(binding.get("capture_run_id")) != capture_run_id
        or not re.fullmatch(identity_pattern, capture_run_id, re.I)
        or not re.fullmatch(identity_pattern, capture_nonce, re.I)
    ):
        return None, None
    if set(payload) != {
        "schema_version",
        "capture_run_id",
        "capture_nonce",
        "source_mode",
        "platform_indicator_policy",
        "aggregate_state",
        "timeframes",
    }:
        return None, None
    if (
        payload.get("schema_version") != profile_policy["state_sidecar_schema_version"]
        or payload.get("capture_run_id") != capture_run_id
        or payload.get("capture_nonce") != capture_nonce
        or payload.get("source_mode") != profile_policy["source_mode"]
        or payload.get("platform_indicator_policy")
        != profile_policy["platform_indicator_policy"]
    ):
        return None, None
    timeframes = payload.get("timeframes")
    expected_timeframes = set(profile_policy["allowed_zone_timeframes"])
    if not isinstance(timeframes, dict) or set(timeframes) != expected_timeframes:
        return None, None
    allowed_states = set(profile_policy["allowed_platform_indicator_states"])
    final_states: list[str] = []
    for timeframe in sorted(expected_timeframes):
        state = timeframes.get(timeframe)
        if not isinstance(state, dict) or set(state) != {
            "initial_state",
            "final_state",
            "correction_attempted",
            "certification_basis",
        }:
            return None, None
        initial = state.get("initial_state")
        final = state.get("final_state")
        attempted = state.get("correction_attempted")
        certification_basis = state.get("certification_basis")
        if initial not in allowed_states or final not in allowed_states:
            return None, None
        if not isinstance(attempted, bool):
            return None, None
        if certification_basis not in set(profile_policy["allowed_certification_bases"]):
            return None, None
        if attempted and initial != "visible":
            return None, None
        if initial == "visible" and not attempted:
            return None, None
        if not attempted and final != initial:
            return None, None
        if attempted and final == "absent":
            return None, None
        expected_basis = (
            profile_policy["certified_absence_basis"]
            if final == "absent"
            else "unverified"
            if final == "unknown"
            else "profile_control"
        )
        if certification_basis != expected_basis:
            return None, None
        final_states.append(final)
    if "visible" in final_states:
        aggregate = "visible"
    elif "unknown" in final_states:
        aggregate = "unknown"
    elif all(state == "absent" for state in final_states):
        aggregate = "absent"
    else:
        aggregate = "hidden"
    if payload.get("aggregate_state") != aggregate:
        return None, None
    return aggregate, relative


def _validate_tradingview_profile_sidecar_binding(
    item: dict[str, Any],
    evidence: dict[str, Any],
    root: Path,
    profile_policy: dict[str, Any],
    issues: list[SemanticIssue],
) -> None:
    """Bind platform state when available; otherwise force the local insufficient branch."""

    metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
    profile = metrics.get("volume_profile") if isinstance(metrics.get("volume_profile"), dict) else {}
    observed_state = _text(profile.get("platform_indicator_state"))
    profile_status = _text(profile.get("status"))
    aggregate_state, relative = _validated_tradingview_profile_sidecar(
        evidence,
        root,
        profile_policy,
    )
    path = f"observations.{_text(item.get('id'))}.metrics.volume_profile"
    if aggregate_state is None:
        if observed_state != "unknown" or profile_status != "insufficient":
            issues.append(SemanticIssue(
                "tradingview.profile_sidecar_fallback_required",
                "missing or invalid profile sidecar requires platform_indicator_state=unknown and status=insufficient",
                path,
            ))
        return
    if observed_state != aggregate_state:
        issues.append(SemanticIssue(
            "tradingview.profile_sidecar_state_mismatch",
            "platform_indicator_state must exactly match the hash-bound profile sidecar aggregate",
            f"{path}.platform_indicator_state",
        ))
    refs = {
        _text(value)
        for value in item.get("evidence_refs", [])
        if _text(value)
    } if isinstance(item.get("evidence_refs"), list) else set()
    if relative not in refs:
        issues.append(SemanticIssue(
            "tradingview.profile_sidecar_reference_missing",
            "the valid profile sidecar must be included in TradingView evidence_refs",
            f"observations.{_text(item.get('id'))}.evidence_refs",
        ))

def _validate_rate_expectation_source(
    payload: dict[str, Any],
    *,
    root: Path | None,
    defects: list[Defect],
) -> None:
    """Certify v2 CME-primary or Kalshi-Plan-C provenance and replayability."""

    source = ((payload.get("sources") or {}).get("FedWatch") or {})
    path = "sources.FedWatch"
    records = _record_paths(source)
    by_name: dict[str, dict[str, Any]] = {}
    for record in records:
        name = Path(_text(record.get("path"))).name
        if name in by_name:
            defects.append(
                Defect(
                    "fedwatch.artifact_name_duplicate",
                    f"FedWatch artifact basename is duplicated: {name}",
                    f"{path}.artifacts",
                )
            )
        by_name[name] = record
    if root is None:
        defects.append(
            Defect(
                "fedwatch.provider_root_missing",
                "evidence v2 provider certification requires an artifact root",
                path,
            )
        )
        return

    try:
        contract_path = root / "data_sources" / "rate_expectation_provider_contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        if not isinstance(contract, dict):
            raise ValueError("provider contract must be an object")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        defects.append(
            Defect(
                "fedwatch.provider_contract_invalid",
                f"rate-expectation provider contract is unreadable: {exc}",
                "data_sources/rate_expectation_provider_contract.json",
            )
        )
        return

    def load_artifact(name: str) -> dict[str, Any]:
        record = by_name.get(name)
        if record is None:
            raise RateExpectationError(f"required artifact is missing: {name}")
        target = (root / _text(record.get("path"))).resolve()
        target.relative_to(root.resolve())
        value = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise RateExpectationError(f"artifact must be a JSON object: {name}")
        return value

    try:
        provenance = load_artifact("rate_expectation_provenance.json")
        validated_meta = validate_rate_provenance(
            provenance,
            contract,
            capture_run_id=_text(payload.get("capture_run_id")),
            artifact_names=set(by_name),
        )
        expected_provenance_keys = {
            "schema_version",
            "logical_source",
            "capture_run_id",
            "selection_mode",
            "provider_id",
            "series_ticker",
            "fallback_reason_code",
            "primary_attempt_artifact_path",
            "raw_artifact_paths",
            "normalized_artifact_path",
            "selected_artifact_paths",
            "provenance_sha256",
        }
        if set(provenance) != expected_provenance_keys:
            raise RateExpectationError("provider provenance fields differ from contract")
        if (
            provenance.get("schema_version") != contract["provenance_schema_version"]
            or provenance.get("logical_source") != contract["logical_source"]
            or provenance.get("capture_run_id") != payload.get("capture_run_id")
            or provenance.get("provenance_sha256")
            != rate_canonical_sha256(provenance, exclude="provenance_sha256")
        ):
            raise RateExpectationError("provider provenance identity or hash is invalid")
        mode = _text(provenance.get("selection_mode"))
        selection = (contract.get("selection_modes") or {}).get(mode)
        if not isinstance(selection, dict):
            raise RateExpectationError("provider selection_mode is unsupported")
        if (
            provenance.get("provider_id") != selection.get("provider_id")
            or provenance.get("series_ticker") != selection.get("series_ticker")
            or provenance.get("primary_attempt_artifact_path")
            != "cme_fedwatch_result.json"
        ):
            raise RateExpectationError("provider provenance differs from selected contract mode")

        expected_meta = {
            "provider_id": selection.get("provider_id"),
            "selection_mode": mode,
            "series_ticker": selection.get("series_ticker"),
            "acquisition_channel": selection.get("acquisition_channel"),
            "method_class": selection.get("method_class"),
            "method_equivalence": selection.get("method_equivalence"),
            "sample_source_class": selection.get("sample_source_class"),
            "quote_basis_code": selection.get("quote_basis_code"),
            "normalization_method_code": selection.get("normalization_method_code"),
            "fallback_reason_code": provenance.get("fallback_reason_code"),
            "provenance_sha256": provenance.get("provenance_sha256"),
        }
        if expected_meta != validated_meta or source.get("meta") != validated_meta:
            raise RateExpectationError("FedWatch source meta differs from sealed provider provenance")

        cme_result = load_artifact("cme_fedwatch_result.json")
        if cme_result.get("capture_run_id") != payload.get("capture_run_id"):
            raise RateExpectationError("CME result capture_run_id differs from evidence")
        if mode == "cme_primary":
            expected_names = {
                "fedwatch.png",
                "cme_fedwatch_result.json",
                "rate_expectation_provenance.json",
            }
            if set(by_name) != expected_names:
                raise RateExpectationError("CME primary artifacts differ from the exact provider set")
            if (
                provenance.get("fallback_reason_code") != "none"
                or provenance.get("raw_artifact_paths") != []
                or provenance.get("normalized_artifact_path") is not None
                or provenance.get("selected_artifact_paths")
                != ["cme_fedwatch_result.json", "fedwatch.png"]
            ):
                raise RateExpectationError("CME primary provenance contains fallback lineage")
            validate_cme_result(cme_result, contract, require_failed=False)
            screenshot = cme_result["output"]
            screenshot_record = by_name["fedwatch.png"]
            if (
                Path(_text(screenshot.get("path"))).name != "fedwatch.png"
                or screenshot.get("sha256") != screenshot_record.get("sha256")
                or screenshot.get("bytes") != screenshot_record.get("bytes")
            ):
                raise RateExpectationError("CME screenshot binding differs from immutable artifact")
            provider_observed_at = _parse_iso_datetime(cme_result.get("completed_at"))
        elif mode == "kalshi_plan_c_fallback":
            expected_names = {
                "cme_fedwatch_result.json",
                "kalshi_feddecision_raw.json",
                "fedwatch.json",
                "rate_expectation_provenance.json",
            }
            if set(by_name) != expected_names:
                raise RateExpectationError("Plan C artifacts differ from the exact provider set")
            if (
                provenance.get("fallback_reason_code")
                not in contract["cme"]["eligible_fallback_codes"]
                or provenance.get("raw_artifact_paths")
                != ["kalshi_feddecision_raw.json"]
                or provenance.get("normalized_artifact_path") != "fedwatch.json"
                or provenance.get("selected_artifact_paths")
                != [
                    "cme_fedwatch_result.json",
                    "fedwatch.json",
                    "kalshi_feddecision_raw.json",
                ]
            ):
                raise RateExpectationError("Plan C provenance lineage is incomplete or unordered")
            validate_cme_result(cme_result, contract, require_failed=True)
            if provenance.get("fallback_reason_code") != cme_result.get("defect_code"):
                raise RateExpectationError("Plan C fallback reason differs from sealed CME failure")
            raw = load_artifact("kalshi_feddecision_raw.json")
            normalized = load_artifact("fedwatch.json")
            replayed = normalize_kalshi_payload(contract, cme_result, raw)
            if normalized != replayed:
                raise RateExpectationError("fedwatch.json differs from independent raw replay")
            if normalized.get("metrics") != replayed.get("metrics"):
                raise RateExpectationError("normalized FedWatch metrics differ from raw replay")
            provider_observed_at = _parse_iso_datetime(raw.get("retrieved_at"))
        else:
            raise RateExpectationError("provider selection_mode is unsupported")
        captured_at = _parse_iso_datetime(payload.get("captured_at"))
        if provider_observed_at is None or captured_at is None:
            raise RateExpectationError("provider/capture time binding is invalid")
        provider_age = captured_at - provider_observed_at
        if provider_age < timedelta(minutes=-5) or provider_age > timedelta(hours=2):
            raise RateExpectationError("provider observation time is outside the capture window")
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        ValueError,
        RateExpectationError,
    ) as exc:
        defects.append(
            Defect(
                "fedwatch.provider_integrity",
                f"rate-expectation provider certification failed: {exc}",
                path,
            )
        )

def evidence_snapshot_sha256(payload: dict[str, Any]) -> str:
    clean = dict(payload)
    clean.pop("snapshot_sha256", None)
    return canonical_sha256(clean)

def evaluate_evidence(
    payload: dict[str, Any],
    *,
    root: Path | None = None,
    expected_contract_sha256: str | None = None,
) -> GateResult:
    defects: list[Defect] = []
    evidence_schema = payload.get("schema_version")
    if evidence_schema not in {"evidence-snapshot-v1", "evidence-snapshot-v2"}:
        defects.append(
            Defect(
                "schema.invalid",
                "expected evidence-snapshot-v1 or evidence-snapshot-v2",
                "schema_version",
            )
        )
    if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", _text(payload.get("trading_date"))):
        defects.append(Defect("date.invalid", "trading_date must be ISO YYYY-MM-DD", "trading_date"))
    if payload.get("slot") not in {"morning", "midday", "evening"}:
        defects.append(Defect("slot.invalid", "slot is invalid", "slot"))
    captured_at = _parse_iso_datetime(payload.get("captured_at"))
    if captured_at is None:
        defects.append(Defect("captured_at.invalid", "captured_at must be an ISO datetime", "captured_at"))
    elif captured_at.astimezone(timezone(timedelta(hours=8))).date().isoformat() != payload.get("trading_date"):
        defects.append(Defect("captured_at.date_mismatch", "captured_at must belong to the trading date in Asia/Shanghai", "captured_at"))
    if expected_contract_sha256 is not None and payload.get("evidence_contract_sha256") != expected_contract_sha256:
        defects.append(Defect("binding.evidence_contract", "evidence snapshot is not bound to the capture contract", "evidence_contract_sha256"))

    sources = payload.get("sources")
    if not isinstance(sources, dict):
        defects.append(Defect("sources.invalid", "sources must be an object", "sources"))
        sources = {}
    missing = [name for name in REQUIRED_SOURCES if name not in sources]
    extra = [name for name in sources if name not in REQUIRED_SOURCES]
    for name in missing:
        defects.append(Defect("source.missing", f"required source is missing: {name}", f"sources.{name}"))
    for name in extra:
        defects.append(Defect("source.unexpected", f"unexpected source: {name}", f"sources.{name}"))

    artifact_paths: list[str] = []
    for name in REQUIRED_SOURCES:
        source = sources.get(name)
        path = f"sources.{name}"
        if not isinstance(source, dict):
            continue
        if source.get("status") != "valid":
            defects.append(Defect("source.invalid", f"{name} status must be valid", f"{path}.status"))
        if source.get("role") != SOURCE_ROLES[name]:
            defects.append(
                Defect(
                    "source.role_drift",
                    f"{name} role must be {SOURCE_ROLES[name]}",
                    f"{path}.role",
                )
            )
        observed_at = _parse_iso_datetime(source.get("observed_at"))
        if observed_at is None:
            defects.append(Defect("source.time_invalid", f"{name} observed_at is invalid", f"{path}.observed_at"))
        elif captured_at is not None:
            age = captured_at - observed_at
            if age < timedelta(minutes=-5) or age > timedelta(hours=2):
                defects.append(Defect("source.capture_time_drift", f"{name} artifact observation time is outside the capture window", f"{path}.observed_at"))
        records = _record_paths(source)
        if not records:
            defects.append(Defect("source.artifact_missing", f"{name} requires evidence artifacts", path))
        for index, record in enumerate(records):
            _validate_file_record(record, path=f"{path}.artifacts[{index}]", defects=defects, root=root)
            relative = _text(record.get("path"))
            if relative:
                try:
                    artifact_key = (
                        str((root / relative).resolve()).casefold()
                        if root is not None
                        else Path(relative).as_posix().casefold()
                    )
                except OSError:
                    artifact_key = Path(relative).as_posix().casefold()
                artifact_paths.append(artifact_key)
        meta = source.get("meta") if isinstance(source.get("meta"), dict) else {}
        if name == "TradingView":
            frames = source.get("timeframes")
            if not isinstance(frames, list):
                frames = []
            if len(frames) != len(set(map(_text, frames))):
                defects.append(Defect("tradingview.timeframe_duplicate", "TradingView timeframe list contains duplicates", f"{path}.timeframes"))
            for frame in sorted(set(map(_text, frames)) - set(TRADINGVIEW_TIMEFRAMES)):
                defects.append(Defect("tradingview.timeframe_unexpected", f"TradingView contains unsupported timeframe: {frame}", f"{path}.timeframes"))
            artifact_frame_counts = {
                frame: sum(_text(record.get("timeframe")) == frame for record in records)
                for frame in TRADINGVIEW_TIMEFRAMES
            }
            for frame in TRADINGVIEW_TIMEFRAMES:
                if frame not in frames:
                    defects.append(Defect("tradingview.timeframe_missing", f"TradingView missing {frame}", f"{path}.timeframes"))
                if artifact_frame_counts[frame] != 1:
                    defects.append(Defect("tradingview.artifact_count", f"TradingView requires exactly one hash-bound {frame} artifact", f"{path}.artifacts"))
        elif name == "BlockBeats":
            expected = {
                "important_only": True,
                "capture_window_hours": 12,
                "window_covered": True,
                "selected_count_required": 3,
                "selected_row_count": 3,
            }
            for key, value in expected.items():
                if meta.get(key) != value:
                    defects.append(Defect("blockbeats.contract", f"BlockBeats {key} must be {value!r}", f"{path}.meta.{key}"))
        elif name == "Farside":
            total = _number(meta.get("latest_total_usd_m"))
            if total is None:
                defects.append(Defect("farside.total_missing", "Farside requires numeric latest_total_usd_m", f"{path}.meta.latest_total_usd_m"))
            latest_text = _text(meta.get("latest_complete_date"))
            if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", latest_text):
                defects.append(Defect("farside.date_missing", "Farside requires the latest complete trading date", f"{path}.meta.latest_complete_date"))
            else:
                try:
                    latest_date = datetime.strptime(latest_text, "%Y-%m-%d").date()
                    trading_date = datetime.strptime(
                        _text(payload.get("trading_date")), "%Y-%m-%d"
                    ).date()
                    age_days = (trading_date - latest_date).days
                    if age_days < 0 or age_days > 7:
                        defects.append(Defect("farside.date_stale", "Farside latest complete date must be current and no more than seven calendar days old", f"{path}.meta.latest_complete_date"))
                except ValueError:
                    defects.append(Defect("farside.date_invalid", "Farside latest complete date is not a real calendar date", f"{path}.meta.latest_complete_date"))
            expected_direction = "inflow" if total is not None and total > 0 else "outflow" if total is not None and total < 0 else "flat"
            if meta.get("flow_direction") != expected_direction:
                defects.append(Defect("farside.direction_mismatch", "Farside flow direction must be derived from latest total", f"{path}.meta.flow_direction"))
            if root is not None:
                farside_records = [
                    record
                    for record in records
                    if Path(_text(record.get("path"))).name == "farside_btc_etf.json"
                ]
                if len(farside_records) != 1:
                    defects.append(Defect("farside.artifact_count", "Farside requires exactly one structured JSON artifact", f"{path}.artifacts"))
                else:
                    try:
                        artifact = json.loads(
                            (root / _text(farside_records[0].get("path"))).read_text(
                                encoding="utf-8"
                            )
                        )
                    except (OSError, UnicodeError, json.JSONDecodeError):
                        artifact = None
                    latest = artifact.get("latest") if isinstance(artifact, dict) else None
                    funds = latest.get("funds") if isinstance(latest, dict) else None
                    published = (
                        [value for value in funds.values() if _number(value) is not None]
                        if isinstance(funds, dict)
                        else []
                    )
                    if not published:
                        defects.append(Defect("farside.incomplete_latest_row", "latest complete Farside row must contain at least one published fund value", f"{path}.artifacts"))
                    if isinstance(latest, dict):
                        if _text(latest.get("date_iso")) != latest_text:
                            defects.append(Defect("farside.meta_date_drift", "Farside meta date differs from the selected complete row", f"{path}.meta.latest_complete_date"))
                        if _number(latest.get("total_usd_m")) != total:
                            defects.append(Defect("farside.meta_total_drift", "Farside meta total differs from the selected complete row", f"{path}.meta.latest_total_usd_m"))
        elif name == "Coinglass":
            try:
                observed_date = datetime.strptime(
                    _text(payload.get("trading_date")), "%Y-%m-%d"
                ).date()
            except ValueError:
                observed_date = None
            expected_windows = (
                ("3d",)
                if observed_date is not None and observed_date.weekday() >= 5
                else ("48h", "24h")
            )
            liquidation_names = {
                Path(_text(record.get("path"))).name.lower()
                for record in records
                if record.get("kind") == "liquidation_map"
            }
            for window in expected_windows:
                expected_name = f"liqheatmap_{window}.png"
                if expected_name not in liquidation_names:
                    defects.append(
                        Defect(
                            "coinglass.liquidation_map_missing",
                            f"Coinglass requires hash-bound {expected_name}",
                            f"{path}.artifacts",
                        )
                    )

    legacy_manifest = payload.get("legacy_capture_manifest")
    if legacy_manifest is not None:
        if not isinstance(legacy_manifest, dict):
            defects.append(Defect("capture_manifest.invalid", "legacy capture manifest record must be an object", "legacy_capture_manifest"))
        else:
            _validate_file_record(
                legacy_manifest,
                path="legacy_capture_manifest",
                defects=defects,
                root=root,
            )
            relative = _text(legacy_manifest.get("path"))
            if relative:
                artifact_paths.append(
                    str((root / relative).resolve()).casefold()
                    if root is not None
                    else Path(relative).as_posix().casefold()
                )

    expected_hash = evidence_snapshot_sha256(payload)
    recorded_hash = _text(payload.get("snapshot_sha256"))
    if recorded_hash and recorded_hash != expected_hash:
        defects.append(Defect("snapshot.hash_mismatch", "evidence snapshot hash does not match content", "snapshot_sha256"))
    if len(artifact_paths) != len(set(artifact_paths)):
        defects.append(Defect("artifact.path_duplicate", "evidence artifact paths must be unique", "sources"))
    if evidence_schema == "evidence-snapshot-v2":
        _validate_rate_expectation_source(payload, root=root, defects=defects)
    if root is not None:
        for issue in validate_visual_artifacts(payload, root=root):
            defects.append(Defect(issue.code, issue.message, issue.path))
    return _result(
        "evidence_integrity",
        defects,
        snapshot_sha256=expected_hash,
        source_count=len(sources),
        artifact_count=len(artifact_paths),
    )

__all__ = ["evaluate_evidence", "evidence_snapshot_sha256"]
