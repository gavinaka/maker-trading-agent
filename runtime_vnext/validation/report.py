"""Report-stage certification, typed projection and quality validation.

The report compiler may format these certified values, but it does not own
their closed vocabularies, state matrices or projection topology.  Those
owners live in :mod:`runtime_vnext.domain_ir.registry` and their generated
contract views live in :mod:`runtime_vnext.domain_ir.projection`.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from outputs.report_lint import lint_report_text

from ..domain_ir.projection import (
    scenario_ownership_projection,
    scenario_projection_contract_projection,
)
from ..domain_ir.registry import (
    MAKER_ORDER_LIFECYCLE_FIELD_ORDER,
    MAKER_FAILURE_ORDER,
    MAKER_SEMANTIC_STATES,
    ORDER_LIFECYCLE_APPLICABILITY,
    ORDER_LIFECYCLE_DISPLAY_BY_STATE,
    ORDER_LIFECYCLE_PATH_FLAGS,
    REGISTRY,
    SCENARIO_CANONICAL_AUDIT_FIELD_ORDER,
    SCENARIO_FIELD_ORDER,
    SCENARIO_OWNER_CLAIM_TYPE_BY_ACCOUNT,
)
from ..plan_semantics import classify_maker_semantic_state
from .common import maker_fill_scenarios

_CONSTRUCTIBILITY_REASON_CN = dict(zip(("constructible", *MAKER_FAILURE_ORDER), (
    "候选结构与执行语义完整", "Maker 当前为无方向观察结论，不适用入场区、名义仓位或风险候选",
    "当前没有认证的 TradingView 入场区间", "候选入场区未绑定首选认证区域",
    "候选方向与认证结构区的支撑/压力角色冲突", "候选限价位于会立即成交或穿越现价的一侧，不满足静置 Maker 语义",
    "方向、现价、触达方向或入场类型不构成同一闭合语义", "候选执行方式与本轮 Maker 不能做结论冲突",
    "候选订单没有同时满足可成交路径与成交前撤单路径", "候选初始止损未绑定本轮认证结构与推理阶段预先密封的外扩缓冲",
    "候选区间的风险数学未满足全部成交组合要求", "候选防守触发价未通过完整分档情景的确定性计算",
), strict=True))
_THRESHOLD_INELIGIBLE_CN = "评分与计划时置信度未同时达到候选门槛"
_REJECTED_RISK_REASONS = dict(zip(
    ("not_applicable", "not_submitted", "recalculated", "not_recalculable"),
    ("qualified_plan_uses_primary_risk_scenarios", "candidate_risk_input_absent", "deterministic_recalculation_succeeded", "candidate_risk_input_failed_recalculation"),
    strict=True,
))

def _canonical_closed_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip()

def certify_maker_semantic_state(maker: Mapping[str, Any]) -> str:
    """Certify the four-state Maker classification from sealed decision facts."""
    sealed_state = maker.get("semantic_state")
    if sealed_state is not None:
        if sealed_state not in MAKER_SEMANTIC_STATES:
            raise ValueError("Maker semantic_state is outside the closed vocabulary")
        return str(sealed_state)
    constructibility = (
        maker.get("plan_constructibility")
        if isinstance(maker.get("plan_constructibility"), Mapping)
        else {}
    )
    lifecycle = (
        maker.get("order_lifecycle")
        if isinstance(maker.get("order_lifecycle"), Mapping)
        else {}
    )
    reach_basis = (
        maker.get("entry_reach_probability_basis")
        if isinstance(maker.get("entry_reach_probability_basis"), Mapping)
        else {}
    )
    return classify_maker_semantic_state(
        plan_state=maker.get("plan_state"),
        direction=maker.get("direction"),
        plan_constructible=maker.get("plan_constructible"),
        threshold_eligible=maker.get("threshold_eligible"),
        risk_plan=maker.get("risk_plan"),
        defense_plan=maker.get("defense_plan"),
        position_notional_usdt=maker.get("position_notional_usdt"),
        entry_type=maker.get("entry_type"),
        order_lifecycle_state=lifecycle.get("state"),
        entry_reach_probability_applicability=reach_basis.get("applicability"),
        constructibility_reason=constructibility.get("primary_reason_code"),
    )

def certify_order_lifecycle(maker: Mapping[str, Any]) -> dict[str, Any]:
    """Certify an exact gate-derived lifecycle without inferring or rewriting it."""
    raw = maker.get("order_lifecycle")
    lifecycle = dict(raw) if isinstance(raw, Mapping) else {}
    if set(lifecycle) != set(MAKER_ORDER_LIFECYCLE_FIELD_ORDER):
        raise ValueError("order lifecycle differs from the closed typed schema")
    if lifecycle.get("schema_version") != REGISTRY.maker_order_lifecycle_schema_version:
        raise ValueError("order lifecycle schema version is unsupported")
    if lifecycle.get("fill_probability") is not None:
        raise ValueError("order lifecycle may not fabricate an actual fill probability")
    state = str(lifecycle.get("state") or "")
    path_flags = ORDER_LIFECYCLE_PATH_FLAGS.get(state)
    probability_applicability = ORDER_LIFECYCLE_APPLICABILITY.get(state)
    if path_flags is None or probability_applicability is None:
        raise ValueError("order lifecycle state is outside the closed vocabulary")
    if (
        lifecycle.get("legal_fill_path_exists")
        is not path_flags["legal_fill_path_exists"]
        or lifecycle.get("legal_cancel_path_exists")
        is not path_flags["legal_cancel_path_exists"]
        or lifecycle.get("fill_probability_applicability")
        != probability_applicability
        or lifecycle.get("reason_code") != state
    ):
        raise ValueError("order lifecycle projection is internally inconsistent")
    return copy.deepcopy(lifecycle)

def order_lifecycle_display(lifecycle: Mapping[str, Any]) -> str:
    """Project the registry-owned Chinese lifecycle explanation."""
    certified = certify_order_lifecycle({"order_lifecycle": lifecycle})
    state = str(certified["state"])
    try:
        return ORDER_LIFECYCLE_DISPLAY_BY_STATE[state]
    except KeyError as exc:  # Registry coherence tests should make this unreachable.
        raise ValueError("order lifecycle state is outside the closed vocabulary") from exc

def scenario_projection_policy(
    presentation_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the exact generated scenario-presentation contract."""
    projection = presentation_contract.get("scenario_projection_contract")
    expected = scenario_projection_contract_projection()
    if not isinstance(projection, Mapping) or dict(projection) != expected:
        raise ValueError("scenario presentation contract is invalid")
    return copy.deepcopy(dict(projection))

