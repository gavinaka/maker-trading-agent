from __future__ import annotations

import copy
import unittest

from runtime_vnext.reasoning_pipeline import (
    PIPELINE_SCHEMA_VERSION,
    PIPELINE_UNIT_FIELDS,
    UNIT_SPECS,
    build_pipeline_units,
    validate_reasoning_pipeline,
)
import tests.test_vnext_workflow as workflow_fixtures


class ReasoningMicroDagContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = workflow_fixtures.VNextWorkflowTests(
            "test_reasoning_accepts_fine_grained_orderflow_scores_through_60"
        )
        self.fixture.setUp()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def candidate(self) -> dict:
        evidence = self.fixture.evidence()
        return self.fixture.reasoning(evidence)

    @staticmethod
    def issue_codes(candidate: dict) -> set[str]:
        issues, _ = validate_reasoning_pipeline(candidate)
        return {issue.code for issue in issues}

    def test_exact_units_order_dependencies_inputs_and_coverage(self) -> None:
        candidate = self.candidate()
        issues, certification = validate_reasoning_pipeline(candidate)
        self.assertEqual(issues, [])

        units = candidate["pipeline_units"]
        expected_ids = [spec.unit_id for spec in UNIT_SPECS]
        self.assertEqual([unit["unit_id"] for unit in units], expected_ids)
        self.assertEqual([unit["sequence"] for unit in units], list(range(1, 18)))
        self.assertTrue(all(set(unit) == PIPELINE_UNIT_FIELDS for unit in units))

        owned_node_ids = [
            node_id
            for unit in units
            for node_id in unit["output_node_ids"]
        ]
        expected_node_ids = {
            str(node["id"])
            for collection in ("observations", "claims", "scenario_tree")
            for node in candidate[collection]
        }
        self.assertEqual(set(owned_node_ids), expected_node_ids)
        self.assertEqual(len(owned_node_ids), len(set(owned_node_ids)))

        by_id = {unit["unit_id"]: unit for unit in units}
        self.assertEqual(
            by_id["join.orderflow_footprint"]["depends_on_unit_ids"],
            ["source.coinglass", "source.exocharts"],
        )
        self.assertEqual(
            by_id["join.orderflow_footprint"]["input_node_ids"],
            ["obs_cg", "obs_exo"],
        )
        self.assertEqual(
            by_id["join.intraday_location"]["input_node_ids"],
            ["claim_chart", "obs_cg"],
        )
        self.assertEqual(
            by_id["join.intraday_location"]["source_scope"],
            ["Coinglass", "TradingView"],
        )
        self.assertEqual(
            by_id["maker.cannot_do_closure"]["depends_on_unit_ids"],
            ["maker.controls", "maker.thesis_score_basis"],
        )
        self.assertEqual(
            by_id["maker.cannot_do_closure"]["input_node_ids"],
            [
                "claim_counter_maker",
                "claim_invalidation_maker",
                "claim_maker",
            ],
        )
        self.assertEqual(
            certification["pipeline_schema_version"], PIPELINE_SCHEMA_VERSION
        )
        self.assertEqual(certification["pipeline_unit_count"], 17)

    def test_etf_join_requires_both_coinglass_and_farside(self) -> None:
        candidate = self.candidate()
        etf = next(
            unit
            for unit in candidate["pipeline_units"]
            if unit["unit_id"] == "join.etf_relation"
        )
        self.assertEqual(etf["source_scope"], ["Coinglass", "Farside"])
        self.assertEqual(
            etf["depends_on_unit_ids"],
            ["source.farside", "source.coinglass"],
        )
        self.assertEqual(etf["input_node_ids"], ["obs_cg", "obs_fs"])

        for field, value in (
            ("source_scope", ["Farside"]),
            ("depends_on_unit_ids", ["source.farside"]),
            ("input_node_ids", ["obs_fs"]),
        ):
            with self.subTest(field=field):
                drifted = copy.deepcopy(candidate)
                drifted_etf = next(
                    unit
                    for unit in drifted["pipeline_units"]
                    if unit["unit_id"] == "join.etf_relation"
                )
                drifted_etf[field] = value
                self.assertIn(
                    "reasoning_pipeline.unit_drift",
                    self.issue_codes(drifted),
                )

    def test_reorder_missing_future_dependency_input_and_coverage_drift_fail(self) -> None:
        candidate = self.candidate()

        reordered = copy.deepcopy(candidate)
        reordered["pipeline_units"][9], reordered["pipeline_units"][10] = (
            reordered["pipeline_units"][10],
            reordered["pipeline_units"][9],
        )
        self.assertIn("reasoning_pipeline.unit_order", self.issue_codes(reordered))

        missing = copy.deepcopy(candidate)
        missing["pipeline_units"] = [
            unit
            for unit in missing["pipeline_units"]
            if unit["unit_id"] != "join.etf_relation"
        ]
        missing_codes = self.issue_codes(missing)
        self.assertIn("reasoning_pipeline.unit_missing", missing_codes)
        self.assertIn("reasoning_pipeline.output_coverage", missing_codes)

        future = copy.deepcopy(candidate)
        fundamental = next(
            unit
            for unit in future["pipeline_units"]
            if unit["unit_id"] == "join.fundamental_context"
        )
        fundamental["depends_on_unit_ids"] = ["maker.thesis_score_basis"]
        self.assertIn(
            "reasoning_pipeline.future_dependency",
            self.issue_codes(future),
        )

        wrong_input = copy.deepcopy(candidate)
        maker_strategy = next(
            unit
            for unit in wrong_input["pipeline_units"]
            if unit["unit_id"] == "maker.thesis_score_basis"
        )
        maker_strategy["input_node_ids"] = ["claim_chart"]
        self.assertIn(
            "reasoning_pipeline.unit_drift",
            self.issue_codes(wrong_input),
        )

        uncovered = copy.deepcopy(candidate)
        source = next(
            unit
            for unit in uncovered["pipeline_units"]
            if unit["unit_id"] == "source.blockbeats"
        )
        source["output_node_ids"] = []
        self.assertIn(
            "reasoning_pipeline.output_coverage",
            self.issue_codes(uncovered),
        )

        derived_future = copy.deepcopy(candidate)
        fundamental_claim = next(
            claim
            for claim in derived_future["claims"]
            if claim["id"] == "claim_fundamental"
        )
        fundamental_claim["support_ids"].append("claim_maker")
        with self.assertRaisesRegex(ValueError, "non-prior unit"):
            build_pipeline_units(derived_future)

    def test_certification_is_deterministic_for_the_same_typed_graph(self) -> None:
        candidate = self.candidate()
        first_issues, first = validate_reasoning_pipeline(copy.deepcopy(candidate))
        second_issues, second = validate_reasoning_pipeline(copy.deepcopy(candidate))
        self.assertEqual(first_issues, [])
        self.assertEqual(second_issues, [])
        self.assertEqual(first, second)
        self.assertEqual(len(first["pipeline_sha256"]), 64)
        self.assertTrue(
            all(
                len(unit["input_sha256"]) == 64
                and len(unit["output_sha256"]) == 64
                for unit in first["pipeline_units"]
            )
        )

        changed_candidate = copy.deepcopy(candidate)
        next(
            observation
            for observation in changed_candidate["observations"]
            if observation["id"] == "obs_bb"
        )["fact"] += "（哈希绑定变更）"
        changed_issues, changed = validate_reasoning_pipeline(changed_candidate)
        self.assertEqual(changed_issues, [])
        self.assertNotEqual(changed["pipeline_sha256"], first["pipeline_sha256"])
        first_by_id = {item["unit_id"]: item for item in first["pipeline_units"]}
        changed_by_id = {
            item["unit_id"]: item for item in changed["pipeline_units"]
        }
        self.assertNotEqual(
            changed_by_id["source.blockbeats"]["output_sha256"],
            first_by_id["source.blockbeats"]["output_sha256"],
        )
        self.assertEqual(
            changed_by_id["source.fedwatch"]["output_sha256"],
            first_by_id["source.fedwatch"]["output_sha256"],
        )

    def test_reasoning_v5_rejects_report_sections_second_truth_channel(self) -> None:
        self.fixture.controller.accept_evidence(
            self.fixture.run_root,
            self.fixture.evidence(),
            evidence_files_root=self.fixture.root,
        )
        evidence = self.fixture.controller.store.load_stage_payload(
            self.fixture.run_root,
            "evidence",
            "evidence",
        )
        candidate = self.fixture.reasoning(evidence)
        candidate["report_sections"] = {
            "strategy": {
                "text": "该自由报告段试图改写类型化策略。",
                "claim_ids": ["claim_main"],
            }
        }
        result = self.fixture.evaluate_reasoning_candidate(evidence, candidate)
        self.assertFalse(result.passed)
        self.assertIn(
            "reasoning.schema_fields",
            {defect.code for defect in result.defects},
        )

    def test_reasoning_nodes_reject_extra_fields_even_when_dag_hashes_them(self) -> None:
        self.fixture.controller.accept_evidence(
            self.fixture.run_root,
            self.fixture.evidence(),
            evidence_files_root=self.fixture.root,
        )
        evidence = self.fixture.controller.store.load_stage_payload(
            self.fixture.run_root,
            "evidence",
            "evidence",
        )
        cases = (
            ("observations", 0, "observation.schema_fields"),
            ("claims", 0, "claim.schema_fields"),
            ("scenario_tree", 0, "scenario.schema_fields"),
        )
        for collection, index, expected_code in cases:
            with self.subTest(collection=collection):
                candidate = self.fixture.reasoning(evidence)
                candidate[collection][index]["extra_narrative"] = "不得被DAG认证后隐藏"
                result = self.fixture.evaluate_reasoning_candidate(evidence, candidate)
                self.assertIn(
                    expected_code,
                    {defect.code for defect in result.defects},
                )


if __name__ == "__main__":
    unittest.main()
