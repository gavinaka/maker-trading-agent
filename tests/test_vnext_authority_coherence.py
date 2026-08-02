from __future__ import annotations

import copy
import json
import re
import shutil
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import runtime.reasoning_contract as legacy_reasoning_contract
import runtime_vnext.gates as vnext_gates
import runtime_vnext.report_compiler as vnext_report_compiler
from runtime_vnext.golden_samples import semantic_invariants
from runtime_vnext.delivery_renderer import WORD_QA_REVIEW_CHECKLIST_KEYS
from runtime_vnext.domain_ir.projection import (
    report_presentation_contract_registry_views,
    scenario_control_binding_projection,
)
from runtime_vnext.domain_ir.registry import DomainRegistry
from runtime_vnext.methodology import (
    CONTROL_PLANE_FILES,
    PHASE_FILES,
    SEMANTIC_CONTRACT_SCHEMA,
    build_methodology_manifest,
    canonical_sha256,
    discover_control_plane_files,
    load_scoring_policy,
    validate_current_methodology_manifest,
    validate_methodology_manifest,
)


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _active_phase_files() -> set[str]:
    return {item for values in PHASE_FILES.values() for item in values}


def _methodology_leaf_paths(contract: dict) -> set[str]:
    methodology = contract["methodology"]
    paths = {
        f"methodology.{name}.{field}"
        for name, spec in methodology["objects"].items()
        for field in spec["field_order"]
    }
    paths.update(
        f"methodology.{name}[*].{field}"
        for name, spec in methodology["arrays"].items()
        for field in spec["item"]["field_order"]
    )
    return paths