def project_scenario_audit(
    reasoning: Mapping[str, Any],
    *,
    account_controls: Mapping[str, Mapping[str, Any]],
    scenario_ownership: Mapping[str, Any],
    presentation_contract: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Project all visible scenario language from certified typed owners."""
    projection = scenario_projection_policy(presentation_contract)
    expected_ownership = scenario_ownership_projection()
    if dict(scenario_ownership) != expected_ownership:
        raise ValueError("scenario ownership policy is invalid")
    expected_items = {
        (str(item["account"]), str(item["scenario_type"])): item
        for item in expected_ownership["items"]
    }
    claims = {
        str(item.get("id")): item
        for item in reasoning.get("claims", [])
        if isinstance(item, Mapping) and str(item.get("id") or "")
    }
    methodology = reasoning.get("methodology")
    methodology_scenarios = (
        methodology.get("scenario_tree")
        if isinstance(methodology, Mapping)
        and isinstance(methodology.get("scenario_tree"), list)
        else []
    )
    methodology_by_key = {
        (str(item.get("account")), str(item.get("kind"))): item
        for item in methodology_scenarios
        if isinstance(item, Mapping)
    }
    projected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in reasoning.get("scenario_tree", []):
        if not isinstance(raw, Mapping) or set(raw) != set(SCENARIO_FIELD_ORDER):
            raise ValueError("scenario does not use the exact typed ownership fields")
        if not all(_canonical_closed_string(value) for value in raw.values()):
            raise ValueError("scenario ownership identifiers are not canonical")
        account = str(raw["account"])
        scenario_type = str(raw["scenario_type"])
        owner_claim_id = str(raw["owner_claim_id"])
        key = (account, scenario_type)
        expected = expected_items.get(key)
        owner_claim = claims.get(owner_claim_id)
        if (
            expected is None
            or key in seen
            or raw["id"] != expected.get("id")
            or not isinstance(owner_claim, Mapping)
            or owner_claim.get("account") != account
            or owner_claim.get("claim_type") != expected.get("owner_claim_type")
        ):
            raise ValueError("scenario typed owner does not match its exact matrix row")
        seen.add(key)
        transition_code = str(
            projection["transition_code_by_type"].get(scenario_type) or ""
        )
        methodology_item = methodology_by_key.get(key)
        if (
            not isinstance(methodology_item, Mapping)
            or methodology_item.get("claim_id") != owner_claim_id
            or methodology_item.get("action") != transition_code
        ):
            raise ValueError(
                "methodology scenario owner or transition code drifted from the "
                "top-level scenario"
            )
        if scenario_type == "base":
            direction = str(owner_claim.get("direction") or "")
            condition = str(
                (
                    projection["base_condition_by_account_direction"].get(account)
                    or {}
                ).get(direction)
                or ""
            )
        else:
            control = (account_controls.get(account) or {}).get(scenario_type)
            if (
                not isinstance(control, Mapping)
                or control.get("claim_id") != owner_claim_id
            ):
                raise ValueError("scenario lacks its same-account typed control")
            condition = str(control.get("condition") or "")
        visible = (
            projection["projection_by_account_and_transition_code"].get(account)
            or {}
        ).get(transition_code)
        if (
            not condition
            or not isinstance(visible, Mapping)
            or set(visible) != {"expected_path", "action"}
        ):
            raise ValueError("scenario deterministic presentation mapping is incomplete")
        values = {
            "id": raw["id"],
            "account": account,
            "scenario_type": scenario_type,
            "owner_claim_id": owner_claim_id,
            "transition_code": transition_code,
            "condition": condition,
            "expected_path": str(visible["expected_path"]),
            "action": str(visible["action"]),
        }
        projected.append(
            {
                field: values[field]
                for field in SCENARIO_CANONICAL_AUDIT_FIELD_ORDER
            }
        )
    if seen != set(expected_items):
        raise ValueError("scenario typed ownership matrix is incomplete")
    validate_scenario_projection(
        projected,
        claims=list(claims.values()),
        account_controls=account_controls,
        presentation_contract=presentation_contract,
    )
    return projected

def validate_scenario_projection(
    scenarios: list[dict[str, Any]],
    *,
    claims: list[dict[str, Any]],
    account_controls: Mapping[str, Mapping[str, Any]],
    presentation_contract: Mapping[str, Any],
) -> None:
    """Validate canonical scenario output by exact structural reconstruction."""
    projection = scenario_projection_policy(presentation_contract)
    fields = set(SCENARIO_CANONICAL_AUDIT_FIELD_ORDER)
    claim_index = {
        str(item.get("id")): item
        for item in claims
        if isinstance(item, Mapping) and str(item.get("id") or "")
    }
    owner_type_by_key = {
        (account, scenario_type): owner_claim_type
        for account, rows in SCENARIO_OWNER_CLAIM_TYPE_BY_ACCOUNT.items()
        for scenario_type, owner_claim_type in rows.items()
    }
    seen: set[tuple[str, str]] = set()
    for item in scenarios:
        if not isinstance(item, Mapping) or set(item) != fields:
            raise ValueError("canonical scenario field set is invalid")
        account = str(item.get("account") or "")
        scenario_type = str(item.get("scenario_type") or "")
        key = (account, scenario_type)
        owner = claim_index.get(str(item.get("owner_claim_id") or ""))
        transition_code = projection["transition_code_by_type"].get(scenario_type)
        if (
            key not in owner_type_by_key
            or key in seen
            or item.get("id") != f"scenario_{account}_{scenario_type}"
            or not isinstance(owner, Mapping)
            or owner.get("account") != account
            or owner.get("claim_type") != owner_type_by_key[key]
            or item.get("transition_code") != transition_code
        ):
            raise ValueError("canonical scenario typed provenance is invalid")
        seen.add(key)
        if scenario_type == "base":
            expected_condition = (
                projection["base_condition_by_account_direction"]
                .get(account, {})
                .get(str(owner.get("direction") or ""))
            )
        else:
            control = (account_controls.get(account) or {}).get(scenario_type)
            if (
                not isinstance(control, Mapping)
                or control.get("claim_id") != item.get("owner_claim_id")
            ):
                raise ValueError("canonical scenario control owner is invalid")
            expected_condition = control.get("condition")
        visible = (
            projection["projection_by_account_and_transition_code"]
            .get(account, {})
            .get(transition_code)
        )
        if (
            not isinstance(visible, Mapping)
            or item.get("condition") != expected_condition
            or item.get("expected_path") != visible.get("expected_path")
            or item.get("action") != visible.get("action")
        ):
            raise ValueError("canonical scenario projection drifted from typed owners")
    if seen != set(owner_type_by_key):
        raise ValueError("canonical scenario matrix is incomplete")
from decimal import Decimal
import re
from ..domain_ir import (
    CertifiedReportProjectionInput,
    ReportBindings,
    ReportField,
    ReportMetadata,
    ReportRecord,
    ReportSectionBinding,
    ReportValue,
    canonical_sha256,
)
from ..gates import REQUIRED_SOURCES
CANONICAL_REPORT_FIELDS = REGISTRY.report_model_field_order
def _freeze_value(value: Any, *, path: str) -> ReportValue:
    if isinstance(value, Mapping):
        return _freeze_record(value, path=path)
    if type(value) in {list, tuple}:
        return tuple(
            _freeze_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        )
    if value is None or type(value) in {bool, int, float, str, Decimal}:
        return value
    raise TypeError(f"unsupported certified report value at {path}: {type(value).__name__}")
def _freeze_record(value: Mapping[str, Any], *, path: str) -> ReportRecord:
    fields: list[ReportField] = []
    for key, item in value.items():
        if type(key) is not str or not key:
            raise TypeError(f"certified report record key is invalid at {path}")
        fields.append(
            ReportField(
                key,
                _freeze_value(item, path=f"{path}.{key}"),
            )
        )
    return ReportRecord(tuple(fields))
def certify_canonical_report_model(
    model: Mapping[str, Any],
    *,
    bindings: ReportBindings,
) -> CertifiedReportProjectionInput:
    """Bind an already-validated current model to explicit immutable sections.
    A persisted legacy model without its own bindings is intentionally not
    promoted through this active projection boundary.
    """
    if set(model) != set(CANONICAL_REPORT_FIELDS):
        raise ValueError("canonical report fields differ from the projection boundary")
    if model.get("schema_version") != REGISTRY.report_model_schema_version:
        raise ValueError("canonical report schema differs from the domain registry")
    clean = dict(model)
    recorded_hash = clean.pop("model_sha256", None)
    if recorded_hash != canonical_sha256(clean):
        raise ValueError("canonical report model hash is invalid")
    authorization = model.get("execution_authorization")
    if not isinstance(authorization, Mapping):
        raise TypeError("canonical execution_authorization must be a mapping")
    cards = model.get("blockbeats_cards")
    if not isinstance(cards, list):
        raise TypeError("canonical blockbeats_cards must be an array")
    if any(not isinstance(item, Mapping) for item in cards):
        raise TypeError("canonical blockbeats_cards must contain only mappings")
    for key in (
        "schema_version",
        "presentation_contract_version",
        "presentation_contract_sha256",
        "run_id",
        "run_sha256",
        "run_mode",
        "trading_date",
        "slot",
        "methodology_sha256",
        "report_contract_sha256",
        "evidence_snapshot_sha256",
        "reasoning_sha256",
        "decision_sha256",
    ):
        value = model.get(key)
        if type(value) is not str or not value.strip():
            raise TypeError(f"canonical report field must be non-empty text: {key}")
    for key in ("frontstage", "maker_summary", "main_summary", "audit"):
        if not isinstance(model.get(key), Mapping):
            raise TypeError(f"canonical report section must be a mapping: {key}")
    if type(bindings) is not ReportBindings:
        raise TypeError("canonical report bindings must be a ReportBindings")
    if bindings.schema_version != REGISTRY.report_bindings_schema_version:
        raise ValueError("canonical report bindings schema differs from the domain registry")
    metadata = ReportMetadata(
        schema_version=model["schema_version"],
        presentation_contract_version=model["presentation_contract_version"],
        presentation_contract_sha256=model["presentation_contract_sha256"],
        run_id=model["run_id"],
        run_sha256=model["run_sha256"],
        run_mode=model["run_mode"],
        execution_authorization=_freeze_record(
            authorization,
            path="execution_authorization",
        ),
        trading_date=model["trading_date"],
        slot=model["slot"],
        methodology_sha256=model["methodology_sha256"],
        report_contract_sha256=model["report_contract_sha256"],
        evidence_snapshot_sha256=model["evidence_snapshot_sha256"],
        reasoning_sha256=model["reasoning_sha256"],
        decision_sha256=model["decision_sha256"],
    )
    return CertifiedReportProjectionInput(
        metadata=metadata,
        bindings=bindings,
        blockbeats_cards=tuple(
            _freeze_record(item, path=f"blockbeats_cards[{index}]")
            for index, item in enumerate(cards)
        ),
        frontstage=_freeze_record(model["frontstage"], path="frontstage"),
        maker_summary=_freeze_record(
            model["maker_summary"], path="maker_summary"
        ),
        main_summary=_freeze_record(model["main_summary"], path="main_summary"),
        audit=_freeze_record(model["audit"], path="audit"),
    )
def build_report_bindings(
    reasoning: Mapping[str, Any],
) -> ReportBindings:
    """Derive report traceability from the certified reasoning support DAG."""
    observations = reasoning.get("observations")
    claims = reasoning.get("claims")
    if not isinstance(observations, list) or not isinstance(claims, list):
        raise TypeError("certified reasoning graph is missing observations or claims")
    observation_rows: list[Mapping[str, Any]] = []
    observation_by_id: dict[str, Mapping[str, Any]] = {}
    for row in observations:
        if not isinstance(row, Mapping):
            raise TypeError("certified reasoning observation must be a mapping")
        observation_id = row.get("id")
        if type(observation_id) is not str or not observation_id:
            raise TypeError("certified reasoning observation id is invalid")
        if observation_id in observation_by_id:
            raise ValueError("certified reasoning observation ids are not unique")
        observation_rows.append(row)
        observation_by_id[observation_id] = row
    claim_rows: list[Mapping[str, Any]] = []
    claim_by_id: dict[str, Mapping[str, Any]] = {}
    for row in claims:
        if not isinstance(row, Mapping):
            raise TypeError("certified reasoning claim must be a mapping")
        claim_id = row.get("id")
        if type(claim_id) is not str or not claim_id:
            raise TypeError("certified reasoning claim id is invalid")
        if claim_id in claim_by_id or claim_id in observation_by_id:
            raise ValueError("certified reasoning graph ids are not unique")
        claim_rows.append(row)
        claim_by_id[claim_id] = row
    def graph_closure(root_claim_ids: list[str]) -> tuple[set[str], set[str]]:
        reachable_claims: set[str] = set()
        reachable_observations: set[str] = set()
        pending = list(root_claim_ids)
        while pending:
            node_id = pending.pop()
            if node_id in observation_by_id:
                reachable_observations.add(node_id)
                continue
            row = claim_by_id.get(node_id)
            if row is None:
                raise ValueError(f"report binding references unknown graph id: {node_id}")
            if node_id in reachable_claims:
                continue
            reachable_claims.add(node_id)
            for field in ("support_ids", "counter_ids"):
                values = row.get(field)
                if not isinstance(values, list) or any(
                    type(value) is not str or not value for value in values
                ):
                    raise TypeError(
                        f"certified reasoning claim {field} is invalid: {node_id}"
                    )
                pending.extend(reversed(values))
        return reachable_claims, reachable_observations
    def section_binding(
        section_id: str,
        model_path: tuple[str, ...],
        root_claim_ids: list[str],
        *,
        forced_observation_ids: set[str] | None = None,
    ) -> ReportSectionBinding:
        reachable_claims, reachable_observations = graph_closure(root_claim_ids)
        reachable_observations.update(forced_observation_ids or set())
        ordered_claim_ids = tuple(
            str(row["id"])
            for row in claim_rows
            if row["id"] in reachable_claims
        )
        ordered_observation_ids = tuple(
            str(row["id"])
            for row in observation_rows
            if row["id"] in reachable_observations
        )
        evidence_refs: list[str] = []
        for observation_id in ordered_observation_ids:
            refs = observation_by_id[observation_id].get("evidence_refs")
            if not isinstance(refs, list) or any(
                type(value) is not str or not value for value in refs
            ):
                raise TypeError(
                    f"certified reasoning evidence_refs are invalid: {observation_id}"
                )
            for value in refs:
                if value not in evidence_refs:
                    evidence_refs.append(value)
        return ReportSectionBinding(
            section_id=section_id,
            model_path=model_path,
            claim_ids=ordered_claim_ids,
            observation_ids=ordered_observation_ids,
            evidence_refs=tuple(evidence_refs),
        )
    main_roots = [
        str(row["id"]) for row in claim_rows if row.get("account") == "main"
    ]
    maker_roots = [
        str(row["id"]) for row in claim_rows if row.get("account") == "maker"
    ]
    all_roots = [str(row["id"]) for row in claim_rows]
    blockbeats_observations = {
        str(row["id"]) for row in observation_rows if row.get("source") == "BlockBeats"
    }
    blockbeats_roots: list[str] = []
    for row in claim_rows:
        _, reachable_observations = graph_closure([str(row["id"])])
        if reachable_observations & blockbeats_observations:
            blockbeats_roots.append(str(row["id"]))
    section_inputs: dict[str, tuple[list[str], set[str] | None]] = {
        "blockbeats_cards": (blockbeats_roots, blockbeats_observations),
        "frontstage": (main_roots + maker_roots, None),
        "maker_summary": (maker_roots, None),
        "main_summary": (main_roots, None),
        "audit": (all_roots, None),
    }
    return ReportBindings(
        schema_version=REGISTRY.report_bindings_schema_version,
        sections=tuple(
            section_binding(
                section_id,
                model_path,
                section_inputs[section_id][0],
                forced_observation_ids=section_inputs[section_id][1],
            )
            for section_id, model_path in (
                REGISTRY.report_binding_section_model_paths
            )
        ),
    )
def certify_report_projection_input(
    *,
    evidence: Mapping[str, Any],
    reasoning: Mapping[str, Any],
    decision: Mapping[str, Any],
    blockbeats_rows: list[dict[str, Any]],
    presentation_contract: Mapping[str, Any],
    presentation_contract_sha256: str,
    methodology_sha256: str,
    report_contract_sha256: str,
) -> CertifiedReportProjectionInput:
    """Certify raw stage owners into the only typed report projection input.
    The controller has already loaded every artifact.  This function performs
    no I/O and never asks a compiler to reconstruct business semantics.
    """
    certify_presentation_contract(presentation_contract)
    _validate_cross_stage_identity(evidence, reasoning, decision)
    observations = _mapping_rows(reasoning.get("observations"), "observations")
    claims = _mapping_rows(reasoning.get("claims"), "claims")
    observation_by_id = _unique_index(observations, "observation")
    claim_by_id = _unique_index(claims, "claim")
    sources = _certify_sources(observations)
    main = _require_mapping(decision.get("main_account"), "decision.main_account")
    maker = _require_mapping(decision.get("maker"), "decision.maker")
    authorization = _require_mapping(
        decision.get("execution_authorization"),
        "decision.execution_authorization",
    )
    continuity = _require_mapping(
        decision.get("continuity_contract"),
        "decision.continuity_contract",
    )
    main_thesis = _single_claim(claims, "main_account_thesis", "main")
    maker_thesis = _single_claim(claims, "maker_thesis", "maker")
    main_counter = _single_claim(claims, "strongest_counterevidence", "main")
    maker_counter = _single_claim(claims, "strongest_counterevidence", "maker")
    main_invalidation = _single_claim(claims, "invalidation_path", "main")
    maker_invalidation = _single_claim(claims, "invalidation_path", "maker")
    fundamental = _single_claim(claims, "fundamental_context")
    orderflow = _single_claim(claims, "orderflow_interpretation")
    chart = _single_claim(claims, "chart_interpretation")
    cannot_do = _single_claim(claims, "cannot_do", "maker")
    account_controls = _account_controls(
        main_counter=main_counter,
        maker_counter=maker_counter,
        main_invalidation=main_invalidation,
        maker_invalidation=maker_invalidation,
        presentation_contract=presentation_contract,
    )
    scenarios = project_scenario_audit(
        reasoning,
        account_controls=account_controls,
        scenario_ownership=scenario_ownership_projection(),
        presentation_contract=presentation_contract,
    )
    cards = _certify_blockbeats_cards(
        blockbeats_rows,
        evidence=evidence,
        trading_date=str(decision["trading_date"]),
        slot=str(decision["slot"]),
    )
    methodology = _require_mapping(reasoning.get("methodology"), "reasoning.methodology")
    multi_timeframe = _require_mapping(
        methodology.get("multi_timeframe_transition"),
        "reasoning.methodology.multi_timeframe_transition",
    )
    maker_lifecycle = certify_order_lifecycle(maker)
    semantic_state = certify_maker_semantic_state(maker)
    maker_execution = _maker_execution_projection(maker)
    risk_scenarios, rejected_risk_scenarios, rejected_risk_recalculation = (
        _risk_projection(maker, semantic_state=semantic_state)
    )
    plan_reason_explanations = _maker_plan_reason_texts(maker)
    run_mode = str(decision["run_mode"])
    maker_summary = dict(maker)
    maker_summary.update(
        {
            "semantic_state": semantic_state,
            "constructibility_reason": (
                _require_mapping(
                    maker.get("plan_constructibility"),
                    "decision.maker.plan_constructibility",
                ).get("primary_reason_code")
            ),
            "order_lifecycle": maker_lifecycle,
            "order_lifecycle_display": order_lifecycle_display(maker_lifecycle),
            "thesis": maker_thesis["conclusion"],
            "counter": maker_counter["conclusion"],
            "invalidation": maker_invalidation["conclusion"],
        }
    )
    main_summary = dict(main)
    main_summary.update(
        {
            "thesis": main_thesis["conclusion"],
            "counter": main_counter["conclusion"],
            "invalidation": main_invalidation["conclusion"],
        }
    )
    frontstage = {
        "opening_quote": "以下结论仅来自本时段完整六源证据、认证推理与独立账户决策。",
        "fundamentals": fundamental["conclusion"],
        "orderflow": orderflow["conclusion"],
        "chart": chart["conclusion"],
        "interpretation": main_thesis["conclusion"],
        "multi_timeframe": multi_timeframe["transition_summary"],
        "main_authorization": _main_authorization_text(main, authorization, run_mode),
        "maker_execution": _maker_execution_text(semantic_state, plan_reason_explanations),
        "maker_authorization": _maker_authorization_text(maker, semantic_state, authorization, run_mode),
        "maker_execution_status": _maker_execution_status_text(maker, run_mode),
        "maker_continuity": _continuity_text(continuity),
        "cannot_do": cannot_do["conclusion"],
        "independent_boundary": "主账户与Maker共享事实层但独立形成论点、反证、失效与执行授权。",
    }
    audit = {
        "sources": sources,
        "observations": observations,
        "claims": claims,
        "methodology": dict(methodology),
        "account_controls": account_controls,
        "scenario_tree": scenarios,
        "proof_chains": _proof_chains(
            claims,
            claim_by_id=claim_by_id,
            observation_by_id=observation_by_id,
        ),
        "reasoning_proof_blocks": _reasoning_proof_blocks(
            claims,
            required_blocks=presentation_contract["required_reasoning_proof_blocks"],
        ),
        "risk_values_owner": "certified_decision_direct_copy",
        "main_plan": dict(main),
        "maker_decision": dict(maker),
        "maker_execution": maker_execution,
        "order_lifecycle": maker_lifecycle,
        "risk_plan": _candidate_plan_audit(
            maker.get("risk_plan"), semantic_state=semantic_state
        ),
        "risk_scenarios": risk_scenarios,
        "defense_plan": _candidate_plan_audit(
            maker.get("defense_plan"), semantic_state=semantic_state
        ),
        "rejected_candidate_risk_recalculation": rejected_risk_recalculation,
        "rejected_candidate_risk_scenarios": rejected_risk_scenarios,
        "continuity": dict(continuity),
    }
    metadata = ReportMetadata(
        schema_version=REGISTRY.report_model_schema_version,
        presentation_contract_version=str(presentation_contract["schema_version"]),
        presentation_contract_sha256=presentation_contract_sha256,
        run_id=str(decision["run_id"]),
        run_sha256=str(decision["run_sha256"]),
        run_mode=str(decision["run_mode"]),
        execution_authorization=_freeze_record(authorization, path="execution_authorization"),
        trading_date=str(decision["trading_date"]),
        slot=str(decision["slot"]),
        methodology_sha256=methodology_sha256,
        report_contract_sha256=report_contract_sha256,
        evidence_snapshot_sha256=str(decision["evidence_snapshot_sha256"]),
        reasoning_sha256=str(decision["reasoning_sha256"]),
        decision_sha256=str(decision["decision_sha256"]),
    )
    return CertifiedReportProjectionInput(
        metadata=metadata,
        bindings=build_report_bindings(reasoning),
        blockbeats_cards=tuple(
            _freeze_record(row, path=f"blockbeats_cards[{index}]")
            for index, row in enumerate(cards)
        ),
        frontstage=_freeze_record(frontstage, path="frontstage"),
        maker_summary=_freeze_record(maker_summary, path="maker_summary"),
        main_summary=_freeze_record(main_summary, path="main_summary"),
        audit=_freeze_record(audit, path="audit"),
    )
def certify_presentation_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Accept only the display-only v12 presentation contract."""
    required = {
        "schema_version",
        "human_surface_source_of_truth",
        "scenario_projection_contract",
        "human_visible_enum_domains",
        "content_order",
        "required_reasoning_proof_blocks",
        "required_frontstage_fields",
        "maker_execution_fields",
        "maker_second_truth_forbidden_fields",
        "timeframe_display_contract",
        "trigger_operator_display",
        "human_surface_forbidden",
        "density_limits",
    }
    missing = sorted(required - set(contract))
    if missing:
        raise ValueError(f"presentation contract is missing display fields: {missing}")
    if (
        contract.get("schema_version")
        != REGISTRY.report_presentation_contract_schema_version
    ):
        raise ValueError("only the active display-only presentation contract is accepted")
    forbidden_business_mirrors = {
        "retry_policy",
        "maker_semantics",
        "continuity_contract",
        "scoring_contract",
        "risk_policy",
    }
    present = sorted(forbidden_business_mirrors & set(contract))
    if present:
        raise ValueError(f"presentation contract contains business mirrors: {present}")
    scenario_projection_policy(contract)
    density = _require_mapping(contract.get("density_limits"), "density_limits")
    for field in ("maximum_heading_count", "maximum_h4_count", "maximum_bullet_ratio"):
        if field not in density:
            raise ValueError(f"presentation density limit is missing: {field}")
    return copy.deepcopy(dict(contract))
def _validate_cross_stage_identity(
    evidence: Mapping[str, Any],
    reasoning: Mapping[str, Any],
    decision: Mapping[str, Any],
) -> None:
    for field in ("trading_date", "slot"):
        values = {str(stage.get(field) or "") for stage in (evidence, reasoning, decision)}
        if len(values) != 1 or "" in values:
            raise ValueError(f"report stage identity mismatch: {field}")
    evidence_hash = str(evidence.get("snapshot_sha256") or "")
    if (
        reasoning.get("evidence_snapshot_sha256") != evidence_hash
        or decision.get("evidence_snapshot_sha256") != evidence_hash
    ):
        raise ValueError("report evidence identity is not closed")
    if decision.get("reasoning_sha256") != reasoning.get("reasoning_sha256"):
        raise ValueError("report reasoning identity is not closed")
    for field in ("run_id", "run_sha256", "run_mode", "decision_sha256"):
        if not isinstance(decision.get(field), str) or not str(decision[field]).strip():
            raise ValueError(f"report decision identity is missing: {field}")
def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    return dict(value)
def _mapping_rows(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(row, Mapping) for row in value):
        raise TypeError(f"{label} must be an array of mappings")
    return [dict(row) for row in value]
def _unique_index(rows: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        item_id = row.get("id")
        if not isinstance(item_id, str) or not item_id or item_id in result:
            raise ValueError(f"{label} ids must be unique non-empty strings")
        result[item_id] = row
    return result
def _single_claim(
    claims: list[dict[str, Any]],
    claim_type: str,
    account: str | None = None,
) -> dict[str, Any]:
    matches = [
        row
        for row in claims
        if row.get("claim_type") == claim_type
        and (account is None or row.get("account") == account)
    ]
    if len(matches) != 1:
        suffix = f"/{account}" if account else ""
        raise ValueError(f"report requires exactly one claim {claim_type}{suffix}")
    for field in ("conclusion", "invalidation"):
        if not isinstance(matches[0].get(field), str) or not str(matches[0][field]).strip():
            raise ValueError(f"report claim lacks model-owned {field}: {matches[0].get('id')}")
    return matches[0]
def _certify_sources(observations: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {source: [] for source in REQUIRED_SOURCES}
    for row in observations:
        source = row.get("source")
        if source not in grouped:
            raise ValueError(f"report observation uses unknown source: {source}")
        grouped[str(source)].append(row)
    if any(not rows for rows in grouped.values()):
        missing = [source for source, rows in grouped.items() if not rows]
        raise ValueError(f"report is missing six-source observations: {missing}")
    result: dict[str, Any] = {}
    for source in REQUIRED_SOURCES:
        rows = grouped[source]
        facts = [str(row.get("fact") or "").strip() for row in rows]
        if any(not fact for fact in facts):
            raise ValueError(f"report source has an empty model-owned fact: {source}")
        result[source] = {
            "fact": "；".join(facts),
            "metrics": copy.deepcopy(rows[0].get("metrics") or {}),
            "uncertainty": "；".join(
                str(row.get("uncertainty") or "").strip()
                for row in rows
                if str(row.get("uncertainty") or "").strip()
            ),
            "observation_ids": [row["id"] for row in rows],
            "evidence_refs": [
                ref
                for row in rows
                for ref in row.get("evidence_refs", [])
                if isinstance(ref, str)
            ],
        }
    return result
def _certify_blockbeats_cards(
    rows: list[dict[str, Any]],
    *,
    evidence: Mapping[str, Any],
    trading_date: str,
    slot: str,
) -> list[dict[str, Any]]:
    sources = _require_mapping(evidence.get("sources"), "evidence.sources")
    blockbeats = _require_mapping(sources.get("BlockBeats"), "evidence.sources.BlockBeats")
    meta = _require_mapping(blockbeats.get("meta"), "evidence.sources.BlockBeats.meta")
    required_count = meta.get("selected_count_required")
    if not isinstance(required_count, int) or required_count <= 0:
        raise ValueError("BlockBeats selected-count contract is invalid")
    if len(rows) != required_count:
        raise ValueError("BlockBeats card rows differ from the certified evidence count")
    certified: list[dict[str, Any]] = []
    for index, raw in enumerate(rows, start=1):
        row = dict(raw)
        if row.get("selected_rank") != index:
            raise ValueError("BlockBeats selected ranks must be contiguous")
        for field in ("time", "title", "body"):
            if not isinstance(row.get(field), str) or not str(row[field]).strip():
                raise ValueError(f"BlockBeats card field is empty: {field}")
        certified.append(
            {
                "selected_rank": index,
                "time": row["time"],
                "title": row["title"],
                "body": row["body"],
                "analysis_priority": copy.deepcopy(row.get("analysis_priority") or {}),
                "filename": f"{trading_date}_{slot}_blockbeats_{index}.png",
                "content_sha256": canonical_sha256(row),
            }
        )
    return certified
_FIELD_LABELS = {
    "timeframes.1d.structure": "日线结构",
    "timeframes.4h.structure": "四小时结构",
    "timeframes.1h.structure": "一小时结构",
    "timeframes.15m.structure": "十五分钟结构",
    "flow_direction": "ETF资金流方向",
    "final_direction": "订单流最终方向",
    "pivot.anchor_reset": "枢轴是否重置",
    "cross_check_result": "足迹交叉核验",
}
def _trigger_condition(claim: Mapping[str, Any], contract: Mapping[str, Any]) -> str:
    logic = _require_mapping(claim.get("trigger_logic"), f"claim {claim.get('id')} trigger_logic")
    clauses = _mapping_rows(logic.get("clauses"), f"claim {claim.get('id')} trigger clauses")
    operators = _require_mapping(contract.get("trigger_operator_display"), "trigger_operator_display")
    rendered: list[str] = []
    for clause in clauses:
        field = str(clause.get("field") or "")
        operator = str(clause.get("operator") or "")
        if operator not in operators:
            raise ValueError(f"trigger operator lacks display projection: {operator}")
        value = clause.get("value")
        if isinstance(value, list):
            value_text = "、".join(str(item) for item in value)
        elif isinstance(value, bool):
            value_text = "是" if value else "否"
        else:
            value_text = str(value)
        rendered.append(f"{_FIELD_LABELS.get(field, field)}{operators[operator]}{value_text}")
    joiner = "且" if logic.get("mode") == "all" else "或"
    return joiner.join(rendered)
def _account_controls(
    *,
    main_counter: Mapping[str, Any],
    maker_counter: Mapping[str, Any],
    main_invalidation: Mapping[str, Any],
    maker_invalidation: Mapping[str, Any],
    presentation_contract: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    return {
        "main": {
            "counter": {
                "claim_id": main_counter["id"],
                "condition": _trigger_condition(main_counter, presentation_contract),
            },
            "invalidation": {
                "claim_id": main_invalidation["id"],
                "condition": _trigger_condition(main_invalidation, presentation_contract),
            },
        },
        "maker": {
            "counter": {
                "claim_id": maker_counter["id"],
                "condition": _trigger_condition(maker_counter, presentation_contract),
            },
            "invalidation": {
                "claim_id": maker_invalidation["id"],
                "condition": _trigger_condition(maker_invalidation, presentation_contract),
            },
        },
    }
def _proof_chains(
    claims: list[dict[str, Any]],
    *,
    claim_by_id: Mapping[str, Mapping[str, Any]],
    observation_by_id: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    chains: list[dict[str, Any]] = []
    for claim in claims:
        support: list[str] = []
        counter: list[str] = []
        for field, target in (("support_ids", support), ("counter_ids", counter)):
            values = claim.get(field)
            if not isinstance(values, list):
                raise TypeError(f"claim graph field is not an array: {claim.get('id')}.{field}")
            for node_id in values:
                node = claim_by_id.get(str(node_id)) or observation_by_id.get(str(node_id))
                if node is None:
                    raise ValueError(f"claim graph references an unknown node: {node_id}")
                text = node.get("conclusion") or node.get("fact")
                if not isinstance(text, str) or not text.strip():
                    raise ValueError(f"claim graph node lacks human meaning: {node_id}")
                target.append(text)
        chains.append(
            {
                "claim_id": claim["id"],
                "claim_type": claim.get("claim_type"),
                "account": claim.get("account"),
                "conclusion": claim.get("conclusion"),
                "support": support,
                "counter": counter,
                "invalidation": claim.get("invalidation"),
            }
        )
    return chains
_PROOF_BLOCK_CLAIM_TYPES = {
    "orderflow_anchor": {"orderflow_interpretation"},
    "footprint_cross_check": {"orderflow_interpretation"},
    "multi_timeframe_structure": {"chart_interpretation"},
    "july_additions": {"etf_confirmation", "liquidation_confirmation", "liquidity_hunt"},
    "fundamental_and_etf_realization": {"fundamental_context", "fundamental_price_realization", "etf_confirmation"},
    "main_account_closure": {"main_account_thesis", "strongest_counterevidence", "invalidation_path"},
    "maker_account_closure": {"maker_thesis", "strongest_counterevidence", "invalidation_path"},
    "account_separation": {"main_account_thesis", "maker_thesis"},
    "score_and_winrate": {"orderflow_interpretation", "chart_interpretation", "maker_thesis"},
    "risk_and_scenarios": {"main_account_thesis", "maker_thesis", "invalidation_path"},
}
def _reasoning_proof_blocks(
    claims: list[dict[str, Any]],
    *,
    required_blocks: Any,
) -> dict[str, list[str]]:
    if not isinstance(required_blocks, list) or set(required_blocks) != set(_PROOF_BLOCK_CLAIM_TYPES):
        raise ValueError("presentation reasoning-proof topology is invalid")
    result: dict[str, list[str]] = {}
    for block in required_blocks:
        allowed_types = _PROOF_BLOCK_CLAIM_TYPES[str(block)]
        ids = [
            str(claim["id"])
            for claim in claims
            if claim.get("claim_type") in allowed_types
            and (
                block not in {"main_account_closure", "maker_account_closure"}
                or claim.get("account") == ("main" if block.startswith("main") else "maker")
            )
        ]
        if not ids:
            raise ValueError(f"reasoning proof block has no certified claim: {block}")
        result[str(block)] = ids
    return result
def _execution_action_text(action: Any) -> str:
    return {"not_attempted": "未尝试真实执行", "place_order": "具备资格并挂出条件订单", "observe": "具备执行环境但本轮仅观望、不挂单", "blocked": "真实执行资格被阻断"}[str(action)]
def _main_authorization_text(main: Mapping[str, Any], authorization: Mapping[str, Any], run_mode: str) -> str:
    observing = main.get("plan_state") == "observe"
    if run_mode == "shadow":
        return "影子主账户观察状态；未读取或改变真实持仓，未生成计划且未尝试任何真实执行。" if observing else "影子候选主账户计划；未读取或改变真实持仓，未尝试任何真实执行。"
    if observing:
        return "主账户观察状态；不生成或执行计划，后续须重新认证并另获生产授权。"
    return "主账户仅可在本轮已认证执行授权内行动。" if authorization.get("live_execution_allowed") is True else "主账户本轮禁止真实执行，仅保留分析与计划投影。"
def _maker_authorization_text(maker: Mapping[str, Any], semantic_state: str, authorization: Mapping[str, Any], run_mode: str) -> str:
    if run_mode == "shadow":
        prefix = {"qualified_candidate": "影子候选计划", "rejected_submitted_candidate": "影子被拒候选审计状态", "directional_thesis_only": "影子方向观察状态", "non_directional_observation": "影子无方向观察状态"}[semantic_state]
        return f"{prefix}；未读取个人持仓/订单状态；未创建、撤销或挂出真实订单"
    eligibility = "当前具备真实执行资格" if authorization.get("live_execution_allowed") is True else "当前不具备真实执行资格"
    return f"计划结论与执行资格独立认证；{eligibility}；{_execution_action_text(maker.get('execution_action'))}"
def _maker_execution_status_text(maker: Mapping[str, Any], run_mode: str) -> str:
    return f"真实执行状态：{_execution_action_text('not_attempted' if run_mode == 'shadow' else maker.get('execution_action'))}"
def _continuity_text(continuity: Mapping[str, Any]) -> str:
    current = continuity.get("current_plan")
    if isinstance(current, Mapping):
        return f"当前计划动作{current.get('action')}，已执行{current.get('executed_pct')}%，有效至{current.get('valid_until')}；{current.get('reason')}"
    return f"影子连续性：计划结论有效至{continuity.get('plan_valid_until')}。"
def _maker_plan_reason_texts(maker: Mapping[str, Any]) -> list[str]:
    value = _require_mapping(maker.get("plan_constructibility"), "decision.maker.plan_constructibility")
    primary = str(value.get("primary_reason_code") or "")
    raw_codes = value.get("failure_codes")
    if not isinstance(raw_codes, list):
        raise ValueError("plan_constructibility.failure_codes must be an array")
    codes = [str(item) for item in raw_codes]
    unknown = [code for code in codes if code not in _CONSTRUCTIBILITY_REASON_CN]
    expected = [code for code in MAKER_FAILURE_ORDER if code in set(codes)]
    if len(codes) != len(set(codes)) or unknown or codes != expected:
        raise ValueError("plan_constructibility.failure_codes is not canonical")
    if (codes and primary != codes[0]) or (not codes and primary != "constructible"):
        raise ValueError("plan_constructibility.primary_reason_code is inconsistent")
    reasons = [_CONSTRUCTIBILITY_REASON_CN[code] for code in codes]
    if maker.get("threshold_eligible") is False:
        reasons.append(_THRESHOLD_INELIGIBLE_CN)
    return reasons or [_CONSTRUCTIBILITY_REASON_CN["constructible"]]
def _maker_execution_text(semantic_state: str, reasons: list[str]) -> str:
    if semantic_state == "qualified_candidate":
        return "候选计划已通过认证；计划结论成立，真实执行资格另由 execution_authorization 决定。"
    if semantic_state == "rejected_submitted_candidate":
        enumerated = "；".join(f"{index}.{reason}" for index, reason in enumerate(reasons, start=1))
        return f"已提交候选未通过认证，不可执行；全部原因={enumerated}"
    if semantic_state == "directional_thesis_only":
        return "本轮仅有方向论点（未提交候选计划，风险与执行均不适用）"
    return "本轮无方向观察（未提交候选计划，风险与执行均不适用）"
def _candidate_plan_audit(value: Any, *, semantic_state: str) -> dict[str, Any]:
    projected = copy.deepcopy(dict(value)) if isinstance(value, Mapping) else {}
    if projected and semantic_state == "rejected_submitted_candidate":
        projected["candidate_status"] = "rejected_not_executable"
    return projected
def _maker_risk_scenarios(maker: Mapping[str, Any]) -> list[dict[str, str]]:
    risk = _require_mapping(maker.get("risk_plan"), "decision.maker.risk_plan")
    return maker_fill_scenarios(
        entries=[Decimal(str(value)) for value in risk.get("entries", [])],
        allocations=[Decimal(str(value)) for value in risk.get("entry_allocations_pct", [])],
        direction=str(maker.get("direction")),
        stop=Decimal(str(risk["stop"])),
        tp1=Decimal(str(risk["tp1"])),
        tp2=Decimal(str(risk["tp2"])),
        leverage=Decimal(str(risk["leverage"])),
    )
def _risk_projection(maker: Mapping[str, Any], *, semantic_state: str) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, str]]:
    def result(status: str, primary: list[dict[str, str]] | None = None, rejected: list[dict[str, str]] | None = None) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, str]]:
        return primary or [], rejected or [], {"status": status, "reason_code": _REJECTED_RISK_REASONS[status]}
    if semantic_state == "qualified_candidate":
        return result("not_applicable", primary=_maker_risk_scenarios(maker))
    risk = maker.get("risk_plan")
    if not isinstance(risk, Mapping) or not risk:
        return result("not_submitted")
    if maker.get("plan_constructible") is not True:
        return result("not_recalculable")
    try:
        rejected = _maker_risk_scenarios(maker)
    except (ArithmeticError, IndexError, KeyError, TypeError, ValueError):
        rejected = []
    return result("recalculated" if rejected else "not_recalculable", rejected=rejected)
def _maker_execution_projection(maker: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        "direction",
        "plan_state",
        "execution_action",
        "strategy_type",
        "order_method",
        "entry_type",
        "exchange",
        "instrument",
        "position_notional_usdt",
        "cannot_do_code",
        "cannot_do_claim_id",
        "threshold_eligible",
        "plan_constructible",
        "plan_constructibility",
        "order_transition_action",
    )
    return {field: copy.deepcopy(maker.get(field)) for field in fields}
def evaluate_human_reasoning_depth(
    model: Mapping[str, Any],
    *,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Certify semantic completeness; do not score prose style or trading quality."""
    certify_presentation_contract(contract)
    defects: list[dict[str, Any]] = []
    audit = model.get("audit") if isinstance(model.get("audit"), Mapping) else {}
    sources = audit.get("sources") if isinstance(audit, Mapping) else {}
    if not isinstance(sources, Mapping) or set(sources) != set(REQUIRED_SOURCES):
        defects.append(_defect("report.depth.six_sources", "six-source projection is incomplete", "audit.sources"))
    chains = audit.get("proof_chains") if isinstance(audit, Mapping) else None
    if not isinstance(chains, list) or not chains:
        defects.append(_defect("report.depth.support_dag", "human-readable support DAG is missing", "audit.proof_chains"))
    blocks = audit.get("reasoning_proof_blocks") if isinstance(audit, Mapping) else None
    required_blocks = contract["required_reasoning_proof_blocks"]
    if not isinstance(blocks, Mapping) or set(blocks) != set(required_blocks) or any(not blocks[key] for key in required_blocks):
        defects.append(_defect("report.depth.proof_blocks", "required reasoning proof topology is incomplete", "audit.reasoning_proof_blocks"))
    if not isinstance(audit, Mapping) or audit.get("risk_values_owner") != "certified_decision_direct_copy":
        defects.append(_defect("report.depth.risk_owner", "risk values are not certified as direct decision copies", "audit.risk_values_owner"))
    scenarios = audit.get("scenario_tree") if isinstance(audit, Mapping) else None
    if not isinstance(scenarios, list) or len(scenarios) != 6:
        defects.append(_defect("report.depth.scenarios", "main/Maker scenario ownership matrix is incomplete", "audit.scenario_tree"))
    maker_summary = model.get("maker_summary") if isinstance(model.get("maker_summary"), Mapping) else {}
    frontstage = model.get("frontstage") if isinstance(model.get("frontstage"), Mapping) else {}
    if maker_summary.get("semantic_state") == "non_directional_observation" and any(
        marker in str(dict(frontstage)) for marker in ("影子候选计划", "候选判断有效至", "BTC（候选策略）", "候选计划结论", "候选减仓规则")
    ):
        defects.append(_defect("report_projection.shadow_semantic_state_conflict", "non-directional Maker state contains directional candidate surface text", "frontstage"))
    for section in ("main_summary", "maker_summary"):
        value = model.get(section)
        if not isinstance(value, Mapping) or any(not str(value.get(field) or "").strip() for field in ("thesis", "counter", "invalidation")):
            defects.append(_defect("report.depth.account_closure", f"{section} lacks thesis/counter/invalidation closure", section))
    return {
        "passed": not defects,
        "defects": defects,
        "facts": {
            "source_count": len(sources) if isinstance(sources, Mapping) else 0,
            "proof_chain_count": len(chains) if isinstance(chains, list) else 0,
            "proof_block_count": len(blocks) if isinstance(blocks, Mapping) else 0,
            "scenario_count": len(scenarios) if isinstance(scenarios, list) else 0,
        },
    }
def evaluate_gold_template_fidelity(
    markdown: str,
    *,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate display-only v12 layout/rhythm constraints in memory."""
    certify_presentation_contract(contract)
    if not isinstance(markdown, str):
        raise TypeError("report markdown must be text")
    defects: list[dict[str, Any]] = []
    lines = markdown.splitlines()
    headings = [line for line in lines if line.startswith("#")]
    h4 = [line for line in lines if line.startswith("#### ")]
    bullets = [line for line in lines if line.startswith(("- ", "* "))]
    nonempty = [line for line in lines if line.strip()]
    density = contract["density_limits"]
    if len(headings) > density["maximum_heading_count"]:
        defects.append(_defect("report.layout.heading_density", "heading count exceeds the presentation contract", "markdown"))
    if len(h4) > density["maximum_h4_count"]:
        defects.append(_defect("report.layout.h4", "H4 headings are forbidden", "markdown"))
    bullet_ratio = len(bullets) / max(len(nonempty), 1)
    if bullet_ratio > density["maximum_bullet_ratio"]:
        defects.append(_defect("report.layout.bullet_density", "bullet ratio exceeds the presentation contract", "markdown"))
    required_markers = (
        "## ① 正文",
        "## 不能做",
        "## ② Maker 计划",
        "## ③ 后附",
        "### C. 人类可读推理证明链",
        "### D. 风险、情景与机械校验",
    )
    positions = [markdown.find(marker) for marker in required_markers]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        defects.append(_defect("report.layout.content_order", "canonical report sections are missing or out of order", "markdown"))
    if re.search(r"\b[0-9a-f]{64}\b", markdown):
        defects.append(_defect("report.layout.raw_hash", "raw authority hashes are forbidden on the human surface", "markdown"))
    return {
        "passed": not defects,
        "defects": defects,
        "facts": {
            "heading_count": len(headings),
            "h4_count": len(h4),
            "bullet_ratio": bullet_ratio,
        },
    }
def run_compatibility_lint(
    markdown: str,
    *,
    report_filename: str,
    trading_date: str,
    slot: str,
) -> dict[str, Any]:
    """Run the complete existing report lint without file I/O."""
    lint = lint_report_text(markdown, report_filename=report_filename)
    defects = list(lint["defects"])
    if report_filename != f"{trading_date}_{slot}_combined.md":
        defects.insert(0, _defect("report.compatibility.filename", "combined report filename is not canonical", "report_filename"))
    output = "\n".join(item["message"] for item in defects)
    return {
        "passed": not defects,
        "exit_code": 0 if not defects else 1,
        "output": output,
        "defects": defects,
    }
def _defect(code: str, message: str, path: str) -> dict[str, Any]:
    return {"code": code, "message": message, "path": path, "severity": "hard"}
__all__ = [
    "CANONICAL_REPORT_FIELDS",
    "build_report_bindings",
    "certify_canonical_report_model",
    "certify_maker_semantic_state",
    "certify_order_lifecycle",
    "certify_presentation_contract",
    "certify_report_projection_input",
    "evaluate_gold_template_fidelity",
    "evaluate_human_reasoning_depth",
    "order_lifecycle_display",
    "project_scenario_audit",
    "run_compatibility_lint",
    "scenario_projection_policy",
    "validate_scenario_projection",
]
