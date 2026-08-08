from __future__ import annotations

import json
import hashlib
import os
import re
import unittest
from decimal import Decimal
from pathlib import Path

from runtime_vnext.gates import (
    _future_trigger_clause_polarities,
    _trigger_logic_policy,
    _typed_direction_prose_issue,
    evaluate_decision,
    evaluate_evidence,
    evaluate_reasoning,
)
from runtime_vnext.controller import (
    _load_blockbeats_rows,
    _load_report_presentation_contract,
)
from runtime_vnext.domain_ir import to_plain
from runtime_vnext.plan_semantics import (
    assess_candidate,
    assess_order_lifecycle,
    cannot_do_conflicts,
    classify_evidence_polarity,
    classify_maker_semantic_state,
    expected_reach_direction,
    resting_maker_order_valid,
    structural_noise_stop_is_outside,
    structure_zone_role_valid,
)
from runtime_vnext.report_compiler import compile_projected_report
from runtime_vnext.validation.report import (
    certify_report_projection_input,
    evaluate_gold_template_fidelity,
    evaluate_human_reasoning_depth,
    run_compatibility_lint,
)


FIXTURE = Path(__file__).parent / "fixtures" / "vnext_semantic_replays.json"
ROOT = Path(__file__).parents[1]


def _json_path(payload, path: str):
    current = payload
    if not path or any(not segment for segment in path.split(".")):
        raise ValueError(f"invalid JSON path: {path}")
    for segment in path.split("."):
        match = re.fullmatch(
            r"([^\[\]]+)((?:\[(?:0|[1-9]\d*)\])*)",
            segment,
        )
        if match is None:
            raise ValueError(f"invalid JSON path: {path}")
        key = match.group(1)
        if not isinstance(current, dict) or key not in current:
            raise KeyError(path)
        current = current[key]
        for index in re.findall(r"\[(\d+)\]", match.group(2)):
            if not isinstance(current, list):
                raise KeyError(path)
            current = current[int(index)]
    return current


def _assert_extracted_equal(test: unittest.TestCase, expected, actual, mode: str):
    if mode == "exact":
        test.assertEqual(actual, expected)
    elif mode == "decimal":
        test.assertEqual(Decimal(str(actual)), Decimal(str(expected)))
    elif mode == "decimal_list":
        test.assertEqual(
            [Decimal(str(value)) for value in actual],
            [Decimal(str(value)) for value in expected],
        )
    else:
        raise AssertionError(f"unsupported extraction comparison: {mode}")


class VNextSemanticReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.cases = {
            item["case_id"]: item for item in cls.payload["cases"]
        }
        cls.reasoning_gate_cases = {
            item["case_id"]: item
            for item in cls.payload["reasoning_gate_cases"]
        }
        cls.downstream_cases = {
            item["case_id"]: item for item in cls.payload["downstream_cases"]
        }

    def test_fixture_is_hash_bound_and_closed(self) -> None:
        self.assertEqual(
            self.payload["schema_version"], "vnext-semantic-replays-v4"
        )
        self.assertEqual(
            set(self.payload),
            {
                "schema_version",
                "cases",
                "downstream_cases",
                "reasoning_gate_cases",
            },
        )
        for case in self.cases.values():
            self.assertRegex(case["source_decision_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(case["source_reasoning_sha256"], r"^[0-9a-f]{64}$")
        for case in self.reasoning_gate_cases.values():
            self.assertRegex(case["source_reasoning_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(case["source_evidence_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            set(self.downstream_cases),
            {
                "v7-non-directional",
                "v7-rejected-submitted",
                "v4-directional-compat",
            },
        )
        for case in self.downstream_cases.values():
            self.assertEqual(
                Path(case["source_run_relpath"]).name,
                case["source_run_id"],
            )
            self.assertIn(case["contract_class"], {"current", "compatibility_only"})
            self.assertFalse(case["clean_eligible"])
            for binding in case["artifacts"].values():
                self.assertEqual(set(binding), {"sha256", "bytes"})
                self.assertRegex(binding["sha256"], r"^[0-9a-f]{64}$")
                self.assertGreater(binding["bytes"], 0)

    def test_downstream_sources_are_hash_bound_and_never_mutated(self) -> None:
        require_all = os.environ.get(
            "VNEXT_REQUIRE_IMMUTABLE_REPLAY_SOURCES", "0"
        ) == "1"
        verified = 0
        missing: list[str] = []
        for case in self.downstream_cases.values():
            run_root = ROOT / case["source_run_relpath"]
            for relative, binding in case["artifacts"].items():
                path = run_root / relative
                if not path.is_file():
                    missing.append(path.as_posix())
                    continue
                preimage = path.read_bytes()
                self.assertEqual(len(preimage), binding["bytes"])
                self.assertEqual(
                    hashlib.sha256(preimage).hexdigest(),
                    binding["sha256"],
                )
                self.assertEqual(path.read_bytes(), preimage)
                self.assertEqual(
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                    binding["sha256"],
                )
                verified += 1
        if missing and require_all:
            self.fail("required immutable replay sources are missing: " + ", ".join(missing))
        if verified == 0:
            self.skipTest("immutable downstream replay sources are not present")
        self.assertFalse(missing)
        self.assertEqual(
            verified,
            sum(len(case["artifacts"]) for case in self.downstream_cases.values()),
        )

    def test_current_downstream_cases_replay_through_pure_report_projection(self) -> None:
        current_cases = {
            case_id: case
            for case_id, case in self.downstream_cases.items()
            if case["contract_class"] == "current"
        }
        self.assertEqual(
            set(current_cases),
            {"v7-non-directional", "v7-rejected-submitted"},
        )
        presentation_contract, presentation_contract_sha256 = (
            _load_report_presentation_contract(ROOT)
        )
        for case in current_cases.values():
            with self.subTest(case=case["case_id"]):
                run_root = ROOT / case["source_run_relpath"]
                preimages = {
                    relative: (run_root / relative).read_bytes()
                    for relative in case["artifacts"]
                }
                run = json.loads(preimages["run.json"].decode("utf-8"))
                evidence = json.loads(
                    preimages["evidence/attempt-001/evidence.json"].decode("utf-8")
                )
                reasoning = json.loads(
                    preimages["reasoning/attempt-001/reasoning.json"].decode("utf-8")
                )
                decision = json.loads(
                    preimages["decision/attempt-001/decision.json"].decode("utf-8")
                )
                methodology = json.loads(
                    preimages["methodology_manifest.json"].decode("utf-8")
                )

                evidence_result = evaluate_evidence(evidence, root=ROOT)
                reasoning_result = evaluate_reasoning(
                    reasoning,
                    evidence=evidence,
                    reasoning_authority_sha256=reasoning[
                        "reasoning_authority_sha256"
                    ],
                    evidence_root=ROOT,
                    methodology_root=ROOT,
                )
                decision_result = evaluate_decision(
                    decision,
                    reasoning=reasoning,
                    run=run,
                    pretrade_gate=None,
                    root=ROOT,
                )

                for result in (
                    evidence_result,
                    reasoning_result,
                    decision_result,
                ):
                    self.assertTrue(
                        result.passed,
                        [(defect.code, defect.path) for defect in result.defects],
                    )
                certified_source = certify_report_projection_input(
                    evidence=evidence,
                    reasoning=reasoning,
                    decision=decision,
                    blockbeats_rows=_load_blockbeats_rows(ROOT, evidence),
                    presentation_contract=presentation_contract,
                    presentation_contract_sha256=(
                        presentation_contract_sha256
                    ),
                    methodology_sha256=(
                        methodology["phases"]["reasoning"]["phase_sha256"]
                    ),
                    report_contract_sha256=(
                        methodology["phases"]["report"]["phase_sha256"]
                    ),
                )
                projected = compile_projected_report(
                    certified_source,
                    presentation_contract,
                )
                model = to_plain(projected.model)
                self.assertIsInstance(model, dict)
                audit = model["audit"]
                self.assertEqual(
                    set(audit["sources"]),
                    {
                        "BlockBeats",
                        "Coinglass",
                        "Exocharts",
                        "FedWatch",
                        "Farside",
                        "TradingView",
                    },
                )
                self.assertTrue(audit["proof_chains"])
                self.assertEqual(len(audit["reasoning_proof_blocks"]), 10)
                self.assertEqual(audit["main_plan"], decision["main_account"])
                self.assertEqual(audit["maker_decision"], decision["maker"])
                self.assertEqual(
                    audit["risk_values_owner"],
                    "certified_decision_direct_copy",
                )
                self.assertEqual(
                    model["maker_summary"]["semantic_state"],
                    case["expected_semantic_state"],
                )
                shadow_prefix = {
                    "qualified_candidate": "影子候选计划",
                    "rejected_submitted_candidate": "影子被拒候选审计状态",
                    "directional_thesis_only": "影子方向观察状态",
                    "non_directional_observation": "影子无方向观察状态",
                }[case["expected_semantic_state"]]
                expected_authorization = f"{shadow_prefix}；未读取个人持仓/订单状态；未创建、撤销或挂出真实订单"
                self.assertEqual(model["frontstage"]["maker_authorization"], expected_authorization)
                self.assertIn(expected_authorization, projected.markdown)
                for marker in (
                    "## ① 正文",
                    "## 不能做",
                    "## ② Maker 计划",
                    "## ③ 后附",
                    "主账户",
                    "Maker",
                    "反证",
                    "失效",
                ):
                    self.assertIn(marker, projected.markdown)
                self.assertTrue(
                    evaluate_human_reasoning_depth(
                        model,
                        contract=presentation_contract,
                    )["passed"]
                )
                self.assertTrue(
                    evaluate_gold_template_fidelity(
                        projected.markdown,
                        contract=presentation_contract,
                    )["passed"]
                )
                lint_result = run_compatibility_lint(
                    projected.markdown,
                    report_filename=(
                        f"{decision['trading_date']}_{decision['slot']}_combined.md"
                    ),
                    trading_date=decision["trading_date"],
                    slot=decision["slot"],
                )
                self.assertTrue(lint_result["passed"], lint_result)

                if case["case_id"] == "v7-non-directional":
                    maker = decision["maker"]
                    self.assertEqual(maker["risk_plan"], {})
                    self.assertIsNone(
                        maker["entry_reach_probability_basis"]["reference_entry"]
                    )
                    self.assertIn("本轮无方向观察", projected.markdown)
                    self.assertIn("未提交候选计划", projected.markdown)
                    self.assertIn(
                        "用户手绘成交量分布本轮证据不足且不可读",
                        projected.markdown,
                    )
                    reference_price = str(
                        maker["entry_reach_probability_basis"]["reference_price"]
                    )
                    for ghost in (
                        f"入场{reference_price}",
                        f"止损{reference_price}",
                        f"未成交取消位：{reference_price}",
                    ):
                        self.assertNotIn(ghost, projected.markdown)

                if case["case_id"] == "v7-rejected-submitted":
                    self.assertIn(
                        "用户手绘成交量分布可读：1D价值区61500–64400",
                        projected.markdown,
                    )
                    self.assertIn(
                        "已提交候选未通过认证，不可执行",
                        projected.markdown,
                    )
                    self.assertIn(
                        "risk_math_invalid",
                        audit["maker_decision"]["plan_constructibility"][
                            "failure_codes"
                        ],
                    )
                    self.assertEqual(
                        audit["risk_plan"]["candidate_status"],
                        "rejected_not_executable",
                    )
                    self.assertIn("仅用于审计", projected.markdown)
                    for executable_surface in (
                        "Maker风险计划：入场",
                        "未成交取消位：",
                        "执行合同：",
                    ):
                        self.assertNotIn(executable_surface, projected.markdown)
                    historical_failure = json.loads(
                        preimages["report/attempt-001/failure.json"].decode(
                            "utf-8"
                        )
                    )
                    self.assertIn(
                        "流动性读位门",
                        historical_failure["defects"][0]["message"],
                    )
                    self.assertNotIn("流动性读位门", lint_result["output"])

                for relative, preimage in preimages.items():
                    self.assertEqual((run_root / relative).read_bytes(), preimage)

    def test_legacy_directional_delivery_remains_compatibility_only(self) -> None:
        case = self.downstream_cases["v4-directional-compat"]
        self.assertEqual(case["contract_class"], "compatibility_only")
        self.assertFalse(case["clean_eligible"])
        run_root = ROOT / case["source_run_relpath"]
        preimages = {
            relative: (run_root / relative).read_bytes()
            for relative in case["artifacts"]
        }
        decision = json.loads(
            preimages["decision/attempt-001/decision.json"].decode("utf-8")
        )
        maker = decision["maker"]
        with self.assertRaisesRegex(ValueError, "candidate-only fields"):
            classify_maker_semantic_state(
                plan_state=maker.get("plan_state"),
                direction=maker.get("direction"),
                plan_constructible=maker.get("plan_constructible"),
                threshold_eligible=maker.get("threshold_eligible"),
                risk_plan=maker.get("risk_plan"),
                defense_plan=maker.get("defense_plan"),
                position_notional_usdt=maker.get("position_notional_usdt"),
                entry_type=maker.get("entry_type"),
                order_lifecycle_state=(maker.get("order_lifecycle") or {}).get(
                    "state"
                ),
                entry_reach_probability_applicability=(
                    maker.get("entry_reach_probability_basis") or {}
                ).get("applicability"),
                constructibility_reason=(
                    maker.get("plan_constructibility") or {}
                ).get("primary_reason_code"),
            )
        persisted_model = json.loads(
            (run_root / "report/attempt-001/canonical_report.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(persisted_model["main_summary"]["direction"], "short")
        self.assertFalse(persisted_model["maker_summary"]["plan_constructible"])
        word_qa = json.loads(
            (run_root / "delivery_assets/word_qa.json").read_text(encoding="utf-8")
        )
        self.assertEqual(word_qa["status"], "passed")
        self.assertTrue(word_qa["visual_qa_pass"])
        for relative, preimage in preimages.items():
            self.assertEqual((run_root / relative).read_bytes(), preimage)

    def test_json_path_parser_rejects_partial_or_malformed_paths(self) -> None:
        payload = {"maker": {"direction": "long", "rows": [{"value": 1}]}}
        self.assertEqual(_json_path(payload, "maker.direction"), "long")
        self.assertEqual(_json_path(payload, "maker.rows[0].value"), 1)
        for path in (
            "maker..direction",
            "maker.direction.",
            ".maker.direction",
            "maker.rows[01].value",
            "maker.rows[abc].value",
            "maker.direction trailing",
        ):
            with self.subTest(path=path):
                with self.assertRaises((KeyError, ValueError)):
                    _json_path(payload, path)

    def test_source_hashes_match_immutable_artifacts_when_available(self) -> None:
        verified = 0
        for case in self.cases.values():
            for kind in ("decision", "reasoning"):
                path = ROOT / case[f"source_{kind}_relpath"]
                if not path.is_file():
                    continue
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                self.assertEqual(digest, case[f"source_{kind}_sha256"])
                verified += 1
        if verified == 0:
            self.skipTest("immutable source run artifacts are not present")
        self.assertEqual(verified, 2 * len(self.cases))

    def test_fixture_values_are_mechanically_extracted_from_bound_artifacts(self) -> None:
        verified = 0
        for case in self.cases.values():
            artifacts = {}
            for kind in ("decision", "reasoning"):
                path = ROOT / case[f"source_{kind}_relpath"]
                if path.is_file():
                    artifacts[kind] = json.loads(path.read_text(encoding="utf-8"))
            if len(artifacts) != 2:
                continue
            for extraction in case.get("source_extractions", []):
                expected = _json_path(case, extraction["fixture_path"])
                actual = _json_path(
                    artifacts[extraction["artifact"]], extraction["json_path"]
                )
                _assert_extracted_equal(
                    self,
                    expected,
                    actual,
                    extraction["comparison"],
                )
                verified += 1
            for absence in case.get("source_absences", []):
                with self.assertRaises(KeyError):
                    _json_path(
                        artifacts[absence["artifact"]], absence["json_path"]
                    )
                verified += 1
        if verified == 0:
            self.skipTest("immutable source run artifacts are not present")
        self.assertEqual(
            verified,
            sum(
                len(case.get("source_extractions", []))
                + len(case.get("source_absences", []))
                for case in self.cases.values()
            ),
        )

    def test_historical_v4_rejected_reasoning_is_hash_bound_and_read_only(
        self,
    ) -> None:
        case = self.reasoning_gate_cases[
            "a5-r2-replacement-01-rejected-reasoning"
        ]
        path = ROOT / case["source_reasoning_relpath"]
        evidence_path = ROOT / case["source_evidence_relpath"]
        if not path.is_file() or not evidence_path.is_file():
            self.skipTest("immutable rejected reasoning artifact is not present")
        reasoning_preimage = path.read_bytes()
        evidence_preimage = evidence_path.read_bytes()
        self.assertEqual(
            hashlib.sha256(reasoning_preimage).hexdigest(),
            case["source_reasoning_sha256"],
        )
        self.assertEqual(
            hashlib.sha256(evidence_preimage).hexdigest(),
            case["source_evidence_sha256"],
        )
        artifact = json.loads(reasoning_preimage.decode("utf-8"))
        self.assertEqual(artifact["schema_version"], "reasoning-model-v4")
        self.assertEqual(path.name, "rejected.json")
        self.assertIn("condition", artifact["scenario_tree"][0])
        self.assertIn("claim_ids", artifact["scenario_tree"][0])
        self.assertNotIn("owner_claim_id", artifact["scenario_tree"][0])
        current_contract = json.loads(
            (ROOT / "scoring" / "reasoning_submission_contract.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            current_contract["certified_schema_version"],
            "reasoning-model-v5",
        )
        for extraction in case["source_extractions"]:
            _assert_extracted_equal(
                self,
                _json_path(case, extraction["fixture_path"]),
                _json_path(artifact, extraction["json_path"]),
                extraction["comparison"],
            )
        self.assertEqual(
            hashlib.sha256(path.read_bytes()).hexdigest(),
            case["source_reasoning_sha256"],
        )
        self.assertEqual(
            hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
            case["source_evidence_sha256"],
        )
        self.assertEqual(path.read_bytes(), reasoning_preimage)
        self.assertEqual(evidence_path.read_bytes(), evidence_preimage)

    def test_a5r2_replay_separates_direction_mechanism_from_trigger_polarity(
        self,
    ) -> None:
        case = self.reasoning_gate_cases[
            "a5-r2-replacement-01-rejected-reasoning"
        ]
        orderflow = case["orderflow"]
        self.assertEqual(
            _typed_direction_prose_issue(
                orderflow["conclusion"],
                orderflow["direction"],
                claim_type=orderflow["claim_type"],
            ),
            case["expected_direction_issue"],
        )

        metadata = {"clause_targets": []}
        for index, clause in enumerate(case["main_counter_trigger"]["clauses"]):
            metadata["clause_targets"].append(
                {
                    "index": index,
                    "owner_type": clause["owner_type"],
                    "owner_id": clause["owner_id"],
                    "source": clause.get("source", ""),
                    "owner_claim_type": clause.get("owner_claim_type", ""),
                    "field": clause["field"],
                    "operator": clause["operator"],
                    "targets": [clause["value"]],
                }
            )
        policy = _trigger_logic_policy(ROOT)
        polarities = _future_trigger_clause_polarities(
            metadata,
            mode=case["main_counter_trigger"]["mode"],
            trigger_policy=policy,
        )
        self.assertEqual(
            [sorted(item["directions"]) for item in polarities],
            case["expected_trigger_clause_directions"],
        )
        self.assertEqual(case["main_thesis_direction"], "neutral")
        scenario_policy = policy["scenario_control_binding"]
        self.assertEqual(
            scenario_policy["ownership_contract_schema_version"],
            "scenario-ownership-v1",
        )
        self.assertFalse(scenario_policy["producer_free_prose_allowed"])
        self.assertNotIn("condition_sentinel", scenario_policy)
        self.assertIn("condition", case["main_counter_scenario"])
        self.assertIn("claim_ids", case["main_counter_scenario"])
        self.assertEqual(
            case["expected_trigger_defect"],
            "claim.trigger_any_clause_not_counter",
        )
        self.assertEqual(
            case["expected_scenario_defect"],
            "scenario.trigger_condition_second_truth",
        )

    def test_a5_short_replay_exposes_every_pre_risk_failure(self) -> None:
        case = self.cases["a5-fresh-01-short-below-market"]
        reference = Decimal(case["reference_price"])
        entries = tuple(Decimal(value) for value in case["entries"])
        resting = resting_maker_order_valid(
            direction=case["direction"],
            reference_price=reference,
            entries=entries,
        )
        lifecycle = assess_order_lifecycle(
            reference_price=reference,
            cancel_price=Decimal(case["cancel_before_fill"]),
            entries=entries,
        )
        failed = set()
        if not structure_zone_role_valid(
            direction=case["direction"],
            zone_kind="structure_zone",
            zone_role=case["zone_role"],
            allowed_roles={
                "short": ("resistance", "breakdown_retest"),
                "long": ("support", "breakout_retest"),
            },
        ):
            failed.add("entry_zone_role_invalid")
        if not resting:
            failed.add("maker_order_marketable")
        if expected_reach_direction(reference, entries[0]) != "up_to_entry":
            failed.add("entry_semantics_invalid")
        if cannot_do_conflicts(
            cannot_do_code=case["cannot_do_code"],
            direction=case["direction"],
            entry_type="left",
            resting_order_valid=resting,
        ):
            failed.add("cannot_do_conflict")
        if lifecycle.state != "fillable":
            failed.add("order_lifecycle_invalid")
        assessment = assess_candidate(failed_checks=failed)
        self.assertEqual(lifecycle.state, case["expected_lifecycle_state"])
        self.assertEqual(list(assessment.failure_codes), case["expected_failures"])

    def test_a5r1i_replay_rejects_cancel_preemption_and_counter_padding(self) -> None:
        case = self.cases["a5-r1i-long-cancel-preempts-fill"]
        lifecycle = assess_order_lifecycle(
            reference_price=Decimal(case["reference_price"]),
            cancel_price=Decimal(case["cancel_before_fill"]),
            entries=tuple(Decimal(value) for value in case["entries"]),
        )
        effects = [
            classify_evidence_polarity(
                subject_direction=case["direction"],
                evidence_direction=evidence_direction,
            ).effect
            for evidence_direction in case["strongest_counter_evidence_directions"]
        ]
        self.assertEqual(lifecycle.state, case["expected_lifecycle_state"])
        self.assertEqual(effects, case["expected_counter_effects"])
        self.assertFalse(all(effect == "counter" for effect in effects))

    def test_a5r1i_positive_buffer_without_visual_boundary_is_not_certified(self) -> None:
        noise = self.cases["a5-r1i-long-cancel-preempts-fill"][
            "structural_noise"
        ]
        certified = structural_noise_stop_is_outside(
            direction="long",
            anchor_price=None,
            noise_outer_boundary=None,
            price_distance=Decimal(noise["price_distance"]),
        )
        self.assertIs(certified, noise["expected_certified"])

    def test_noise_sufficiency_is_evidence_based_not_fixed_distance(self) -> None:
        self.assertTrue(
            structural_noise_stop_is_outside(
                direction="long",
                anchor_price=Decimal("100"),
                noise_outer_boundary=Decimal("99.9"),
                price_distance=Decimal("0.2"),
            )
        )
        self.assertFalse(
            structural_noise_stop_is_outside(
                direction="short",
                anchor_price=Decimal("100"),
                noise_outer_boundary=Decimal("500"),
                price_distance=Decimal("180"),
            )
        )


if __name__ == "__main__":
    unittest.main()