class VNextAuthorityCoherenceTests(unittest.TestCase):
    """Maintenance-time coherence checks, never an additional production gate."""

    def test_domain_qualified_visible_enum_contract_keeps_legacy_boundary(
        self,
    ):
        language = _read("governance/vnext_report_language_contract.md")
        self.assertIn(
            "列入 `human_visible_enum_domains` 的承重或存在同值歧义字段",
            language,
        )
        self.assertIn(
            "其它既有、无歧义且已闭合的 `METRIC_VALUE_CN` 映射",
            language,
        )
        self.assertIn(
            "新增承重字段或同值多义字段必须先进入字段域合同",
            language,
        )

    def test_a5r2g5_trigger_and_scenario_authority_is_symmetric(self):
        trigger_owner_docs = (
            "scoring/reasoning_depth_checklist.md",
            "scoring/golden_report_reasoning_alignment.md",
            "constitution/trading_constitution.md",
            "governance/vnext_daily_workflow.md",
        )
        scenario_owner_docs = (
            "scoring/reasoning_depth_checklist.md",
            "scoring/golden_report_reasoning_alignment.md",
            "constitution/trading_constitution.md",
            "governance/vnext_daily_workflow.md",
            "governance/vnext_report_language_contract.md",
        )
        projection_docs = (
            "scoring/reasoning_depth_checklist.md",
            "scoring/golden_report_reasoning_alignment.md",
            "governance/vnext_daily_workflow.md",
            "governance/vnext_report_language_contract.md",
        )
        for relative in trigger_owner_docs:
            text = _read(relative)
            self.assertIn("account-trigger-logic-v5", text, relative)
            self.assertIn("one_of_at_trigger", text, relative)
            self.assertIn("equals_at_trigger", text, relative)
            self.assertIn("becomes", text, relative)
        for relative in scenario_owner_docs:
            self.assertIn("scenario-ownership-v1", _read(relative), relative)
        for relative in projection_docs:
            text = _read(relative)
            self.assertRegex(text, r"附录 D|Appendix D", relative)
        trigger_authority_text = "\n".join(
            _read(relative)
            for relative in sorted(
                _active_phase_files()
                | {
                    "AGENTS.md",
                    ".agents/skills/daily-report/SKILL.md",
                    "governance/vnext_daily_workflow.md",
                    "runtime_vnext/README.md",
                }
            )
        )
        self.assertEqual(
            set(re.findall(r"\baccount-trigger-logic-v\d+\b", trigger_authority_text)),
            {"account-trigger-logic-v5"},
        )

    def test_word_qa_review_checklist_matches_presentation_contract(self):
        contract = json.loads(
            _read("governance/vnext_report_presentation_contract.json")
        )
        self.assertEqual(
            contract["schema_version"],
            "vnext-report-presentation-contract-v11",
        )
        self.assertEqual(
            tuple(contract["word_visual_qa"]["required_review_checklist"]),
            WORD_QA_REVIEW_CHECKLIST_KEYS,
        )
        semantic = contract["semantic_projection_contract"]
        for key in (
            "secondary_signal_disposition_reason_must_be_visible",
            "all_constructibility_failures_must_be_visible_in_authority_order",
            "all_non_execution_reasons_must_be_visible",
            "rejected_candidate_risk_values_must_be_visible_when_recalculable",
            "rejected_candidate_unrecalculable_reason_must_be_visible",
            "rejected_candidate_parameters_forbidden_in_maker_frontstage",
            "rejected_candidate_audit_requires_non_executable_disclosure",
            "non_applicable_entry_reach_probability_must_render_as_na",
            "numeric_zero_must_not_render_as_na_when_applicable",
            "actual_fill_probability_must_remain_null",
        ):
            self.assertIs(semantic[key], True)
        self.assertFalse(
            semantic[
                "coinglass_observation_may_own_liquidation_confirmation_result"
            ]
        )
        self.assertEqual(
            semantic["liquidation_confirmation_owner"],
            "claims.liquidation_confirmation.confirmation_result",
        )
        self.assertEqual(
            semantic["equals_at_trigger_projection"], "触发时必须为"
        )
        self.assertEqual(
            semantic["one_of_at_trigger_projection"], "触发时必须属于"
        )
        probability_fields = contract["entry_reach_probability_basis_fields"]
        self.assertEqual(probability_fields["reference_source"], "TradingView")
        self.assertEqual(probability_fields["reference_timeframe"], "1h")
        self.assertEqual(
            set(probability_fields["required"]),
            {
                "applicability",
                "reference_price",
                "reference_entry",
                "entry_distance",
                "reach_direction",
                "claim_ids",
            },
        )
        self.assertNotIn("rationale", probability_fields["required"])
        self.assertIs(
            contract["word_visual_qa"][
                "rejected_candidate_audit_uses_neutral_styling"
            ],
            True,
        )
        self.assertIs(
            contract["word_visual_qa"][
                "rejected_candidate_audit_unbounded_keep_chain_forbidden"
            ],
            True,
        )

    def test_timeframe_display_authority_matches_typed_code_domains(self):
        contract = json.loads(
            _read("governance/vnext_report_presentation_contract.json")
        )
        display = vnext_report_compiler._validated_timeframe_display_contract(
            contract
        )
        policy = load_scoring_policy()
        gold = policy["gold_methodology"]
        tradingview_codes = set(gold["timeframes"])
        liquidation_codes = {
            code
            for values in gold["liquidation_capture_windows"].values()
            for code in values
        }
        expected_mapping = {
            "1d": "1D",
            "4h": "4H",
            "1h": "1H",
            "15m": "15m",
            "3d": "3天",
            "48h": "48H",
            "24h": "24H",
        }
        self.assertEqual(display["canonical_by_code"], expected_mapping)
        self.assertEqual(set(expected_mapping), tradingview_codes | liquidation_codes)
        self.assertEqual(
            tuple(display["tradingview_projection_order"]),
            ("1d", "4h", "1h", "15m"),
        )
        self.assertEqual(
            tuple(
                display["canonical_by_code"][code]
                for code in display["tradingview_projection_order"]
            ),
            vnext_gates.TRADINGVIEW_TIMEFRAMES,
        )
        self.assertEqual(
            len(set(display["canonical_by_code"].values())),
            len(display["canonical_by_code"]),
        )
        self.assertNotIn("four_timeframe_tokens", contract)

    def test_timeframe_display_authority_rejects_stale_or_ambiguous_contracts(self):
        contract = json.loads(
            _read("governance/vnext_report_presentation_contract.json")
        )
        mutations = []

        missing = copy.deepcopy(contract)
        del missing["timeframe_display_contract"]["canonical_by_code"]["1d"]
        mutations.append(missing)

        extra = copy.deepcopy(contract)
        extra["timeframe_display_contract"]["canonical_by_code"]["2h"] = "2H"
        mutations.append(extra)

        duplicate = copy.deepcopy(contract)
        duplicate["timeframe_display_contract"]["canonical_by_code"]["1d"] = "4H"
        mutations.append(duplicate)

        stale_schema = copy.deepcopy(contract)
        stale_schema["timeframe_display_contract"]["schema_version"] = "timeframe-display-v0"
        mutations.append(stale_schema)

        stale_owner = copy.deepcopy(contract)
        stale_owner["four_timeframe_tokens"] = ["日线", "4H", "1H", "15m"]
        mutations.append(stale_owner)

        for mutated in mutations:
            with self.subTest(mutated=mutated):
                with self.assertRaises(ValueError):
                    vnext_report_compiler._validated_timeframe_display_contract(
                        mutated
                    )

    def test_a5r2c_projection_authority_closes_control_event_and_maker_state(self):
        contract = json.loads(
            _read("governance/vnext_report_presentation_contract.json")
        )
        semantic = contract["semantic_projection_contract"]
        self.assertTrue(semantic["typed_account_control_is_sole_load_bearing_owner"])
        self.assertEqual(
            semantic["free_control_conclusion_or_invalidation_role"],
            "upstream_audit_only",
        )
        self.assertFalse(
            semantic["free_control_conclusion_or_invalidation_projectable"]
        )
        self.assertFalse(
            semantic[
                "free_control_conclusion_or_invalidation_allowed_in_reasoning_proof"
            ]
        )
        self.assertFalse(
            semantic[
                "free_control_conclusion_or_invalidation_allowed_in_scenario_condition"
            ]
        )
        self.assertEqual(
            semantic["maker_summary_and_execution_frontstage_owner"],
            "audit.maker_execution",
        )
        self.assertEqual(
            semantic["main_authorization_owner"],
            "audit.main_plan.plan_state",
        )
        registry_views = report_presentation_contract_registry_views()
        for field in (
            "scenario_condition_owner",
            "scenario_transition_owner",
            "free_scenario_prose_projectable",
            "execution_lifecycle_owner",
        ):
            self.assertEqual(
                semantic[field],
                registry_views[("semantic_projection_contract", field)],
            )
        self.assertEqual(
            set(contract["maker_execution_fields"]),
            {
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
            },
        )

        maker_state = contract["maker_semantic_state_contract"]
        self.assertEqual(maker_state["schema_version"], "maker-semantic-state-v1")
        self.assertEqual(
            maker_state["candidate_submission_owner"],
            "maker.risk_plan_nonempty",
        )
        self.assertEqual(
            maker_state["exclusive_states"],
            [
                "qualified_candidate",
                "rejected_submitted_candidate",
                "directional_thesis_only",
                "non_directional_observation",
            ],
        )
        self.assertEqual(
            maker_state["rejected_submitted_candidate"]["plan_constructible"],
            [True, False],
        )
        for state in ("directional_thesis_only", "non_directional_observation"):
            self.assertFalse(
                maker_state[state]["candidate_or_rejected_candidate_label_allowed"]
            )
            self.assertTrue(
                maker_state[state]["explicit_absence_disclosure_required"]
            )

        event_v1 = contract["fundamental_event_assessment_v1_projection"]
        self.assertEqual(
            event_v1["role"],
            "observation_only_no_event_aligned_price_attribution",
        )
        self.assertFalse(event_v1["load_bearing_allowed"])
        self.assertEqual(
            event_v1["observation_only_reason_code"],
            "event_price_attribution_unavailable",
        )
        self.assertEqual(
            event_v1["forbidden_load_bearing_uses"],
            [
                "winrate_adjustment",
                "account_current_basis",
                "account_trigger_logic",
            ],
        )
        self.assertTrue(event_v1["price_attribution_basis_required_to_reenable"])
        self.assertEqual(event_v1["secondary_signal"], "fundamental_price_realization")
        self.assertEqual(event_v1["required_disposition"], "no_adjustment")
        self.assertEqual(
            event_v1["required_no_adjustment_reason_code"],
            "event_price_attribution_unavailable",
        )

        authority_docs = (
            "governance/vnext_daily_workflow.md",
            "governance/vnext_report_language_contract.md",
            "scoring/golden_report_reasoning_alignment.md",
            ".agents/skills/daily-report/SKILL.md",
        )
        for relative in authority_docs:
            text = _read(relative)
            self.assertIn("maker-semantic-state-v1", text, relative)
            self.assertIn("event_price_attribution_unavailable", text, relative)
            self.assertIn("price_attribution_basis_required_to_reenable", text, relative)
            self.assertIn("current_basis", text, relative)
            self.assertIn("trigger_logic", text, relative)

    def test_vnext_current_basis_policy_rejects_unknown_fields(self):
        policy = copy.deepcopy(load_scoring_policy(root=ROOT))
        policy["gold_methodology"]["account_current_basis"][
            "claim_source_requirements"
        ] = {}
        with patch.object(vnext_gates, "load_scoring_policy", return_value=policy):
            with self.assertRaisesRegex(
                ValueError, "account_current_basis policy has an invalid field set"
            ):
                vnext_gates._current_basis_policy(ROOT)

    def test_phase_authority_is_business_only_and_control_plane_is_hash_closed(self):
        phase_files = _active_phase_files()
        forbidden_phase_files = {
            "AGENTS.md",
            ".agents/skills/daily-report/SKILL.md",
            "sessions/日报SOP.md",
            "governance/daily_runtime_contract.md",
            "governance/vnext_daily_workflow.md",
            "governance/vnext_sample_outcome_contract.json",
            "memory/notion-publish-checklist.md",
            "memory/report-template-alignment.md",
            "memory/independent-report-no-user-reference.md",
            "memory/precise-numbers-no-fuzzy.md",
            "memory/report-chinese-only-narrative.md",
            "outputs/publish_report.py",
        }
        self.assertTrue(forbidden_phase_files.isdisjoint(phase_files))
        self.assertTrue(all(Path(item).suffix in {".md", ".json"} for item in phase_files))

        control_files = set(CONTROL_PLANE_FILES)
        for required in (
            "AGENTS.md",
            ".agents/skills/daily-report/SKILL.md",
            "governance/vnext_daily_workflow.md",
            "governance/vnext_sample_outcome_contract.json",
            "runtime_vnext/effort_policy.py",
            "runtime/host_capability.py",
            "tools/browser_capture/capture_all.js",
            "tools/browser_capture/capture_delta.js",
            "tools/browser_capture/capture_blockbeats.js",
            "tools/browser_capture/capture_coinglass.js",
            "tools/browser_capture/capture_exo.js",
            "tools/browser_capture/capture_farside_btc_etf.js",
            "tools/browser_capture/capture_fedwatch.js",
            "tools/browser_capture/capture_kalshi_feddecision.js",
            "tools/browser_capture/capture_rate_expectation.js",
            "tools/browser_capture/rate_expectation_state.js",
            "tools/browser_capture/capture_tv.js",
            "tools/browser_capture/cleanup.js",
            "tools/browser_capture/farside_row_policy.js",
            "tools/browser_capture/package.json",
            "tools/browser_capture/package-lock.json",
            "schemas/capture_run_manifest_schema.json",
            "runtime_vnext/rate_expectation.py",
            "outputs/daily_publish_contract.py",
            "outputs/daily_payload_builder.py",
            "outputs/blockbeats_card.py",
            "outputs/report_structure_gate.py",
            "outputs/report_lint.py",
            "outputs/word_qa.py",
        ):
            self.assertIn(required, control_files)
        runtime_python_files = {
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / "runtime_vnext").rglob("*.py")
            if path.is_file()
        }
        self.assertTrue(runtime_python_files.issubset(control_files))
        self.assertEqual(
            tuple(sorted(control_files)),
            discover_control_plane_files(root=ROOT),
        )
        self.assertIn(
            "data_sources/rate_expectation_provider_contract.json",
            PHASE_FILES["evidence"],
        )

        report_phase = set(PHASE_FILES["report"])
        self.assertEqual(
            report_phase,
            {
                "governance/vnext_golden_sample_contract.json",
                "governance/vnext_report_presentation_contract.json",
                "governance/vnext_report_language_contract.md",
            },
        )
        self.assertNotIn(
            "governance/vnext_golden_sample_contract.json",
            PHASE_FILES["reasoning"],
        )
        self.assertNotIn(
            "governance/vnext_report_presentation_contract.json",
            PHASE_FILES["reasoning"],
        )
        manifest = build_methodology_manifest(root=ROOT)
        self.assertEqual(manifest["schema_version"], "methodology-manifest-v3")
        identity = validate_methodology_manifest(manifest)
        self.assertEqual(
            identity.semantic_contract_sha256,
            manifest["semantic_contract_sha256"],
        )
        self.assertEqual(identity.release_sha256, manifest["release_sha256"])
        self.assertEqual(identity.manifest_sha256, manifest["manifest_sha256"])

    def test_methodology_three_hashes_separate_semantics_release_and_envelope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = set(CONTROL_PLANE_FILES) | {
                relative
                for relatives in PHASE_FILES.values()
                for relative in relatives
            }
            for relative in inputs:
                source = ROOT / relative
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)

            baseline = build_methodology_manifest(root=root)
            validate_methodology_manifest(baseline)

            scoring_path = root / "scoring" / "scoring_contract.json"
            scoring_payload = json.loads(scoring_path.read_text(encoding="utf-8"))
            scoring_path.write_text(
                json.dumps(scoring_payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            reformatted = build_methodology_manifest(root=root)
            self.assertEqual(
                reformatted["semantic_contract_sha256"],
                baseline["semantic_contract_sha256"],
            )
            self.assertEqual(reformatted["release_sha256"], baseline["release_sha256"])
            self.assertNotEqual(
                reformatted["manifest_sha256"], baseline["manifest_sha256"]
            )

            added_module = root / "runtime_vnext" / "identity_inventory_probe.py"
            added_module.write_text("# release inventory probe\n", encoding="utf-8")
            code_changed = build_methodology_manifest(root=root)
            self.assertIn(
                "runtime_vnext/identity_inventory_probe.py",
                {
                    record["path"]
                    for record in code_changed["control_plane"]["files"]
                },
            )
            self.assertEqual(
                code_changed["semantic_contract_sha256"],
                reformatted["semantic_contract_sha256"],
            )
            self.assertNotEqual(
                code_changed["release_sha256"], reformatted["release_sha256"]
            )
            self.assertNotEqual(
                code_changed["manifest_sha256"], reformatted["manifest_sha256"]
            )

            semantic_changed = build_methodology_manifest(
                root=root,
                registry=DomainRegistry(schema_version="vnext-domain-registry-test-v3"),
            )
            self.assertNotEqual(
                semantic_changed["semantic_contract_sha256"],
                code_changed["semantic_contract_sha256"],
            )
            self.assertEqual(
                semantic_changed["release_sha256"], code_changed["release_sha256"]
            )
            self.assertNotEqual(
                semantic_changed["manifest_sha256"], code_changed["manifest_sha256"]
            )

    def test_production_manifest_rejects_generated_reasoning_view_drift(self):
        tamper_cases = (
            (
                "maker_thesis_direction_deleted",
                lambda payload: payload["claim_fields_by_type"][
                    "maker_thesis"
                ].remove("direction"),
            ),
            (
                "tradingview_observation_fields_reordered",
                lambda payload: payload["observation_fields_by_source"][
                    "TradingView"
                ].reverse(),
            ),
            (
                "top_level_field_order_reordered",
                lambda payload: payload["top_level"]["field_order"].reverse(),
            ),
            (
                "pipeline_unit_fields_reordered",
                lambda payload: payload["pipeline_unit_fields"].reverse(),
            ),
        )

        for case_name, tamper in tamper_cases:
            with (
                self.subTest(case=case_name),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                inputs = set(CONTROL_PLANE_FILES) | {
                    relative
                    for relatives in PHASE_FILES.values()
                    for relative in relatives
                }
                for relative in inputs:
                    source = ROOT / relative
                    target = root / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)

                contract_path = (
                    root / "scoring" / "reasoning_submission_contract.json"
                )
                contract = json.loads(contract_path.read_text(encoding="utf-8"))
                tamper(contract)
                contract_path.write_text(
                    json.dumps(contract, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )

                with self.assertRaisesRegex(
                    ValueError,
                    "reasoning submission contract deterministic views differ",
                ):
                    build_methodology_manifest(root=root)

    def test_production_manifest_rejects_generated_report_presentation_drift(
        self,
    ):
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
                "semantic_condition_owner",
                lambda payload: payload["semantic_projection_contract"].__setitem__(
                    "scenario_condition_owner",
                    "changed owner",
                ),
            ),
            (
                "semantic_transition_owner",
                lambda payload: payload["semantic_projection_contract"].__setitem__(
                    "scenario_transition_owner",
                    "changed owner",
                ),
            ),
            (
                "semantic_free_prose_policy",
                lambda payload: payload["semantic_projection_contract"].__setitem__(
                    "free_scenario_prose_projectable",
                    True,
                ),
            ),
            (
                "execution_lifecycle_owner",
                lambda payload: payload["semantic_projection_contract"].__setitem__(
                    "execution_lifecycle_owner",
                    "changed owner",
                ),
            ),
        )

        for case_name, tamper in tamper_cases:
            with self.subTest(case=case_name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                inputs = set(CONTROL_PLANE_FILES) | {
                    relative
                    for relatives in PHASE_FILES.values()
                    for relative in relatives
                }
                for relative in inputs:
                    source = ROOT / relative
                    target = root / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)

                contract_path = (
                    root
                    / "governance"
                    / "vnext_report_presentation_contract.json"
                )
                contract = json.loads(contract_path.read_text(encoding="utf-8"))
                tamper(contract)
                contract_path.write_text(
                    json.dumps(contract, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )

                with self.assertRaisesRegex(
                    ValueError,
                    "report presentation contract deterministic views differ",
                ):
                    build_methodology_manifest(root=root)

    def test_methodology_manifest_v2_remains_read_only_compatible(self):
        legacy = {
            "schema_version": "methodology-manifest-v2",
            "policy": "historical-test-envelope",
            "phases": {},
        }
        legacy["manifest_sha256"] = canonical_sha256(legacy)
        original = copy.deepcopy(legacy)
        identity = validate_methodology_manifest(legacy)
        self.assertTrue(identity.legacy_combined_identity)
        self.assertIsNone(identity.semantic_contract_sha256)
        self.assertIsNone(identity.release_sha256)
        self.assertEqual(identity.manifest_sha256, legacy["manifest_sha256"])
        self.assertEqual(legacy, original)

    def test_methodology_manifest_v3_rejects_identity_tampering(self):
        manifest = build_methodology_manifest(root=ROOT)
        tampered = copy.deepcopy(manifest)
        tampered["release_sha256"] = "0" * 64
        tampered["manifest_sha256"] = canonical_sha256(tampered)
        with self.assertRaisesRegex(ValueError, "release hash"):
            validate_methodology_manifest(tampered)

    def test_current_manifest_rejects_self_consistent_phase_subset(self):
        manifest = build_methodology_manifest(root=ROOT)
        tampered = copy.deepcopy(manifest)
        phase_name = next(
            name
            for name, value in tampered["phases"].items()
            if len(value["files"]) > 1
        )
        phase = tampered["phases"][phase_name]
        removed = phase["files"].pop()
        removed_semantic = phase["semantic_files"].pop()
        self.assertEqual(removed["path"], removed_semantic["path"])
        phase["phase_sha256"] = canonical_sha256({"files": phase["files"]})
        phase["semantic_phase_sha256"] = canonical_sha256(
            {"files": phase["semantic_files"]}
        )
        tampered["semantic_contract_sha256"] = canonical_sha256(
            {
                "schema_version": SEMANTIC_CONTRACT_SCHEMA,
                "domain_registry_sha256": tampered["domain_registry_sha256"],
                "phase_semantic_sha256": {
                    name: value["semantic_phase_sha256"]
                    for name, value in sorted(tampered["phases"].items())
                },
            }
        )
        tampered["manifest_sha256"] = canonical_sha256(tampered)

        validate_methodology_manifest(tampered)
        with self.assertRaisesRegex(ValueError, "differs from the current release"):
            validate_current_methodology_manifest(tampered, root=ROOT)

    def test_current_manifest_rejects_different_registry_identity(self):
        foreign_registry = DomainRegistry(
            schema_version="vnext-domain-registry-foreign-test-v1"
        )
        manifest = build_methodology_manifest(
            root=ROOT,
            registry=foreign_registry,
        )

        validate_methodology_manifest(manifest)
        with self.assertRaisesRegex(ValueError, "differs from the current release"):
            validate_current_methodology_manifest(manifest, root=ROOT)

    def test_vnext_delivery_control_authority_has_one_machine_owned_sequence(self):
        skill = _read(".agents/skills/daily-report/SKILL.md")
        readme = _read("runtime_vnext/README.md")
        cli = _read("runtime_vnext/cli.py")
        delivery = _read("runtime_vnext/delivery_renderer.py")
        sequence = (
            "compile -> word-qa-export -> word-qa-approve -> shadow-delivery"
        )

        for relative, text in (
            (".agents/skills/daily-report/SKILL.md", skill),
            ("runtime_vnext/README.md", readme),
        ):
            self.assertIn(sequence, text, relative)
            self.assertIn(
                "word-qa-export owns the run-local render",
                text,
                relative,
            )
        self.assertNotIn(
            "must use only `runtime_vnext.cli compile` and "
            "`runtime_vnext.cli shadow-delivery`",
            skill,
        )
        self.assertNotIn("py -m runtime_vnext.cli evidence", readme)
        self.assertIn(
            "canonical_report_renderer.render_canonical",
            delivery,
        )
        self.assertNotIn('commands.add_parser("render")', cli)

    def test_active_phase_structural_noise_buffer_schema_matches_machine_truth(self):
        policy = load_scoring_policy(root=ROOT)
        expected_schema = policy["risk_execution"][
            "structural_noise_buffer_judgment"
        ]["schema_version"]
        self.assertEqual(expected_schema, "structural-noise-buffer-v2")

        version_pattern = re.compile(r"\bstructural-noise-buffer-v\d+\b")
        declarations = {}
        for relative in sorted(_active_phase_files()):
            versions = sorted(set(version_pattern.findall(_read(relative))))
            if versions:
                declarations[relative] = versions

        for required in (
            "constitution/trading_constitution.md",
            "scoring/golden_report_reasoning_alignment.md",
            "scoring/scoring_contract.json",
        ):
            self.assertIn(required, declarations)
        stale = {
            relative: versions
            for relative, versions in declarations.items()
            if versions != [expected_schema]
        }
        self.assertEqual(
            stale,
            {},
            "active phase authority declares a stale structural-noise-buffer schema",
        )

    def test_vnext_requested_effort_authority_is_exact_xhigh(self):
        policy_path = ROOT / "runtime_vnext" / "effort_policy.py"
        self.assertTrue(policy_path.is_file(), "vNext effort machine truth is missing")
        policy = policy_path.read_text(encoding="utf-8")
        self.assertIn('REQUESTED_MODEL = "gpt-5.6-sol"', policy)
        self.assertIn('REQUESTED_EFFORT = "xhigh"', policy)

        authority_docs = (
            "AGENTS.md",
            ".agents/skills/daily-report/SKILL.md",
            "scoring/golden_report_reasoning_alignment.md",
            "scoring/reasoning_depth_checklist.md",
            "runtime_vnext/README.md",
        )
        stale_patterns = (
            r"new vNext run[^\n]*exactly `high`",
            r"新 run 请求的推理努力固定且只能为 `high`",
            r"生产规定的 `high` 推理强度",
            r"gpt-5\.6-sol\s*\+\s*`?high`?",
        )
        for relative in authority_docs:
            text = _read(relative)
            self.assertIn("xhigh", text, relative)
            for pattern in stale_patterns:
                self.assertIsNone(re.search(pattern, text), f"{relative}: {pattern}")
        skill = _read(".agents/skills/daily-report/SKILL.md")
        self.assertIn("Steps 8–9 are legacy-engine-only", skill)
        self.assertIn("--minimum-effort xhigh", skill)
        self.assertIn("runtime_vnext.cli host", skill)
        self.assertIn("cannot authorize vNext", skill)

    def test_active_phase_reasoning_authority_closes_methodology_ownership(self):
        contract = json.loads(
            _read("scoring/reasoning_submission_contract.json")
        )
        scoring = json.loads(_read("scoring/scoring_contract.json"))
        self.assertEqual(
            contract["schema_version"],
            "reasoning-submission-contract-v6",
        )
        self.assertEqual(
            contract["scaffold_policy"]["schema_version"],
            "reasoning-submission-scaffold-v6",
        )
        self.assertEqual(
            contract["certified_schema_version"],
            "reasoning-model-v5",
        )
        self.assertEqual(
            contract["scenario_fields"],
            ["id", "account", "scenario_type", "owner_claim_id"],
        )
        ownership = contract["scenario_ownership"]
        self.assertEqual(ownership["schema_version"], "scenario-ownership-v1")
        self.assertFalse(ownership["producer_free_prose_allowed"])
        projection = contract["server_projection"]
        self.assertEqual(
            projection["schema_version"],
            "reasoning-server-projection-v4",
        )
        self.assertFalse(
            projection["producer_values_at_server_owned_paths_authoritative"]
        )
        self.assertTrue(projection["projection_must_run_inside_reasoning_attempt"])
        self.assertTrue(projection["business_judgment_repair_forbidden"])
        observation_ownership = projection["observation_mechanical_ownership"]
        self.assertEqual(
            observation_ownership["evidence_refs_semantics"],
            "sealed_same_source_artifact_inventory_not_visual_read_proof",
        )
        self.assertIn(
            "observations[*].visual_citations[*].crop",
            observation_ownership["model_owned_visual_proof_paths"],
        )
        topology = contract["claim_topology"]
        self.assertEqual(topology["schema_version"], "claim-topology-v1")
        self.assertEqual(topology["support_selection_owner"], "model")
        self.assertFalse(topology["server_support_edge_injection_allowed"])
        self.assertEqual(
            topology["required_reachable_claim_types_by_claim_type"][
                "invalidation_path"
            ],
            ["market_regime"],
        )
        self.assertEqual(
            topology["required_reachable_claim_types_by_claim_type"]["cannot_do"],
            [
                "maker_thesis",
                "strongest_counterevidence",
                "invalidation_path",
                "market_regime",
            ],
        )
        narrative = contract["typed_narrative_ownership"]
        self.assertEqual(
            narrative["schema_version"],
            "typed-narrative-ownership-v1",
        )
        self.assertFalse(narrative["prose_keyword_inference_allowed"])
        self.assertTrue(narrative["compiler_typed_projection_required"])
        self.assertIn("scenario_tree", projection["server_owned_paths"])
        self.assertIn(
            "methodology.scenario_tree",
            projection["server_owned_paths"],
        )
        self.assertIn(
            "scoring/reasoning_submission_contract.json",
            PHASE_FILES["reasoning"],
        )

        leaf_ownership = projection["methodology_leaf_ownership"]
        self.assertEqual(
            leaf_ownership["schema_version"],
            "methodology-leaf-ownership-v1",
        )
        self.assertEqual(
            set(leaf_ownership["server_owned_subtrees"]),
            {
                "methodology.account_separation",
                "methodology.scenario_tree",
            },
        )
        self.assertEqual(
            set(leaf_ownership["model_owned_paths"]),
            {
                "methodology.independent_synthesis.market_stage_claim_id",
                "methodology.independent_synthesis.primary_evidence_claim_ids",
                "methodology.independent_synthesis.strongest_counter_claim_id",
                "methodology.independent_synthesis.action_claim_id",
                "methodology.fundamental_event_assessments[*].impact_channel",
                "methodology.fundamental_event_assessments[*].expected_effect",
                "methodology.fundamental_event_assessments[*].counter_claim_ids",
                "methodology.multi_timeframe_transition.transition_summary",
            },
        )
        self.assertEqual(
            set(leaf_ownership["producer_key_paths"]),
            {
                (
                    "methodology.fundamental_event_assessments[*]."
                    "selected_event_sha256"
                )
            },
        )
        self.assertEqual(
            leaf_ownership["unclassified_leaf_policy"],
            "preflight_hard_stop",
        )
        self.assertEqual(
            leaf_ownership["server_owned_bindings"][
                "methodology.volume_profile_liquidity.claim_id"
            ],
            {
                "resolver": "unique_claim_id",
                "claim_type": "chart_interpretation",
                "account": "shared",
            },
        )

        methodology_leaves = _methodology_leaf_paths(contract)
        self.assertEqual(len(methodology_leaves), 54)
        self.assertEqual(leaf_ownership["leaf_count"], len(methodology_leaves))
        server_bindings = set(leaf_ownership["server_owned_bindings"])
        model_owned = set(leaf_ownership["model_owned_paths"])
        producer_keys = set(leaf_ownership["producer_key_paths"])
        subtree_leaves = {
            path
            for path in methodology_leaves
            if any(
                path.startswith(f"{subtree}.")
                or path.startswith(f"{subtree}[")
                for subtree in leaf_ownership["server_owned_subtrees"]
            )
        }
        self.assertTrue(server_bindings.isdisjoint(model_owned))
        self.assertTrue(server_bindings.isdisjoint(producer_keys))
        self.assertTrue(model_owned.isdisjoint(producer_keys))
        self.assertTrue(
            subtree_leaves.isdisjoint(
                server_bindings | model_owned | producer_keys
            )
        )
        self.assertEqual(
            server_bindings | model_owned | producer_keys | subtree_leaves,
            methodology_leaves,
            "every methodology leaf requires exactly one declared owner",
        )

        pipeline_policy = scoring["gold_methodology"]["reasoning_pipeline"]
        self.assertIs(
            pipeline_policy["report_sections_forbidden_in_reasoning_v5"],
            True,
        )
        self.assertNotIn(
            "report_sections_forbidden_in_reasoning_v4",
            pipeline_policy,
        )

        active_text = "\n".join(
            _read(relative) for relative in sorted(_active_phase_files())
        )
        reasoning_text = "\n".join(
            _read(relative) for relative in sorted(PHASE_FILES["reasoning"])
        )
        self.assertEqual(
            set(
                re.findall(
                    r"\breasoning-submission-contract-v\d+\b",
                    reasoning_text,
                )
            ),
            {"reasoning-submission-contract-v6"},
        )
        self.assertEqual(
            set(
                re.findall(
                    r"\breasoning-submission-scaffold-v\d+\b",
                    reasoning_text,
                )
            ),
            {"reasoning-submission-scaffold-v6"},
        )
        self.assertEqual(
            set(
                re.findall(
                    r"\breasoning-server-projection-v\d+\b",
                    reasoning_text,
                )
            ),
            {"reasoning-server-projection-v4"},
        )
        for stale in (
            "reasoning-submission-contract-v5",
            "reasoning-submission-contract-v4",
            "reasoning-submission-contract-v3",
            "reasoning-submission-scaffold-v5",
            "reasoning-submission-scaffold-v4",
            "reasoning-submission-scaffold-v3",
            "reasoning-server-projection-v3",
            "reasoning-server-projection-v2",
            "reasoning-server-projection-v1",
        ):
            self.assertNotIn(stale, reasoning_text)
        self.assertEqual(
            set(re.findall(r"\bscenario-ownership-v\d+\b", active_text)),
            {"scenario-ownership-v1"},
        )
        self.assertEqual(
            set(re.findall(r"\breasoning-model-v\d+\b", active_text)),
            {"reasoning-model-v5"},
        )
        self.assertEqual(
            set(
                re.findall(
                    r"\bvnext-report-presentation-contract-v\d+\b",
                    active_text,
                )
            ),
            {"vnext-report-presentation-contract-v11"},
        )

    def test_active_authority_has_no_legacy_path_or_stale_market_anchor(self):
        active_text = "\n".join(_read(relative) for relative in sorted(_active_phase_files()))
        self.assertIsNone(
            re.search(r"`(?:agents|state|sessions|runtime)/[^`]+`", active_text)
        )
        for stale in (
            "database_id",
            "agents/footprint_agent.md",
            "state/maker_state.json",
            "sessions/日报SOP.md",
            "session_runner.py",
            "manual_notion_reference_options",
            "⑤源",
            "target_clean_trades",
            "current_progress_pct",
            "current_defense_layer = 5",
            "66,950",
            "64,800",
            "63,900",
            "64,150",
            "64,221",
            "66,800",
            "71,2xx",
            "71,7xx",
            "70,420",
            "70,500",
        ):
            self.assertNotIn(stale, active_text)

    def test_report_phase_forbids_legacy_delivery_and_reverse_inference(self):
        report_text = "\n".join(_read(relative) for relative in PHASE_FILES["report"])
        for forbidden in (
            "NOTION_TOKEN",
            "publish_report.py",
            "session_runner.py",
            "page_id",
            "runtime_state/",
            "中文数字替换",
        ):
            self.assertNotIn(forbidden, report_text)
        for required in (
            "阿拉伯数字",
            "source/hash-bound continuity artifact",
            "禁止从止损、R、仓位上限、计划价或报告文字反推",
            "2–5 个不同挂单档位",
            "合计 100%",
            "中文",
            "逐页 PNG",
        ):
            self.assertIn(required, report_text)

    def test_orderflow_domain_is_continuous_and_extreme_is_bounded(self):
        policy = load_scoring_policy(root=ROOT)
        orderflow = policy["maker_score"]["orderflow"]
        self.assertEqual(orderflow["minimum_score"], 0)
        self.assertEqual(orderflow["maximum_score"], 70)
        self.assertTrue(orderflow["integer_only"])
        self.assertEqual(orderflow["non_extreme_max"], 60)
        self.assertEqual(orderflow["extreme_score"], 70)
        self.assertEqual(
            set(orderflow["extreme_candidate_combinations"]),
            {"C19", "C22", "C56", "C59"},
        )
        self.assertNotIn("manual_notion_reference_options", orderflow)

        method = _read("scoring/orderflow_methodology.md")
        self.assertIn("0–60 内任意整数", method)
        self.assertIn("C19/C22/C56/C59", method)
        self.assertNotIn("50→55", method)
        self.assertNotIn("手动凑分", method)

    def test_machine_policy_keeps_maker_ladder_and_account_separation(self):
        policy = json.loads(_read("scoring/scoring_contract.json"))
        risk = policy["risk_execution"]
        self.assertEqual(risk["maker_order_method"], "Maker")
        self.assertEqual(risk["maker_fixed_leverage"], 5)
        self.assertEqual(risk["maker_entry_types"], ["left", "right"])
        self.assertEqual(
            risk["maker_non_directional_entry_type"], "not_applicable"
        )
        visible_enum_domains = json.loads(
            _read("governance/vnext_report_presentation_contract.json")
        )["human_visible_enum_domains"]
        self.assertEqual(
            set(visible_enum_domains["maker.entry_type"]),
            {
                *risk["maker_entry_types"],
                risk["maker_non_directional_entry_type"],
            },
        )
        self.assertEqual(
            set(
                visible_enum_domains[
                    "tradingview.chart_basis.volume_price_state"
                ]
            ),
            {"confirm", "weaken", "neutral", "conflicted", "not_available"},
        )
        self.assertEqual(
            set(
                visible_enum_domains[
                    "tradingview.chart_basis.trendline_status"
                ]
            ),
            {"intact", "broken", "ambiguous", "not_available"},
        )
        self.assertEqual(risk["maker_entry_mode"], "ladder_only")
        self.assertEqual(risk["minimum_entry_levels"], 2)
        self.assertEqual(risk["maximum_entry_levels"], 5)
        self.assertEqual(risk["entry_allocation_total_pct"], 100)

        main = risk["main_account"]
        self.assertEqual(main["maximum_nominal_risk_pct"], 8)
        self.assertEqual(main["risk_fill_scenarios"], "all_non_empty_combinations")
        self.assertEqual(main["risk_failure_behavior"], "observe")
        self.assertIn("main_risk_above_8", main["plan_rejection_reason_codes"])
        self.assertEqual(risk["maximum_nominal_risk_pct"], 3)
        self.assertEqual(risk["risk_formula"], main["risk_formula"])
        probability = risk["entry_reach_probability_applicability"]
        self.assertEqual(
            probability["allowed_statuses"],
            [
                "applicable",
                "not_applicable_no_certified_entry_geometry",
            ],
        )
        self.assertEqual(
            probability["applicable_requires"],
            [
                "certified_tradingview_entry_zone",
                "at_least_one_typed_candidate_entry_within_zone",
                "complete_tradingview_1h_reach_geometry",
            ],
        )
        self.assertIsNone(probability["not_applicable_probability_value"])
        self.assertTrue(probability["numeric_zero_is_not_a_null_sentinel"])
        lifecycle = risk["maker_order_lifecycle"]
        self.assertEqual(lifecycle["schema_version"], "maker-order-lifecycle-v1")
        self.assertTrue(lifecycle["gate_derives_exact_object"])
        self.assertTrue(lifecycle["actual_fill_probability_is_not_estimated"])

        current_basis = policy["gold_methodology"]["account_current_basis"]
        self.assertEqual(current_basis["schema_version"], "account-current-basis-v2")
        self.assertEqual(current_basis["minimum_clause_count"], 1)
        self.assertEqual(
            current_basis["evidence_polarity"]["strongest_counter_required_effect"],
            "counter",
        )
        self.assertEqual(
            legacy_reasoning_contract.ACCOUNT_CURRENT_BASIS_POLICY_FIELDS,
            vnext_gates.ACCOUNT_CURRENT_BASIS_POLICY_FIELDS,
        )
        self.assertEqual(
            set(current_basis),
            vnext_gates.ACCOUNT_CURRENT_BASIS_POLICY_FIELDS,
        )
        self.assertNotIn("claim_source_requirements", current_basis)
        self.assertTrue(current_basis["separate_from_future_trigger_logic"])
        self.assertEqual(
            policy["gold_methodology"]["account_trigger_logic"][
                "account_source_requirements"
            ],
            {
                "main": {
                    "always": ["TradingView"],
                    "one_of_sources": ["Farside"],
                    "one_of_claim_types": ["fundamental_price_realization"],
                },
                "maker_counter": {
                    "always": ["TradingView"],
                    "one_of_sources": ["Coinglass", "Exocharts"],
                },
                "maker_invalidation": {
                    "always": ["TradingView", "Coinglass"]
                },
            },
        )
        trigger = policy["gold_methodology"]["account_trigger_logic"]
        self.assertEqual(trigger["schema_version"], "account-trigger-logic-v5")
        self.assertTrue(trigger["any_clause_requires_independent_counter_polarity"])
        self.assertTrue(trigger["all_directional_clauses_must_match_counter_polarity"])
        self.assertTrue(trigger["one_of_direction_targets_must_have_single_polarity"])
        relative = trigger["relative_direction_observation_fields"]["Exocharts"][
            "cross_check_result"
        ]
        self.assertEqual(
            relative["reference_operator_policy"],
            {
                "target_equals_current": "equals_at_trigger",
                "target_differs_from_current": "becomes",
            },
        )
        self.assertEqual(relative["relative_operator"], "equals_at_trigger")
        self.assertEqual(
            trigger["future_trigger_current_truth_quantifier_by_mode"],
            {"all": "all", "any": "any"},
        )
        self.assertNotIn(
            "future_trigger_requires_at_least_one_currently_unsatisfied_clause",
            trigger,
        )
        scenario_control = trigger["scenario_control_binding"]
        self.assertEqual(scenario_control, scenario_control_binding_projection())

        noise = risk["structural_noise_buffer_judgment"]
        self.assertEqual(noise["schema_version"], "structural-noise-buffer-v2")
        self.assertIn("noise_outer_boundary", noise["required_fields"])

        liquidation = policy["gold_methodology"][
            "liquidation_confirmation_ownership"
        ]
        self.assertEqual(
            liquidation["confirmation_result_owner"],
            "liquidation_confirmation claim",
        )
        self.assertEqual(
            liquidation["required_direct_observation_sources"], ["Coinglass"]
        )
        self.assertEqual(
            liquidation["required_direct_claim_types"],
            ["chart_interpretation"],
        )

        stop_policy = risk["maker_initial_stop_policy"]
        self.assertTrue(stop_policy["outward_buffer_required"])
        self.assertTrue(
            stop_policy[
                "buffer_claim_id_must_equal_same_account_invalidation_claim"
            ]
        )
        self.assertFalse(stop_policy["risk_budget_may_shrink_structural_stop"])
        self.assertEqual(
            set(stop_policy["allowed_buffer_basis_codes"]),
            {"current_run_typed_market_noise_allowance"},
        )
        self.assertIn(
            "structural_stop_invalid",
            risk["maker_plan_constructibility_reason_codes"],
        )

        defense = risk["defense_trigger_policy"]
        self.assertTrue(defense["generic_plus_minus_formula_forbidden"])
        self.assertEqual(defense["decision_mode"], "ladder_prefill_exact_scenarios")
        self.assertEqual(
            set(defense["allowed_rounding_rules"]),
            {"exact_no_rounding", "nearest_step_half_up"},
        )
        self.assertIn("first_trigger_price_raw", defense["trigger_scenario_required_fields"])
        self.assertIn("rounding_step", defense["trigger_scenario_required_fields"])
        self.assertIn(
            "defense_trigger_invalid",
            risk["maker_plan_constructibility_reason_codes"],
        )
        self.assertNotIn("ladder_first_formula", risk)
        self.assertNotIn("ladder_second_formula", risk)

        reasoning = "\n".join(_read(relative) for relative in PHASE_FILES["reasoning"])
        self.assertIn("主账户与 Maker", reasoning)
        self.assertIn("不得互相引用结论", _read("governance/vnext_report_language_contract.md"))

    def test_golden_semantic_shape_requires_exact_defense_prices_without_exposing_values(self):
        valid = semantic_invariants(
            [
                "反弹空：100-102，按区间分档执行",
                "第一层：价格触及 98.5（+1.5R）后执行动态止损规则",
                "第二层：价格触及 97（+2R）后只设保本损",
            ]
        )
        self.assertTrue(all(valid.values()))

        formula_only = semantic_invariants(
            [
                "反弹空：100-102，按区间分档执行",
                "第一层：实际加权成交价 ± 1.5R 后执行动态止损规则",
                "第二层：实际加权成交价 ± 2R 后只设保本损",
            ]
        )
        self.assertFalse(formula_only["defense_first_exact_trigger_price"])
        self.assertFalse(formula_only["defense_second_exact_trigger_price"])
        self.assertFalse(formula_only["defense_layers_are_not_generic_formula_only"])

    def test_six_source_roles_and_source_boundaries_are_complete(self):
        policy = load_scoring_policy(root=ROOT)
        roles = policy["gold_methodology"]["source_roles"]
        self.assertEqual(
            set(roles),
            {
                "blockbeats",
                "coinglass",
                "exocharts",
                "fedwatch",
                "farside_btc_etf",
                "tradingview",
            },
        )
        self.assertEqual(
            roles["blockbeats"]["vnext_observation_metric_fields"],
            [
                "tier",
                "event_window_hours",
                "selected_event_count",
                "selected_event_sha256",
            ],
        )
        self.assertNotIn(
            "selected_event_sha256",
            roles["blockbeats"]["required_value_paths"],
        )
        self.assertEqual(
            policy["gold_methodology"]["fedwatch_outcome_step_bp"],
            25,
        )

        coinglass = _read("data_sources/collectors/coinglass.md")
        self.assertIn("同一张 BTC 1H 四面板", coinglass)
        self.assertIn("同一价格 pivot", coinglass)
        self.assertIn("无同一 1H pivot 四面板 PNG 时必须 `valid:false`", coinglass)

        exocharts = _read("data_sources/collectors/exocharts.md")
        for token in (
            "Bybit BTCUSD",
            "D",
            "Tick 120",
            "Bid-Ask Profile",
            "Imbalance",
            "Candle None",
            "FPBS",
            "vWap",
        ):
            self.assertIn(token, exocharts)

        fedwatch = _read("data_sources/collectors/fedwatch.md")
        self.assertIn("Data as of", fedwatch)
        self.assertIn("CT", fedwatch)
        self.assertIn("主机", fedwatch)
        self.assertIn("禁止", fedwatch)

    def test_evidence_freshness_is_vnext_run_local_and_fail_closed(self):
        freshness = _read("data_sources/freshness_rules.md")
        for required in (
            "date + slot + run_id + capture_id",
            "不可变 evidence snapshot",
            "整个 evidence stage 失败",
            "不得生成部分报告",
            "预算耗尽进入 `needs_review`",
            "后续阶段失败不得触发重采",
        ):
            self.assertIn(required, freshness)
        for legacy in (
            "`workflow.md`",
            "_manifest.json",
            "data_collection_agent",
            "session_state.tasks",
            "output_agent",
            "score_state.current_score",
            "score_state.historical_reference",
            "4 - 6 小时",
            "重采集失败 ≥ 3 次",
        ):
            self.assertNotIn(legacy, freshness)

        source_rules = _read("data_sources/source_rules.md")
        self.assertIn("任一必需源读取失败，整个 vNext evidence stage 必须失败", source_rules)
        self.assertIn("禁止旧源替代、部分报告或整轮循环", source_rules)

    def test_fedwatch_plan_c_is_closed_and_capture_entry_is_unique(self):
        required_sources = _read("data_sources/required_sources.md")
        fedwatch = _read("data_sources/collectors/fedwatch.md")
        capture_all = _read("tools/browser_capture/capture_all.js")
        capture_delta = _read("tools/browser_capture/capture_delta.js")
        self.assertIn("只由 control-plane hash 绑定的 `capture_all.js`", required_sources)
        self.assertNotIn("capture_delta.js", required_sources)
        self.assertNotIn("authoritative_web_fallback", required_sources + fedwatch)
        self.assertIn("每个 slot 重新 `page.goto` CME 官方页面", fedwatch)
        self.assertIn("`Target Rate Probabilities`", fedwatch)
        self.assertIn("状态机才可调用 Kalshi **一次**", fedwatch)
        self.assertIn("method_equivalence=non_equivalent", fedwatch)
        self.assertIn("不是并行数据源、交叉挑选器或", fedwatch)
        self.assertIn("不伪造 CME 截图", fedwatch)
        self.assertIn("禁止付费 CME API、Federal Reserve、媒体", required_sources)
        self.assertEqual(
            len(
                re.findall(
                    r"(?m)^\s*'capture_rate_expectation\.js',\s*$",
                    capture_all,
                )
            ),
            1,
        )
        self.assertEqual(
            len(
                re.findall(
                    r"(?m)^\s*script:\s*'capture_rate_expectation\.js',\s*$",
                    capture_delta,
                )
            ),
            1,
        )
        other_collectors = "\n".join(
            _read(path)
            for path in (
                "data_sources/collectors/blockbeats.md",
                "data_sources/collectors/coinglass.md",
                "data_sources/collectors/exocharts.md",
                "data_sources/collectors/farside_btc_etf.md",
                "data_sources/collectors/tradingview.md",
            )
        )
        self.assertNotIn("KXFEDDECISION", other_collectors)
        self.assertNotIn("kalshi_plan_c_fallback", other_collectors)

    def test_manual_profile_and_liquidation_have_one_non_directional_role(self):
        policy = load_scoring_policy(root=ROOT)
        profile = policy["tradingview_profile_policy"]
        self.assertEqual(profile["source_mode"], "user_drawn_manual_only")
        self.assertEqual(profile["platform_indicator_policy"], "hide_and_never_use")
        self.assertFalse(profile["automated_numeric_values_allowed"])
        self.assertFalse(profile["coinglass_substitution_allowed"])
        self.assertFalse(profile["directional_use"])
        self.assertEqual(profile["insufficient_liquidity_hunt_score"], 0)

        chart = _read("scoring/chart_methodology.md")
        self.assertIn("用户手绘成交量分布", chart)
        self.assertIn("平台内置 VRVP", chart)
        self.assertIn("清算地图只能辅助印证", chart)
        self.assertIn("不能替代手绘区域、补分或翻向", chart)

    def test_all_three_slots_are_independent(self):
        constitution = _read("constitution/trading_constitution.md")
        self.assertIn("早间盘前", constitution)
        self.assertIn("午间", constitution)
        self.assertIn("晚20:00-20:30", constitution)

        chart = _read("scoring/chart_methodology.md")
        self.assertIn("morning / midday / evening", chart)
        self.assertIn("3 次完全独立重评", chart)

        maker = _read("execution/maker_execution.md")
        self.assertIn("morning", maker)
        self.assertIn("midday", maker)
        self.assertIn("evening", maker)
        self.assertIn("完整六源", maker)


if __name__ == "__main__":
    unittest.main()
