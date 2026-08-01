"""Typed logical micro-DAG certification for one atomic reasoning candidate.

The pipeline is a data-flow proof inside the existing reasoning stage.  It is
not a new runtime stage, does not call a model, and creates no unit checkpoint
or retry budget.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable


PIPELINE_SCHEMA_VERSION = "reasoning-pipeline-certification-v2"
PIPELINE_UNIT_FIELDS = {
    "unit_id",
    "sequence",
    "unit_type",
    "account_scope",
    "source_scope",
    "depends_on_unit_ids",
    "input_node_ids",
    "output_node_ids",
}


@dataclass(frozen=True)
class UnitSpec:
    unit_id: str
    sequence: int
    unit_type: str
    account_scope: str


@dataclass(frozen=True)
class PipelineIssue:
    code: str
    message: str
    path: str


UNIT_SPECS: tuple[UnitSpec, ...] = (
    UnitSpec("source.blockbeats", 1, "source_analysis", "shared"),
    UnitSpec("source.fedwatch", 2, "source_analysis", "shared"),
    UnitSpec("source.farside", 3, "source_analysis", "shared"),
    UnitSpec("source.coinglass", 4, "source_analysis", "shared"),
    UnitSpec("source.exocharts", 5, "source_analysis", "shared"),
    UnitSpec("source.tradingview", 6, "source_analysis", "shared"),
    UnitSpec("join.fundamental_context", 7, "cross_source_join", "shared"),
    UnitSpec("join.orderflow_footprint", 8, "cross_source_join", "shared"),
    UnitSpec("join.chart_trend", 9, "cross_source_join", "shared"),
    UnitSpec("join.etf_relation", 10, "cross_source_join", "shared"),
    UnitSpec("join.intraday_location", 11, "cross_source_join", "shared"),
    UnitSpec("join.fundamental_realization", 12, "cross_source_join", "shared"),
    UnitSpec("main.controls", 13, "account_control", "main"),
    UnitSpec("main.strategy", 14, "account_strategy", "main"),
    UnitSpec("maker.controls", 15, "account_control", "maker"),
    UnitSpec("maker.thesis_score_basis", 16, "account_strategy", "maker"),
    UnitSpec("maker.cannot_do_closure", 17, "closure", "maker"),
)

SOURCE_UNIT_BY_NAME = {
    "BlockBeats": "source.blockbeats",
    "FedWatch": "source.fedwatch",
    "Farside": "source.farside",
    "Coinglass": "source.coinglass",
    "Exocharts": "source.exocharts",
    "TradingView": "source.tradingview",
}
SPEC_BY_ID = {item.unit_id: item for item in UNIT_SPECS}
SEQUENCE_BY_ID = {item.unit_id: item.sequence for item in UNIT_SPECS}


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _node_index(payload: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[PipelineIssue]]:
    nodes: dict[str, dict[str, Any]] = {}
    issues: list[PipelineIssue] = []
    groups = (
        ("observations", payload.get("observations")),
        ("claims", payload.get("claims")),
        ("scenario_tree", payload.get("scenario_tree")),
    )
    for group, values in groups:
        for index, raw in enumerate(values if isinstance(values, list) else []):
            if not isinstance(raw, dict) or not str(raw.get("id") or ""):
                issues.append(
                    PipelineIssue(
                        "reasoning_pipeline.node_id_invalid",
                        "pipeline-owned nodes require a non-empty id",
                        f"{group}[{index}].id",
                    )
                )
                continue
            node_id = str(raw["id"])
            if node_id in nodes:
                issues.append(
                    PipelineIssue(
                        "reasoning_pipeline.node_id_duplicate",
                        f"node id is duplicated across reasoning collections: {node_id}",
                        f"{group}[{index}].id",
                    )
                )
                continue
            node = dict(raw)
            node["__pipeline_group__"] = group
            nodes[node_id] = node
    return nodes, issues


def _expected_owner(node: dict[str, Any]) -> str | None:
    group = node.get("__pipeline_group__")
    if group == "observations":
        return SOURCE_UNIT_BY_NAME.get(str(node.get("source") or ""))
    if group == "scenario_tree":
        return {
            "main": "main.strategy",
            "maker": "maker.thesis_score_basis",
        }.get(str(node.get("account") or ""))
    if group != "claims":
        return None
    claim_type = str(node.get("claim_type") or "")
    account = str(node.get("account") or "")
    if claim_type == "fundamental_context":
        return "join.fundamental_context"
    if claim_type == "orderflow_interpretation":
        return "join.orderflow_footprint"
    if claim_type == "chart_interpretation":
        return "join.chart_trend"
    if claim_type == "etf_confirmation":
        return "join.etf_relation"
    if claim_type in {"liquidation_confirmation", "liquidity_hunt"}:
        return "join.intraday_location"
    if claim_type in {"fundamental_event_realization", "fundamental_price_realization"}:
        return "join.fundamental_realization"
    if claim_type in {"market_regime", "strongest_counterevidence", "invalidation_path"}:
        return f"{account}.controls" if account in {"main", "maker"} else None
    if claim_type == "main_account_thesis" and account == "main":
        return "main.strategy"
    if claim_type == "maker_thesis" and account == "maker":
        return "maker.thesis_score_basis"
    if claim_type == "cannot_do" and account == "maker":
        return "maker.cannot_do_closure"
    return None


def _nested_owner_ids(value: Any) -> Iterable[str]:
    if not isinstance(value, dict):
        return ()
    clauses = value.get("clauses")
    if not isinstance(clauses, list):
        return ()
    return tuple(
        str(item.get("owner_id"))
        for item in clauses
        if isinstance(item, dict) and str(item.get("owner_id") or "")
    )


def _direct_refs(node: dict[str, Any]) -> set[str]:
    group = node.get("__pipeline_group__")
    refs: set[str] = set()
    if group == "claims":
        for field in ("support_ids", "counter_ids"):
            values = node.get(field)
            if isinstance(values, list):
                refs.update(str(value) for value in values if str(value))
        if str(node.get("invalidation_id") or ""):
            refs.add(str(node["invalidation_id"]))
        refs.update(_nested_owner_ids(node.get("current_basis")))
        refs.update(_nested_owner_ids(node.get("trigger_logic")))
        buffer = node.get("structural_noise_buffer")
        if isinstance(buffer, dict) and str(buffer.get("observation_id") or ""):
            refs.add(str(buffer["observation_id"]))
    elif group == "scenario_tree":
        if str(node.get("owner_claim_id") or ""):
            refs.add(str(node["owner_claim_id"]))
    return refs


def _reachable_sources(
    output_ids: Iterable[str],
    nodes: dict[str, dict[str, Any]],
) -> list[str]:
    pending = list(output_ids)
    visited: set[str] = set()
    sources: set[str] = set()
    while pending:
        node_id = str(pending.pop())
        if node_id in visited or node_id not in nodes:
            continue
        visited.add(node_id)
        node = nodes[node_id]
        if node.get("__pipeline_group__") == "observations":
            source = str(node.get("source") or "")
            if source:
                sources.add(source)
            continue
        if node.get("__pipeline_group__") == "claims":
            pending.extend(str(value) for value in node.get("support_ids") or [])
        elif node.get("__pipeline_group__") == "scenario_tree":
            owner_claim_id = str(node.get("owner_claim_id") or "")
            if owner_claim_id:
                pending.append(owner_claim_id)
    return sorted(sources)


def build_pipeline_units(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the exact declarative micro-DAG for a complete candidate.

    This helper is used by fixtures and by the controller's authority-owned
    projection inside the already-open sealed reasoning attempt. The gate
    validates the projected result but never repairs it after certification.
    """

    nodes, node_issues = _node_index(payload)
    if node_issues:
        raise ValueError(node_issues[0].message)
    owner_by_node: dict[str, str] = {}
    outputs_by_unit = {spec.unit_id: [] for spec in UNIT_SPECS}
    for node_id, node in nodes.items():
        owner = _expected_owner(node)
        if owner is None:
            raise ValueError(f"reasoning node has no pipeline owner: {node_id}")
        owner_by_node[node_id] = owner
        outputs_by_unit[owner].append(node_id)

    result: list[dict[str, Any]] = []
    for spec in UNIT_SPECS:
        output_ids = sorted(outputs_by_unit[spec.unit_id])
        input_ids: set[str] = set()
        for output_id in output_ids:
            input_ids.update(
                ref
                for ref in _direct_refs(nodes[output_id])
                if ref not in output_ids
            )
        unknown = input_ids - set(nodes)
        if unknown:
            raise ValueError(f"pipeline input references unknown node(s): {sorted(unknown)}")
        dependency_ids = sorted(
            {owner_by_node[node_id] for node_id in input_ids},
            key=SEQUENCE_BY_ID.__getitem__,
        )
        if any(SEQUENCE_BY_ID[unit_id] >= spec.sequence for unit_id in dependency_ids):
            raise ValueError(
                f"pipeline unit {spec.unit_id} depends on a non-prior unit"
            )
        result.append(
            {
                "unit_id": spec.unit_id,
                "sequence": spec.sequence,
                "unit_type": spec.unit_type,
                "account_scope": spec.account_scope,
                "source_scope": _reachable_sources(output_ids, nodes),
                "depends_on_unit_ids": dependency_ids,
                "input_node_ids": sorted(input_ids),
                "output_node_ids": output_ids,
            }
        )
    return result


