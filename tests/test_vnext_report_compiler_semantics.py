from __future__ import annotations

import ast
import inspect
import json
import unittest
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from runtime_vnext.controller import (
    _load_blockbeats_rows,
    _load_report_presentation_contract,
)
from runtime_vnext.domain_ir import CertifiedReportProjectionInput, to_plain
from runtime_vnext.report_compiler import compile_projected_report
from runtime_vnext.validation.report import (
    certify_report_projection_input,
    evaluate_gold_template_fidelity,
    evaluate_human_reasoning_depth,
    run_compatibility_lint,
)
from tests import test_vnext_workflow as workflow_tests


ROOT = Path(__file__).resolve().parents[1]
COMPILER_PATH = ROOT / "runtime_vnext" / "report_compiler.py"


class VNextReportCompilerSemanticsTests(unittest.TestCase):
    def setUp(self) -> None:
        # Import the module, not the TestCase class, so unittest does not
        # rediscover the entire workflow suite through this focused module.
        self.fixture = workflow_tests.VNextWorkflowTests(
            methodName="test_shadow_decision_never_loads_pretrade_and_keeps_full_qualified_plan"
        )
        self.fixture.setUp()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def certified_source(
        self,
        *,
        decision_mutator: Callable[[dict], None] | None = None,
    ) -> tuple[CertifiedReportProjectionInput, dict]:
        self.fixture.prepare_through_decision()
        controller = self.fixture.controller
        evidence = controller.store.load_stage_payload(
            self.fixture.run_root, "evidence", "evidence"
        )
        reasoning = controller.store.load_stage_payload(
            self.fixture.run_root, "reasoning", "reasoning"
        )
        decision = controller.store.load_stage_payload(
            self.fixture.run_root, "decision", "decision"
        )
        if decision_mutator is not None:
            decision_mutator(decision)
        methodology = json.loads(
            (self.fixture.run_root / "methodology_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        contract, contract_sha256 = _load_report_presentation_contract(
            self.fixture.root
        )
        source = certify_report_projection_input(
            evidence=evidence,
            reasoning=reasoning,
            decision=decision,
            blockbeats_rows=_load_blockbeats_rows(self.fixture.root, evidence),
            presentation_contract=contract,
            presentation_contract_sha256=contract_sha256,
            methodology_sha256=methodology["phases"]["reasoning"]["phase_sha256"],
            report_contract_sha256=methodology["phases"]["report"]["phase_sha256"],
        )
        return source, contract

    def test_compiler_is_a_pure_typed_projection_boundary(self) -> None:
        tree = ast.parse(COMPILER_PATH.read_text(encoding="utf-8"))
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        banned = {
            "json",
            "os",
            "pathlib",
            "subprocess",
            "runtime_vnext.validation.report",
            "runtime_vnext.gates",
            "runtime_vnext.methodology",
        }
        self.assertFalse(
            {
                name
                for name in imports
                if name in banned
                or any(name.startswith(prefix + ".") for prefix in banned)
            }
        )
        called_attributes = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertFalse(
            called_attributes
            & {"read_text", "read_bytes", "write_text", "write_bytes", "run", "Popen"}
        )
        signature = inspect.signature(compile_projected_report)
        self.assertEqual(tuple(signature.parameters), ("source", "display_projection"))
        self.assertEqual(
            signature.parameters["source"].annotation,
            "CertifiedReportProjectionInput",
        )

    def test_projection_is_deterministic_and_in_memory(self) -> None:
        source, contract = self.certified_source()
        first = compile_projected_report(source, contract)
        second = compile_projected_report(source, contract)
        self.assertEqual(to_plain(first.model), to_plain(second.model))
        self.assertEqual(first.markdown, second.markdown)
        self.assertEqual(to_plain(first.cards_spec), to_plain(second.cards_spec))

    def test_compiler_does_not_reinterpret_certified_frontstage_from_run_mode(self) -> None:
        source, contract = self.certified_source()
        changed_metadata = replace(source.metadata, run_mode="production")
        changed_source = replace(source, metadata=changed_metadata)
        baseline = compile_projected_report(source, contract)
        changed = compile_projected_report(changed_source, contract)
        self.assertEqual(baseline.markdown, changed.markdown)
        baseline_model = to_plain(baseline.model)
        changed_model = to_plain(changed.model)
        for section in ("frontstage", "main_summary", "maker_summary", "audit"):
            self.assertEqual(baseline_model[section], changed_model[section])

    def test_projection_preserves_six_sources_and_support_dag(self) -> None:
        source, contract = self.certified_source()
        model = to_plain(compile_projected_report(source, contract).model)
        self.assertIsInstance(model, dict)
        audit = model["audit"]
        self.assertEqual(
            set(audit["sources"]),
            {"BlockBeats", "Coinglass", "Exocharts", "FedWatch", "Farside", "TradingView"},
        )
        self.assertTrue(audit["proof_chains"])
        self.assertEqual(len(audit["reasoning_proof_blocks"]), 10)

    def test_main_and_maker_risk_values_are_direct_decision_copies(self) -> None:
        source, contract = self.certified_source()
        model = to_plain(compile_projected_report(source, contract).model)
        decision = self.fixture.controller.store.load_stage_payload(
            self.fixture.run_root, "decision", "decision"
        )
        self.assertEqual(model["audit"]["main_plan"], decision["main_account"])
        self.assertEqual(model["audit"]["maker_decision"], decision["maker"])
        self.assertEqual(
            model["audit"]["risk_values_owner"],
            "certified_decision_direct_copy",
        )

    def test_blockbeats_cards_copy_the_hash_bound_selected_rows(self) -> None:
        source, contract = self.certified_source()
        cards_spec = to_plain(compile_projected_report(source, contract).cards_spec)
        evidence = self.fixture.controller.store.load_stage_payload(
            self.fixture.run_root, "evidence", "evidence"
        )
        selected = _load_blockbeats_rows(self.fixture.root, evidence)
        cards = cards_spec["cards"]
        self.assertEqual(len(cards), len(selected))
        for card, row in zip(cards, selected, strict=True):
            self.assertEqual(card["time"], row["time"])
            self.assertEqual(card["title"], row["title"])
            self.assertEqual(card["body"], row["body"])

    def test_chinese_report_closes_both_accounts_and_passes_quality_checks(self) -> None:
        source, contract = self.certified_source()
        projected = compile_projected_report(source, contract)
        model = to_plain(projected.model)
        markdown = projected.markdown
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
            self.assertIn(marker, markdown)
        self.assertTrue(
            evaluate_human_reasoning_depth(model, contract=contract)["passed"]
        )
        self.assertTrue(
            evaluate_gold_template_fidelity(markdown, contract=contract)["passed"]
        )
        self.assertTrue(
            run_compatibility_lint(
                markdown,
                report_filename=(
                    f"{self.fixture.date}_{self.fixture.slot}_combined.md"
                ),
                trading_date=self.fixture.date,
                slot=self.fixture.slot,
            )["passed"]
        )

    def test_shadow_qualified_plan_separates_plan_and_execution_authority(self) -> None:
        source, contract = self.certified_source()
        projected = compile_projected_report(source, contract)
        frontstage = to_plain(projected.model)["frontstage"]
        self.assertEqual(frontstage["main_authorization"], "影子候选主账户计划；未读取或改变真实持仓，未尝试任何真实执行。")
        self.assertEqual(frontstage["maker_authorization"], "影子候选计划；未读取个人持仓/订单状态；未创建、撤销或挂出真实订单")
        self.assertEqual(frontstage["maker_execution"], "候选计划已通过认证；计划结论成立，真实执行资格另由 execution_authorization 决定。")
        self.assertEqual(frontstage["maker_execution_status"], "真实执行状态：未尝试真实执行")
        for value in (frontstage["maker_execution"], frontstage["maker_execution_status"], frontstage["maker_authorization"]):
            self.assertIn(value, projected.markdown)
        self.assertNotIn("可按已认证计划执行", projected.markdown)

    def test_shadow_main_observe_authorization_is_not_promoted_to_candidate(self) -> None:
        source, contract = self.certified_source(
            decision_mutator=lambda decision: decision["main_account"].update(
                {"plan_state": "observe", "action": "observe"}
            )
        )
        projected = compile_projected_report(source, contract)
        authorization = to_plain(projected.model)["frontstage"]["main_authorization"]
        self.assertEqual(authorization, "影子主账户观察状态；未读取或改变真实持仓，未生成计划且未尝试任何真实执行。")
        self.assertNotIn("影子候选主账户计划", authorization)

    def test_compiler_rejects_untyped_raw_stage_input(self) -> None:
        _, contract = self.certified_source()
        with self.assertRaises((TypeError, AttributeError)):
            compile_projected_report(  # type: ignore[arg-type]
                {"evidence": {}, "reasoning": {}, "decision": {}},
                contract,
            )

    def test_rejected_submitted_typed_tuple_keeps_exact_failure_reasons(self) -> None:
        failure_codes = ["maker_order_marketable", "order_lifecycle_invalid"]

        def reject_candidate(decision: dict) -> None:
            maker = decision["maker"]
            maker.update(
                {
                    "semantic_state": None,
                    "plan_state": "observe",
                    "threshold_eligible": False,
                    "plan_constructible": False,
                    "execution_action": "not_attempted",
                    "order_transition_action": "not_attempted",
                }
            )
            maker["plan_constructibility"].update(
                {
                    "status": "not_constructible",
                    "primary_reason_code": failure_codes[0],
                    "failure_codes": failure_codes,
                }
            )

        source, contract = self.certified_source(
            decision_mutator=reject_candidate
        )
        projected = compile_projected_report(source, contract)
        model = to_plain(projected.model)
        sentence = model["frontstage"]["maker_execution"]
        typed_codes = model["audit"]["maker_decision"][
            "plan_constructibility"
        ]["failure_codes"]

        self.assertEqual(typed_codes, failure_codes)
        self.assertIn("已提交候选未通过认证，不可执行", sentence)
        self.assertIn("候选限价位于会立即成交或穿越现价的一侧", sentence)
        self.assertIn("候选订单没有同时满足可成交路径与成交前撤单路径", sentence)
        self.assertNotIn("认证条件未闭合", sentence)
        self.assertEqual(model["frontstage"]["maker_authorization"], "影子被拒候选审计状态；未读取个人持仓/订单状态；未创建、撤销或挂出真实订单")
        self.assertNotIn("### BTC（被拒候选审计）", projected.markdown)
        self.assertIn("### BTC（未通过认证）", projected.markdown)
        frontstage, appendix_d = projected.markdown.split(
            "### D. 风险、情景与机械校验", maxsplit=1
        )
        self.assertNotIn("订单生命周期：", frontstage)
        self.assertNotIn("候选名义持仓750", frontstage)
        self.assertNotIn("入场99.8、100", frontstage)
        self.assertIn("被拒候选参数审计（不可执行，不得用于下单）", appendix_d)
        self.assertIn("候选名义持仓750", appendix_d)
        self.assertIn("入场99.8、100", appendix_d)
        self.assertIn("被拒候选订单生命周期审计（不可执行，不得用于下单）", appendix_d)
        self.assertIn("存在合法入场路径", appendix_d)
        for line in appendix_d.splitlines():
            if "被拒候选风险情景（审计）" in line:
                self.assertIn("不可执行，不得用于下单", line)

    def test_directional_thesis_only_has_exact_shadow_authorization_and_no_plan_numbers(self) -> None:
        def keep_thesis_without_candidate(decision: dict) -> None:
            maker = decision["maker"]
            maker.update({"semantic_state": None, "plan_state": "observe", "risk_plan": {}, "defense_plan": {}, "plan_constructible": False, "execution_action": "not_attempted", "order_transition_action": "not_attempted", "position_notional_usdt": None, "entry_type": "not_applicable", "entry_zone_basis": None, "entry_reach_probability": None})
            maker["entry_reach_probability_basis"].update({"applicability": "not_applicable_no_certified_entry_geometry", "reference_entry": None, "entry_distance": None, "reach_direction": None})
            maker["order_lifecycle"] = {"schema_version": "maker-order-lifecycle-v1", "state": "not_applicable_no_candidate_geometry", "legal_fill_path_exists": False, "legal_cancel_path_exists": False, "fill_probability": None, "fill_probability_applicability": "not_applicable_no_candidate_geometry", "reason_code": "not_applicable_no_candidate_geometry"}
            maker["plan_constructibility"].update({"status": "not_constructible", "primary_reason_code": "no_certified_entry_zone", "failure_codes": ["no_certified_entry_zone"]})

        source, contract = self.certified_source(decision_mutator=keep_thesis_without_candidate)
        projected = compile_projected_report(source, contract)
        model = to_plain(projected.model)
        self.assertEqual(model["maker_summary"]["semantic_state"], "directional_thesis_only")
        self.assertEqual(model["frontstage"]["maker_authorization"], "影子方向观察状态；未读取个人持仓/订单状态；未创建、撤销或挂出真实订单")
        self.assertIn("未提交候选计划", projected.markdown)
        self.assertNotIn("Maker风险计划：入场区间", projected.markdown)


if __name__ == "__main__":
    unittest.main()
