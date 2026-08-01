"""Producer-visible reasoning submission contract and deterministic scaffold.

The scaffold removes JSON-shape guesswork before a model is called.  It does
not validate business semantics, create an attempt, or write runtime state.
The formal reasoning gate still validates the complete submitted candidate
inside the normal attempt budget.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.golden_methodology import get_methodology_runtime_inventory

from .reasoning_pipeline import (
    PIPELINE_UNIT_FIELDS,
    SOURCE_UNIT_BY_NAME,
    UNIT_SPECS,
    build_pipeline_units,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = Path("scoring/reasoning_submission_contract.json")


@dataclass(frozen=True)
class SubmissionShapeIssue:
    code: str
    message: str
    path: str


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def load_reasoning_submission_contract(*, root: Path = ROOT) -> dict[str, Any]:
    path = root.resolve() / CONTRACT_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != "reasoning-submission-contract-v6"
        or payload.get("certified_schema_version") != "reasoning-model-v5"
        or payload.get("additional_fields_allowed") is not False
    ):
        raise ValueError("reasoning submission contract is invalid")
    methodology = payload.get("methodology")
    if not isinstance(methodology, dict):
        raise ValueError("reasoning submission methodology contract is missing")
    field_order = methodology.get("field_order")
    objects = methodology.get("objects")
    arrays = methodology.get("arrays")
    if (
        not isinstance(field_order, list)
        or not isinstance(objects, dict)
        or not isinstance(arrays, dict)
        or set(field_order) != set(objects) | set(arrays)
        or len(field_order) != len(set(field_order))
    ):
        raise ValueError("reasoning methodology field inventory is invalid")
    return payload


def _policy_value(policy: dict[str, Any], path: str) -> Any:
    value: Any = policy
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            raise ValueError(f"reasoning submission policy path is missing: {path}")
        value = value[part]
    return value


def _record_shape_issues(
    value: Any,
    spec: dict[str, Any],
    *,
    path: str,
    full_policy: dict[str, Any],
) -> list[SubmissionShapeIssue]:
    issues: list[SubmissionShapeIssue] = []
    if not isinstance(value, dict):
        return [
            SubmissionShapeIssue(
                "reasoning_shape.object_required",
                "expected an object",
                path,
            )
        ]

    field_order = spec.get("field_order")
    expected = set(field_order if isinstance(field_order, list) else [])
    actual = set(value)
    for field in sorted(expected - actual):
        issues.append(
            SubmissionShapeIssue(
                "reasoning_shape.field_missing",
                f"required field is missing: {field}",
                f"{path}.{field}",
            )
        )
    for field in sorted(actual - expected):
        issues.append(
            SubmissionShapeIssue(
                "reasoning_shape.field_unknown",
                f"unknown field is forbidden: {field}",
                f"{path}.{field}",
            )
        )

    for field in spec.get("string_fields") or []:
        if field in value and (
            not isinstance(value[field], str) or not value[field].strip()
        ):
            issues.append(
                SubmissionShapeIssue(
                    "reasoning_shape.string_required",
                    "expected a non-empty string",
                    f"{path}.{field}",
                )
            )
    for field, minimum in (spec.get("string_min_lengths") or {}).items():
        if (
            field in value
            and isinstance(value[field], str)
            and len(value[field].strip()) < int(minimum)
        ):
            issues.append(
                SubmissionShapeIssue(
                    "reasoning_shape.string_too_short",
                    f"string requires at least {int(minimum)} characters",
                    f"{path}.{field}",
                )
            )
    for field in spec.get("boolean_fields") or []:
        if field in value and type(value[field]) is not bool:
            issues.append(
                SubmissionShapeIssue(
                    "reasoning_shape.boolean_required",
                    "expected a JSON boolean",
                    f"{path}.{field}",
                )
            )
    for field, array_spec in (spec.get("string_array_fields") or {}).items():
        if field not in value:
            continue
        items = value[field]
        if not isinstance(items, list):
            issues.append(
                SubmissionShapeIssue(
                    "reasoning_shape.array_required",
                    "expected an array of non-empty strings",
                    f"{path}.{field}",
                )
            )
            continue
        minimum = int((array_spec or {}).get("min_items", 0))
        maximum = (array_spec or {}).get("max_items")
        if len(items) < minimum or (
            isinstance(maximum, int) and len(items) > maximum
        ):
            issues.append(
                SubmissionShapeIssue(
                    "reasoning_shape.array_cardinality",
                    (
                        f"array requires at least {minimum} item(s)"
                        if maximum is None
                        else f"array requires {minimum}..{maximum} item(s)"
                    ),
                    f"{path}.{field}",
                )
            )
        for index, item in enumerate(items):
            if not isinstance(item, str) or not item.strip():
                issues.append(
                    SubmissionShapeIssue(
                        "reasoning_shape.string_required",
                        "array item must be a non-empty string",
                        f"{path}.{field}[{index}]",
                    )
                )
    for field, enum_spec in (spec.get("enum_fields") or {}).items():
        if field not in value:
            continue
        allowed = enum_spec.get("values")
        if allowed is None:
            allowed = _policy_value(full_policy, str(enum_spec["policy_path"]))
        if not isinstance(allowed, list):
            raise ValueError(f"reasoning submission enum is invalid: {path}.{field}")
        if type(value[field]) not in {str, bool, int, float} or value[field] not in allowed:
            issues.append(
                SubmissionShapeIssue(
                    "reasoning_shape.enum_invalid",
                    f"value must be one of {allowed}",
                    f"{path}.{field}",
                )
            )
    for field, policy_path in (spec.get("exact_policy_values") or {}).items():
        if field in value and value[field] != _policy_value(full_policy, policy_path):
            issues.append(
                SubmissionShapeIssue(
                    "reasoning_shape.policy_value_mismatch",
                    f"value must exactly match authority policy {policy_path}",
                    f"{path}.{field}",
                )
            )
    for field, expected_value in (spec.get("exact_values") or {}).items():
        if field in value and (
            type(value[field]) is not type(expected_value)
            or value[field] != expected_value
        ):
            issues.append(
                SubmissionShapeIssue(
                    "reasoning_shape.exact_value_mismatch",
                    f"value must exactly equal {expected_value!r}",
                    f"{path}.{field}",
                )
            )
    return issues


def validate_methodology_submission_shape(
    methodology: Any,
    *,
    contract: dict[str, Any],
    full_policy: dict[str, Any],
) -> list[SubmissionShapeIssue]:
    """Return every producer-shape defect in methodology, without fail-fast."""

    if not isinstance(methodology, dict):
        return [
            SubmissionShapeIssue(
                "reasoning_shape.object_required",
                "methodology must be an object",
                "methodology",
            )
        ]

    methodology_contract = contract["methodology"]
    field_order = methodology_contract["field_order"]
    expected = set(field_order)
    actual = set(methodology)
    issues: list[SubmissionShapeIssue] = []
    for field in sorted(expected - actual):
        issues.append(
            SubmissionShapeIssue(
                "reasoning_shape.field_missing",
                f"required methodology block is missing: {field}",
                f"methodology.{field}",
            )
        )
    for field in sorted(actual - expected):
        issues.append(
            SubmissionShapeIssue(
                "reasoning_shape.field_unknown",
                f"unknown methodology block is forbidden: {field}",
                f"methodology.{field}",
            )
        )

    for field, spec in methodology_contract["objects"].items():
        if field in methodology:
            issues.extend(
                _record_shape_issues(
                    methodology[field],
                    spec,
                    path=f"methodology.{field}",
                    full_policy=full_policy,
                )
            )
    for field, array_spec in methodology_contract["arrays"].items():
        if field not in methodology:
            continue
        values = methodology[field]
        path = f"methodology.{field}"
        if not isinstance(values, list):
            issues.append(
                SubmissionShapeIssue(
                    "reasoning_shape.array_required",
                    "expected an array",
                    path,
                )
            )
            continue
        minimum = int(array_spec.get("min_items", 0))
        maximum = array_spec.get("max_items")
        if len(values) < minimum or (
            isinstance(maximum, int) and len(values) > maximum
        ):
            issues.append(
                SubmissionShapeIssue(
                    "reasoning_shape.array_cardinality",
                    (
                        f"array requires at least {minimum} item(s)"
                        if maximum is None
                        else f"array requires {minimum}..{maximum} item(s)"
                    ),
                    path,
                )
            )
        item_spec = array_spec.get("item")
        for index, item in enumerate(values):
            issues.extend(
                _record_shape_issues(
                    item,
                    item_spec,
                    path=f"{path}[{index}]",
                    full_policy=full_policy,
                )
            )

    scenarios = methodology.get("scenario_tree")
    if isinstance(scenarios, list):
        matrix = {
            (item.get("account"), item.get("kind"))
            for item in scenarios
            if isinstance(item, dict)
        }
        expected_matrix = {
            (account, kind)
            for account in ("main", "maker")
            for kind in ("base", "counter", "invalidation")
        }
        if matrix != expected_matrix or len(scenarios) != len(expected_matrix):
            issues.append(
                SubmissionShapeIssue(
                    "reasoning_shape.scenario_matrix",
                    "methodology scenario_tree requires exactly one main/maker base/counter/invalidation item",
                    "methodology.scenario_tree",
                )
            )
    return issues


def _blank_record(
    spec: dict[str, Any],
    *,
    full_policy: dict[str, Any],
) -> dict[str, Any]:
    value: dict[str, Any] = {}
    string_arrays = spec.get("string_array_fields") or {}
    exact_policy_values = spec.get("exact_policy_values") or {}
    exact_values = spec.get("exact_values") or {}
    for field in spec.get("field_order") or []:
        if field in string_arrays:
            value[field] = []
        elif field in exact_values:
            value[field] = copy.deepcopy(exact_values[field])
        elif field in exact_policy_values:
            value[field] = copy.deepcopy(
                _policy_value(full_policy, exact_policy_values[field])
            )
        else:
            value[field] = None
    return value


def _fedwatch_contract_source(evidence: dict[str, Any]) -> str:
    source = ((evidence.get("sources") or {}).get("FedWatch") or {})
    meta = source.get("meta") if isinstance(source.get("meta"), dict) else {}
    return (
        "FedWatchPlanC"
        if meta.get("selection_mode") == "kalshi_plan_c_fallback"
        else "FedWatch"
    )


def _source_artifact_records(
    evidence: dict[str, Any],
    source: str,
) -> list[dict[str, Any]]:
    source_evidence = ((evidence.get("sources") or {}).get(source) or {})
    records = source_evidence.get("artifacts")
    if not isinstance(records, list):
        return []
    return [
        item
        for item in records
        if isinstance(item, dict)
        and isinstance(item.get("path"), str)
        and item["path"]
    ]


def _unique_artifact_by_name(
    records: list[dict[str, Any]],
    filename: str,
) -> dict[str, Any] | None:
    matches = [
        item
        for item in records
        if Path(str(item.get("path"))).name.lower() == filename.lower()
    ]
    return matches[0] if len(matches) == 1 else None


def _visual_review_evidence_sha256(
    observation: dict[str, Any],
    records: list[dict[str, Any]],
) -> str:
    records_by_path = {
        str(item["path"]): item
        for item in records
    }
    citations = observation.get("visual_citations")
    cited_hashes: list[str] = []
    if isinstance(citations, list):
        for citation in citations:
            if not isinstance(citation, dict):
                continue
            relative = citation.get("evidence_ref")
            record = (
                records_by_path.get(relative)
                if isinstance(relative, str)
                else None
            )
            if (
                record is None
                or Path(str(record.get("path"))).suffix.lower() != ".png"
                or not isinstance(record.get("sha256"), str)
            ):
                continue
            cited_hashes.append(str(record["sha256"]))
    return _canonical_sha256(
        {"artifact_sha256s": sorted(set(cited_hashes))}
    )


def project_observation_mechanical_fields(
    observation: dict[str, Any],
    *,
    source: str,
    evidence: dict[str, Any],
    contract: dict[str, Any],
    pending_model_values: bool = False,
) -> dict[str, Any]:
    """Project only sealed artifact inventory and deterministic hash bindings.

    ``evidence_refs`` is the same-source sealed artifact inventory, not proof
    that a visual artifact was read.  Visual proof remains model-owned through
    citation selection, crop geometry and metric coverage.
    """

    projected = copy.deepcopy(observation)
    records = _source_artifact_records(evidence, source)
    projected["evidence_refs"] = [
        str(item["path"])
        for item in records
    ]

    ownership = contract["server_projection"][
        "observation_mechanical_ownership"
    ]
    contract_source = (
        _fedwatch_contract_source(evidence)
        if source == "FedWatch"
        else source
    )
    structured_filename = ownership[
        "structured_artifact_filename_by_contract_source"
    ].get(contract_source)
    if isinstance(structured_filename, str):
        record = _unique_artifact_by_name(records, structured_filename)
        if record is None:
            projected["structured_binding"] = {}
        else:
            metrics = (
                projected.get("metrics")
                if isinstance(projected.get("metrics"), dict)
                else {}
            )
            projected["structured_binding"] = {
                "artifact_path": record.get("path"),
                "artifact_sha256": record.get("sha256"),
                "metrics_sha256": (
                    None
                    if pending_model_values
                    else _canonical_sha256(metrics)
                ),
            }

    if "visual_review" in projected:
        review = (
            copy.deepcopy(projected.get("visual_review"))
            if isinstance(projected.get("visual_review"), dict)
            else projected.get("visual_review")
        )
        if isinstance(review, dict):
            metrics = (
                projected.get("metrics")
                if isinstance(projected.get("metrics"), dict)
                else {}
            )
            review["metrics_sha256"] = (
                None
                if pending_model_values
                else _canonical_sha256(metrics)
            )
            review["evidence_sha256"] = (
                None
                if pending_model_values
                else _visual_review_evidence_sha256(projected, records)
            )
            projected["visual_review"] = review
    return projected


def _blank_observation(
    source: str,
    *,
    evidence: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    projection = contract["server_projection"]
    contract_source = (
        _fedwatch_contract_source(evidence) if source == "FedWatch" else source
    )
    fields = contract["observation_fields_by_source"][contract_source]
    source_evidence = ((evidence.get("sources") or {}).get(source) or {})
    fixed = {
        "id": projection["observation_id_by_source"][source],
        "kind": projection["observation_kind_by_contract_source"][
            contract_source
        ],
        "source": source,
        "observed_at": source_evidence.get("observed_at"),
    }
    object_fields = {"metrics", "structured_binding", "visual_review"}
    array_fields = {"evidence_refs", "visual_citations"}
    blank = {
        field: (
            copy.deepcopy(fixed[field])
            if field in fixed
            else {}
            if field in object_fields
            else []
            if field in array_fields
            else None
        )
        for field in fields
    }
    return project_observation_mechanical_fields(
        blank,
        source=source,
        evidence=evidence,
        contract=contract,
        pending_model_values=True,
    )


def _unique_claim_id(
    claims: list[Any],
    *,
    claim_type: str,
    account: str,
) -> str | None:
    matches = [
        str(item.get("id"))
        for item in claims
        if isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and item.get("id")
        and item.get("claim_type") == claim_type
        and item.get("account") == account
    ]
    return matches[0] if len(matches) == 1 else None


def _unique_claim(
    claims: list[Any],
    *,
    claim_type: str,
    account: str,
) -> dict[str, Any] | None:
    matches = [
        item
        for item in claims
        if isinstance(item, dict)
        and item.get("claim_type") == claim_type
        and item.get("account") == account
    ]
    return matches[0] if len(matches) == 1 else None


def _unique_observation(
    observations: list[Any],
    *,
    source: str,
) -> dict[str, Any] | None:
    matches = [
        item
        for item in observations
        if isinstance(item, dict) and item.get("source") == source
    ]
    return matches[0] if len(matches) == 1 else None


def _nested_value(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return copy.deepcopy(current)


def _resolve_methodology_server_binding(
    binding: dict[str, Any],
    *,
    observations: list[Any],
    claims: list[Any],
    full_policy: dict[str, Any],
) -> Any:
    resolver = binding.get("resolver")
    if resolver == "literal":
        return copy.deepcopy(binding.get("value"))
    if resolver == "single_policy_value":
        values = _policy_value(full_policy, str(binding["policy_path"]))
        return copy.deepcopy(values[0]) if isinstance(values, list) and len(values) == 1 else None
    if resolver in {"observation_id", "observation_field"}:
        observation = _unique_observation(
            observations,
            source=str(binding["source"]),
        )
        if observation is None:
            return None
        if resolver == "observation_id":
            value = observation.get("id")
            return value if isinstance(value, str) and value else None
        return _nested_value(observation, str(binding["field_path"]))
    if resolver in {"unique_claim_id", "unique_claim_field"}:
        claim = _unique_claim(
            claims,
            claim_type=str(binding["claim_type"]),
            account=str(binding["account"]),
        )
        if claim is None:
            return None
        if resolver == "unique_claim_id":
            value = claim.get("id")
            return value if isinstance(value, str) and value else None
        return _nested_value(claim, str(binding["field_path"]))
    if resolver == "ordered_unique_claim_ids":
        values = [
            _unique_claim_id(
                claims,
                claim_type=str(item["claim_type"]),
                account=str(item["account"]),
            )
            for item in binding["bindings"]
        ]
        if any(value is None for value in values) or len(set(values)) != len(values):
            return []
        return values
    raise ValueError(f"unsupported methodology server resolver: {resolver}")


def _set_methodology_server_path(
    methodology: dict[str, Any],
    path: str,
    value: Any,
) -> None:
    parts = path.split(".")
    if len(parts) < 3 or parts[0] != "methodology" or "[*]" in path:
        raise ValueError(f"invalid methodology server path: {path}")
    current: Any = methodology
    for part in parts[1:-1]:
        if not isinstance(current, dict) or not isinstance(current.get(part), dict):
            return
        current = current[part]
    if isinstance(current, dict):
        current[parts[-1]] = copy.deepcopy(value)


def _project_methodology_server_bindings(
    methodology: dict[str, Any],
    *,
    observations: list[Any],
    claims: list[Any],
    contract: dict[str, Any],
    full_policy: dict[str, Any],
) -> None:
    ownership = contract["server_projection"]["methodology_leaf_ownership"]
    for path, binding in ownership["server_owned_bindings"].items():
        if "[*]" not in path:
            _set_methodology_server_path(
                methodology,
                path,
                _resolve_methodology_server_binding(
                    binding,
                    observations=observations,
                    claims=claims,
                    full_policy=full_policy,
                ),
            )
            continue

        prefix, field = path.split("[*].", 1)
        parts = prefix.split(".")
        if len(parts) != 2 or parts[0] != "methodology":
            raise ValueError(f"invalid methodology wildcard server path: {path}")
        items = methodology.get(parts[1])
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            if binding.get("resolver") == "event_realization_claim_id":
                key_value = item.get(str(binding["key_field"]))
                matches = [
                    claim
                    for claim in claims
                    if isinstance(claim, dict)
                    and claim.get("claim_type") == binding.get("claim_type")
                    and claim.get("account") == binding.get("account")
                    and claim.get(str(binding["claim_match_field"])) == key_value
                    and isinstance(key_value, str)
                    and key_value
                ]
                value = (
                    matches[0].get("id")
                    if len(matches) == 1
                    and isinstance(matches[0].get("id"), str)
                    and matches[0].get("id")
                    else None
                )
            else:
                value = _resolve_methodology_server_binding(
                    binding,
                    observations=observations,
                    claims=claims,
                    full_policy=full_policy,
                )
            item[field] = copy.deepcopy(value)


def _unique_claim_index(claims: list[Any]) -> dict[str, dict[str, Any]]:
    by_id: dict[str, list[dict[str, Any]]] = {}
    for item in claims:
        if (
            isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and item.get("id")
        ):
            by_id.setdefault(str(item["id"]), []).append(item)
    return {
        claim_id: items[0]
        for claim_id, items in by_id.items()
        if len(items) == 1
    }


def derive_methodology_trigger_claim_ids(
    owner_claim_id: str,
    claims: dict[str, dict[str, Any]],
) -> list[str]:
    """Project direct claim supports in owner order; observations are excluded."""

    owner = claims.get(owner_claim_id)
    if not isinstance(owner, dict):
        return []
    support_ids = owner.get("support_ids")
    if not isinstance(support_ids, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for raw in support_ids:
        if (
            not isinstance(raw, str)
            or not raw
            or raw == owner_claim_id
            or raw not in claims
            or raw in seen
        ):
            continue
        seen.add(raw)
        result.append(raw)
    return result


def _normalize_observations(
    observations: Any,
    *,
    evidence: dict[str, Any],
    contract: dict[str, Any],
) -> Any:
    if not isinstance(observations, list):
        return copy.deepcopy(observations)
    expected_sources = contract["server_projection"]["observation_source_order"]
    by_source: dict[str, list[dict[str, Any]]] = {
        source: [] for source in expected_sources
    }
    for item in observations:
        source_value = item.get("source") if isinstance(item, dict) else None
        if not isinstance(source_value, str) or source_value not in by_source:
            return copy.deepcopy(observations)
        by_source[source_value].append(item)
    if any(len(items) != 1 for items in by_source.values()):
        return copy.deepcopy(observations)

    normalized: list[dict[str, Any]] = []
    for source in expected_sources:
        raw = by_source[source][0]
        blank = _blank_observation(
            source,
            evidence=evidence,
            contract=contract,
        )
        fixed_fields = {"id", "kind", "source", "observed_at"}
        projected = copy.deepcopy(raw)
        for field in fixed_fields:
            projected[field] = copy.deepcopy(blank[field])
        normalized.append(
            project_observation_mechanical_fields(
                projected,
                source=source,
                evidence=evidence,
                contract=contract,
            )
        )
    return normalized


def _project_relative_trigger_operators(
    claims: list[Any],
    *,
    observations: list[Any],
    contract: dict[str, Any],
) -> None:
    """Canonicalize only the operators of an explicit Exocharts reference pair.

    The producer continues to own whether the pair exists, its target values,
    clause order and all other trigger semantics.  Missing, ambiguous, any-mode
    or malformed pairs are left untouched for the independent reasoning gate.
    """

    policy = contract["server_projection"][
        "relative_trigger_operator_projection"
    ]
    reference_source = str(policy["reference_source"])
    relative_source = str(policy["relative_source"])
    reference_id = contract["server_projection"]["observation_id_by_source"][
        reference_source
    ]
    relative_id = contract["server_projection"]["observation_id_by_source"][
        relative_source
    ]
    reference_observation = _unique_observation(
        observations,
        source=reference_source,
    )
    if reference_observation is None:
        return
    current_reference = _nested_value(
        reference_observation.get("metrics") or {},
        str(policy["reference_field"]),
    )
    if current_reference is None:
        return

    scalar_clause_fields = {"owner_type", "owner_id", "field", "operator", "value"}
    allowed_claim_types = set(policy["claim_types"])
    for claim in claims:
        if (
            not isinstance(claim, dict)
            or claim.get("claim_type") not in allowed_claim_types
        ):
            continue
        trigger = claim.get("trigger_logic")
        if (
            not isinstance(trigger, dict)
            or trigger.get("mode") != policy["required_mode"]
            or not isinstance(trigger.get("clauses"), list)
        ):
            continue
        clauses = trigger["clauses"]
        references = [
            clause
            for clause in clauses
            if isinstance(clause, dict)
            and clause.get("owner_type") == "observation"
            and clause.get("owner_id") == reference_id
            and clause.get("field") == policy["reference_field"]
        ]
        relatives = [
            clause
            for clause in clauses
            if isinstance(clause, dict)
            and clause.get("owner_type") == "observation"
            and clause.get("owner_id") == relative_id
            and clause.get("field") == policy["relative_field"]
        ]
        if (
            len(references) != 1
            or len(relatives) != 1
            or set(references[0]) != scalar_clause_fields
            or set(relatives[0]) != scalar_clause_fields
        ):
            continue

        reference_target = references[0]["value"]
        same_state = (
            type(reference_target) is type(current_reference)
            and reference_target == current_reference
        )
        references[0]["operator"] = policy[
            "reference_operator_when_target_equals_current"
            if same_state
            else "reference_operator_when_target_differs_current"
        ]
        relatives[0]["operator"] = policy["relative_operator"]


def assemble_reasoning_submission(
    payload: dict[str, Any],
    *,
    evidence: dict[str, Any],
    reasoning_authority_sha256: str,
    contract: dict[str, Any],
    full_policy: dict[str, Any],
) -> dict[str, Any]:
    """Apply authority-owned structural projection inside one sealed attempt.

    The projection never invents facts, visual judgments, claim conclusions,
    current state, or future trigger values. It only closes authority-owned
    identities, typed-owner mirrors, constants, and structural wrappers.
    Missing or ambiguous model-owned inputs remain empty and are rejected by
    the normal reasoning gate.
    """

    candidate = copy.deepcopy(payload)
    candidate["schema_version"] = contract["certified_schema_version"]
    candidate["trading_date"] = evidence.get("trading_date")
    candidate["slot"] = evidence.get("slot")
    candidate["evidence_snapshot_sha256"] = evidence.get("snapshot_sha256")
    candidate["reasoning_authority_sha256"] = reasoning_authority_sha256
    candidate["observations"] = _normalize_observations(
        candidate.get("observations"),
        evidence=evidence,
        contract=contract,
    )

    claims = candidate.get("claims")
    claim_list = claims if isinstance(claims, list) else []
    projected_claims = copy.deepcopy(claim_list)
    coinglass_directions = [
        ((item.get("metrics") or {}).get("final_direction"))
        for item in (
            candidate.get("observations")
            if isinstance(candidate.get("observations"), list)
            else []
        )
        if isinstance(item, dict)
        and item.get("source") == "Coinglass"
        and isinstance(item.get("metrics"), dict)
    ]
    orderflow_indexes = [
        index
        for index, item in enumerate(projected_claims)
        if isinstance(item, dict)
        and item.get("claim_type") == "orderflow_interpretation"
        and item.get("account") == "shared"
    ]
    if len(orderflow_indexes) == 1 and len(coinglass_directions) == 1:
        mapping = _policy_value(
            full_policy,
            contract["server_projection"]["orderflow_direction_policy_path"],
        )
        source_direction = coinglass_directions[0]
        direction = (
            mapping.get(source_direction)
            if isinstance(mapping, dict)
            and isinstance(source_direction, str)
            else None
        )
        projected_claims[orderflow_indexes[0]]["direction"] = direction
    candidate["claims"] = projected_claims if isinstance(claims, list) else claims

    _project_relative_trigger_operators(
        projected_claims,
        observations=(
            candidate.get("observations")
            if isinstance(candidate.get("observations"), list)
            else []
        ),
        contract=contract,
    )

    claim_index = _unique_claim_index(projected_claims)
    projection = contract["server_projection"]
    claim_bindings = {
        field: _unique_claim_id(
            projected_claims,
            claim_type=str(binding["claim_type"]),
            account=str(binding["account"]),
        )
        for field, binding in projection["account_claim_bindings"].items()
    }
    account_separation = {
        "main_priority": copy.deepcopy(
            _policy_value(full_policy, "gold_methodology.main_account_priority")
        ),
        "maker_priority": copy.deepcopy(
            _policy_value(full_policy, "gold_methodology.maker_priority")
        ),
        **claim_bindings,
        "conflict_policy": _policy_value(
            full_policy,
            "gold_methodology.account_independence.conflict_policy",
        ),
        "forced_consensus": False,
    }

    owner_by_key: dict[tuple[str, str], str | None] = {}
    top_level_scenarios: list[dict[str, Any]] = []
    for item in contract["scenario_ownership"]["items"]:
        owner_id = _unique_claim_id(
            projected_claims,
            claim_type=str(item["owner_claim_type"]),
            account=str(item["account"]),
        )
        key = (str(item["account"]), str(item["scenario_type"]))
        owner_by_key[key] = owner_id
        top_level_scenarios.append(
            {
                "id": item["id"],
                "account": item["account"],
                "scenario_type": item["scenario_type"],
                "owner_claim_id": owner_id,
            }
        )
    methodology_scenarios = [
        {
            "account": account,
            "kind": kind,
            "claim_id": owner_by_key[(account, kind)],
            "trigger_claim_ids": derive_methodology_trigger_claim_ids(
                str(owner_by_key[(account, kind)] or ""),
                claim_index,
            ),
            "action": contract["scenario_ownership"][
                "transition_code_by_type"
            ][kind],
        }
        for account in ("main", "maker")
        for kind in ("base", "counter", "invalidation")
    ]

    methodology = candidate.get("methodology")
    projected_methodology = (
        copy.deepcopy(methodology) if isinstance(methodology, dict) else {}
    )
    projected_methodology["account_separation"] = account_separation
    projected_methodology["scenario_tree"] = methodology_scenarios
    _project_methodology_server_bindings(
        projected_methodology,
        observations=(
            candidate.get("observations")
            if isinstance(candidate.get("observations"), list)
            else []
        ),
        claims=projected_claims,
        contract=contract,
        full_policy=full_policy,
    )
    candidate["methodology"] = projected_methodology
    candidate["scenario_tree"] = top_level_scenarios
    try:
        candidate["pipeline_units"] = build_pipeline_units(candidate)
    except (AttributeError, KeyError, TypeError, ValueError):
        candidate["pipeline_units"] = []
    return candidate


def _compare_runtime_inventory(
    expected: Any,
    actual: Any,
    *,
    path: str,
) -> list[SubmissionShapeIssue]:
    """Return stable, field-specific differences between runtime and contract."""

    if type(expected) is not type(actual):
        return [
            SubmissionShapeIssue(
                "reasoning_contract.methodology_inventory",
                (
                    "contract value type differs from the golden evaluator "
                    f"inventory: expected {type(expected).__name__}, "
                    f"received {type(actual).__name__}"
                ),
                path,
            )
        ]
    if isinstance(expected, dict):
        issues: list[SubmissionShapeIssue] = []
        expected_keys = set(expected)
        actual_keys = set(actual)
        for key in sorted(expected_keys - actual_keys):
            issues.append(
                SubmissionShapeIssue(
                    "reasoning_contract.methodology_inventory",
                    "contract is missing a golden evaluator inventory field",
                    f"{path}.{key}",
                )
            )
        for key in sorted(actual_keys - expected_keys):
            issues.append(
                SubmissionShapeIssue(
                    "reasoning_contract.methodology_inventory",
                    "contract contains a field absent from the golden evaluator inventory",
                    f"{path}.{key}",
                )
            )
        for key in expected:
            if key not in actual:
                continue
            issues.extend(
                _compare_runtime_inventory(
                    expected[key],
                    actual[key],
                    path=f"{path}.{key}",
                )
            )
        return issues
    if isinstance(expected, list):
        if expected == actual:
            return []
        return [
            SubmissionShapeIssue(
                "reasoning_contract.methodology_inventory",
                "contract sequence differs from the golden evaluator inventory",
                path,
            )
        ]
    if expected != actual:
        return [
            SubmissionShapeIssue(
                "reasoning_contract.methodology_inventory",
                "contract value differs from the golden evaluator inventory",
                path,
            )
        ]
    return []


def build_reasoning_submission_scaffold(
    *,
    evidence: dict[str, Any],
    reasoning_authority_sha256: str,
    contract: dict[str, Any],
    full_policy: dict[str, Any],
) -> dict[str, Any]:
    """Build a run-bound structural template with no market judgment."""

    methodology_contract = contract["methodology"]
    methodology: dict[str, Any] = {}
    for field in methodology_contract["field_order"]:
        if field in methodology_contract["objects"]:
            methodology[field] = _blank_record(
                methodology_contract["objects"][field],
                full_policy=full_policy,
            )
        else:
            array_spec = methodology_contract["arrays"][field]
            item_spec = array_spec["item"]
            count = int(array_spec.get("min_items", 0))
            methodology[field] = [
                _blank_record(item_spec, full_policy=full_policy)
                for _ in range(count)
            ]

    methodology_scenarios = methodology["scenario_tree"]
    transition_code_by_type = contract["scenario_ownership"][
        "transition_code_by_type"
    ]
    for item, (account, kind) in zip(
        methodology_scenarios,
        (
            (account, kind)
            for account in ("main", "maker")
            for kind in ("base", "counter", "invalidation")
        ),
        strict=True,
    ):
        item["account"] = account
        item["kind"] = kind
        item["action"] = transition_code_by_type[kind]

    top_level_scenarios = [
        {
            "id": item["id"],
            "account": item["account"],
            "scenario_type": item["scenario_type"],
            "owner_claim_id": None,
        }
        for item in contract["scenario_ownership"]["items"]
    ]
    observations = [
        _blank_observation(
            source,
            evidence=evidence,
            contract=contract,
        )
        for source in contract["server_projection"]["observation_source_order"]
    ]
    _project_methodology_server_bindings(
        methodology,
        observations=observations,
        claims=[],
        contract=contract,
        full_policy=full_policy,
    )

    pipeline_units = [
        {
            field: (
                spec.unit_id
                if field == "unit_id"
                else spec.sequence
                if field == "sequence"
                else spec.unit_type
                if field == "unit_type"
                else spec.account_scope
                if field == "account_scope"
                else []
            )
            for field in contract["pipeline_unit_fields"]
        }
        for spec in UNIT_SPECS
    ]
    submission = {
        "schema_version": contract["certified_schema_version"],
        "trading_date": evidence.get("trading_date"),
        "slot": evidence.get("slot"),
        "evidence_snapshot_sha256": evidence.get("snapshot_sha256"),
        "reasoning_authority_sha256": reasoning_authority_sha256,
        "observations": observations,
        "claims": [],
        "methodology": methodology,
        "scenario_tree": top_level_scenarios,
        "pipeline_units": pipeline_units,
    }
    return {
        "schema_version": contract["scaffold_policy"]["schema_version"],
        "contract_sha256": _canonical_sha256(contract),
        "certified_schema_version": contract["certified_schema_version"],
        "business_semantics_checked": False,
        "model_called": False,
        "attempt_created": False,
        "pipeline_instruction": (
            "producer fills only model-owned values; the controller applies "
            "server_projection and derives pipeline_units inside the sealed attempt"
        ),
        "server_projection": copy.deepcopy(contract["server_projection"]),
        "claim_topology": copy.deepcopy(contract["claim_topology"]),
        "typed_narrative_ownership": copy.deepcopy(
            contract["typed_narrative_ownership"]
        ),
        "visual_citation_policy": copy.deepcopy(
            contract["visual_citation_policy"]
        ),
        "submission_template": submission,
    }


def validate_contract_runtime_compatibility(
    contract: dict[str, Any],
    *,
    full_policy: dict[str, Any],
) -> list[SubmissionShapeIssue]:
    """Verify static contract/handler compatibility before any model call."""

    issues: list[SubmissionShapeIssue] = []
    try:
        runtime_inventory = get_methodology_runtime_inventory(
            policy=full_policy["gold_methodology"],
            profile="vnext_submission",
        )
    except (KeyError, TypeError, ValueError) as exc:
        issues.append(
            SubmissionShapeIssue(
                "reasoning_contract.methodology_runtime_inventory",
                str(exc),
                "methodology",
            )
        )
        runtime_inventory = None
    expected_sources = {
        "BlockBeats",
        "Coinglass",
        "Exocharts",
        "FedWatch",
        "FedWatchPlanC",
        "Farside",
        "TradingView",
    }
    if set(contract["observation_fields_by_source"]) != expected_sources:
        issues.append(
            SubmissionShapeIssue(
                "reasoning_contract.observation_inventory",
                "observation contract differs from the six-source handler inventory",
                "observation_fields_by_source",
            )
        )
    expected_claim_types = {
        "cannot_do",
        "chart_interpretation",
        "etf_confirmation",
        "fundamental_context",
        "fundamental_event_realization",
        "fundamental_price_realization",
        "invalidation_path",
        "liquidation_confirmation",
        "liquidity_hunt",
        "main_account_thesis",
        "maker_thesis",
        "market_regime",
        "orderflow_interpretation",
        "strongest_counterevidence",
    }
    if set(contract["claim_fields_by_type"]) != expected_claim_types:
        issues.append(
            SubmissionShapeIssue(
                "reasoning_contract.claim_inventory",
                "claim contract differs from the reasoning handler inventory",
                "claim_fields_by_type",
            )
        )
    expected_top_level = {
        "schema_version",
        "trading_date",
        "slot",
        "evidence_snapshot_sha256",
        "reasoning_authority_sha256",
        "observations",
        "claims",
        "methodology",
        "scenario_tree",
        "pipeline_units",
    }
    if set(contract["top_level"]["field_order"]) != expected_top_level:
        issues.append(
            SubmissionShapeIssue(
                "reasoning_contract.top_level_inventory",
                "top-level contract differs from the reasoning-model-v5 handler inventory",
                "top_level.field_order",
            )
        )
    expected_leaf_ownership = (
        copy.deepcopy(runtime_inventory["leaf_ownership"])
        if isinstance(runtime_inventory, dict)
        else {
            "server_owned_subtrees": [],
            "server_owned_bindings": {},
        }
    )
    expected_projection = {
        "schema_version": "reasoning-server-projection-v4",
        "server_owned_paths": [
            "schema_version",
            "trading_date",
            "slot",
            "evidence_snapshot_sha256",
            "reasoning_authority_sha256",
            "observations[*].id",
            "observations[*].kind",
            "observations[*].source",
            "observations[*].observed_at",
            "observations[*].evidence_refs",
            "observations[kind=structured_observation].structured_binding",
            "observations[kind=visual_judgment].visual_review.metrics_sha256",
            "observations[kind=visual_judgment].visual_review.evidence_sha256",
            *expected_leaf_ownership["server_owned_subtrees"],
            *expected_leaf_ownership["server_owned_bindings"],
            "scenario_tree",
            "claims[claim_type=orderflow_interpretation].direction",
            (
                "claims[claim_type=strongest_counterevidence|invalidation_path]."
                "trigger_logic.clauses[source=Coinglass,field=final_direction,"
                "paired_with=Exocharts].operator"
            ),
            (
                "claims[claim_type=strongest_counterevidence|invalidation_path]."
                "trigger_logic.clauses[source=Exocharts,"
                "field=cross_check_result].operator"
            ),
            "pipeline_units",
        ],
        "observation_source_order": list(SOURCE_UNIT_BY_NAME),
        "observation_id_by_source": {
            "BlockBeats": "obs_bb",
            "FedWatch": "obs_fw",
            "Farside": "obs_fs",
            "Coinglass": "obs_cg",
            "Exocharts": "obs_exo",
            "TradingView": "obs_tv",
        },
        "observation_kind_by_contract_source": {
            "BlockBeats": "structured_observation",
            "FedWatch": "visual_judgment",
            "FedWatchPlanC": "structured_observation",
            "Farside": "structured_observation",
            "Coinglass": "visual_judgment",
            "Exocharts": "visual_judgment",
            "TradingView": "visual_judgment",
        },
        "observation_mechanical_ownership": {
            "schema_version": "observation-mechanical-ownership-v1",
            "evidence_refs_semantics": (
                "sealed_same_source_artifact_inventory_not_visual_read_proof"
            ),
            "structured_artifact_filename_by_contract_source": {
                "BlockBeats": "blockbeats.json",
                "Farside": "farside_btc_etf.json",
                "FedWatchPlanC": "fedwatch.json",
            },
            "structured_binding_fields": [
                "artifact_path",
                "artifact_sha256",
                "metrics_sha256",
            ],
            "visual_review_hash_fields": [
                "metrics_sha256",
                "evidence_sha256",
            ],
            "model_owned_visual_proof_paths": [
                "observations[*].visual_citations[*].evidence_ref",
                "observations[*].visual_citations[*].metric_paths",
                "observations[*].visual_citations[*].crop",
                "claims[claim_type=invalidation_path].structural_noise_buffer.visual_evidence_ref",
            ],
        },
        "account_claim_bindings": {
            "main_claim_id": {
                "claim_type": "main_account_thesis",
                "account": "main",
            },
            "maker_claim_id": {
                "claim_type": "maker_thesis",
                "account": "maker",
            },
            "main_regime_claim_id": {
                "claim_type": "market_regime",
                "account": "main",
            },
            "maker_regime_claim_id": {
                "claim_type": "market_regime",
                "account": "maker",
            },
            "main_counter_claim_id": {
                "claim_type": "strongest_counterevidence",
                "account": "main",
            },
            "maker_counter_claim_id": {
                "claim_type": "strongest_counterevidence",
                "account": "maker",
            },
            "main_invalidation_claim_id": {
                "claim_type": "invalidation_path",
                "account": "main",
            },
            "maker_invalidation_claim_id": {
                "claim_type": "invalidation_path",
                "account": "maker",
            },
        },
        "methodology_leaf_ownership": expected_leaf_ownership,
        "methodology_trigger_claim_ids_policy_path": (
            "gold_methodology.account_trigger_logic.scenario_control_binding."
            "methodology_trigger_claim_ids_source"
        ),
        "orderflow_direction_policy_path": (
            "maker_score.orderflow.final_direction_to_claim_direction"
        ),
        "relative_trigger_operator_projection": {
            "schema_version": "relative-trigger-operator-projection-v1",
            "claim_types": ["strongest_counterevidence", "invalidation_path"],
            "required_mode": "all",
            "relative_source": "Exocharts",
            "relative_field": "cross_check_result",
            "relative_operator": "equals_at_trigger",
            "reference_source": "Coinglass",
            "reference_field": "final_direction",
            "reference_operator_when_target_equals_current": (
                "equals_at_trigger"
            ),
            "reference_operator_when_target_differs_current": "becomes",
            "projection_scope": "operators_only",
            "missing_or_ambiguous_behavior": (
                "leave_unmodified_for_gate_rejection"
            ),
            "clause_presence_order_target_and_relation_mutation_forbidden": True,
        },
        "producer_values_at_server_owned_paths_authoritative": False,
        "projection_must_run_inside_reasoning_attempt": True,
        "business_judgment_repair_forbidden": True,
    }
    if contract.get("server_projection") != expected_projection:
        issues.append(
            SubmissionShapeIssue(
                "reasoning_contract.server_projection",
                "server-owned reasoning projection differs from the runtime contract",
                "server_projection",
            )
        )
    try:
        submission_relative = contract["server_projection"][
            "relative_trigger_operator_projection"
        ]
        scoring_relative = _policy_value(
            full_policy,
            (
                "gold_methodology.account_trigger_logic."
                "relative_direction_observation_fields."
                "Exocharts.cross_check_result"
            ),
        )
        submission_relative_view = {
            "reference_source": submission_relative["reference_source"],
            "reference_field": submission_relative["reference_field"],
            "target_equals_current": submission_relative[
                "reference_operator_when_target_equals_current"
            ],
            "target_differs_from_current": submission_relative[
                "reference_operator_when_target_differs_current"
            ],
            "relative_operator": submission_relative["relative_operator"],
        }
        scoring_relative_view = {
            "reference_source": scoring_relative["reference_source"],
            "reference_field": scoring_relative["reference_field"],
            "target_equals_current": scoring_relative[
                "reference_operator_policy"
            ]["target_equals_current"],
            "target_differs_from_current": scoring_relative[
                "reference_operator_policy"
            ]["target_differs_from_current"],
            "relative_operator": scoring_relative["relative_operator"],
        }
        if submission_relative_view != scoring_relative_view:
            raise ValueError(
                "relative trigger operator projection differs from scoring policy"
            )
    except (KeyError, TypeError, ValueError) as exc:
        issues.append(
            SubmissionShapeIssue(
                "reasoning_contract.relative_trigger_policy_drift",
                str(exc),
                "server_projection.relative_trigger_operator_projection",
            )
        )
    expected_scaffold_policy = {
        "schema_version": "reasoning-submission-scaffold-v6",
        "business_semantics_checked": False,
        "attempt_created": False,
        "null_means_producer_must_supply": False,
        "model_owned_null_means_producer_must_supply": True,
        "server_owned_null_means_pending_projection": True,
        "authority_constants_may_be_prefilled": True,
        "business_direction_or_action_may_be_prefilled": False,
        "authority_transition_codes_may_be_prefilled": True,
        "server_projection_is_authoritative": True,
        "claim_topology_visible_before_attempt": True,
        "typed_narrative_ownership_visible_before_attempt": True,
    }
    if contract.get("scaffold_policy") != expected_scaffold_policy:
        issues.append(
            SubmissionShapeIssue(
                "reasoning_contract.scaffold_policy",
                "reasoning scaffold policy differs from the runtime contract",
                "scaffold_policy",
            )
        )
    if contract.get("visual_citation_policy") != {
        "schema_version": "visual-citation-leaf-policy-v1",
        "empty_collections_are_metric_leaves": True,
        "empty_collection_semantics": (
            "observable_absence_requires_bounded_citation"
        ),
    }:
        issues.append(
            SubmissionShapeIssue(
                "reasoning_contract.visual_citation_policy",
                "visual metric leaf semantics differ from the fail-closed runtime",
                "visual_citation_policy",
            )
        )
    expected_claim_topology = {
        "schema_version": "claim-topology-v1",
        "support_selection_owner": "model",
        "server_support_edge_injection_allowed": False,
        "direct_observation_support_policy": (
            "exact_for_listed_claim_types_claim_only_otherwise"
        ),
        "exact_direct_observation_sources_by_claim_type": {
            "fundamental_context": ["BlockBeats", "FedWatch", "Farside"],
            "orderflow_interpretation": ["Coinglass", "Exocharts"],
            "chart_interpretation": ["TradingView"],
            "etf_confirmation": ["Coinglass", "Farside"],
            "liquidation_confirmation": ["Coinglass"],
        },
        "required_reachable_claim_types_by_claim_type": {
            "fundamental_price_realization": [
                "fundamental_context",
                "chart_interpretation",
            ],
            "market_regime": [
                "fundamental_price_realization",
                "orderflow_interpretation",
                "chart_interpretation",
            ],
            "liquidation_confirmation": ["chart_interpretation"],
            "liquidity_hunt": [
                "chart_interpretation",
                "liquidation_confirmation",
            ],
            "main_account_thesis": [
                "market_regime",
                "fundamental_price_realization",
                "etf_confirmation",
            ],
            "maker_thesis": [
                "market_regime",
                "orderflow_interpretation",
                "chart_interpretation",
                "liquidity_hunt",
            ],
            "strongest_counterevidence": ["market_regime"],
            "invalidation_path": ["market_regime"],
            "cannot_do": [
                "maker_thesis",
                "strongest_counterevidence",
                "invalidation_path",
                "market_regime",
            ],
        },
        "required_direct_claim_types_by_claim_type": {
            "fundamental_event_realization": [
                "fundamental_context",
                "chart_interpretation",
            ],
            "fundamental_price_realization": [
                "fundamental_context",
                "chart_interpretation",
            ],
            "liquidation_confirmation": ["chart_interpretation"],
        },
    }
    if contract.get("claim_topology") != expected_claim_topology:
        issues.append(
            SubmissionShapeIssue(
                "reasoning_contract.claim_topology",
                "producer-visible claim topology differs from the runtime contract",
                "claim_topology",
            )
        )
    expected_typed_narrative_ownership = {
        "schema_version": "typed-narrative-ownership-v1",
        "typed_control_paths": [
            "claims[claim_type=fundamental_price_realization].realization_state",
            "claims[claim_type=etf_confirmation].price_relation",
            "claims[claim_type=liquidation_confirmation].confirmation_result",
            "observations[source=TradingView].metrics.chart_scoring_basis",
        ],
        "audit_narrative_paths": [
            "claims[claim_type=fundamental_price_realization].conclusion",
            "claims[claim_type=etf_confirmation].conclusion",
            "claims[claim_type=liquidation_confirmation].conclusion",
            "observations[source=TradingView].metrics.chart_component_rationales",
        ],
        "prose_keyword_inference_allowed": False,
        "compiler_typed_projection_required": True,
    }
    if (
        contract.get("typed_narrative_ownership")
        != expected_typed_narrative_ownership
    ):
        issues.append(
            SubmissionShapeIssue(
                "reasoning_contract.typed_narrative_ownership",
                "typed control and audit narrative ownership is inconsistent",
                "typed_narrative_ownership",
            )
        )
    try:
        if _policy_value(
            full_policy,
            expected_projection[
                "methodology_trigger_claim_ids_policy_path"
            ],
        ) != "bound_owner_claim.direct_support_claim_ids":
            raise ValueError("methodology trigger projection policy is invalid")
        if _policy_value(
            full_policy,
            expected_projection["orderflow_direction_policy_path"],
        ) != {
            "bullish": "long",
            "bearish": "short",
            "neutral": "observe",
            "mixed": "observe",
        }:
            raise ValueError("orderflow direction projection policy is invalid")
        scenario_binding = _policy_value(
            full_policy,
            "gold_methodology.account_trigger_logic.scenario_control_binding",
        )
        if (
            scenario_binding.get("methodology_trigger_order")
            != "owner_support_order_first_occurrence"
            or scenario_binding.get(
                "methodology_trigger_observation_ids_excluded"
            )
            is not True
            or scenario_binding.get(
                "methodology_trigger_owner_self_reference_allowed"
            )
            is not False
        ):
            raise ValueError("methodology trigger projection closure is invalid")
    except (KeyError, TypeError, ValueError) as exc:
        issues.append(
            SubmissionShapeIssue(
                "reasoning_contract.server_projection_policy",
                str(exc),
                "server_projection",
            )
        )
    scenario_ownership = contract.get("scenario_ownership")
    expected_scenario_items = [
        {
            "id": f"scenario_{account}_{scenario_type}",
            "account": account,
            "scenario_type": scenario_type,
            "owner_claim_type": (
                "main_account_thesis"
                if (account, scenario_type) == ("main", "base")
                else "maker_thesis"
                if (account, scenario_type) == ("maker", "base")
                else "strongest_counterevidence"
                if scenario_type == "counter"
                else "invalidation_path"
            ),
        }
        for account in ("main", "maker")
        for scenario_type in ("base", "counter", "invalidation")
    ]
    expected_transition_codes = {
        "base": "retain_certified_assessment",
        "counter": "reassess_on_typed_counter",
        "invalidation": "invalidate_and_recollect_evidence",
    }
    if (
        not isinstance(scenario_ownership, dict)
        or scenario_ownership.get("schema_version") != "scenario-ownership-v1"
        or scenario_ownership.get("items") != expected_scenario_items
        or scenario_ownership.get("transition_code_by_type")
        != expected_transition_codes
        or scenario_ownership.get("producer_free_prose_allowed") is not False
        or scenario_ownership.get("execution_lifecycle_owner")
        != "decision_and_continuity"
        or contract.get("scenario_fields")
        != ["id", "account", "scenario_type", "owner_claim_id"]
    ):
        issues.append(
            SubmissionShapeIssue(
                "reasoning_contract.scenario_ownership",
                "scenario ownership contract differs from the v5 runtime inventory",
                "scenario_ownership",
            )
        )
    methodology_scenario_spec = contract["methodology"]["arrays"][
        "scenario_tree"
    ]["item"]
    if (
        methodology_scenario_spec.get("enum_fields", {})
        .get("action", {})
        .get("values")
        != list(expected_transition_codes.values())
    ):
        issues.append(
            SubmissionShapeIssue(
                "reasoning_contract.scenario_transition_codes",
                "methodology scenario action must use the authority transition codes",
                "methodology.arrays.scenario_tree.item.enum_fields.action.values",
            )
        )
    if set(contract["pipeline_unit_fields"]) != PIPELINE_UNIT_FIELDS:
        issues.append(
            SubmissionShapeIssue(
                "reasoning_contract.pipeline_inventory",
                "pipeline unit contract differs from the runtime handler inventory",
                "pipeline_unit_fields",
            )
        )
    expected_unit_order = [item.unit_id for item in UNIT_SPECS]
    if contract.get("pipeline_unit_order") != expected_unit_order:
        issues.append(
            SubmissionShapeIssue(
                "reasoning_contract.pipeline_order",
                "pipeline order differs from the runtime micro-DAG inventory",
                "pipeline_unit_order",
            )
        )
    if runtime_inventory is not None:
        expected_methodology = {
            "field_order": runtime_inventory["field_order"],
            "objects": runtime_inventory["objects"],
            "arrays": runtime_inventory["arrays"],
        }
        issues.extend(
            _compare_runtime_inventory(
                expected_methodology,
                contract["methodology"],
                path="methodology",
            )
        )
        scenario_count = int(
            runtime_inventory["policy_bindings"][
                "legacy_minimum_scenario_count"
            ]
        )
        vnext_count = int(
            runtime_inventory["policy_bindings"]["vnext_scenario_count"]
        )
        if scenario_count <= 0 or scenario_count > vnext_count:
            issues.append(
                SubmissionShapeIssue(
                    "reasoning_contract.methodology_inventory",
                    (
                        "legacy scenario minimum is incompatible with the "
                        "vNext exact account-kind matrix"
                    ),
                    "methodology.arrays.scenario_tree.min_items",
                )
            )
    for group in ("objects", "arrays"):
        for name, spec in contract["methodology"][group].items():
            try:
                _blank_record(
                    spec.get("item") if group == "arrays" else spec,
                    full_policy=full_policy,
                )
                for enum_spec in (
                    (spec.get("item") if group == "arrays" else spec).get(
                        "enum_fields"
                    )
                    or {}
                ).values():
                    if "policy_path" in enum_spec:
                        allowed = _policy_value(
                            full_policy, str(enum_spec["policy_path"])
                        )
                        if not isinstance(allowed, list) or not allowed:
                            raise ValueError("enum policy path is not a non-empty array")
            except (KeyError, TypeError, ValueError) as exc:
                issues.append(
                    SubmissionShapeIssue(
                        "reasoning_contract.policy_binding",
                        str(exc),
                        f"methodology.{group}.{name}",
                    )
                )
    return issues
