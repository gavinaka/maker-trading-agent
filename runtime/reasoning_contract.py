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
SCORING_CONTRACT_SCHEMA_VERSION = "trading-scoring-contract-v4"
ACCOUNT_CURRENT_BASIS_POLICY_FIELDS = frozenset(
    {
        "schema_version",
        "required_claim_types",
        "required_fields",
        "allowed_modes",
        "minimum_clause_count",
        "clause_required_fields",
        "allowed_operators",
        "observation_fields",
        "claim_fields",
        "evidence_polarity",
        "owner_must_be_reachable_from_support_dag",
        "owner_account_must_be_shared_or_same_account",
        "value_must_equal_current_owner_field",
        "separate_from_future_trigger_logic",
        "compiler_may_infer_missing_current_basis",
    }
)
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
CLAIM_ACCOUNT_SCOPES = {
    "fundamental_context": {"shared"},
    "fundamental_event_realization": {"shared"},
    "fundamental_price_realization": {"shared"},
    "orderflow_interpretation": {"shared"},
    "chart_interpretation": {"shared"},
    "etf_confirmation": {"shared"},
    "liquidation_confirmation": {"shared"},
    "liquidity_hunt": {"shared"},
    "market_regime": {"main", "maker"},
    "strongest_counterevidence": {"main", "maker"},
    "invalidation_path": {"main", "maker"},
    "main_account_thesis": {"main"},
    "maker_thesis": {"maker"},
    "cannot_do": {"maker"},
}
FUNDAMENTAL_REALIZATION_STATES = {
    "realized",
    "partially_realized",
    "not_realized",
    "conflicted",
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
SOURCE_POLICY_NAMES = {
    "blockbeats": "BlockBeats",
    "coinglass": "Coinglass",
    "exocharts": "Exocharts",
    "fedwatch": "FedWatch",
    "farside_btc_etf": "Farside",
    "tradingview": "TradingView",
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


def _nested_value(value: Any, path: str) -> tuple[bool, Any]:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


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
    if payload.get("schema_version") != SCORING_CONTRACT_SCHEMA_VERSION:
        raise ValueError(
            "unsupported scoring contract version: legacy reasoning v2 requires "
            + SCORING_CONTRACT_SCHEMA_VERSION
        )
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


def _normalize_current_basis(
    value: Any,
    *,
    claim_id: str,
    claim_type: str,
    account: str,
    support_ids: list[str],
    observations: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    policy: dict[str, Any],
) -> dict[str, Any]:
    field = f"claim {claim_id}.current_basis"
    if not isinstance(value, dict) or set(value) != set(
        policy.get("required_fields") or []
    ):
        raise ValueError(f"{field} must use the exact typed field set")
    mode = str(value.get("mode", ""))
    if mode not in set(policy.get("allowed_modes") or []):
        raise ValueError(f"{field}.mode is outside the closed authority vocabulary")
    clauses = value.get("clauses")
    minimum = int(policy.get("minimum_clause_count") or 0)
    if not isinstance(clauses, list) or len(clauses) < minimum:
        raise ValueError(f"{field}.clauses requires at least {minimum} clauses")
    reachable: set[str] = set()
    pending = list(support_ids)
    while pending:
        node_id = pending.pop()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        if node_id in claims:
            pending.extend(claims[node_id].get("support_ids") or [])
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    required_clause_fields = set(policy.get("clause_required_fields") or [])
    allowed_operators = set(policy.get("allowed_operators") or [])
    for index, item in enumerate(clauses):
        item_field = f"{field}.clauses[{index}]"
        if not isinstance(item, dict) or set(item) != required_clause_fields:
            raise ValueError(f"{item_field} must use the exact typed clause field set")
        owner_type = str(item.get("owner_type", ""))
        owner_id = str(item.get("owner_id", ""))
        owner_field = str(item.get("field", ""))
        if item.get("operator") not in allowed_operators:
            raise ValueError(f"{item_field}.operator must be equals")
        if owner_id not in reachable:
            raise ValueError(f"{item_field}.owner_id is outside the support DAG")
        if owner_type == "observation":
            owner = observations.get(owner_id)
            if owner is None:
                raise ValueError(f"{item_field}.owner_id is not an observation")
            source = SOURCE_POLICY_NAMES.get(str(owner.get("source", "")), "")
            allowed_values = set(
                ((policy.get("observation_fields") or {}).get(source) or {}).get(
                    owner_field
                )
                or []
            )
            current: Any = owner.get("values")
            for part in owner_field.split("."):
                if not isinstance(current, dict) or part not in current:
                    raise ValueError(f"{item_field}.field is absent from its owner")
                current = current[part]
        elif owner_type == "claim":
            owner = claims.get(owner_id)
            if owner is None:
                raise ValueError(f"{item_field}.owner_id is not a claim")
            owner_claim_type = str(owner.get("claim_type", ""))
            if owner.get("account") not in {"shared", account}:
                raise ValueError(f"{item_field}.owner_id crosses account scope")
            allowed_values = set(
                ((policy.get("claim_fields") or {}).get(owner_claim_type) or {}).get(
                    owner_field
                )
                or []
            )
            current = owner
            for part in owner_field.split("."):
                if not isinstance(current, dict) or part not in current:
                    raise ValueError(f"{item_field}.field is absent from its owner")
                current = current[part]
        else:
            raise ValueError(f"{item_field}.owner_type must be observation or claim")
        if not allowed_values:
            raise ValueError(f"{item_field}.field is outside the typed-owner policy")
        declared = item.get("value")
        if declared not in allowed_values:
            raise ValueError(f"{item_field}.value is outside the typed domain")
        if not (type(declared) is type(current) and declared == current):
            raise ValueError(f"{item_field}.value differs from the current owner field")
        signature = (owner_type, owner_id, owner_field)
        if signature in seen:
            raise ValueError(f"{item_field} duplicates a typed owner")
        seen.add(signature)
        normalized.append(dict(item))
    return {"mode": mode, "clauses": normalized}


def _normalize_claims(
    items: Any,
    observations: dict[str, dict[str, Any]],
    methodology_policy: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    if not isinstance(items, list):
        raise ValueError("claims must be an array")
    normalized: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    types_seen: set[str] = set()
    type_account_seen: set[tuple[str, str]] = set()
    event_hashes_seen: set[str] = set()
    known = set(observations)
    current_basis_policy = methodology_policy.get("account_current_basis")
    if not isinstance(current_basis_policy, dict):
        raise ValueError("gold methodology is missing account_current_basis policy")
    if set(current_basis_policy) != ACCOUNT_CURRENT_BASIS_POLICY_FIELDS:
        raise ValueError("account_current_basis policy has an invalid field set")
    event_policy = methodology_policy.get("fundamental_event_assessment_policy")
    if not isinstance(event_policy, dict):
        raise ValueError(
            "gold methodology is missing fundamental_event_assessment_policy"
        )
    event_claim_type = str(event_policy.get("event_realization_claim_type") or "")
    allowed_event_states = set(event_policy.get("event_realization_states") or [])
    allowed_price_relations = set(methodology_policy.get("price_relations") or [])
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"claims[{index}] must be an object")
        item_id = _id(item.get("id"), f"claims[{index}].id")
        if item_id in known:
            raise ValueError(f"duplicate reasoning node id: {item_id}")
        claim_type = _text(item.get("claim_type"), f"claim {item_id}.claim_type")
        allowed_accounts = CLAIM_ACCOUNT_SCOPES.get(claim_type)
        if allowed_accounts is None:
            raise ValueError(f"claim {item_id} has ungoverned claim_type: {claim_type}")
        account = str(item.get("account", ""))
        if account not in allowed_accounts:
            raise ValueError(
                f"claim {item_id}.account must be one of {sorted(allowed_accounts)}"
            )
        if claim_type != event_claim_type:
            type_account_key = (claim_type, account)
            if type_account_key in type_account_seen:
                raise ValueError(
                    f"claim type/account cardinality must be unique: {claim_type}/{account}"
                )
            type_account_seen.add(type_account_key)
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
            "account": account,
            "statement": _text(item.get("statement"), f"claim {item_id}.statement", 12),
            "support_ids": clean_support,
            "counter_ids": clean_counter,
            "inference": _text(item.get("inference"), f"claim {item_id}.inference", 12),
            "confidence_band": confidence,
            "invalidation": _text(
                item.get("invalidation"), f"claim {item_id}.invalidation", 8
            ),
        }
        if claim_type in {"main_account_thesis", "maker_thesis"}:
            allowed_directions = (
                {"long", "short", "neutral"}
                if claim_type == "main_account_thesis"
                else {"long", "short", "observe"}
            )
            direction = str(item.get("direction", ""))
            if direction not in allowed_directions:
                raise ValueError(
                    f"claim {item_id}.direction must be one of {sorted(allowed_directions)}"
                )
            record["direction"] = direction
        elif "direction" in item:
            raise ValueError(
                f"claim {item_id}.direction is not owned by {claim_type}"
            )
        if claim_type in {"fundamental_price_realization", event_claim_type}:
            realization_state = str(item.get("realization_state", ""))
            allowed_states = (
                allowed_event_states
                if claim_type == event_claim_type
                else FUNDAMENTAL_REALIZATION_STATES
            )
            if realization_state not in allowed_states:
                raise ValueError(
                    f"claim {item_id}.realization_state must be one of "
                    f"{sorted(allowed_states)}"
                )
            record["realization_state"] = realization_state
        elif "realization_state" in item:
            raise ValueError(
                f"claim {item_id}.realization_state is owned only by "
                "fundamental_price_realization or fundamental_event_realization"
            )
        if claim_type == event_claim_type:
            selected_event_sha256 = str(item.get("selected_event_sha256") or "")
            if not SHA256_RE.fullmatch(selected_event_sha256):
                raise ValueError(
                    f"claim {item_id}.selected_event_sha256 must be lowercase SHA-256"
                )
            if selected_event_sha256 in event_hashes_seen:
                raise ValueError(
                    "fundamental_event_realization must be unique per selected-event hash"
                )
            event_hashes_seen.add(selected_event_sha256)
            record["selected_event_sha256"] = selected_event_sha256
        elif "selected_event_sha256" in item:
            raise ValueError(
                f"claim {item_id}.selected_event_sha256 is owned only by "
                "fundamental_event_realization"
            )
        if claim_type == "etf_confirmation":
            price_relation = str(item.get("price_relation") or "")
            if price_relation not in allowed_price_relations:
                raise ValueError(
                    f"claim {item_id}.price_relation is outside the closed ETF relation vocabulary"
                )
            record["price_relation"] = price_relation
        elif "price_relation" in item:
            raise ValueError(
                f"claim {item_id}.price_relation is owned only by etf_confirmation"
            )
        required_current_claim_types = set(
            current_basis_policy.get("required_claim_types")
            or [current_basis_policy.get("required_claim_type")]
        ) - {None, ""}
        if claim_type in required_current_claim_types:
            record["current_basis"] = _normalize_current_basis(
                item.get("current_basis"),
                claim_id=item_id,
                claim_type=claim_type,
                account=account,
                support_ids=clean_support,
                observations=observations,
                claims=by_id,
                policy=current_basis_policy,
            )
        elif "current_basis" in item:
            raise ValueError(
                f"claim {item_id}.current_basis is not owned by {claim_type}"
            )
        normalized.append(record)
        by_id[item_id] = record
        known.add(item_id)
        types_seen.add(claim_type)
    missing_types = sorted(REQUIRED_CLAIM_TYPES - types_seen)
    if missing_types:
        raise ValueError("claims missing required types: " + ", ".join(missing_types))
    for claim in normalized:
        account = claim["account"]
        for ref in [*claim["support_ids"], *claim["counter_ids"]]:
            referenced = by_id.get(ref)
            if referenced is None:
                continue
            referenced_account = referenced["account"]
            if account == "shared" and referenced_account != "shared":
                raise ValueError(
                    f"shared claim {claim['id']} cannot depend on account claim {ref}"
                )
            if account in {"main", "maker"} and referenced_account not in {
                "shared",
                account,
            }:
                raise ValueError(
                    f"{account} claim {claim['id']} cannot depend on "
                    f"{referenced_account} claim {ref}"
                )
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
    if value == extreme_score:
        confirmation = orderflow_policy.get("extreme_confirmation") or {}
        if confirmation.get("production_enabled") is not True:
            raise ValueError(
                "orderflow 70 is unavailable until native structured extreme proof is production-enabled; cap at 60"
            )
        raise ValueError(
            "orderflow 70 is unavailable because the native structured extreme proof validator is not implemented; cap at 60"
        )
    if extreme:
        raise ValueError(
            "extreme_confirmed=true is unavailable until the native structured proof validator is implemented"
        )
    if value > Decimal(str(orderflow_policy["non_extreme_max"])):
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
    observations: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    methodology: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("conviction must be an object")
    expected_fields = {
        "metric_kind",
        "calibrated_probability",
        "anchor",
        "anchor_claim_ids",
        "anchor_rationale",
        "adjustments",
        "counter_resolution",
        "final",
    }
    normalized_fields = expected_fields | {"report_label", "adjustment_total"}
    if frozenset(payload) not in {
        frozenset(expected_fields),
        frozenset(normalized_fields),
    }:
        raise ValueError("conviction must use the exact anchor/adjustment field set")
    expected = policy["conviction"]
    if "report_label" in payload and payload.get("report_label") != expected["report_label"]:
        raise ValueError("conviction report_label differs from policy")
    if payload.get("metric_kind") != expected["metric_kind"]:
        raise ValueError("conviction metric_kind must be plan_time_conviction")
    if payload.get("calibrated_probability") is not False:
        raise ValueError("conviction must not claim calibrated probability")
    anchor_raw = payload.get("anchor")
    if not isinstance(anchor_raw, int) or isinstance(anchor_raw, bool):
        raise ValueError("conviction.anchor must be an integer")
    anchor = Decimal(anchor_raw)
    anchor_claim_ids = payload.get("anchor_claim_ids")
    if (
        not isinstance(anchor_claim_ids, list)
        or not anchor_claim_ids
        or len({str(value) for value in anchor_claim_ids}) != len(anchor_claim_ids)
    ):
        raise ValueError("conviction.anchor_claim_ids must be a non-empty unique array")
    clean_anchor_claim_ids = [str(value) for value in anchor_claim_ids]
    if any(claim_id not in claims for claim_id in clean_anchor_claim_ids):
        raise ValueError("conviction.anchor_claim_ids references a missing claim")
    _text(
        payload.get("anchor_rationale"), "conviction.anchor_rationale", 8
    )
    adjustments = payload.get("adjustments")
    if not isinstance(adjustments, list):
        raise ValueError("conviction.adjustments must be an array")
    normalized = []
    total_delta = Decimal("0")
    adjustment_policy = expected.get("adjustment_policy")
    if not isinstance(adjustment_policy, dict):
        raise ValueError("conviction adjustment policy is missing")
    required_fields = set(adjustment_policy.get("required_adjustment_fields") or [])
    reason_policies = adjustment_policy.get("reason_codes")
    if not required_fields or not isinstance(reason_policies, dict):
        raise ValueError("conviction adjustment reason-code policy is incomplete")

    def support_reachability(root_claim_ids: list[str]) -> tuple[set[str], set[str]]:
        reachable_nodes: set[str] = set()
        pending = list(root_claim_ids)
        while pending:
            node_id = pending.pop()
            if node_id in reachable_nodes:
                continue
            if node_id not in claims and node_id not in observations:
                raise ValueError("conviction support DAG references an unknown node")
            reachable_nodes.add(node_id)
            if node_id in claims:
                pending.extend(str(value) for value in claims[node_id].get("support_ids") or [])
        reachable_sources = {
            SOURCE_POLICY_NAMES.get(str(observations[node_id].get("source") or ""), "")
            for node_id in reachable_nodes
            if node_id in observations
        } - {""}
        return reachable_nodes, reachable_sources

    anchor_policy = expected.get("anchor_policy")
    if not isinstance(anchor_policy, dict):
        raise ValueError("conviction anchor policy is missing")
    anchor_rationale = str(anchor_policy.get("canonical_rationale") or "").strip()
    if len(anchor_rationale) < 8:
        raise ValueError("conviction anchor policy lacks canonical_rationale")
    anchor_claims = [claims[claim_id] for claim_id in clean_anchor_claim_ids]
    allowed_accounts = set(anchor_policy.get("allowed_claim_accounts") or [])
    forbidden_types = set(anchor_policy.get("forbidden_claim_types") or [])
    axis_types = anchor_policy.get("required_claim_types_by_axis")
    source_axes = anchor_policy.get("required_reachable_sources_by_axis")
    optional_types = set(anchor_policy.get("optional_claim_types") or [])
    if (
        not allowed_accounts
        or not isinstance(axis_types, dict)
        or not isinstance(source_axes, dict)
    ):
        raise ValueError("conviction anchor policy is incomplete")
    allowed_types = optional_types | {
        str(claim_type)
        for values in axis_types.values()
        for claim_type in (values if isinstance(values, list) else [])
    }
    for claim in anchor_claims:
        claim_type = str(claim.get("claim_type") or "")
        account = str(claim.get("account") or "")
        if (
            account not in allowed_accounts
            or claim_type in forbidden_types
            or claim_type not in allowed_types
            or (claim_type == "invalidation_path" and account != "maker")
        ):
            raise ValueError("conviction anchor binds a forbidden claim or account")
    for axis, allowed_axis_types in axis_types.items():
        allowed_axis_type_set = set(allowed_axis_types or [])
        axis_claim_ids = [
            claim_id
            for claim_id in clean_anchor_claim_ids
            if str(claims[claim_id].get("claim_type") or "")
            in allowed_axis_type_set
        ]
        if not axis_claim_ids:
            raise ValueError(f"conviction anchor lacks required {axis} axis")
        _, reachable_sources = support_reachability(axis_claim_ids)
        missing_axis_sources = set(source_axes.get(axis) or []) - reachable_sources
        if missing_axis_sources:
            raise ValueError(
                f"conviction anchor {axis} axis lacks sources: {sorted(missing_axis_sources)}"
            )
    maker_claims = [
        claim
        for claim in claims.values()
        if claim.get("claim_type") == "maker_thesis"
    ]
    maker_direction = (
        str(maker_claims[0].get("direction") or "")
        if len(maker_claims) == 1
        else ""
    )
    seen_reason_codes: set[str] = set()
    seen_adjustment_claim_ids: set[str] = set()
    seen_typed_owner_signatures: set[tuple[str, str, str]] = set()
    for index, item in enumerate(adjustments):
        if not isinstance(item, dict):
            raise ValueError(f"conviction.adjustments[{index}] must be an object")
        item_field = f"conviction.adjustments[{index}]"
        if set(item) != required_fields:
            raise ValueError(
                f"{item_field} must use the exact closed reason-code field set"
            )
        reason_code = str(item.get("reason_code") or "")
        reason_policy = reason_policies.get(reason_code)
        if not isinstance(reason_policy, dict):
            raise ValueError(f"{item_field}.reason_code is outside the closed policy")
        if reason_code in seen_reason_codes:
            raise ValueError(f"{item_field}.reason_code duplicates an earlier adjustment")
        seen_reason_codes.add(reason_code)
        delta_raw = item.get("delta")
        if (
            not isinstance(delta_raw, int)
            or isinstance(delta_raw, bool)
            or delta_raw == 0
        ):
            raise ValueError(f"{item_field}.delta must be a non-zero integer")
        delta = Decimal(delta_raw)
        expected_sign = str(reason_policy.get("delta_sign") or "")
        if (
            (expected_sign == "positive" and delta_raw <= 0)
            or (expected_sign == "negative" and delta_raw >= 0)
            or expected_sign not in {"positive", "negative"}
        ):
            raise ValueError(
                f"{item_field}.delta sign differs from reason_code policy"
            )
        refs = item.get("claim_ids")
        if not isinstance(refs, list) or not refs:
            raise ValueError(f"{item_field} requires claim_ids")
        clean_refs = []
        for ref in refs:
            ref_id = str(ref)
            if ref_id not in claims:
                raise ValueError(
                    f"{item_field} references missing claim"
                )
            if ref_id not in clean_refs:
                clean_refs.append(ref_id)
        if len(clean_refs) != len(refs):
            raise ValueError(f"{item_field}.claim_ids must be unique")
        overlap = set(clean_refs) & seen_adjustment_claim_ids
        if overlap:
            raise ValueError(f"{item_field}.claim_ids reuse an earlier adjustment claim")
        if set(clean_refs) & set(clean_anchor_claim_ids):
            raise ValueError(f"{item_field}.claim_ids reuse an anchor claim")
        seen_adjustment_claim_ids.update(clean_refs)
        bound_claims = [claims[ref] for ref in clean_refs]
        allowed_claim_types = set(reason_policy.get("allowed_claim_types") or [])
        if not allowed_claim_types or any(
            str(claim.get("claim_type")) not in allowed_claim_types
            for claim in bound_claims
        ):
            raise ValueError(
                f"{item_field}.claim_ids bind a claim type outside reason_code policy"
            )
        required_claim_account = str(reason_policy.get("required_claim_account") or "")
        if required_claim_account and any(
            str(claim.get("account") or "") != required_claim_account
            for claim in bound_claims
        ):
            raise ValueError(f"{item_field}.claim_ids bind the wrong account")
        reachable_nodes, reachable_sources = support_reachability(clean_refs)
        missing_sources = set(reason_policy.get("required_reachable_sources") or []) - reachable_sources
        if missing_sources:
            raise ValueError(
                f"{item_field}.claim_ids are missing reachable sources: {sorted(missing_sources)}"
            )
        typed_owner_mode = str(reason_policy.get("typed_value_owner_mode") or "")
        typed_values: list[Any] = []
        for owner_spec in reason_policy.get("typed_value_owners") or []:
            if not isinstance(owner_spec, dict):
                raise ValueError(f"{item_field} has invalid typed owner policy")
            owner_type = str(owner_spec.get("owner_type") or "")
            owner_field = str(owner_spec.get("field") or "")
            candidates: list[dict[str, Any]] = []
            if owner_type == "observation":
                source = str(owner_spec.get("source") or "")
                candidates = [
                    observations[node_id]
                    for node_id in reachable_nodes
                    if node_id in observations
                    and SOURCE_POLICY_NAMES.get(
                        str(observations[node_id].get("source") or ""), ""
                    )
                    == source
                ]
                owner_root = candidates[0].get("values") if len(candidates) == 1 else None
                owner_id = str(candidates[0].get("id")) if len(candidates) == 1 else ""
            elif owner_type == "claim":
                owner_claim_type = str(owner_spec.get("claim_type") or "")
                candidates = [
                    claim
                    for claim in bound_claims
                    if claim.get("claim_type") == owner_claim_type
                ]
                owner_root = candidates[0] if len(candidates) == 1 else None
                owner_id = str(candidates[0].get("id")) if len(candidates) == 1 else ""
            else:
                raise ValueError(f"{item_field} has invalid typed owner type")
            found, typed_value = _nested_value(owner_root, owner_field)
            if not found:
                raise ValueError(
                    f"{item_field} cannot resolve its typed current owner"
                )
            value_contract = str(owner_spec.get("value_contract") or "")
            allowed_values = owner_spec.get("allowed_values")
            if value_contract == "certified_source_schema":
                if owner_type != "observation":
                    raise ValueError(
                        f"{item_field} certified source value must be observation-owned"
                    )
            elif typed_value not in set(allowed_values or []):
                raise ValueError(
                    f"{item_field} typed current value is outside reason_code policy"
                )
            signature = (owner_type, owner_id, owner_field)
            if signature in seen_typed_owner_signatures:
                raise ValueError(f"{item_field} reuses a typed owner")
            seen_typed_owner_signatures.add(signature)
            typed_values.append(typed_value)
        if not typed_values and typed_owner_mode != "selected_current_basis_clauses":
            raise ValueError(f"{item_field} requires typed current values")
        direction_relation = str(
            reason_policy.get("typed_value_relation_to_maker_direction") or ""
        )
        if direction_relation:
            typed_direction = {
                "bullish": "long",
                "bearish": "short",
            }.get(str(typed_values[0]))
            relation_valid = (
                typed_direction == maker_direction
                if direction_relation == "same"
                else typed_direction != maker_direction
                if direction_relation == "opposite_or_nonconfirming"
                else False
            )
            if not relation_valid:
                raise ValueError(
                    f"{item_field} typed direction does not satisfy Maker relation"
                )
        normalized.append(
            {
                "reason_code": reason_code,
                "label": _text(item.get("label"), f"{item_field}.label", 2),
                "delta": delta_raw,
                "claim_ids": clean_refs,
                "rationale": _text(
                    item.get("rationale"), f"{item_field}.rationale", 8
                ),
            }
        )
        total_delta += delta

    counter_policy = expected.get("counter_resolution_policy")
    counter_resolution = payload.get("counter_resolution")
    if not isinstance(counter_policy, dict) or not isinstance(counter_resolution, dict):
        raise ValueError("conviction counter_resolution policy or payload is missing")
    required_resolution_fields = set(counter_policy.get("required_fields") or [])
    if not required_resolution_fields or set(counter_resolution) != required_resolution_fields:
        raise ValueError("conviction.counter_resolution differs from the closed schema")
    counter_claim_id = str(counter_resolution.get("counter_claim_id") or "")
    account_separation = (
        methodology.get("account_separation")
        if isinstance(methodology.get("account_separation"), dict)
        else {}
    )
    if counter_claim_id != str(account_separation.get("maker_counter_claim_id") or ""):
        raise ValueError("conviction.counter_resolution must bind the methodology Maker counter")
    counter_claim = claims.get(counter_claim_id)
    if (
        not isinstance(counter_claim, dict)
        or counter_claim.get("claim_type") != "strongest_counterevidence"
        or counter_claim.get("account") != "maker"
    ):
        raise ValueError("conviction.counter_resolution binds an invalid Maker counter")
    disposition = str(counter_resolution.get("disposition") or "")
    if disposition not in set(counter_policy.get("allowed_dispositions") or []):
        raise ValueError("conviction.counter_resolution disposition is invalid")
    adjusted_reason_code = str(counter_policy.get("adjusted_reason_code") or "")
    counter_adjustments = [
        item
        for item in normalized
        if item.get("reason_code") == adjusted_reason_code
    ]
    residual_indexes = counter_resolution.get("residual_clause_indexes")
    resolution_claim_ids = counter_resolution.get("resolution_claim_ids")
    if not isinstance(residual_indexes, list) or not isinstance(resolution_claim_ids, list):
        raise ValueError("conviction.counter_resolution arrays are invalid")
    if disposition == "adjusted":
        residual_indexes_are_ints = all(
            isinstance(index, int) and not isinstance(index, bool)
            for index in residual_indexes
        )
        if (
            counter_resolution.get("adjustment_reason_code") != adjusted_reason_code
            or len(counter_adjustments) != 1
            or counter_adjustments[0].get("claim_ids") != [counter_claim_id]
            or resolution_claim_ids != []
            or not residual_indexes
            or not residual_indexes_are_ints
            or (
                residual_indexes_are_ints
                and len(set(residual_indexes)) != len(residual_indexes)
            )
        ):
            raise ValueError("adjusted Maker counter resolution is inconsistent")
        clauses = ((counter_claim.get("current_basis") or {}).get("clauses") or [])
        expected_residual_indexes = list(range(len(clauses)))
        if residual_indexes != expected_residual_indexes:
            raise ValueError(
                "Maker counter residual clauses must cover current_basis in order"
            )
        if any(index < 0 or index >= len(clauses) for index in residual_indexes):
            raise ValueError("Maker counter residual clause index is outside current_basis")
        for index in residual_indexes:
            clause = clauses[index]
            signature = (
                str(clause.get("owner_type") or ""),
                str(clause.get("owner_id") or ""),
                str(clause.get("field") or ""),
            )
            if signature in seen_typed_owner_signatures:
                raise ValueError("Maker counter residual clause reuses a typed owner")
            seen_typed_owner_signatures.add(signature)

    required_first_reason_code = str(
        adjustment_policy.get("required_first_reason_code") or ""
    )
    if (
        not required_first_reason_code
        or not normalized
        or normalized[0].get("reason_code") != required_first_reason_code
    ):
        raise ValueError(
            "conviction current Maker counter adjustment must be first"
        )

    final = anchor + total_delta
    if final < 0 or final > 100:
        raise ValueError("conviction final must be between 0 and 100")
    claimed = _decimal(payload.get("final"), "conviction.final")
    if claimed != final:
        raise ValueError("conviction final does not equal anchor + adjustments")
    if "adjustment_total" in payload and _decimal(
        payload.get("adjustment_total"), "conviction.adjustment_total"
    ) != total_delta:
        raise ValueError("conviction adjustment_total differs from adjustments")
    return {
        "metric_kind": expected["metric_kind"],
        "calibrated_probability": False,
        "report_label": expected["report_label"],
        "anchor": _plain(anchor),
        "anchor_claim_ids": clean_anchor_claim_ids,
        "anchor_rationale": anchor_rationale,
        "adjustments": normalized,
        "counter_resolution": {
            "counter_claim_id": counter_claim_id,
            "disposition": disposition,
            "adjustment_reason_code": counter_resolution.get(
                "adjustment_reason_code"
            ),
            "residual_clause_indexes": list(residual_indexes),
            "resolution_claim_ids": [str(value) for value in resolution_claim_ids],
        },
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
    methodology_policy = policy.get("gold_methodology")
    if not isinstance(methodology_policy, dict):
        raise ValueError("scoring contract is missing gold_methodology policy")
    claims, claims_by_id = _normalize_claims(
        payload.get("claims"), observations_by_id, methodology_policy
    )
    methodology = normalize_methodology(
        payload.get("methodology"), observations_by_id, claims_by_id,
        methodology_policy,
        profile_policy=policy["tradingview_profile_policy"],
    )
    report_projection = normalize_report_projection(
        payload.get("report_projection"), observations_by_id, claims_by_id,
        methodology_policy,
    )
    score = _normalize_score(
        payload.get("score"), observations_by_id, claims_by_id, policy, methodology
    )
    conviction = _normalize_conviction(
        payload.get("conviction"),
        observations_by_id,
        claims_by_id,
        methodology,
        policy,
    )
    decision = payload.get("decision")
    if not isinstance(decision, dict):
        raise ValueError("decision must be an object")
    primary = str(decision.get("primary_claim_id", ""))
    strongest_counter = str(decision.get("strongest_counter_claim_id", ""))
    invalidation = str(decision.get("invalidation_claim_id", ""))
    if (
        primary not in claims_by_id
        or claims_by_id[primary].get("claim_type") != "maker_thesis"
        or claims_by_id[primary].get("account") != "maker"
    ):
        raise ValueError("decision primary_claim_id must bind the Maker thesis")
    if (
        strongest_counter not in claims_by_id
        or claims_by_id[strongest_counter].get("claim_type")
        != "strongest_counterevidence"
        or claims_by_id[strongest_counter].get("account") != "maker"
    ):
        raise ValueError("decision strongest counter claim must bind Maker")
    if (
        invalidation not in claims_by_id
        or claims_by_id[invalidation].get("claim_type") != "invalidation_path"
        or claims_by_id[invalidation].get("account") != "maker"
    ):
        raise ValueError("decision invalidation claim must bind Maker")
    competing = decision.get("competing_claim_ids")
    if not isinstance(competing, list) or not competing:
        raise ValueError("decision requires competing_claim_ids")
    clean_competing = []
    for ref in competing:
        ref_id = str(ref)
        if (
            ref_id not in claims_by_id
            or ref_id == primary
            or claims_by_id[ref_id].get("account") not in {"shared", "maker"}
        ):
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