def validate_reasoning_pipeline(
    payload: dict[str, Any],
) -> tuple[list[PipelineIssue], dict[str, Any]]:
    nodes, issues = _node_index(payload)
    units = payload.get("pipeline_units")
    if not isinstance(units, list):
        return [
            *issues,
            PipelineIssue(
                "reasoning_pipeline.invalid",
                "pipeline_units must be an array",
                "pipeline_units",
            ),
        ], {}

    by_id: dict[str, dict[str, Any]] = {}
    seen_outputs: dict[str, str] = {}
    for index, raw in enumerate(units):
        path = f"pipeline_units[{index}]"
        if not isinstance(raw, dict) or set(raw) != PIPELINE_UNIT_FIELDS:
            issues.append(
                PipelineIssue(
                    "reasoning_pipeline.unit_schema",
                    "pipeline unit must use the exact closed field set",
                    path,
                )
            )
            continue
        unit_id = str(raw.get("unit_id") or "")
        if unit_id in by_id:
            issues.append(
                PipelineIssue(
                    "reasoning_pipeline.unit_duplicate",
                    f"pipeline unit is duplicated: {unit_id}",
                    f"{path}.unit_id",
                )
            )
        else:
            by_id[unit_id] = raw
        submitted_sequence = raw.get("sequence")
        sequence_value = (
            submitted_sequence
            if isinstance(submitted_sequence, int)
            and not isinstance(submitted_sequence, bool)
            else -1
        )
        for dependency_id in (
            raw.get("depends_on_unit_ids")
            if isinstance(raw.get("depends_on_unit_ids"), list)
            else []
        ):
            if SEQUENCE_BY_ID.get(str(dependency_id), 10**6) >= sequence_value:
                issues.append(
                    PipelineIssue(
                        "reasoning_pipeline.future_dependency",
                        f"{unit_id} depends on a non-prior unit: {dependency_id}",
                        f"{path}.depends_on_unit_ids",
                    )
                )
        outputs = raw.get("output_node_ids")
        if isinstance(outputs, list):
            for output_id in outputs:
                node_id = str(output_id)
                if node_id in seen_outputs:
                    issues.append(
                        PipelineIssue(
                            "reasoning_pipeline.output_duplicate",
                            f"node is owned by multiple units: {node_id}",
                            f"{path}.output_node_ids",
                        )
                    )
                else:
                    seen_outputs[node_id] = unit_id

    submitted_ids = [str(item.get("unit_id") or "") for item in units if isinstance(item, dict)]
    expected_ids = [item.unit_id for item in UNIT_SPECS]
    if submitted_ids != expected_ids:
        issues.append(
            PipelineIssue(
                "reasoning_pipeline.unit_order",
                "pipeline units must match the authority-owned topological order",
                "pipeline_units",
            )
        )
    if set(seen_outputs) != set(nodes):
        issues.append(
            PipelineIssue(
                "reasoning_pipeline.output_coverage",
                "every observation, claim and scenario must be owned exactly once",
                "pipeline_units.output_node_ids",
            )
        )

    try:
        expected = build_pipeline_units(payload)
    except ValueError as exc:
        issues.append(
            PipelineIssue(
                "reasoning_pipeline.owner_invalid",
                str(exc),
                "pipeline_units",
            )
        )
        expected = []
    for index, expected_unit in enumerate(expected):
        actual = by_id.get(expected_unit["unit_id"])
        if actual is None:
            issues.append(
                PipelineIssue(
                    "reasoning_pipeline.unit_missing",
                    f"required pipeline unit is missing: {expected_unit['unit_id']}",
                    "pipeline_units",
                )
            )
            continue
        for field in PIPELINE_UNIT_FIELDS - {"unit_id"}:
            if actual.get(field) != expected_unit[field]:
                code = (
                    "reasoning_pipeline.future_dependency"
                    if field == "depends_on_unit_ids"
                    and any(
                        SEQUENCE_BY_ID.get(str(dep), 10**6)
                        >= int(actual.get("sequence") or 0)
                        for dep in (actual.get(field) or [])
                    )
                    else "reasoning_pipeline.unit_drift"
                )
                issues.append(
                    PipelineIssue(
                        code,
                        f"{expected_unit['unit_id']} {field} differs from the typed node graph",
                        f"pipeline_units[{index}].{field}",
                    )
                )

    if issues:
        return issues, {}

    clean_nodes = {
        node_id: {key: value for key, value in node.items() if key != "__pipeline_group__"}
        for node_id, node in nodes.items()
    }
    output_hash_by_unit: dict[str, str] = {}
    certified_units: list[dict[str, Any]] = []
    for unit in expected:
        input_payload = {
            "nodes": [clean_nodes[node_id] for node_id in unit["input_node_ids"]],
            "dependency_output_sha256s": [
                output_hash_by_unit[unit_id]
                for unit_id in unit["depends_on_unit_ids"]
            ],
        }
        output_payload = {
            "nodes": [clean_nodes[node_id] for node_id in unit["output_node_ids"]]
        }
        output_sha = _canonical_sha256(output_payload)
        output_hash_by_unit[unit["unit_id"]] = output_sha
        certified_units.append(
            {
                "unit_id": unit["unit_id"],
                "sequence": unit["sequence"],
                "input_sha256": _canonical_sha256(input_payload),
                "output_sha256": output_sha,
            }
        )
    certification = {
        "pipeline_schema_version": PIPELINE_SCHEMA_VERSION,
        "pipeline_unit_count": len(certified_units),
        "pipeline_units": certified_units,
    }
    certification["pipeline_sha256"] = _canonical_sha256(certification)
    return [], certification
