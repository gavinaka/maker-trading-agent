from __future__ import annotations

import ast
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.golden_methodology import get_methodology_runtime_inventory
from runtime_vnext import gates, plan_semantics, reasoning_pipeline
import runtime_vnext.domain_ir.registry as domain_registry_module
from runtime_vnext.domain_ir.contract_codegen import (
    contract_is_current,
    write_materialized_contracts,
)
from runtime_vnext.domain_ir.projection import (
    deterministic_contract_sections,
    deterministic_projection_drift,
    projected_report_presentation_contract,
    projected_v6_contract,
    reference_trigger_operator,
    report_presentation_projection_drift,
    scenario_projection_contract_projection,
    timeframe_display_contract_projection,
    trigger_operator_display_projection,
)
from runtime_vnext.domain_ir.registry import (
    CLAIM_ACCOUNT_SCOPES,
    CLAIM_TYPES,
    CONTRACT_SOURCES,
    EVIDENCE_SOURCE_ORDER,
    MAKER_FAILURE_ORDER,
    MAKER_SEMANTIC_STATES,
    METADATA_COMPONENT_NAMES,
    MODEL_OWNED_SEMANTIC_SURFACES,
    PIPELINE_SOURCE_UNIT_BY_NAME,
    PRESENTATION_COMPONENT_NAMES,
    REGISTRY,
    REASONING_OBSERVATION_SOURCE_ORDER,
    SEMANTIC_COMPONENT_NAMES,
)
from runtime_vnext.domain_ir.types import Account, ClaimType, canonical_sha256
from runtime_vnext.methodology import load_scoring_policy
from runtime_vnext.reasoning_submission import (
    load_reasoning_submission_contract,
    validate_contract_runtime_compatibility,
)


ROOT = Path(__file__).resolve().parents[1]


class VNextDomainRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load_reasoning_submission_contract(root=ROOT)
        cls.policy = load_scoring_policy(root=ROOT)
        cls.inventory = get_methodology_runtime_inventory(
            policy=cls.policy["gold_methodology"],
            profile="vnext_submission",
        )
        cls.sections = deterministic_contract_sections(
            methodology_leaf_ownership=cls.inventory["leaf_ownership"]
        )
        cls.presentation_contract = json.loads(
            (
                ROOT
                / "governance"
                / "vnext_report_presentation_contract.json"
            ).read_text(encoding="utf-8")
        )

    def test_registry_materializes_the_committed_v6_transport_exactly(self) -> None:
        self.assertTrue(contract_is_current(root=ROOT))
        self.assertEqual(
            projected_v6_contract(
                self.contract,
                methodology_leaf_ownership=self.inventory["leaf_ownership"],
            ),
            self.contract,
        )
        self.assertFalse(
            deterministic_projection_drift(
                self.contract,
                methodology_leaf_ownership=self.inventory["leaf_ownership"],
            )
        )
        self.assertEqual(
            validate_contract_runtime_compatibility(
                self.contract,
                full_policy=self.policy,
            ),
            [],
        )
        self.assertFalse(
            report_presentation_projection_drift(self.presentation_contract)
        )
        self.assertEqual(
            projected_report_presentation_contract(self.presentation_contract),
            self.presentation_contract,
        )
        self.assertEqual(
            self.presentation_contract["scenario_projection_contract"],
            scenario_projection_contract_projection(),
        )
        self.assertEqual(
            self.presentation_contract["timeframe_display_contract"],
            timeframe_display_contract_projection(),
        )
        self.assertEqual(
            self.presentation_contract["trigger_operator_display"],
            trigger_operator_display_projection(),
        )

    def test_registry_closes_source_claim_account_and_scenario_identity(self) -> None:
        self.assertEqual(len(EVIDENCE_SOURCE_ORDER), 6)
        self.assertEqual(len(CONTRACT_SOURCES), 7)
        self.assertIn("FedWatchPlanC", CONTRACT_SOURCES)
        self.assertEqual(
            tuple(PIPELINE_SOURCE_UNIT_BY_NAME),
            REASONING_OBSERVATION_SOURCE_ORDER,
        )
        self.assertEqual(set(CLAIM_ACCOUNT_SCOPES), set(CLAIM_TYPES))
        self.assertEqual(
            CLAIM_ACCOUNT_SCOPES[ClaimType.MAIN_ACCOUNT_THESIS.value],
            frozenset({Account.MAIN.value}),
        )
        self.assertEqual(
            CLAIM_ACCOUNT_SCOPES[ClaimType.MAKER_THESIS.value],
            frozenset({Account.MAKER.value}),
        )
        self.assertEqual(
            len(self.sections["scenario_ownership"]["items"]),
            6,
        )

    def test_compatibility_facades_are_registry_derived(self) -> None:
        self.assertIs(gates.REQUIRED_SOURCES, EVIDENCE_SOURCE_ORDER)
        self.assertIs(gates.REQUIRED_CLAIM_TYPES, CLAIM_TYPES)
        self.assertIs(plan_semantics.FAILURE_ORDER, MAKER_FAILURE_ORDER)
        self.assertIs(plan_semantics.MAKER_SEMANTIC_STATES, MAKER_SEMANTIC_STATES)
        self.assertEqual(
            reasoning_pipeline.SOURCE_UNIT_BY_NAME,
            PIPELINE_SOURCE_UNIT_BY_NAME,
        )

    def test_reference_operator_uses_exact_json_scalar_type(self) -> None:
        self.assertEqual(reference_trigger_operator(False, False), "equals_at_trigger")
        self.assertEqual(reference_trigger_operator(0, 0), "equals_at_trigger")
        self.assertEqual(reference_trigger_operator(False, 0), "becomes")
        self.assertEqual(reference_trigger_operator(1, True), "becomes")
        self.assertEqual(reference_trigger_operator("x", "x"), "equals_at_trigger")
        self.assertEqual(reference_trigger_operator("x", "y"), "becomes")

    def test_registry_projection_never_claims_model_support_selection(self) -> None:
        topology = self.sections["claim_topology"]
        self.assertEqual(topology["support_selection_owner"], "model")
        self.assertIs(topology["server_support_edge_injection_allowed"], False)
        server_paths = set(self.sections["server_projection"]["server_owned_paths"])
        for path in (
            "claims[*].supports",
            "claims[claim_type=main_account_thesis]",
            "claims[claim_type=maker_thesis]",
            "claims[claim_type=strongest_counterevidence]",
            "claims[claim_type=invalidation_path]",
        ):
            self.assertIn(path, MODEL_OWNED_SEMANTIC_SURFACES)
            self.assertNotIn(path, server_paths)

    def test_generated_sections_repair_only_deterministic_contract_views(self) -> None:
        tampered = copy.deepcopy(self.contract)
        tampered["claim_topology"]["support_selection_owner"] = "server"
        self.assertTrue(
            deterministic_projection_drift(
                tampered,
                methodology_leaf_ownership=self.inventory["leaf_ownership"],
            )
        )
        projected = projected_v6_contract(
            tampered,
            methodology_leaf_ownership=self.inventory["leaf_ownership"],
        )
        self.assertEqual(projected["claim_topology"], self.contract["claim_topology"])
        self.assertEqual(
            projected["claim_fields_by_type"],
            self.contract["claim_fields_by_type"],
        )

    def _assert_codegen_rejects_contract(self, contract: dict) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scoring = root / "scoring"
            scoring.mkdir(parents=True)
            governance = root / "governance"
            governance.mkdir(parents=True)
            (scoring / "reasoning_submission_contract.json").write_text(
                json.dumps(contract, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            (scoring / "scoring_contract.json").write_text(
                (ROOT / "scoring" / "scoring_contract.json").read_text(
                    encoding="utf-8"
                ),
                encoding="utf-8",
            )
            (
                governance / "vnext_report_presentation_contract.json"
            ).write_text(
                json.dumps(
                    self.presentation_contract,
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertFalse(contract_is_current(root=root))

    def _assert_codegen_rejects_presentation(self, presentation: dict) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scoring = root / "scoring"
            scoring.mkdir(parents=True)
            governance = root / "governance"
            governance.mkdir(parents=True)
            (scoring / "reasoning_submission_contract.json").write_text(
                json.dumps(self.contract, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            (scoring / "scoring_contract.json").write_text(
                (ROOT / "scoring" / "scoring_contract.json").read_text(
                    encoding="utf-8"
                ),
                encoding="utf-8",
            )
            (
                governance / "vnext_report_presentation_contract.json"
            ).write_text(
                json.dumps(presentation, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            self.assertFalse(contract_is_current(root=root))
            written = write_materialized_contracts(root=root)
            self.assertEqual(
                tuple(path.relative_to(root).as_posix() for path in written),
                (
                    "scoring/reasoning_submission_contract.json",
                    "scoring/scoring_contract.json",
                    "governance/vnext_report_presentation_contract.json",
                ),
            )
            self.assertTrue(contract_is_current(root=root))
            repaired = json.loads(
                (
                    governance / "vnext_report_presentation_contract.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(repaired, self.presentation_contract)

    def test_codegen_check_rejects_missing_maker_thesis_direction(self) -> None:
        tampered = copy.deepcopy(self.contract)
        tampered["claim_fields_by_type"]["maker_thesis"].remove("direction")
        self._assert_codegen_rejects_contract(tampered)
        projected = projected_v6_contract(
            tampered,
            methodology_leaf_ownership=self.inventory["leaf_ownership"],
        )
        self.assertEqual(
            projected["claim_fields_by_type"]["maker_thesis"],
            self.contract["claim_fields_by_type"]["maker_thesis"],
        )

    def test_codegen_check_rejects_pipeline_reordering(self) -> None:
        tampered = copy.deepcopy(self.contract)
        tampered["pipeline_unit_order"][0:2] = reversed(
            tampered["pipeline_unit_order"][0:2]
        )
        self._assert_codegen_rejects_contract(tampered)
        projected = projected_v6_contract(
            tampered,
            methodology_leaf_ownership=self.inventory["leaf_ownership"],
        )
        self.assertEqual(
            projected["pipeline_unit_order"],
            self.contract["pipeline_unit_order"],
        )

    def test_codegen_check_rejects_report_presentation_projection_drift(
        self,
    ) -> None:
        tamper_cases = (
            (
                "transition_code",
                lambda payload: payload["scenario_projection_contract"][
                    "transition_code_by_type"
                ].__setitem__("base", "changed_transition"),
            ),
            (
                "canonical_field_order",
                lambda payload: payload["scenario_projection_contract"][
                    "canonical_audit_field_order"
                ].reverse(),
            ),
            (
                "base_condition_text",
                lambda payload: payload["scenario_projection_contract"][
                    "base_condition_by_account_direction"
                ]["main"].__setitem__("long", "changed condition"),
            ),
            (
                "timeframe_schema",
                lambda payload: payload["timeframe_display_contract"].__setitem__(
                    "schema_version", "timeframe-display-v0"
                ),
            ),
            (
                "timeframe_label",
                lambda payload: payload["timeframe_display_contract"][
                    "canonical_by_code"
                ].__setitem__("1d", "日线"),
            ),
            (
                "timeframe_order",
                lambda payload: payload["timeframe_display_contract"][
                    "tradingview_projection_order"
                ].reverse(),
            ),
            (
                "operator_label",
                lambda payload: payload["trigger_operator_display"].__setitem__(
                    "equals_at_trigger", "changed label"
                ),
            ),
        )
        for case_name, tamper in tamper_cases:
            with self.subTest(case=case_name):
                presentation = copy.deepcopy(self.presentation_contract)
                tamper(presentation)
                self.assertTrue(
                    report_presentation_projection_drift(presentation)
                )
                self._assert_codegen_rejects_presentation(presentation)

    def test_presentation_contract_has_no_business_owner_mirrors(self) -> None:
        retired_keys = {
            "appendix_semantic_ownership",
            "maker_decision_exact_fields",
            "maker_semantic_state_contract",
            "fundamental_event_assessment_v1_projection",
            "continuity_semantics",
            "score_display_contract",
            "semantic_projection_contract",
            "maker_defense_projection",
            "retry_policy",
            "entry_reach_probability_basis_fields",
        }
        self.assertFalse(retired_keys & set(self.presentation_contract))
        self.assertEqual(
            set(self.presentation_contract["human_surface_source_of_truth"]),
            {
                "kind",
                "inputs",
                "report_sections_role",
                "free_text_second_truth_allowed",
            },
        )
        reintroduced = copy.deepcopy(self.presentation_contract)
        reintroduced["maker_semantic_state_contract"] = {"owner": "json"}
        self.assertTrue(report_presentation_projection_drift(reintroduced))
        self._assert_codegen_rejects_presentation(reintroduced)

    def test_projection_and_semantic_validation_do_not_redeclare_registry_owners(
        self,
    ) -> None:
        forbidden_assignments = {
            "OBSERVATION_MECHANICAL_OWNERSHIP",
            "RELATIVE_TRIGGER_OPERATOR_PROJECTION",
            "SCAFFOLD_POLICY",
            "VISUAL_CITATION_POLICY",
            "SCENARIO_TRANSITION_CODES",
            "SCENARIO_FIELDS",
            "TRIGGER_OBSERVATION_FIELDS",
            "TRIGGER_CLAIM_FIELDS",
            "DIRECTION_VALUE_MAP",
            "DIRECT_DIRECTION_OBSERVATION_FIELDS",
            "RELATIVE_EXOCHARTS_DIRECTION",
            "STRUCTURED_SOURCES",
            "VISUAL_SOURCES",
            "POLICY_SOURCE_NAMES",
        }
        assigned: set[str] = set()
        for relative in (
            "runtime_vnext/domain_ir/projection.py",
            "runtime_vnext/validation/common.py",
            "runtime_vnext/validation/evidence.py",
            "runtime_vnext/validation/reasoning.py",
            "runtime_vnext/validation/decision.py",
            "runtime_vnext/validation/report.py",
            "runtime_vnext/validation/delivery.py",
        ):
            tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                targets = node.targets if isinstance(node, ast.Assign) else ()
                if isinstance(node, ast.AnnAssign):
                    targets = (node.target,)
                assigned.update(
                    target.id for target in targets if isinstance(target, ast.Name)
                )
        self.assertFalse(assigned & forbidden_assignments)

        production_sources = {
            relative: (ROOT / relative).read_text(encoding="utf-8")
            for relative in (
                "runtime_vnext/domain_ir/projection.py",
                "runtime_vnext/methodology.py",
                "runtime_vnext/plan_semantics.py",
                "runtime_vnext/report_compiler.py",
            )
        }
        self.assertNotIn(
            REGISTRY.evidence_polarity_schema_version,
            production_sources["runtime_vnext/domain_ir/projection.py"],
        )
        self.assertNotIn(
            REGISTRY.maker_order_lifecycle_schema_version,
            production_sources["runtime_vnext/methodology.py"],
        )
        self.assertNotIn(
            "bound_owner_claim.typed_state_or_trigger_logic",
            production_sources["runtime_vnext/report_compiler.py"],
        )
        self.assertNotIn(
            "scenario_ownership.transition_code_by_type",
            production_sources["runtime_vnext/report_compiler.py"],
        )
        self.assertNotIn(
            "decision_and_continuity",
            production_sources["runtime_vnext/report_compiler.py"],
        )
        self.assertIn(
            "ORDER_LIFECYCLE_PATH_FLAGS",
            production_sources["runtime_vnext/plan_semantics.py"],
        )

    def test_registry_identity_is_canonical_and_contains_no_consumer_import(self) -> None:
        identity = REGISTRY.identity_payload()
        self.assertEqual(
            REGISTRY.semantic_contract_sha256,
            canonical_sha256(dict(reversed(list(identity.items())))),
        )
        registry_path = ROOT / "runtime_vnext" / "domain_ir" / "registry.py"
        tree = ast.parse(registry_path.read_text(encoding="utf-8"))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            str(node.module)
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        self.assertFalse(
            imported
            & {
                "runtime_vnext.gates",
                "runtime_vnext.reasoning_submission",
                "runtime_vnext.report_compiler",
                "runtime_vnext.controller",
            }
        )

    def test_schema_versions_follow_their_semantic_impact_class(
        self,
    ) -> None:
        semantic_versions = REGISTRY.identity_payload()["contract_schema_versions"]
        self.assertEqual(
            set(semantic_versions),
            {
                "account_current_basis",
                "account_trigger_logic",
                "decision_model",
                "evidence_polarity",
                "maker_entry_semantics",
                "maker_order_lifecycle",
                "maker_semantic_state",
                "reasoning_model",
                "reasoning_server_projection",
                "reasoning_submission",
                "report_bindings",
                "scenario_control_binding",
                "scenario_ownership",
                "shadow_continuity",
            },
        )
        self.assertEqual(
            set(REGISTRY.presentation_payload()["contract_schema_versions"]),
            {
                "blockbeats_cards",
                "report_model",
                "report_presentation_contract",
                "scenario_projection",
                "timeframe_display",
            },
        )
        baseline = REGISTRY.semantic_contract_sha256
        baseline_presentation = REGISTRY.presentation_payload()
        semantic_change = domain_registry_module.DomainRegistry(
            decision_model_schema_version="decision-model-semantic-test"
        )
        self.assertNotEqual(semantic_change.semantic_contract_sha256, baseline)
        with patch.object(
            domain_registry_module,
            "REPORT_MODEL_SCHEMA_VERSION",
            "canonical-report-model-presentation-test",
        ):
            self.assertEqual(REGISTRY.semantic_contract_sha256, baseline)
            self.assertNotEqual(
                REGISTRY.presentation_payload(),
                baseline_presentation,
            )
        with patch.object(
            domain_registry_module,
            "SHADOW_CONTINUITY_SCHEMA_VERSION",
            "shadow-continuity-semantic-test",
        ):
            self.assertNotEqual(REGISTRY.semantic_contract_sha256, baseline)
        with patch.object(
            domain_registry_module,
            "REPORT_BINDINGS_SCHEMA_VERSION",
            "report-section-bindings-semantic-test",
        ):
            self.assertNotEqual(REGISTRY.semantic_contract_sha256, baseline)
            self.assertEqual(REGISTRY.presentation_payload(), baseline_presentation)

    def test_registry_constant_owners_cannot_be_overridden_per_instance(self) -> None:
        for field in (
            "report_model_schema_version",
            "report_bindings_schema_version",
            "blockbeats_cards_schema_version",
            "shadow_continuity_schema_version",
            "scenario_ownership_schema_version",
            "scenario_projection_schema_version",
            "maker_semantic_state_schema_version",
            "timeframe_display_schema_version",
            "report_model_field_order",
            "reasoning_model_field_order",
            "decision_model_field_order",
        ):
            with self.subTest(field=field), self.assertRaises(TypeError):
                domain_registry_module.DomainRegistry(**{field: "override"})

    def test_runtime_field_order_properties_follow_their_single_registry_owner(
        self,
    ) -> None:
        baseline_semantic = REGISTRY.semantic_contract_sha256
        baseline_presentation = REGISTRY.presentation_payload()

        changed_report = (*domain_registry_module.REPORT_MODEL_FIELD_ORDER, "probe")
        with patch.object(
            domain_registry_module,
            "REPORT_MODEL_FIELD_ORDER",
            changed_report,
        ):
            self.assertEqual(REGISTRY.report_model_field_order, changed_report)
            self.assertEqual(REGISTRY.semantic_contract_sha256, baseline_semantic)
            self.assertNotEqual(REGISTRY.presentation_payload(), baseline_presentation)

        for constant_name, property_name in (
            ("TOP_LEVEL_FIELD_ORDER", "reasoning_model_field_order"),
            ("DECISION_MODEL_FIELD_ORDER", "decision_model_field_order"),
        ):
            original = getattr(domain_registry_module, constant_name)
            changed = (*original, "probe")
            with self.subTest(owner=constant_name), patch.object(
                domain_registry_module,
                constant_name,
                changed,
            ):
                self.assertEqual(getattr(REGISTRY, property_name), changed)
                self.assertNotEqual(REGISTRY.semantic_contract_sha256, baseline_semantic)

    def test_every_public_registry_owner_is_classified_and_identity_bound(self) -> None:
        public_constants = {
            name for name in vars(domain_registry_module) if name.isupper()
        }
        classes = (
            set(SEMANTIC_COMPONENT_NAMES),
            set(PRESENTATION_COMPONENT_NAMES),
            set(METADATA_COMPONENT_NAMES),
        )
        self.assertFalse(classes[0] & classes[1])
        self.assertFalse(classes[0] & classes[2])
        self.assertFalse(classes[1] & classes[2])
        classified = set().union(*classes)
        self.assertEqual(public_constants, classified)
        self.assertEqual(
            set(REGISTRY.identity_payload()["semantic_components"]),
            set(SEMANTIC_COMPONENT_NAMES),
        )
        self.assertEqual(
            set(REGISTRY.presentation_payload()["presentation_components"]),
            set(PRESENTATION_COMPONENT_NAMES),
        )
        self.assertEqual(
            set(METADATA_COMPONENT_NAMES),
            {
                "REGISTRY",
                "SEMANTIC_COMPONENT_NAMES",
                "PRESENTATION_COMPONENT_NAMES",
                "METADATA_COMPONENT_NAMES",
            },
        )
        enum_vocabularies = REGISTRY.identity_payload()["semantic_components"][
            "DOMAIN_ENUM_VOCABULARIES"
        ]
        self.assertEqual(
            enum_vocabularies["EntryType"],
            ["left", "right", "not_applicable"],
        )

    def test_report_binding_topology_is_registry_owned_semantic_authority(
        self,
    ) -> None:
        expected = (
            ("blockbeats_cards", ("blockbeats_cards",)),
            ("frontstage", ("frontstage",)),
            ("maker_summary", ("maker_summary",)),
            ("main_summary", ("main_summary",)),
            ("audit", ("audit",)),
        )
        self.assertEqual(REGISTRY.report_binding_section_model_paths, expected)
        semantic_components = REGISTRY.identity_payload()["semantic_components"]
        self.assertEqual(
            semantic_components["REPORT_BINDING_SECTION_MODEL_PATHS"],
            [[section_id, list(model_path)] for section_id, model_path in expected],
        )

        original_sha256 = REGISTRY.semantic_contract_sha256
        original_presentation = REGISTRY.presentation_payload()
        changed = expected[:-1] + (("audit", ("audit", "changed")),)
        with patch.object(
            domain_registry_module,
            "REPORT_BINDING_SECTION_MODEL_PATHS",
            changed,
        ):
            self.assertEqual(
                REGISTRY.report_binding_section_model_paths,
                changed,
            )
            self.assertNotEqual(
                REGISTRY.semantic_contract_sha256,
                original_sha256,
            )
            self.assertEqual(REGISTRY.presentation_payload(), original_presentation)

    def test_report_traceability_and_safety_owners_are_semantic_hash_bound(
        self,
    ) -> None:
        semantic_components = REGISTRY.identity_payload()["semantic_components"]
        original_sha256 = REGISTRY.semantic_contract_sha256
        for name in (
            "REPORT_SECTIONS",
            "NON_ACTION_REPORT_SECTIONS",
            "NON_TRACEABLE_REPORT_SECTIONS",
            "SECTION_REQUIRED_CLAIM_TYPES",
        ):
            with self.subTest(owner=name):
                value = getattr(domain_registry_module, name)
                self.assertIn(name, semantic_components)
                changed = copy.deepcopy(value)
                if isinstance(changed, dict):
                    changed["__identity_probe__"] = frozenset({"cannot_do"})
                else:
                    changed = frozenset({*changed, "__identity_probe__"})
                with patch.object(domain_registry_module, name, changed):
                    self.assertNotEqual(
                        REGISTRY.semantic_contract_sha256,
                        original_sha256,
                    )

    def test_lifecycle_and_scenario_owners_have_exact_identity_classes(
        self,
    ) -> None:
        semantic_owner_names = (
            "ORDER_LIFECYCLE_PATH_FLAGS",
            "SCENARIO_CONDITION_OWNER_BY_TYPE",
            "SCENARIO_EXECUTION_LIFECYCLE_OWNER",
            "SCENARIO_FREE_PROSE_PROJECTABLE",
            "SCENARIO_TRANSITION_OWNER",
        )
        presentation_owner_names = (
            "ORDER_LIFECYCLE_DISPLAY_BY_STATE",
            "SCENARIO_CANONICAL_AUDIT_FIELD_ORDER",
            "SCENARIO_BASE_CONDITION_BY_ACCOUNT_DIRECTION",
            "SCENARIO_VISIBLE_PROJECTION_BY_ACCOUNT_AND_TRANSITION_CODE",
        )
        semantic_components = REGISTRY.identity_payload()["semantic_components"]
        original_sha256 = REGISTRY.semantic_contract_sha256
        for name in semantic_owner_names:
            with self.subTest(owner=name):
                value = getattr(domain_registry_module, name)
                expected_json = json.loads(
                    json.dumps(value, ensure_ascii=False, sort_keys=True)
                )
                self.assertEqual(semantic_components[name], expected_json)
                if isinstance(value, dict):
                    changed = copy.deepcopy(value)
                    changed["__identity_probe__"] = "changed"
                elif isinstance(value, tuple):
                    changed = (*value, "__identity_probe__")
                else:
                    changed = f"{value}__identity_probe__"
                with patch.object(domain_registry_module, name, changed):
                    self.assertNotEqual(
                        REGISTRY.semantic_contract_sha256,
                        original_sha256,
                    )
        presentation_components = REGISTRY.presentation_payload()[
            "presentation_components"
        ]
        for name in presentation_owner_names:
            with self.subTest(owner=name):
                value = getattr(domain_registry_module, name)
                expected_json = json.loads(
                    json.dumps(value, ensure_ascii=False, sort_keys=True)
                )
                self.assertEqual(presentation_components[name], expected_json)
                if isinstance(value, dict):
                    changed = copy.deepcopy(value)
                    changed["__identity_probe__"] = "展示变化"
                elif isinstance(value, tuple):
                    changed = (*value, "__identity_probe__")
                else:
                    changed = f"{value}__identity_probe__"
                with patch.object(domain_registry_module, name, changed):
                    self.assertEqual(
                        REGISTRY.semantic_contract_sha256,
                        original_sha256,
                    )
                    self.assertNotEqual(
                        REGISTRY.presentation_payload()["presentation_components"][
                            name
                        ],
                        expected_json,
                    )

    def test_scenario_condition_projection_is_derived_from_per_type_owner_map(
        self,
    ) -> None:
        changed = copy.deepcopy(
            domain_registry_module.SCENARIO_CONDITION_OWNER_BY_TYPE
        )
        changed["base"] = "bound_owner_claim.revised_typed_state"
        with patch.dict(
            domain_registry_module.SCENARIO_CONDITION_OWNER_BY_TYPE,
            changed,
            clear=True,
        ):
            projected = projected_report_presentation_contract(
                self.presentation_contract
            )
            self.assertEqual(
                projected["scenario_projection_contract"][
                    "condition_owner_by_type"
                ]["base"],
                "bound_owner_claim.revised_typed_state",
            )
            self.assertTrue(
                report_presentation_projection_drift(self.presentation_contract)
            )

    def test_registry_json_projection_contains_plain_strings_not_enums(self) -> None:
        encoded = json.loads(
            json.dumps(self.sections, ensure_ascii=False, sort_keys=True)
        )
        self.assertEqual(encoded, self.sections)


if __name__ == "__main__":
    unittest.main()
