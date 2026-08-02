from __future__ import annotations

import ast
import copy
import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import runtime.golden_methodology as golden_methodology
import runtime_vnext.reasoning_submission as reasoning_submission
from runtime_vnext.domain_ir.registry import (
    ORDERFLOW_FINAL_DIRECTION_TO_CLAIM_DIRECTION,
)
from runtime_vnext.errors import FailureClass, WorkflowFailure
from runtime_vnext.gates import _execution_parameter_leak, evaluate_reasoning
from runtime_vnext.methodology import (
    build_methodology_manifest,
    canonical_sha256,
    load_scoring_policy,
)
from runtime_vnext.reasoning_submission import (
    load_reasoning_submission_contract,
    project_observation_mechanical_fields,
    validate_contract_runtime_compatibility,
    validate_methodology_submission_shape,
)


ROOT = Path(__file__).resolve().parents[1]

EXPECTED_BUSINESS_DEFECTS = (
    (
        "reasoning_shape.string_required",
        "methodology.independent_synthesis.action_claim_id",
        "expected a non-empty string",
    ),
    (
        "reasoning_shape.string_too_short",
        "methodology.multi_timeframe_transition.transition_summary",
        "string requires at least 20 characters",
    ),
    (
        "reasoning_shape.enum_invalid",
        "methodology.fundamental_event_assessments[0].impact_channel",
        "value must be one of ['liquidity', 'regulation', 'risk_appetite']",
    ),
)


def _tree_snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _diff_paths(left, right, path: str = "") -> list[str]:
    if type(left) is not type(right):
        return [path]
    if isinstance(left, dict):
        paths: list[str] = []
        for key in sorted(set(left) | set(right)):
            child = f"{path}.{key}" if path else str(key)
            if key not in left or key not in right:
                paths.append(child)
            else:
                paths.extend(_diff_paths(left[key], right[key], child))
        return paths
    if isinstance(left, list):
        paths = []
        if len(left) != len(right):
            paths.append(f"{path}.length")
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            paths.extend(
                _diff_paths(left_item, right_item, f"{path}[{index}]")
            )
        return paths
    return [] if left == right else [path]


def _claims_without_relative_pair_operators(
    payload: dict,
    *,
    claim_id: str,
) -> list:
    claims = copy.deepcopy(payload["claims"])
    for claim in claims:
        if not isinstance(claim, dict) or claim.get("id") != claim_id:
            continue
        trigger = claim.get("trigger_logic") if isinstance(claim, dict) else None
        clauses = trigger.get("clauses") if isinstance(trigger, dict) else None
        if not isinstance(clauses, list):
            continue
        for clause in clauses:
            if not isinstance(clause, dict):
                continue
            if (
                clause.get("owner_id") == "obs_cg"
                and clause.get("field") == "final_direction"
            ) or (
                clause.get("owner_id") == "obs_exo"
                and clause.get("field") == "cross_check_result"
            ):
                clause.pop("operator", None)
    return claims


def _malformed_live_methodology() -> dict:
    scenarios = []
    action_by_kind = {
        "base": "retain_certified_assessment",
        "counter": "reassess_on_typed_counter",
        "invalidation": "invalidate_and_recollect_evidence",
    }
    for account in ("main", "maker"):
        for kind in ("base", "counter", "invalidation"):
            scenarios.append(
                {
                    "account": account,
                    "kind": kind,
                    "claim_id": f"claim_{account}_{kind}",
                    "trigger_claim_ids": ["claim_trigger"],
                    "action": action_by_kind[kind],
                }
            )
    return {
        "account_separation": {
            "main_claim_id": "claim_main",
            "maker_claim_id": "claim_maker",
            "maker_counter_claim_id": "claim_maker_counter",
            "posthoc_comparison_only": True,
        },
        "cannot_do_derivation": {
            "claim_id": "claim_cannot",
            "support_claim_ids": [
                "claim_maker",
                "claim_maker_counter",
                "claim_maker_invalidation",
            ],
        },
        "etf_flow_relation": {
            "claim_id": "claim_etf",
            "price_relation": "confirm",
        },
        "footprint_cross_check": {
            "claim_id": "claim_orderflow",
            "observation_id": "obs_exocharts",
            "relationship": "confirm",
        },
        "fundamental_event_assessments": [
            {
                "boundary_code": "no_standalone_direction_requires_cross_source_realization",
                "counter_claim_ids": ["claim_chart"],
                "expected_effect": "adverse_for_risk_assets",
                "impact_channel": "liquidity",
                "realization_claim_id": f"claim_event_{index}",
                "selected_event_sha256": str(index) * 64,
            }
            for index in range(1, 4)
        ],
        "fundamental_price_realization": {
            "claim_id": "claim_realization",
            "realization_state": "partially_realized",
        },
        "independent_synthesis": {
            "market_stage_claim_id": "claim_maker_regime",
            "primary_evidence_claim_ids": ["claim_orderflow", "claim_chart"],
        },
        "multi_timeframe_transition": {
            "claim_id": "claim_chart",
            "observation_id": "obs_tradingview",
            "timeframes": {},
        },
        "same_pivot_orderflow": {
            "claim_id": "claim_orderflow",
            "combination_id": "C50",
            "final_direction": "bearish",
            "observation_id": "obs_coinglass",
        },
        "scenario_tree": scenarios,
        "volume_profile_liquidity": {
            "claim_id": "claim_chart",
            "liquidation_confirmation": "neutral",
            "observation_id": "obs_tradingview",
            "profile_status": "insufficient",
        },
    }


def _methodology_ownership_drift_cases(
    contract: dict,
) -> list[tuple[str, dict]]:
    binding_path = "methodology.volume_profile_liquidity.claim_id"
    cases: list[tuple[str, dict]] = []

    missing_binding = copy.deepcopy(contract)
    del missing_binding["server_projection"]["methodology_leaf_ownership"][
        "server_owned_bindings"
    ][binding_path]
    cases.append(("missing_binding", missing_binding))

    overlapping_owner = copy.deepcopy(contract)
    overlap_path = (
        "methodology.independent_synthesis.market_stage_claim_id"
    )
    overlapping_owner["server_projection"]["methodology_leaf_ownership"][
        "server_owned_bindings"
    ][overlap_path] = {
        "resolver": "unique_claim_id",
        "claim_type": "market_regime",
        "account": "main",
    }
    overlapping_owner["server_projection"]["server_owned_paths"].append(
        overlap_path
    )
    cases.append(("server_model_overlap", overlapping_owner))

    wrong_resolver = copy.deepcopy(contract)
    wrong_resolver["server_projection"]["methodology_leaf_ownership"][
        "server_owned_bindings"
    ][binding_path]["resolver"] = "first_claim_id"
    cases.append(("wrong_resolver", wrong_resolver))

    wrong_owner = copy.deepcopy(contract)
    wrong_owner["server_projection"]["methodology_leaf_ownership"][
        "server_owned_bindings"
    ][binding_path]["account"] = "maker"
    cases.append(("wrong_owner", wrong_owner))

    return cases


class ReasoningSubmissionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load_reasoning_submission_contract(root=ROOT)
        cls.policy = load_scoring_policy(root=ROOT)

    def test_contract_is_runtime_compatible_and_evidence_phase_is_frozen(self) -> None:
        self.assertEqual(
            validate_contract_runtime_compatibility(
                self.contract,
                full_policy=self.policy,
            ),
            [],
        )
        manifest = build_methodology_manifest(root=ROOT)
        self.assertEqual(
            manifest["phases"]["evidence"]["phase_sha256"],
            "3233b3adcbe537c403b9dfa5e68ae796e086ddb92c0b803bc6022af7aa8127ad",
        )
        self.assertIn(
            "scoring/reasoning_submission_contract.json",
            {
                item["path"]
                for item in manifest["phases"]["reasoning"]["files"]
            },
        )
        self.assertNotIn(
            "scoring/reasoning_submission_contract.json",
            {
                item["path"]
                for item in manifest["phases"]["evidence"]["files"]
            },
        )

    def test_scenario_submission_contract_has_one_typed_owner_and_no_prose(self) -> None:
        self.assertEqual(
            self.contract["schema_version"],
            "reasoning-submission-contract-v6",
        )
        self.assertEqual(
            self.contract["certified_schema_version"],
            "reasoning-model-v5",
        )
        self.assertEqual(
            self.contract["scenario_fields"],
            ["id", "account", "scenario_type", "owner_claim_id"],
        )
        self.assertEqual(
            self.contract["scenario_ownership"],
            {
                "schema_version": "scenario-ownership-v1",
                "items": [
                    {
                        "id": "scenario_main_base",
                        "account": "main",
                        "scenario_type": "base",
                        "owner_claim_type": "main_account_thesis",
                    },
                    {
                        "id": "scenario_main_counter",
                        "account": "main",
                        "scenario_type": "counter",
                        "owner_claim_type": "strongest_counterevidence",
                    },
                    {
                        "id": "scenario_main_invalidation",
                        "account": "main",
                        "scenario_type": "invalidation",
                        "owner_claim_type": "invalidation_path",
                    },
                    {
                        "id": "scenario_maker_base",
                        "account": "maker",
                        "scenario_type": "base",
                        "owner_claim_type": "maker_thesis",
                    },
                    {
                        "id": "scenario_maker_counter",
                        "account": "maker",
                        "scenario_type": "counter",
                        "owner_claim_type": "strongest_counterevidence",
                    },
                    {
                        "id": "scenario_maker_invalidation",
                        "account": "maker",
                        "scenario_type": "invalidation",
                        "owner_claim_type": "invalidation_path",
                    },
                ],
                "transition_code_by_type": {
                    "base": "retain_certified_assessment",
                    "counter": "reassess_on_typed_counter",
                    "invalidation": "invalidate_and_recollect_evidence",
                },
                "producer_free_prose_allowed": False,
                "execution_lifecycle_owner": "decision_and_continuity",
            },
        )
        scenario_spec = self.contract["methodology"]["arrays"]["scenario_tree"][
            "item"
        ]
        self.assertEqual(
            scenario_spec["enum_fields"]["action"]["values"],
            [
                "retain_certified_assessment",
                "reassess_on_typed_counter",
                "invalidate_and_recollect_evidence",
            ],
        )
        self.assertNotIn("action", scenario_spec.get("string_fields", []))
        self.assertNotIn("action", scenario_spec.get("string_min_lengths", {}))

        scaffold = reasoning_submission.build_reasoning_submission_scaffold(
            evidence={
                "trading_date": "2026-07-29",
                "slot": "midday",
                "snapshot_sha256": "a" * 64,
            },
            reasoning_authority_sha256="b" * 64,
            contract=self.contract,
            full_policy=self.policy,
        )
        self.assertEqual(
            scaffold["schema_version"],
            "reasoning-submission-scaffold-v6",
        )
        scenarios = scaffold["submission_template"]["scenario_tree"]
        self.assertEqual(
            [
                (item["id"], item["account"], item["scenario_type"])
                for item in scenarios
            ],
            [
                ("scenario_main_base", "main", "base"),
                ("scenario_main_counter", "main", "counter"),
                ("scenario_main_invalidation", "main", "invalidation"),
                ("scenario_maker_base", "maker", "base"),
                ("scenario_maker_counter", "maker", "counter"),
                ("scenario_maker_invalidation", "maker", "invalidation"),
            ],
        )
        self.assertTrue(
            all(set(item) == set(self.contract["scenario_fields"]) for item in scenarios)
        )
        methodology_scenarios = scaffold["submission_template"]["methodology"][
            "scenario_tree"
        ]
        action_by_kind = {
            "base": "retain_certified_assessment",
            "counter": "reassess_on_typed_counter",
            "invalidation": "invalidate_and_recollect_evidence",
        }
        self.assertEqual(
            [item["action"] for item in methodology_scenarios],
            [action_by_kind[item["kind"]] for item in methodology_scenarios],
        )

    def test_server_projection_contract_and_scaffold_are_explicit(self) -> None:
        self.assertEqual(
            self.contract["schema_version"],
            "reasoning-submission-contract-v6",
        )
        projection = self.contract["server_projection"]
        self.assertEqual(
            projection["schema_version"],
            "reasoning-server-projection-v4",
        )
        ownership = projection["methodology_leaf_ownership"]
        self.assertEqual(
            ownership["schema_version"],
            "methodology-leaf-ownership-v1",
        )
        self.assertEqual(
            ownership["server_owned_subtrees"],
            [
                "methodology.account_separation",
                "methodology.scenario_tree",
            ],
        )
        self.assertEqual(
            ownership["model_owned_paths"],
            [
                "methodology.independent_synthesis.market_stage_claim_id",
                "methodology.independent_synthesis.primary_evidence_claim_ids",
                "methodology.independent_synthesis.strongest_counter_claim_id",
                "methodology.independent_synthesis.action_claim_id",
                (
                    "methodology.fundamental_event_assessments[*]."
                    "impact_channel"
                ),
                (
                    "methodology.fundamental_event_assessments[*]."
                    "expected_effect"
                ),
                (
                    "methodology.fundamental_event_assessments[*]."
                    "counter_claim_ids"
                ),
                (
                    "methodology.multi_timeframe_transition."
                    "transition_summary"
                ),
            ],
        )
        self.assertEqual(
            ownership["producer_key_paths"],
            [
                (
                    "methodology.fundamental_event_assessments[*]."
                    "selected_event_sha256"
                )
            ],
        )
        self.assertEqual(ownership["leaf_count"], 54)
        self.assertEqual(
            ownership["server_owned_bindings"][
                "methodology.volume_profile_liquidity.claim_id"
            ],
            {
                "resolver": "unique_claim_id",
                "claim_type": "chart_interpretation",
                "account": "shared",
            },
        )
        self.assertTrue(
            set(ownership["server_owned_bindings"])
            <= set(projection["server_owned_paths"])
        )
        self.assertEqual(
            self.contract["scaffold_policy"]["schema_version"],
            "reasoning-submission-scaffold-v6",
        )
        self.assertFalse(
            projection["producer_values_at_server_owned_paths_authoritative"]
        )
        self.assertTrue(projection["projection_must_run_inside_reasoning_attempt"])
        self.assertTrue(projection["business_judgment_repair_forbidden"])
        self.assertEqual(
            projection["relative_trigger_operator_projection"],
            {
                "schema_version": "relative-trigger-operator-projection-v1",
                "claim_types": [
                    "strongest_counterevidence",
                    "invalidation_path",
                ],
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
        )
        trigger_policy = self.policy["gold_methodology"]["account_trigger_logic"]
        self.assertEqual(trigger_policy["schema_version"], "account-trigger-logic-v5")
        self.assertEqual(
            trigger_policy["relative_direction_observation_fields"]["Exocharts"][
                "cross_check_result"
            ]["reference_operator_policy"],
            {
                "target_equals_current": "equals_at_trigger",
                "target_differs_from_current": "becomes",
            },
        )
        self.assertEqual(
            trigger_policy["future_trigger_current_truth_quantifier_by_mode"],
            {"all": "all", "any": "any"},
        )
        self.assertEqual(
            projection["methodology_trigger_claim_ids_policy_path"],
            (
                "gold_methodology.account_trigger_logic."
                "scenario_control_binding.methodology_trigger_claim_ids_source"
            ),
        )
        self.assertEqual(
            projection["orderflow_direction_policy_path"],
            "maker_score.orderflow.final_direction_to_claim_direction",
        )
        self.assertEqual(
            self.policy["gold_methodology"]["account_independence"][
                "conflict_policy"
            ],
            "preserve_independent_outputs",
        )
        self.assertEqual(
            self.contract["methodology"]["objects"]["account_separation"][
                "exact_policy_values"
            ]["conflict_policy"],
            "gold_methodology.account_independence.conflict_policy",
        )

        evidence = {
            "trading_date": "2026-07-29",
            "slot": "midday",
            "snapshot_sha256": "a" * 64,
            "sources": {
                source: {
                    "observed_at": f"2026-07-29T0{index}:00:00+08:00",
                    "source_meta": {},
                }
                for index, source in enumerate(
                    (
                        "BlockBeats",
                        "FedWatch",
                        "Farside",
                        "Coinglass",
                        "Exocharts",
                        "TradingView",
                    ),
                    start=1,
                )
            },
        }
        scaffold = reasoning_submission.build_reasoning_submission_scaffold(
            evidence=evidence,
            reasoning_authority_sha256="b" * 64,
            contract=self.contract,
            full_policy=self.policy,
        )
        self.assertEqual(
            scaffold["schema_version"],
            "reasoning-submission-scaffold-v6",
        )
        self.assertEqual(scaffold["server_projection"], projection)
        self.assertEqual(scaffold["claim_topology"], self.contract["claim_topology"])
        self.assertEqual(
            scaffold["typed_narrative_ownership"],
            self.contract["typed_narrative_ownership"],
        )
        self.assertEqual(
            scaffold["claim_topology"][
                "required_reachable_claim_types_by_claim_type"
            ]["invalidation_path"],
            ["market_regime"],
        )
        self.assertFalse(
            scaffold["claim_topology"]["server_support_edge_injection_allowed"]
        )
        self.assertEqual(
            scaffold["visual_citation_policy"],
            {
                "schema_version": "visual-citation-leaf-policy-v1",
                "empty_collections_are_metric_leaves": True,
                "empty_collection_semantics": (
                    "observable_absence_requires_bounded_citation"
                ),
            },
        )
        observations = scaffold["submission_template"]["observations"]
        self.assertEqual(
            [item["source"] for item in observations],
            [
                "BlockBeats",
                "FedWatch",
                "Farside",
                "Coinglass",
                "Exocharts",
                "TradingView",
            ],
        )
        for item in observations:
            self.assertEqual(
                set(item),
                set(self.contract["observation_fields_by_source"][item["source"]]),
            )
            self.assertEqual(item["evidence_refs"], [])
        self.assertNotIn(
            "pivot_id",
            next(item for item in observations if item["source"] == "Exocharts"),
        )
        self.assertIn(
            "timeframe",
            next(item for item in observations if item["source"] == "TradingView"),
        )
        plan_c_evidence = copy.deepcopy(evidence)
        plan_c_evidence["sources"]["FedWatch"]["meta"] = {
            "selection_mode": "kalshi_plan_c_fallback"
        }
        plan_c_scaffold = reasoning_submission.build_reasoning_submission_scaffold(
            evidence=plan_c_evidence,
            reasoning_authority_sha256="b" * 64,
            contract=self.contract,
            full_policy=self.policy,
        )
        plan_c_fedwatch = next(
            item
            for item in plan_c_scaffold["submission_template"]["observations"]
            if item["source"] == "FedWatch"
        )
        self.assertEqual(
            set(plan_c_fedwatch),
            set(self.contract["observation_fields_by_source"]["FedWatchPlanC"]),
        )
        self.assertEqual(
            plan_c_fedwatch["kind"],
            "structured_observation",
        )
        self.assertEqual(plan_c_fedwatch["id"], "obs_fw")
        self.assertEqual(plan_c_fedwatch["source"], "FedWatch")
        self.assertEqual(
            plan_c_fedwatch["observed_at"],
            plan_c_evidence["sources"]["FedWatch"]["observed_at"],
        )
        self.assertEqual(
            plan_c_scaffold,
            reasoning_submission.build_reasoning_submission_scaffold(
                evidence=plan_c_evidence,
                reasoning_authority_sha256="b" * 64,
                contract=self.contract,
                full_policy=self.policy,
            ),
        )

    def test_orderflow_direction_projection_is_closed_and_deterministic(self) -> None:
        evidence = {
            "trading_date": "2026-07-29",
            "slot": "midday",
            "snapshot_sha256": "a" * 64,
            "sources": {
                source: {
                    "observed_at": "2026-07-29T12:00:00+08:00",
                    "meta": {},
                }
                for source in (
                    "BlockBeats",
                    "FedWatch",
                    "Farside",
                    "Coinglass",
                    "Exocharts",
                    "TradingView",
                )
            },
        }
        scaffold = reasoning_submission.build_reasoning_submission_scaffold(
            evidence=evidence,
            reasoning_authority_sha256="b" * 64,
            contract=self.contract,
            full_policy=self.policy,
        )["submission_template"]
        scaffold["claims"] = [
            {
                "id": "claim_orderflow",
                "claim_type": "orderflow_interpretation",
                "account": "shared",
                "direction": "producer-value",
                "support_ids": [],
            }
        ]
        expected = (
            ("bullish", "long"),
            ("bearish", "short"),
            ("neutral", "observe"),
            ("mixed", "observe"),
            ("unknown", None),
            (" bullish ", None),
            (7, None),
        )
        for source_direction, claim_direction in expected:
            with self.subTest(source_direction=source_direction):
                candidate = copy.deepcopy(scaffold)
                next(
                    item
                    for item in candidate["observations"]
                    if item["source"] == "Coinglass"
                )["metrics"]["final_direction"] = source_direction
                first = reasoning_submission.assemble_reasoning_submission(
                    candidate,
                    evidence=evidence,
                    reasoning_authority_sha256="b" * 64,
                    contract=self.contract,
                    full_policy=self.policy,
                )
                second = reasoning_submission.assemble_reasoning_submission(
                    candidate,
                    evidence=evidence,
                    reasoning_authority_sha256="b" * 64,
                    contract=self.contract,
                    full_policy=self.policy,
                )
                self.assertEqual(first, second)
                self.assertEqual(
                    first["claims"][0]["direction"],
                    claim_direction,
                )
        malformed = copy.deepcopy(scaffold)
        malformed["observations"][0]["source"] = []
        projected = reasoning_submission.assemble_reasoning_submission(
            malformed,
            evidence=evidence,
            reasoning_authority_sha256="b" * 64,
            contract=self.contract,
            full_policy=self.policy,
        )
        self.assertEqual(projected["observations"][0]["source"], [])

    def test_direct_support_projection_has_an_independent_closed_oracle(self) -> None:
        claims = {
            "claim_owner": {
                "id": "claim_owner",
                "support_ids": [
                    "obs_current",
                    "claim_direct_b",
                    "claim_direct_a",
                    "claim_direct_b",
                    "claim_owner",
                    "claim_missing",
                ],
            },
            "claim_direct_a": {
                "id": "claim_direct_a",
                "support_ids": [],
            },
            "claim_direct_b": {
                "id": "claim_direct_b",
                "support_ids": ["claim_transitive"],
            },
            "claim_transitive": {
                "id": "claim_transitive",
                "support_ids": [],
            },
        }
        self.assertEqual(
            reasoning_submission.derive_methodology_trigger_claim_ids(
                "claim_owner",
                claims,
            ),
            ["claim_direct_b", "claim_direct_a"],
        )

    def test_static_runtime_compatibility_negative_matrix(self) -> None:
        cases = (
            (
                "event_field_rename",
                lambda contract, policy: policy["gold_methodology"][
                    "fundamental_event_assessment_policy"
                ].__setitem__("methodology_field", "fundamental_events_v2"),
                "methodology.field_order",
            ),
            (
                "event_required_item_field",
                lambda contract, policy: policy["gold_methodology"][
                    "fundamental_event_assessment_policy"
                ]["required_item_fields"].append(
                    "event_price_attribution_basis"
                ),
                "methodology",
            ),
            (
                "block_order",
                lambda contract, policy: contract["methodology"].__setitem__(
                    "field_order",
                    list(reversed(contract["methodology"]["field_order"])),
                ),
                "methodology.field_order",
            ),
            (
                "wrong_enum_policy_path",
                lambda contract, policy: contract["methodology"]["objects"][
                    "independent_synthesis"
                ]["enum_fields"]["dominant_leg"].__setitem__(
                    "policy_path",
                    "gold_methodology.price_relations",
                ),
                (
                    "methodology.objects.independent_synthesis.enum_fields."
                    "dominant_leg.policy_path"
                ),
            ),
            (
                "minimum_string_length",
                lambda contract, policy: contract["methodology"]["objects"][
                    "multi_timeframe_transition"
                ]["string_min_lengths"].__setitem__(
                    "transition_summary",
                    1,
                ),
                (
                    "methodology.objects.multi_timeframe_transition."
                    "string_min_lengths.transition_summary"
                ),
            ),
            (
                "array_cardinality",
                lambda contract, policy: contract["methodology"]["arrays"][
                    "fundamental_event_assessments"
                ].update({"min_items": 2, "max_items": 2}),
                "methodology.arrays.fundamental_event_assessments.min_items",
            ),
            (
                "exact_policy_binding",
                lambda contract, policy: contract["methodology"]["objects"][
                    "account_separation"
                ]["exact_policy_values"].__setitem__(
                    "maker_priority",
                    "gold_methodology.main_account_priority",
                ),
                (
                    "methodology.objects.account_separation."
                    "exact_policy_values.maker_priority"
                ),
            ),
            (
                "scenario_core_minimum_exceeds_vnext_matrix",
                lambda contract, policy: policy["gold_methodology"].__setitem__(
                    "minimum_scenario_count",
                    7,
                ),
                "methodology.arrays.scenario_tree.min_items",
            ),
        )

        for name, mutate, expected_path in cases:
            with self.subTest(name=name):
                contract = copy.deepcopy(self.contract)
                policy = copy.deepcopy(self.policy)
                mutate(contract, policy)

                issues = validate_contract_runtime_compatibility(
                    contract,
                    full_policy=policy,
                )

                self.assertTrue(issues)
                expected_code = (
                    "reasoning_contract.methodology_runtime_inventory"
                    if name == "event_required_item_field"
                    else "reasoning_contract.methodology_inventory"
                )
                self.assertIn(
                    expected_code,
                    {item.code for item in issues},
                )
                self.assertIn(expected_path, {item.path for item in issues})

    def test_static_preflight_rejects_server_projection_drift(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["server_projection"][
            "producer_values_at_server_owned_paths_authoritative"
        ] = True
        issues = validate_contract_runtime_compatibility(
            contract,
            full_policy=self.policy,
        )
        self.assertIn(
            (
                "reasoning_contract.server_projection",
                "server_projection",
            ),
            {(item.code, item.path) for item in issues},
        )

        policy = copy.deepcopy(self.policy)
        policy["maker_score"]["orderflow"][
            "final_direction_to_claim_direction"
        ]["bullish"] = "bullish"
        issues = validate_contract_runtime_compatibility(
            self.contract,
            full_policy=policy,
        )
        self.assertIn(
            (
                "reasoning_contract.server_projection_policy",
                "server_projection",
            ),
            {(item.code, item.path) for item in issues},
        )

    def test_orderflow_direction_policy_is_registry_consumed_without_local_mirror(
        self,
    ) -> None:
        source = Path(reasoning_submission.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        mirror_lines: list[int] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            try:
                value = ast.literal_eval(node)
            except (TypeError, ValueError):
                continue
            if value == ORDERFLOW_FINAL_DIRECTION_TO_CLAIM_DIRECTION:
                mirror_lines.append(node.lineno)
        self.assertEqual(mirror_lines, [])

        policy_path = self.contract["server_projection"][
            "orderflow_direction_policy_path"
        ]
        policy_value = self.policy
        for part in policy_path.split("."):
            policy_value = policy_value[part]
        self.assertEqual(
            policy_value,
            ORDERFLOW_FINAL_DIRECTION_TO_CLAIM_DIRECTION,
        )
        self.assertEqual(
            validate_contract_runtime_compatibility(
                self.contract,
                full_policy=self.policy,
            ),
            [],
        )

        altered_owner = dict(ORDERFLOW_FINAL_DIRECTION_TO_CLAIM_DIRECTION)
        altered_owner["bullish"] = "short"
        with patch.object(
            reasoning_submission,
            "ORDERFLOW_FINAL_DIRECTION_TO_CLAIM_DIRECTION",
            altered_owner,
        ):
            issues = validate_contract_runtime_compatibility(
                self.contract,
                full_policy=self.policy,
            )
        self.assertIn(
            (
                "reasoning_contract.server_projection_policy",
                "server_projection",
            ),
            {(item.code, item.path) for item in issues},
        )

    def test_static_preflight_rejects_relative_operator_cross_contract_drift(
        self,
    ) -> None:
        scoring_mutations = {
            "target_equals_current": lambda relative: relative[
                "reference_operator_policy"
            ].__setitem__("target_equals_current", "becomes"),
            "target_differs_from_current": lambda relative: relative[
                "reference_operator_policy"
            ].__setitem__("target_differs_from_current", "equals_at_trigger"),
            "relative_operator": lambda relative: relative.__setitem__(
                "relative_operator",
                "becomes",
            ),
        }
        for name, mutate in scoring_mutations.items():
            with self.subTest(scoring_drift=name):
                scoring_drift = copy.deepcopy(self.policy)
                scoring_relative = scoring_drift["gold_methodology"][
                    "account_trigger_logic"
                ]["relative_direction_observation_fields"]["Exocharts"][
                    "cross_check_result"
                ]
                mutate(scoring_relative)
                issues = validate_contract_runtime_compatibility(
                    self.contract,
                    full_policy=scoring_drift,
                )
                self.assertIn(
                    (
                        "reasoning_contract.relative_trigger_policy_drift",
                        "server_projection.relative_trigger_operator_projection",
                    ),
                    {(item.code, item.path) for item in issues},
                )

        submission_drift = copy.deepcopy(self.contract)
        submission_drift["server_projection"][
            "relative_trigger_operator_projection"
        ]["reference_operator_when_target_differs_current"] = "equals_at_trigger"
        issues = validate_contract_runtime_compatibility(
            submission_drift,
            full_policy=self.policy,
        )
        self.assertIn(
            (
                "reasoning_contract.relative_trigger_policy_drift",
                "server_projection.relative_trigger_operator_projection",
            ),
            {(item.code, item.path) for item in issues},
        )

    def test_static_preflight_rejects_topology_and_narrative_drift(self) -> None:

        hidden_edge_contract = copy.deepcopy(self.contract)
        hidden_edge_contract["claim_topology"][
            "required_reachable_claim_types_by_claim_type"
        ]["invalidation_path"].append("strongest_counterevidence")
        issues = validate_contract_runtime_compatibility(
            hidden_edge_contract,
            full_policy=self.policy,
        )
        self.assertIn(
            ("reasoning_contract.claim_topology", "claim_topology"),
            {(item.code, item.path) for item in issues},
        )

        prose_owned_contract = copy.deepcopy(self.contract)
        prose_owned_contract["typed_narrative_ownership"][
            "prose_keyword_inference_allowed"
        ] = True
        issues = validate_contract_runtime_compatibility(
            prose_owned_contract,
            full_policy=self.policy,
        )
        self.assertIn(
            (
                "reasoning_contract.typed_narrative_ownership",
                "typed_narrative_ownership",
            ),
            {(item.code, item.path) for item in issues},
        )

    def test_methodology_ownership_completeness_drift_is_fail_closed(
        self,
    ) -> None:
        for name, contract in _methodology_ownership_drift_cases(self.contract):
            with self.subTest(name=name):
                issues = validate_contract_runtime_compatibility(
                    contract,
                    full_policy=self.policy,
                )
                self.assertIn(
                    (
                        "reasoning_contract.server_projection",
                        "server_projection",
                    ),
                    {(item.code, item.path) for item in issues},
                )

    def test_methodology_shape_returns_every_independent_live_defect(self) -> None:
        issues = validate_methodology_submission_shape(
            _malformed_live_methodology(),
            contract=self.contract,
            full_policy=self.policy,
        )
        missing = [
            item for item in issues if item.code == "reasoning_shape.field_missing"
        ]
        unknown = [
            item for item in issues if item.code == "reasoning_shape.field_unknown"
        ]
        self.assertEqual(len(missing), 25)
        self.assertEqual(len(unknown), 8)
        self.assertNotIn(
            "reasoning_shape.string_too_short",
            {item.code for item in issues},
        )
        self.assertEqual(len(issues), 33)
        self.assertEqual(
            [(item.code, item.path, item.message) for item in issues],
            [
                (item.code, item.path, item.message)
                for item in validate_methodology_submission_shape(
                    _malformed_live_methodology(),
                    contract=self.contract,
                    full_policy=self.policy,
                )
            ],
        )

    def test_sma20_period_is_not_an_execution_number_but_prices_remain_blocked(
        self,
    ) -> None:
        for text in (
            "多周期结构偏空且价格低于SMA20，但急跌后临近支撑并缺少可认证入场区。",
            "多周期结构偏空且价格低于二十期均线，但急跌后临近支撑并缺少可认证入场区。",
            "二十周期均线附近存在潜在入场区。",
        ):
            self.assertIsNone(_execution_parameter_leak(text), text)

        for text, expected in (
            ("SMA20附近入场区62800", "62800"),
            ("二十周期均线附近入场区62800-62900", "62800"),
            ("SMA20附近入场区，止损63100", "63100"),
            ("SMA20附近入场区，仓位750 USDT", "750"),
        ):
            self.assertEqual(_execution_parameter_leak(text), expected, text)


class ReasoningSubmissionControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        from tests.test_vnext_workflow import VNextWorkflowTests

        self.harness = VNextWorkflowTests(methodName="runTest")
        self.harness.setUp()
        raw_evidence = self.harness.evidence()
        self.harness.controller.accept_evidence(
            self.harness.run_root,
            raw_evidence,
            evidence_files_root=self.harness.root,
        )
        self.evidence = self.harness.controller.store.load_stage_payload(
            self.harness.run_root,
            "evidence",
            "evidence",
        )

    def candidate_with_business_defects(self) -> dict:
        candidate = self.harness.reasoning(self.evidence)
        methodology = candidate["methodology"]
        methodology["independent_synthesis"]["action_claim_id"] = ""
        methodology["multi_timeframe_transition"]["transition_summary"] = "short"
        methodology["fundamental_event_assessments"][0][
            "impact_channel"
        ] = "producer-invalid-impact"
        shape_issues = validate_methodology_submission_shape(
            methodology,
            contract=load_reasoning_submission_contract(root=self.harness.root),
            full_policy=load_scoring_policy(root=self.harness.root),
        )
        self.assertEqual(
            [
                (item.code, item.path, item.message)
                for item in shape_issues
            ],
            list(EXPECTED_BUSINESS_DEFECTS),
        )
        return candidate

    def reasoning_authority_sha256(self) -> str:
        methodology_manifest = json.loads(
            (self.harness.run_root / "methodology_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        return methodology_manifest["phases"]["reasoning"]["phase_sha256"]

    @staticmethod
    def methodology_defect_triples(defects: list[dict]) -> list[tuple[str, str, str]]:
        return [
            (item["code"], item["path"], item["message"])
            for item in defects
            if str(item.get("path", "")).startswith("methodology")
        ]

    @staticmethod
    def gate_methodology_defect_triples(defects) -> list[tuple[str, str, str]]:
        return [
            (item.code, item.path, item.message)
            for item in defects
            if str(item.path).startswith("methodology")
        ]

    def tearDown(self) -> None:
        self.harness.tearDown()

    def test_static_preflight_and_scaffold_do_not_create_an_attempt(self) -> None:
        before = _tree_snapshot(self.harness.run_root)
        result = self.harness.controller.reasoning_contract_preflight(
            self.harness.run_root
        )
        scaffold = self.harness.controller.reasoning_scaffold(
            self.harness.run_root
        )
        after = _tree_snapshot(self.harness.run_root)

        self.assertEqual(result["status"], "reasoning_contract_ready")
        contract = load_reasoning_submission_contract(root=self.harness.root)
        self.assertEqual(
            result["claim_topology_schema_version"],
            "claim-topology-v1",
        )
        self.assertEqual(
            result["claim_topology_sha256"],
            canonical_sha256(contract["claim_topology"]),
        )
        self.assertEqual(
            result["typed_narrative_ownership_sha256"],
            canonical_sha256(contract["typed_narrative_ownership"]),
        )
        self.assertEqual(scaffold["claim_topology"], contract["claim_topology"])
        self.assertEqual(
            scaffold["typed_narrative_ownership"],
            contract["typed_narrative_ownership"],
        )
        self.assertFalse(result["model_called"])
        self.assertFalse(result["attempt_created"])
        self.assertFalse(scaffold["business_semantics_checked"])
        self.assertFalse(scaffold["model_called"])
        self.assertFalse(scaffold["attempt_created"])
        self.assertEqual(
            set(scaffold["submission_template"]["methodology"]),
            set(
                load_reasoning_submission_contract(
                    root=self.harness.root
                )["methodology"]["field_order"]
            ),
        )
        methodology = scaffold["submission_template"]["methodology"]
        self.assertFalse(
            methodology["fundamental_price_realization"][
                "historical_market_fact_used"
            ]
        )
        self.assertTrue(
            methodology["same_pivot_orderflow"]["leg_selected"]
        )
        self.assertTrue(
            methodology["same_pivot_orderflow"]["pullback_anchor_checked"]
        )
        self.assertTrue(
            methodology["same_pivot_orderflow"]["four_dimensions_same_anchor"]
        )
        self.assertTrue(
            methodology["volume_profile_liquidity"][
                "user_drawn_profile_primary"
            ]
        )
        self.assertTrue(
            methodology["volume_profile_liquidity"]["liquidation_auxiliary"]
        )
        self.assertFalse(
            methodology["account_separation"]["forced_consensus"]
        )
        self.assertEqual(
            len(scaffold["submission_template"]["pipeline_units"]),
            17,
        )
        self.assertEqual(before, after)
        self.assertFalse((self.harness.run_root / "reasoning").exists())

    def test_controller_projects_server_owned_fields_inside_one_attempt(self) -> None:
        candidate = self.harness.reasoning(self.evidence)
        contract = load_reasoning_submission_contract(root=self.harness.root)
        expected_observations = {
            item["source"]: project_observation_mechanical_fields(
                item,
                source=item["source"],
                evidence=self.evidence,
                contract=contract,
            )
            for item in candidate["observations"]
        }
        visual_citations = {
            item["source"]: copy.deepcopy(item.get("visual_citations"))
            for item in candidate["observations"]
            if "visual_citations" in item
        }
        for observation in candidate["observations"]:
            observation["evidence_refs"] = []
            if "structured_binding" in observation:
                observation["structured_binding"] = {}
            review = observation.get("visual_review")
            if isinstance(review, dict):
                review.pop("metrics_sha256", None)
                review.pop("evidence_sha256", None)
        raw_gate = evaluate_reasoning(
            copy.deepcopy(candidate),
            evidence=self.evidence,
            reasoning_authority_sha256=self.reasoning_authority_sha256(),
            evidence_root=self.harness.root,
            methodology_root=self.harness.root,
        )
        self.assertIn(
            "tradingview.profile_sidecar_reference_missing",
            {item.code for item in raw_gate.defects},
        )
        candidate["schema_version"] = "producer-copy-is-not-authoritative"
        candidate["trading_date"] = "1900-01-01"
        candidate["slot"] = "evening"
        candidate["evidence_snapshot_sha256"] = "0" * 64
        candidate["reasoning_authority_sha256"] = "1" * 64
        candidate["methodology"]["account_separation"][
            "conflict_policy"
        ] = "follow_main_account_claim"
        for scenario in candidate["scenario_tree"]:
            scenario["owner_claim_id"] = "claim_wrong"
        for scenario in candidate["methodology"]["scenario_tree"]:
            scenario["claim_id"] = "claim_wrong"
            scenario["trigger_claim_ids"] = ["claim_wrong"]
            scenario["action"] = "retain_certified_assessment"
        for claim in candidate["claims"]:
            if claim["claim_type"] == "orderflow_interpretation":
                claim["direction"] = "bullish"
        candidate["pipeline_units"] = []

        self.harness.controller.accept_reasoning(
            self.harness.run_root,
            candidate,
        )
        certified = self.harness.controller.store.load_stage_payload(
            self.harness.run_root,
            "reasoning",
            "reasoning",
        )

        self.assertEqual(certified["schema_version"], "reasoning-model-v5")
        self.assertEqual(certified["trading_date"], self.evidence["trading_date"])
        self.assertEqual(certified["slot"], self.evidence["slot"])
        self.assertEqual(
            certified["evidence_snapshot_sha256"],
            self.evidence["snapshot_sha256"],
        )
        self.assertEqual(
            certified["methodology"]["account_separation"]["conflict_policy"],
            "preserve_independent_outputs",
        )
        methodology_manifest = json.loads(
            (
                self.harness.run_root / "methodology_manifest.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            certified["reasoning_authority_sha256"],
            methodology_manifest["phases"]["reasoning"]["phase_sha256"],
        )
        self.assertEqual(
            certified["methodology"]["account_separation"],
            {
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
        )
        expected_scenarios = [
            (
                "main",
                "base",
                "claim_main",
                [
                    "claim_regime_main",
                    "claim_realization",
                    "claim_etf",
                ],
                "retain_certified_assessment",
            ),
            (
                "main",
                "counter",
                "claim_counter_main",
                ["claim_regime_main", "claim_chart", "claim_etf"],
                "reassess_on_typed_counter",
            ),
            (
                "main",
                "invalidation",
                "claim_invalidation_main",
                [
                    "claim_counter_main",
                    "claim_regime_main",
                    "claim_chart",
                ],
                "invalidate_and_recollect_evidence",
            ),
            (
                "maker",
                "base",
                "claim_maker",
                [
                    "claim_regime_maker",
                    "claim_orderflow",
                    "claim_chart",
                    "claim_liq",
                ],
                "retain_certified_assessment",
            ),
            (
                "maker",
                "counter",
                "claim_counter_maker",
                ["claim_regime_maker", "claim_chart", "claim_orderflow"],
                "reassess_on_typed_counter",
            ),
            (
                "maker",
                "invalidation",
                "claim_invalidation_maker",
                [
                    "claim_counter_maker",
                    "claim_regime_maker",
                    "claim_chart",
                ],
                "invalidate_and_recollect_evidence",
            ),
        ]
        self.assertEqual(
            [
                (
                    item["account"],
                    item["kind"],
                    item["claim_id"],
                    item["trigger_claim_ids"],
                    item["action"],
                )
                for item in certified["methodology"]["scenario_tree"]
            ],
            expected_scenarios,
        )
        self.assertEqual(
            [
                (
                    item["account"],
                    item["scenario_type"],
                    item["owner_claim_id"],
                )
                for item in certified["scenario_tree"]
            ],
            [
                (account, kind, claim_id)
                for account, kind, claim_id, _, _ in expected_scenarios
            ],
        )
        self.assertEqual(len(certified["pipeline_units"]), 17)
        self.assertEqual(
            next(
                claim["direction"]
                for claim in certified["claims"]
                if claim["claim_type"] == "orderflow_interpretation"
            ),
            "short",
        )
        for observation in certified["observations"]:
            self.assertEqual(
                set(observation),
                set(
                    load_reasoning_submission_contract(
                        root=self.harness.root
                    )["observation_fields_by_source"][observation["source"]]
                ),
            )
            expected = expected_observations[observation["source"]]
            self.assertEqual(
                observation["evidence_refs"],
                expected["evidence_refs"],
            )
            if "structured_binding" in observation:
                self.assertEqual(
                    observation["structured_binding"],
                    expected["structured_binding"],
                )
            if "visual_review" in observation:
                self.assertEqual(
                    observation["visual_review"]["metrics_sha256"],
                    expected["visual_review"]["metrics_sha256"],
                )
                self.assertEqual(
                    observation["visual_review"]["evidence_sha256"],
                    expected["visual_review"]["evidence_sha256"],
                )
                self.assertEqual(
                    observation["visual_citations"],
                    visual_citations[observation["source"]],
                )
        self.assertEqual(
            [
                (
                    item["source"],
                    item["id"],
                    item["kind"],
                    item["observed_at"],
                )
                for item in certified["observations"]
            ],
            [
                (
                    "BlockBeats",
                    "obs_bb",
                    "structured_observation",
                    "2026-07-13T06:30:00+08:00",
                ),
                (
                    "FedWatch",
                    "obs_fw",
                    "visual_judgment",
                    "2026-07-13T06:30:00+08:00",
                ),
                (
                    "Farside",
                    "obs_fs",
                    "structured_observation",
                    "2026-07-13T06:30:00+08:00",
                ),
                (
                    "Coinglass",
                    "obs_cg",
                    "visual_judgment",
                    "2026-07-13T06:30:00+08:00",
                ),
                (
                    "Exocharts",
                    "obs_exo",
                    "visual_judgment",
                    "2026-07-13T06:30:00+08:00",
                ),
                (
                    "TradingView",
                    "obs_tv",
                    "visual_judgment",
                    "2026-07-13T06:30:00+08:00",
                ),
            ],
        )
        self.assertEqual(
            self.harness.controller.store.attempt_count(
                self.harness.run_root,
                "reasoning",
            ),
            1,
        )
        submitted = json.loads(
            (
                self.harness.run_root
                / "reasoning"
                / "attempt-001"
                / "submitted.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            submitted["methodology"]["account_separation"]["conflict_policy"],
            "follow_main_account_claim",
        )
        for observation in submitted["observations"]:
            self.assertEqual(observation["evidence_refs"], [])
            if "structured_binding" in observation:
                self.assertEqual(observation["structured_binding"], {})
            if "visual_review" in observation:
                self.assertNotIn("metrics_sha256", observation["visual_review"])
                self.assertNotIn("evidence_sha256", observation["visual_review"])
        self.assertEqual(submitted["pipeline_units"], [])
        self.assertFalse(
            (
                self.harness.run_root
                / "reasoning"
                / "attempt-001"
                / "rejected.json"
            ).exists()
        )

    def test_volume_profile_claim_id_is_projected_from_unique_chart_owner(
        self,
    ) -> None:
        candidate = self.harness.reasoning(self.evidence)
        candidate["methodology"]["volume_profile_liquidity"][
            "claim_id"
        ] = "claim_liq"
        raw_gate = evaluate_reasoning(
            copy.deepcopy(candidate),
            evidence=self.evidence,
            reasoning_authority_sha256=self.reasoning_authority_sha256(),
            evidence_root=self.harness.root,
            methodology_root=self.harness.root,
        )
        self.assertFalse(raw_gate.passed)
        self.assertIn(
            (
                "methodology.server_projection_drift",
                "methodology.volume_profile_liquidity.claim_id",
            ),
            {(item.code, item.path) for item in raw_gate.defects},
        )

        self.harness.controller.accept_reasoning(
            self.harness.run_root,
            candidate,
        )

        certified = self.harness.controller.store.load_stage_payload(
            self.harness.run_root,
            "reasoning",
            "reasoning",
        )
        self.assertEqual(
            certified["methodology"]["volume_profile_liquidity"]["claim_id"],
            "claim_chart",
        )
        submitted = json.loads(
            (
                self.harness.run_root
                / "reasoning"
                / "attempt-001"
                / "submitted.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            submitted["methodology"]["volume_profile_liquidity"]["claim_id"],
            "claim_liq",
        )

    def test_relative_trigger_operator_is_projected_from_current_reference_state(
        self,
    ) -> None:
        candidate = self.harness.reasoning(self.evidence)
        claims = {item["id"]: item for item in candidate["claims"]}
        claims["claim_maker"].update(
            {
                "direction": "observe",
                "conclusion": "当前没有方向候选，保持观察并等待新的方向条件。",
                "invalidation": "出现闭合方向条件后重新评估。",
            }
        )
        claims["claim_invalidation_maker"]["structural_noise_buffer"].update(
            {
                "status": "insufficient",
                "anchor_kind": None,
                "anchor_source_field": None,
                "anchor_price": None,
                "noise_outer_boundary": None,
                "price_distance": None,
                "insufficiency_reason_code": (
                    "not_applicable_non_directional_thesis"
                ),
            }
        )
        trigger = claims["claim_counter_maker"]["trigger_logic"]
        claims["claim_counter_maker"]["current_basis"] = {
            "mode": "all",
            "clauses": [
                {
                    "owner_type": "observation",
                    "owner_id": "obs_tv",
                    "field": "timeframes.1h.structure",
                    "operator": "equals",
                    "value": "bearish",
                },
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
            ],
        }
        trigger["clauses"][0].update(
            {
                "field": "timeframes.15m.structure",
                "operator": "becomes",
                "value": "bearish",
            }
        )
        reference = next(
            item for item in trigger["clauses"] if item["field"] == "final_direction"
        )
        relative = next(
            item
            for item in trigger["clauses"]
            if item["field"] == "cross_check_result"
        )

        # Coinglass is currently bearish.  A bearish target is persistence at
        # the time another clause changes, not a second impossible transition.
        reference.update({"operator": "becomes", "value": "bearish"})
        relative["operator"] = "becomes"
        submitted_trigger = copy.deepcopy(trigger)
        projected = reasoning_submission.assemble_reasoning_submission(
            candidate,
            evidence=self.evidence,
            reasoning_authority_sha256=self.reasoning_authority_sha256(),
            contract=load_reasoning_submission_contract(root=self.harness.root),
            full_policy=load_scoring_policy(root=self.harness.root),
        )
        projected_claims = {item["id"]: item for item in projected["claims"]}
        projected_trigger = projected_claims["claim_counter_maker"]["trigger_logic"]
        projected_reference = next(
            item
            for item in projected_trigger["clauses"]
            if item["field"] == "final_direction"
        )
        projected_relative = next(
            item
            for item in projected_trigger["clauses"]
            if item["field"] == "cross_check_result"
        )

        self.assertEqual(projected_reference["operator"], "equals_at_trigger")
        self.assertEqual(projected_relative["operator"], "equals_at_trigger")
        self.assertEqual(projected_reference["value"], "bearish")
        self.assertEqual(projected_relative["value"], "confirm")
        self.assertEqual(
            _diff_paths(submitted_trigger, projected_trigger),
            [
                "clauses[1].operator",
                "clauses[2].operator",
            ],
        )
        self.assertEqual(
            _claims_without_relative_pair_operators(
                candidate,
                claim_id="claim_counter_maker",
            ),
            _claims_without_relative_pair_operators(
                projected,
                claim_id="claim_counter_maker",
            ),
        )
        gate = evaluate_reasoning(
            projected,
            evidence=self.evidence,
            reasoning_authority_sha256=self.reasoning_authority_sha256(),
            evidence_root=self.harness.root,
            methodology_root=self.harness.root,
        )
        self.assertTrue(gate.passed, gate.defects)

        tampered = copy.deepcopy(projected)
        tampered_claims = {item["id"]: item for item in tampered["claims"]}
        tampered_reference = next(
            item
            for item in tampered_claims["claim_counter_maker"]["trigger_logic"][
                "clauses"
            ]
            if item["field"] == "final_direction"
        )
        tampered_reference["operator"] = "becomes"
        tampered_gate = evaluate_reasoning(
            tampered,
            evidence=self.evidence,
            reasoning_authority_sha256=self.reasoning_authority_sha256(),
            evidence_root=self.harness.root,
            methodology_root=self.harness.root,
        )
        self.assertFalse(tampered_gate.passed)
        self.assertIn(
            "claim.trigger_no_state_change",
            {item.code for item in tampered_gate.defects},
        )
        self.assertIn(
            "claim.exocharts_counter_polarity",
            {item.code for item in tampered_gate.defects},
        )

    def test_relative_trigger_operator_becomes_when_reference_target_changes(
        self,
    ) -> None:
        candidate = self.harness.reasoning(self.evidence)
        claims = {item["id"]: item for item in candidate["claims"]}
        trigger = claims["claim_counter_maker"]["trigger_logic"]
        reference = next(
            item for item in trigger["clauses"] if item["field"] == "final_direction"
        )
        relative = next(
            item
            for item in trigger["clauses"]
            if item["field"] == "cross_check_result"
        )
        reference["operator"] = "equals_at_trigger"
        relative["operator"] = "becomes"
        submitted_trigger = copy.deepcopy(trigger)

        projected = reasoning_submission.assemble_reasoning_submission(
            candidate,
            evidence=self.evidence,
            reasoning_authority_sha256=self.reasoning_authority_sha256(),
            contract=load_reasoning_submission_contract(root=self.harness.root),
            full_policy=load_scoring_policy(root=self.harness.root),
        )
        projected_claims = {item["id"]: item for item in projected["claims"]}
        projected_trigger = projected_claims["claim_counter_maker"]["trigger_logic"]
        projected_reference = next(
            item
            for item in projected_trigger["clauses"]
            if item["field"] == "final_direction"
        )
        projected_relative = next(
            item
            for item in projected_trigger["clauses"]
            if item["field"] == "cross_check_result"
        )

        self.assertEqual(projected_reference["operator"], "becomes")
        self.assertEqual(projected_relative["operator"], "equals_at_trigger")
        self.assertEqual(projected_reference["value"], "bullish")
        self.assertEqual(projected_relative["value"], "confirm")
        self.assertEqual(
            _diff_paths(submitted_trigger, projected_trigger),
            [
                "clauses[1].operator",
                "clauses[2].operator",
            ],
        )
        self.assertEqual(
            _claims_without_relative_pair_operators(
                candidate,
                claim_id="claim_counter_maker",
            ),
            _claims_without_relative_pair_operators(
                projected,
                claim_id="claim_counter_maker",
            ),
        )
        clean_gate = evaluate_reasoning(
            projected,
            evidence=self.evidence,
            reasoning_authority_sha256=self.reasoning_authority_sha256(),
            evidence_root=self.harness.root,
            methodology_root=self.harness.root,
        )
        self.assertTrue(clean_gate.passed, clean_gate.defects)

        tampered = copy.deepcopy(projected)
        tampered_claims = {item["id"]: item for item in tampered["claims"]}
        tampered_reference = next(
            item
            for item in tampered_claims["claim_counter_maker"]["trigger_logic"][
                "clauses"
            ]
            if item["field"] == "final_direction"
        )
        tampered_reference["operator"] = "equals_at_trigger"
        tampered_gate = evaluate_reasoning(
            tampered,
            evidence=self.evidence,
            reasoning_authority_sha256=self.reasoning_authority_sha256(),
            evidence_root=self.harness.root,
            methodology_root=self.harness.root,
        )
        self.assertFalse(tampered_gate.passed)
        self.assertIn(
            "claim.exocharts_counter_polarity",
            {item.code for item in tampered_gate.defects},
        )

    def test_future_trigger_rejects_a_group_already_satisfied_by_current_state(
        self,
    ) -> None:
        candidate = self.harness.reasoning(self.evidence)
        claims = {item["id"]: item for item in candidate["claims"]}
        claims["claim_maker"].update(
            {
                "direction": "observe",
                "conclusion": "当前没有方向候选，保持观察并等待新的方向条件。",
                "invalidation": "出现闭合方向条件后重新评估。",
            }
        )
        counter = claims["claim_counter_maker"]
        counter["current_basis"] = {
            "mode": "all",
            "clauses": [
                {
                    "owner_type": "observation",
                    "owner_id": "obs_tv",
                    "field": "timeframes.1h.structure",
                    "operator": "equals",
                    "value": "bearish",
                },
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
            ],
        }
        counter["trigger_logic"] = {
            "mode": "all",
            "effect": "counter",
            "clauses": [
                {
                    "owner_type": "observation",
                    "owner_id": "obs_tv",
                    "field": "timeframes.1h.structure",
                    "operator": "equals_at_trigger",
                    "value": "bearish",
                },
                {
                    "owner_type": "observation",
                    "owner_id": "obs_cg",
                    "field": "final_direction",
                    "operator": "equals_at_trigger",
                    "value": "bearish",
                },
                {
                    "owner_type": "observation",
                    "owner_id": "obs_exo",
                    "field": "cross_check_result",
                    "operator": "equals_at_trigger",
                    "value": "confirm",
                },
            ],
        }

        projected = reasoning_submission.assemble_reasoning_submission(
            candidate,
            evidence=self.evidence,
            reasoning_authority_sha256=self.reasoning_authority_sha256(),
            contract=load_reasoning_submission_contract(root=self.harness.root),
            full_policy=load_scoring_policy(root=self.harness.root),
        )
        gate = evaluate_reasoning(
            projected,
            evidence=self.evidence,
            reasoning_authority_sha256=self.reasoning_authority_sha256(),
            evidence_root=self.harness.root,
            methodology_root=self.harness.root,
        )
        self.assertIn(
            "claim.trigger_already_satisfied",
            {item.code for item in gate.defects},
        )

    def test_relative_trigger_projection_does_not_repair_unbound_geometry(
        self,
    ) -> None:
        def missing_reference(trigger: dict) -> None:
            trigger["clauses"] = [
                item
                for item in trigger["clauses"]
                if item["field"] != "final_direction"
            ]

        def multiple_references(trigger: dict) -> None:
            reference = next(
                item
                for item in trigger["clauses"]
                if item["field"] == "final_direction"
            )
            trigger["clauses"].append(copy.deepcopy(reference))

        def any_mode(trigger: dict) -> None:
            trigger["mode"] = "any"

        for label, mutation in (
            ("missing_reference", missing_reference),
            ("multiple_references", multiple_references),
            ("any_mode", any_mode),
        ):
            with self.subTest(label=label):
                candidate = self.harness.reasoning(self.evidence)
                claims = {item["id"]: item for item in candidate["claims"]}
                trigger = claims["claim_counter_maker"]["trigger_logic"]
                mutation(trigger)
                submitted_trigger = copy.deepcopy(trigger)

                projected = reasoning_submission.assemble_reasoning_submission(
                    candidate,
                    evidence=self.evidence,
                    reasoning_authority_sha256=self.reasoning_authority_sha256(),
                    contract=load_reasoning_submission_contract(
                        root=self.harness.root
                    ),
                    full_policy=load_scoring_policy(root=self.harness.root),
                )
                projected_claims = {
                    item["id"]: item for item in projected["claims"]
                }
                projected_trigger = projected_claims[
                    "claim_counter_maker"
                ]["trigger_logic"]
                self.assertEqual(projected_trigger, submitted_trigger)

                gate = evaluate_reasoning(
                    projected,
                    evidence=self.evidence,
                    reasoning_authority_sha256=(
                        self.reasoning_authority_sha256()
                    ),
                    evidence_root=self.harness.root,
                    methodology_root=self.harness.root,
                )
                self.assertFalse(gate.passed)
                self.assertIn(
                    "claim.exocharts_counter_polarity",
                    {item.code for item in gate.defects},
                )

    def test_every_declared_methodology_server_binding_is_projected(self) -> None:
        contract = load_reasoning_submission_contract(root=self.harness.root)
        full_policy = load_scoring_policy(root=self.harness.root)
        authority_sha256 = self.reasoning_authority_sha256()
        candidate = self.harness.reasoning(self.evidence)
        expected = reasoning_submission.assemble_reasoning_submission(
            candidate,
            evidence=self.evidence,
            reasoning_authority_sha256=authority_sha256,
            contract=contract,
            full_policy=full_policy,
        )
        poisoned = copy.deepcopy(candidate)

        def leaf_values(payload: dict, path: str) -> list:
            block_name, field = path.removeprefix("methodology.").split(".", 1)
            if block_name.endswith("[*]"):
                items = payload["methodology"][block_name.removesuffix("[*]")]
                return [item[field] for item in items]
            return [payload["methodology"][block_name][field]]

        def poison_leaf(payload: dict, path: str) -> None:
            block_name, field = path.removeprefix("methodology.").split(".", 1)
            blocks = (
                payload["methodology"][block_name.removesuffix("[*]")]
                if block_name.endswith("[*]")
                else [payload["methodology"][block_name]]
            )
            for block in blocks:
                value = block[field]
                block[field] = (
                    not value
                    if isinstance(value, bool)
                    else ["producer-poison"]
                    if isinstance(value, list)
                    else "producer-poison"
                )

        bindings = contract["server_projection"]["methodology_leaf_ownership"][
            "server_owned_bindings"
        ]
        for path in bindings:
            poison_leaf(poisoned, path)
        submitted = copy.deepcopy(poisoned)
        projected = reasoning_submission.assemble_reasoning_submission(
            poisoned,
            evidence=self.evidence,
            reasoning_authority_sha256=authority_sha256,
            contract=contract,
            full_policy=full_policy,
        )

        self.assertEqual(poisoned, submitted)
        for path in bindings:
            with self.subTest(path=path):
                self.assertEqual(
                    leaf_values(projected, path),
                    leaf_values(expected, path),
                )

    def test_assembler_preserves_every_model_owned_leaf_and_event_key(
        self,
    ) -> None:
        candidate = self.harness.reasoning(self.evidence)
        synthesis = candidate["methodology"]["independent_synthesis"]
        synthesis["market_stage_claim_id"] = "producer-market-stage"
        synthesis["primary_evidence_claim_ids"] = [
            "producer-primary-a",
            "producer-primary-b",
        ]
        synthesis["strongest_counter_claim_id"] = "producer-counter"
        synthesis["action_claim_id"] = "producer-action"
        events = candidate["methodology"]["fundamental_event_assessments"]
        for index, event in enumerate(events):
            event["selected_event_sha256"] = str(index + 7) * 64
            event["impact_channel"] = f"producer-impact-{index}"
            event["expected_effect"] = f"producer-effect-{index}"
            event["counter_claim_ids"] = [f"producer-counter-{index}"]
        candidate["methodology"]["multi_timeframe_transition"][
            "transition_summary"
        ] = "producer transition summary must remain byte-for-byte"

        before = copy.deepcopy(candidate)
        projected = reasoning_submission.assemble_reasoning_submission(
            candidate,
            evidence=self.evidence,
            reasoning_authority_sha256=self.reasoning_authority_sha256(),
            contract=load_reasoning_submission_contract(root=self.harness.root),
            full_policy=load_scoring_policy(root=self.harness.root),
        )

        self.assertEqual(candidate, before)
        projected_synthesis = projected["methodology"]["independent_synthesis"]
        for field in (
            "market_stage_claim_id",
            "primary_evidence_claim_ids",
            "strongest_counter_claim_id",
            "action_claim_id",
        ):
            self.assertEqual(projected_synthesis[field], synthesis[field])
        for original, actual in zip(
            events,
            projected["methodology"]["fundamental_event_assessments"],
            strict=True,
        ):
            for field in (
                "selected_event_sha256",
                "impact_channel",
                "expected_effect",
                "counter_claim_ids",
            ):
                self.assertEqual(actual[field], original[field])
        self.assertEqual(
            projected["methodology"]["multi_timeframe_transition"][
                "transition_summary"
            ],
            candidate["methodology"]["multi_timeframe_transition"][
                "transition_summary"
            ],
        )

    def test_duplicate_shared_chart_owner_projects_none_not_first_match(
        self,
    ) -> None:
        candidate = self.harness.reasoning(self.evidence)
        chart = next(
            item
            for item in candidate["claims"]
            if item["claim_type"] == "chart_interpretation"
            and item["account"] == "shared"
        )
        duplicate = copy.deepcopy(chart)
        duplicate["id"] = "claim_chart_duplicate"
        candidate["claims"].append(duplicate)

        projected = reasoning_submission.assemble_reasoning_submission(
            candidate,
            evidence=self.evidence,
            reasoning_authority_sha256=self.reasoning_authority_sha256(),
            contract=load_reasoning_submission_contract(root=self.harness.root),
            full_policy=load_scoring_policy(root=self.harness.root),
        )

        self.assertIsNone(
            projected["methodology"]["fundamental_price_realization"][
                "price_claim_id"
            ]
        )
        self.assertIsNone(
            projected["methodology"]["multi_timeframe_transition"]["claim_id"]
        )
        self.assertIsNone(
            projected["methodology"]["volume_profile_liquidity"]["claim_id"]
        )

    def test_gate_independently_rejects_tampered_server_projection_once(
        self,
    ) -> None:
        candidate = self.harness.reasoning(self.evidence)
        projected = reasoning_submission.assemble_reasoning_submission(
            candidate,
            evidence=self.evidence,
            reasoning_authority_sha256=self.reasoning_authority_sha256(),
            contract=load_reasoning_submission_contract(root=self.harness.root),
            full_policy=load_scoring_policy(root=self.harness.root),
        )
        clean_gate = evaluate_reasoning(
            copy.deepcopy(projected),
            evidence=self.evidence,
            reasoning_authority_sha256=self.reasoning_authority_sha256(),
            evidence_root=self.harness.root,
            methodology_root=self.harness.root,
        )
        self.assertTrue(clean_gate.passed)

        path = "methodology.volume_profile_liquidity.claim_id"
        projected["methodology"]["volume_profile_liquidity"][
            "claim_id"
        ] = "claim_liq"
        tampered_gate = evaluate_reasoning(
            projected,
            evidence=self.evidence,
            reasoning_authority_sha256=self.reasoning_authority_sha256(),
            evidence_root=self.harness.root,
            methodology_root=self.harness.root,
        )

        self.assertFalse(tampered_gate.passed)
        self.assertEqual(
            [(item.code, item.path) for item in tampered_gate.defects],
            [("methodology.server_projection_drift", path)],
        )
        self.assertNotIn(
            ("methodology.parity_failed", path),
            {(item.code, item.path) for item in tampered_gate.defects},
        )

    def test_gate_independently_rejects_observation_projection_drift(self) -> None:
        candidate = self.harness.reasoning(self.evidence)
        projected = reasoning_submission.assemble_reasoning_submission(
            candidate,
            evidence=self.evidence,
            reasoning_authority_sha256=self.reasoning_authority_sha256(),
            contract=load_reasoning_submission_contract(root=self.harness.root),
            full_policy=load_scoring_policy(root=self.harness.root),
        )
        tradingview = next(
            item
            for item in projected["observations"]
            if item["source"] == "TradingView"
        )
        tradingview["evidence_refs"] = list(reversed(tradingview["evidence_refs"]))

        gate = evaluate_reasoning(
            projected,
            evidence=self.evidence,
            reasoning_authority_sha256=self.reasoning_authority_sha256(),
            evidence_root=self.harness.root,
            methodology_root=self.harness.root,
        )

        self.assertFalse(gate.passed)
        self.assertIn(
            (
                "observation.server_projection_drift",
                "observations.obs_tv.evidence_refs",
            ),
            {(item.code, item.path) for item in gate.defects},
        )

    def test_assembler_does_not_repair_model_owned_visual_proof(self) -> None:
        contract = load_reasoning_submission_contract(root=self.harness.root)
        policy = load_scoring_policy(root=self.harness.root)
        for case, expected_code in (
            ("crop", "visual.crop_invalid"),
            (
                "structural_noise_visual_ref",
                "claim.structural_noise_buffer_visual_binding",
            ),
        ):
            with self.subTest(case=case):
                candidate = self.harness.reasoning(self.evidence)
                if case == "crop":
                    tradingview = next(
                        item
                        for item in candidate["observations"]
                        if item["source"] == "TradingView"
                    )
                    tradingview["visual_citations"][0]["crop"] = [0, 0, 1]
                else:
                    invalidation = next(
                        item
                        for item in candidate["claims"]
                        if item["claim_type"] == "invalidation_path"
                        and item["account"] == "maker"
                    )
                    invalidation["structural_noise_buffer"][
                        "visual_evidence_ref"
                    ] = "evidence/not-sealed.png"

                projected = reasoning_submission.assemble_reasoning_submission(
                    candidate,
                    evidence=self.evidence,
                    reasoning_authority_sha256=self.reasoning_authority_sha256(),
                    contract=contract,
                    full_policy=policy,
                )
                gate = evaluate_reasoning(
                    projected,
                    evidence=self.evidence,
                    reasoning_authority_sha256=self.reasoning_authority_sha256(),
                    evidence_root=self.harness.root,
                    methodology_root=self.harness.root,
                )

                self.assertFalse(gate.passed)
                self.assertIn(expected_code, {item.code for item in gate.defects})
                if case == "crop":
                    projected_tradingview = next(
                        item
                        for item in projected["observations"]
                        if item["source"] == "TradingView"
                    )
                    self.assertEqual(
                        projected_tradingview["visual_citations"][0]["crop"],
                        [0, 0, 1],
                    )
                else:
                    projected_invalidation = next(
                        item
                        for item in projected["claims"]
                        if item["claim_type"] == "invalidation_path"
                        and item["account"] == "maker"
                    )
                    self.assertEqual(
                        projected_invalidation["structural_noise_buffer"][
                            "visual_evidence_ref"
                        ],
                        "evidence/not-sealed.png",
                    )

    def test_observation_extra_or_missing_model_fields_remain_fail_closed(
        self,
    ) -> None:
        candidate = self.harness.reasoning(self.evidence)
        exocharts = next(
            item
            for item in candidate["observations"]
            if item["source"] == "Exocharts"
        )
        exocharts["pivot_id"] = "producer-extra"
        tradingview = next(
            item
            for item in candidate["observations"]
            if item["source"] == "TradingView"
        )
        tradingview.pop("timeframe")

        with self.assertRaises(WorkflowFailure):
            self.harness.controller.accept_reasoning(
                self.harness.run_root,
                candidate,
            )
        attempt_root = self.harness.run_root / "reasoning" / "attempt-001"
        failure = json.loads(
            (attempt_root / "failure.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            {
                item["path"]
                for item in failure["defects"]
                if item["code"] == "observation.schema_fields"
            },
            {"observations[4]", "observations[5]"},
        )
        rejected = json.loads(
            (attempt_root / "rejected.json").read_text(encoding="utf-8")
        )
        rejected_exocharts = next(
            item
            for item in rejected["observations"]
            if item["source"] == "Exocharts"
        )
        rejected_tradingview = next(
            item
            for item in rejected["observations"]
            if item["source"] == "TradingView"
        )
        self.assertEqual(rejected_exocharts["pivot_id"], "producer-extra")
        self.assertNotIn("timeframe", rejected_tradingview)

    def test_unknown_orderflow_direction_is_projected_to_none_and_rejected(
        self,
    ) -> None:
        candidate = self.harness.reasoning(self.evidence)
        coinglass = next(
            item
            for item in candidate["observations"]
            if item["source"] == "Coinglass"
        )
        coinglass["metrics"]["final_direction"] = "unknown"
        coinglass["visual_review"]["metrics_sha256"] = canonical_sha256(
            coinglass["metrics"]
        )
        next(
            item
            for item in candidate["claims"]
            if item["claim_type"] == "orderflow_interpretation"
        )["direction"] = "producer-value-must-not-survive"

        with self.assertRaises(WorkflowFailure):
            self.harness.controller.accept_reasoning(
                self.harness.run_root,
                candidate,
            )

        attempt_root = self.harness.run_root / "reasoning" / "attempt-001"
        failure = json.loads(
            (attempt_root / "failure.json").read_text(encoding="utf-8")
        )
        self.assertIn(
            "coinglass.final_direction",
            {item["code"] for item in failure["defects"]},
        )
        rejected = json.loads(
            (attempt_root / "rejected.json").read_text(encoding="utf-8")
        )
        orderflow = next(
            item
            for item in rejected["claims"]
            if item["claim_type"] == "orderflow_interpretation"
        )
        self.assertIsNone(orderflow["direction"])
        submitted = json.loads(
            (attempt_root / "submitted.json").read_text(encoding="utf-8")
        )
        submitted_orderflow = next(
            item
            for item in submitted["claims"]
            if item["claim_type"] == "orderflow_interpretation"
        )
        self.assertEqual(
            submitted_orderflow["direction"],
            "producer-value-must-not-survive",
        )

    def test_legacy_methodology_binding_is_preserved_and_rejected(self) -> None:
        candidate = self.harness.reasoning(self.evidence)
        candidate["methodology_sha256"] = "f" * 64
        with self.assertRaises(WorkflowFailure):
            self.harness.controller.accept_reasoning(
                self.harness.run_root,
                candidate,
            )
        attempt_root = self.harness.run_root / "reasoning" / "attempt-001"
        failure = json.loads(
            (attempt_root / "failure.json").read_text(encoding="utf-8")
        )
        self.assertIn(
            "binding.legacy_methodology_field",
            {item["code"] for item in failure["defects"]},
        )
        submitted = json.loads(
            (attempt_root / "submitted.json").read_text(encoding="utf-8")
        )
        rejected = json.loads(
            (attempt_root / "rejected.json").read_text(encoding="utf-8")
        )
        self.assertEqual(submitted["methodology_sha256"], "f" * 64)
        self.assertEqual(rejected["methodology_sha256"], "f" * 64)

    def test_internal_projection_error_is_sealed_not_orphaned(self) -> None:
        candidate = self.harness.reasoning(self.evidence)
        with patch(
            "runtime_vnext.controller.assemble_reasoning_submission",
            side_effect=TypeError("synthetic projection failure"),
        ):
            with self.assertRaises(WorkflowFailure) as caught:
                self.harness.controller.accept_reasoning(
                    self.harness.run_root,
                    candidate,
                )
        self.assertEqual(
            caught.exception.failure_class,
            FailureClass.MANUAL_REVIEW,
        )
        attempt_root = self.harness.run_root / "reasoning" / "attempt-001"
        failure = json.loads(
            (attempt_root / "failure.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            [item["code"] for item in failure["defects"]],
            ["reasoning.internal_validation_error"],
        )
        self.assertTrue((attempt_root / "submitted.json").is_file())
        checkpoint = self.harness.controller.store.load_checkpoint(
            self.harness.run_root
        )
        self.assertEqual(checkpoint["status"], "needs_review")
        self.assertFalse((attempt_root / "manifest.json").exists())

    def test_bad_candidate_creates_one_sealed_attempt_with_complete_shape_defects(
        self,
    ) -> None:
        candidate = self.harness.reasoning(self.evidence)
        candidate["methodology"] = _malformed_live_methodology()
        with self.assertRaises(WorkflowFailure):
            self.harness.controller.accept_reasoning(
                self.harness.run_root,
                candidate,
            )

        attempts = sorted((self.harness.run_root / "reasoning").glob("attempt-*"))
        self.assertEqual(len(attempts), 1)
        failure = json.loads(
            (attempts[0] / "failure.json").read_text(encoding="utf-8")
        )
        defects = failure["defects"]
        self.assertEqual(
            {
                item["path"]
                for item in defects
                if item["code"] == "reasoning_shape.field_missing"
            },
            {
                "methodology.independent_synthesis.action_claim_id",
                "methodology.independent_synthesis.strongest_counter_claim_id",
                "methodology.multi_timeframe_transition.transition_summary",
            },
        )
        self.assertEqual(
            {
                item["path"]
                for item in defects
                if item["code"] == "reasoning_shape.field_unknown"
            },
            {
                "methodology.fundamental_price_realization.claim_id",
                "methodology.same_pivot_orderflow.combination_id",
                "methodology.same_pivot_orderflow.final_direction",
                "methodology.multi_timeframe_transition.timeframes",
                "methodology.volume_profile_liquidity.observation_id",
                "methodology.volume_profile_liquidity.profile_status",
                "methodology.cannot_do_derivation.support_claim_ids",
            },
        )
        self.assertEqual(
            sum(item["code"] == "reasoning_shape.string_too_short" for item in defects),
            0,
        )
        shape_paths = {
            item["path"]
            for item in defects
            if str(item["code"]).startswith("reasoning_shape.")
        }
        parity_paths = {
            item["path"]
            for item in defects
            if item["code"] == "methodology.parity_failed"
        }
        self.assertFalse(parity_paths)
        self.assertTrue(shape_paths.isdisjoint(parity_paths))
        rejected = json.loads(
            (attempts[0] / "rejected.json").read_text(encoding="utf-8")
        )
        for field in (
            "market_stage_claim_id",
            "primary_evidence_claim_ids",
        ):
            self.assertEqual(
                rejected["methodology"]["independent_synthesis"][field],
                candidate["methodology"]["independent_synthesis"][field],
            )
        for original, actual in zip(
            candidate["methodology"]["fundamental_event_assessments"],
            rejected["methodology"]["fundamental_event_assessments"],
            strict=True,
        ):
            for field in (
                "selected_event_sha256",
                "impact_channel",
                "expected_effect",
                "counter_claim_ids",
            ):
                self.assertEqual(actual[field], original[field])
        self.assertNotEqual(
            rejected["methodology"]["account_separation"],
            candidate["methodology"]["account_separation"],
        )
        self.assertNotEqual(
            rejected["methodology"]["scenario_tree"],
            candidate["methodology"]["scenario_tree"],
        )

    def test_exact_shape_business_defects_are_aggregated_once(self) -> None:
        candidate = self.candidate_with_business_defects()
        with self.assertRaises(WorkflowFailure) as caught:
            self.harness.controller.accept_reasoning(
                self.harness.run_root,
                candidate,
            )

        self.assertEqual(
            caught.exception.failure_class,
            FailureClass.REASONING_CONSISTENCY,
        )
        attempts = sorted((self.harness.run_root / "reasoning").glob("attempt-*"))
        self.assertEqual(len(attempts), 1)
        failure = json.loads(
            (attempts[0] / "failure.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            self.methodology_defect_triples(failure["defects"]),
            list(EXPECTED_BUSINESS_DEFECTS),
        )
        self.assertEqual(
            self.harness.controller.store.attempt_count(
                self.harness.run_root,
                "reasoning",
            ),
            1,
        )
        self.assertFalse(
            (self.harness.run_root / "reasoning" / "attempt-002").exists()
        )
        rejected = json.loads(
            (attempts[0] / "rejected.json").read_text(encoding="utf-8")
        )
        self.assertEqual(rejected["methodology"], candidate["methodology"])

    def test_server_owned_mirror_poison_is_projected_before_gate(self) -> None:
        candidate = self.harness.reasoning(self.evidence)
        methodology = candidate["methodology"]
        expected_footprint = methodology["footprint_cross_check"][
            "relationship"
        ]
        expected_etf = methodology["etf_flow_relation"]["price_relation"]
        methodology["same_pivot_orderflow"] = []
        methodology["footprint_cross_check"]["relationship"] = "contradict"
        methodology["etf_flow_relation"]["price_relation"] = "weaken"
        shape_issues = validate_methodology_submission_shape(
            methodology,
            contract=load_reasoning_submission_contract(root=self.harness.root),
            full_policy=load_scoring_policy(root=self.harness.root),
        )
        self.assertEqual(
            [(item.code, item.path, item.message) for item in shape_issues],
            [
                (
                    "reasoning_shape.object_required",
                    "methodology.same_pivot_orderflow",
                    "expected an object",
                )
            ],
        )

        with self.assertRaises(WorkflowFailure):
            self.harness.controller.accept_reasoning(
                self.harness.run_root,
                candidate,
            )
        attempt_root = self.harness.run_root / "reasoning" / "attempt-001"
        failure = json.loads(
            (attempt_root / "failure.json").read_text(encoding="utf-8")
        )
        expected = [
            (
                "reasoning_shape.object_required",
                "methodology.same_pivot_orderflow",
                "expected an object",
            ),
        ]
        actual = self.methodology_defect_triples(failure["defects"])
        self.assertEqual(actual, expected)
        rejected = json.loads(
            (attempt_root / "rejected.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            rejected["methodology"]["footprint_cross_check"]["relationship"],
            expected_footprint,
        )
        self.assertEqual(
            rejected["methodology"]["etf_flow_relation"]["price_relation"],
            expected_etf,
        )
        self.assertNotIn("methodology", {item[1] for item in actual})

    def test_runtime_inventory_drift_fails_preflight_without_attempt(self) -> None:
        full_policy = load_scoring_policy(root=self.harness.root)
        runtime_inventory = golden_methodology.get_methodology_runtime_inventory(
            policy=full_policy["gold_methodology"],
            profile="vnext_submission",
        )
        drifted_inventory = copy.deepcopy(runtime_inventory)
        drifted_inventory["objects"]["independent_synthesis"][
            "field_order"
        ].append("runtime_only_drift_probe")
        before = _tree_snapshot(self.harness.run_root)

        with patch.object(
            reasoning_submission,
            "get_methodology_runtime_inventory",
            return_value=drifted_inventory,
        ):
            with self.assertRaises(WorkflowFailure) as caught:
                self.harness.controller.reasoning_contract_preflight(
                    self.harness.run_root
                )

        self.assertEqual(caught.exception.failure_class, FailureClass.MANUAL_REVIEW)
        self.assertIn(
            "reasoning_contract.methodology_inventory",
            {item["code"] for item in caught.exception.defects},
        )
        self.assertEqual(before, _tree_snapshot(self.harness.run_root))
        self.assertEqual(
            self.harness.controller.store.attempt_count(
                self.harness.run_root,
                "reasoning",
            ),
            0,
        )
        self.assertFalse((self.harness.run_root / "reasoning").exists())

    def test_relative_operator_split_brain_fails_preflight_without_attempt(
        self,
    ) -> None:
        drifted_policy = load_scoring_policy(root=self.harness.root)
        drifted_policy["gold_methodology"]["account_trigger_logic"][
            "relative_direction_observation_fields"
        ]["Exocharts"]["cross_check_result"]["reference_operator_policy"][
            "target_equals_current"
        ] = "becomes"
        before = _tree_snapshot(self.harness.run_root)

        with patch(
            "runtime_vnext.controller.load_scoring_policy",
            return_value=drifted_policy,
        ):
            with self.assertRaises(WorkflowFailure) as caught:
                self.harness.controller.reasoning_contract_preflight(
                    self.harness.run_root
                )

        self.assertEqual(caught.exception.failure_class, FailureClass.MANUAL_REVIEW)
        self.assertIn(
            (
                "reasoning_contract.relative_trigger_policy_drift",
                "server_projection.relative_trigger_operator_projection",
            ),
            {
                (item["code"], item["path"])
                for item in caught.exception.defects
            },
        )
        self.assertEqual(before, _tree_snapshot(self.harness.run_root))
        self.assertEqual(
            self.harness.controller.store.attempt_count(
                self.harness.run_root,
                "reasoning",
            ),
            0,
        )
        self.assertFalse((self.harness.run_root / "reasoning").exists())

    def test_methodology_ownership_drift_fails_preflight_without_attempt(
        self,
    ) -> None:
        contract = load_reasoning_submission_contract(root=self.harness.root)
        before = _tree_snapshot(self.harness.run_root)
        for name, drifted in _methodology_ownership_drift_cases(contract):
            with self.subTest(name=name), patch(
                "runtime_vnext.controller.load_reasoning_submission_contract",
                return_value=drifted,
            ):
                with self.assertRaises(WorkflowFailure) as caught:
                    self.harness.controller.reasoning_contract_preflight(
                        self.harness.run_root
                    )
                self.assertEqual(
                    caught.exception.failure_class,
                    FailureClass.MANUAL_REVIEW,
                )
                self.assertIn(
                    (
                        "reasoning_contract.server_projection",
                        "server_projection",
                    ),
                    {
                        (item["code"], item["path"])
                        for item in caught.exception.defects
                    },
                )
                self.assertEqual(before, _tree_snapshot(self.harness.run_root))
                self.assertEqual(
                    self.harness.controller.store.attempt_count(
                        self.harness.run_root,
                        "reasoning",
                    ),
                    0,
                )
                self.assertFalse(
                    (self.harness.run_root / "reasoning").exists()
                )

    def test_sealed_rejected_candidate_replay_is_read_only(self) -> None:
        candidate = self.candidate_with_business_defects()
        with self.assertRaises(WorkflowFailure):
            self.harness.controller.accept_reasoning(
                self.harness.run_root,
                candidate,
            )
        attempt_root = self.harness.run_root / "reasoning" / "attempt-001"
        failure = json.loads(
            (attempt_root / "failure.json").read_text(encoding="utf-8")
        )
        rejected = json.loads(
            (attempt_root / "rejected.json").read_text(encoding="utf-8")
        )
        methodology_manifest = json.loads(
            (self.harness.run_root / "methodology_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        before_tree = _tree_snapshot(self.harness.run_root)
        before_checkpoint = copy.deepcopy(
            self.harness.controller.store.load_checkpoint(self.harness.run_root)
        )
        before_attempt_count = self.harness.controller.store.attempt_count(
            self.harness.run_root,
            "reasoning",
        )

        replay_results = [
            evaluate_reasoning(
                copy.deepcopy(rejected),
                evidence=self.evidence,
                reasoning_authority_sha256=methodology_manifest["phases"][
                    "reasoning"
                ]["phase_sha256"],
                evidence_root=self.harness.root,
                methodology_root=self.harness.root,
            )
            for _ in range(2)
        ]

        sealed_defects = self.methodology_defect_triples(failure["defects"])
        self.assertEqual(sealed_defects, list(EXPECTED_BUSINESS_DEFECTS))
        for replay in replay_results:
            self.assertFalse(replay.passed)
            self.assertEqual(
                self.gate_methodology_defect_triples(replay.defects),
                sealed_defects,
            )
        self.assertEqual(before_tree, _tree_snapshot(self.harness.run_root))
        self.assertEqual(
            before_checkpoint,
            self.harness.controller.store.load_checkpoint(self.harness.run_root),
        )
        self.assertEqual(
            before_attempt_count,
            self.harness.controller.store.attempt_count(
                self.harness.run_root,
                "reasoning",
            ),
        )
        self.assertEqual(before_attempt_count, 1)
        self.assertFalse(
            (self.harness.run_root / "reasoning" / "attempt-002").exists()
        )


if __name__ == "__main__":
    unittest.main()
