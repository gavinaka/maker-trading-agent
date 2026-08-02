from __future__ import annotations

import ast
import unittest
from pathlib import Path

from runtime_vnext import controller
import runtime_vnext.report_compiler as report_compiler
from runtime_vnext.validation import (
    claim_graph,
    decision_main,
    decision_maker,
    delivery,
    evidence,
    reasoning_semantics,
    reasoning_shape,
    report_quality,
    report_semantics,
    risk_math,
)
from runtime_vnext.validation.common import LegacyDelegate, legacy_callable


class VNextValidationBoundaryTests(unittest.TestCase):
    def test_report_scenario_and_lifecycle_certifiers_are_validation_owned(self) -> None:
        compatibility_names = (
            "_maker_semantic_state",
            "_typed_order_lifecycle",
            "_order_lifecycle_display",
            "_scenario_projection_policy",
            "_scenario_audit",
            "_validate_scenario_projection",
        )
        self.assertTrue(
            all(
                getattr(report_compiler, name).__module__
                == "runtime_vnext.validation.report_semantics"
                for name in compatibility_names
            )
        )

        compiler_path = (
            Path(__file__).resolve().parents[1]
            / "runtime_vnext"
            / "report_compiler.py"
        )
        compiler_source = compiler_path.read_text(encoding="utf-8")
        tree = ast.parse(compiler_source)
        locally_defined = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertFalse(set(compatibility_names) & locally_defined)
        for former_owner_literal in (
            "not_estimated_lifecycle_only",
            "撤单价会先于所有入场档触发，订单没有可成交路径",
            "retain_certified_assessment",
            "scenario_main_base",
        ):
            self.assertNotIn(former_owner_literal, compiler_source)

        semantic_path = (
            Path(__file__).resolve().parents[1]
            / "runtime_vnext"
            / "validation"
            / "report_semantics.py"
        )
        semantic_tree = ast.parse(semantic_path.read_text(encoding="utf-8"))
        imported_modules = {
            node.module
            for node in ast.walk(semantic_tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        self.assertNotIn("runtime_vnext.report_compiler", imported_modules)
        self.assertNotIn("report_compiler", imported_modules)

    def test_controller_enters_the_four_stage_facades(self) -> None:
        self.assertEqual(
            controller.evaluate_evidence.__module__,
            "runtime_vnext.validation.evidence",
        )
        self.assertEqual(
            controller.evaluate_reasoning.__module__,
            "runtime_vnext.validation.reasoning_shape",
        )
        self.assertEqual(
            controller.evaluate_decision.__module__,
            "runtime_vnext.validation.decision_main",
        )
        self.assertEqual(
            controller.evaluate_delivery.__module__,
            "runtime_vnext.validation.delivery",
        )
        self.assertEqual(
            controller.evaluate_shadow_delivery.__module__,
            "runtime_vnext.validation.delivery",
        )

    def test_report_quality_is_not_owned_by_the_projector_entrypoint(self) -> None:
        self.assertEqual(
            controller.evaluate_human_reasoning_depth.__module__,
            "runtime_vnext.validation.report_quality",
        )
        self.assertEqual(
            controller.evaluate_gold_template_fidelity.__module__,
            "runtime_vnext.validation.report_quality",
        )
        self.assertEqual(
            controller.run_compatibility_lint.__module__,
            "runtime_vnext.validation.report_quality",
        )

    def test_every_declared_legacy_delegate_is_explicit_and_callable(self) -> None:
        delegates: list[LegacyDelegate] = [
            evidence.LEGACY_GATE_DELEGATE,
            evidence.LEGACY_VISUAL_DELEGATE,
            evidence.LEGACY_PROFILE_DELEGATE,
            reasoning_shape.LEGACY_DELEGATE,
            reasoning_semantics.LEGACY_DELEGATE,
            claim_graph.LEGACY_DELEGATE,
            decision_main.LEGACY_DELEGATE,
            decision_maker.LEGACY_DELEGATE,
            risk_math.LEGACY_DELEGATE,
            report_quality.LEGACY_REASONING_DEPTH_DELEGATE,
            report_quality.LEGACY_TEMPLATE_FIDELITY_DELEGATE,
            report_quality.LEGACY_COMPATIBILITY_LINT_DELEGATE,
            delivery.LEGACY_SHADOW_DELEGATE,
            delivery.LEGACY_PRODUCTION_DELEGATE,
        ]
        self.assertEqual(len(delegates), 14)
        for delegate in delegates:
            with self.subTest(stage=delegate.stage, domain=delegate.domain):
                self.assertIn(delegate.coverage, {"domain", "full_stage", "projection"})
                self.assertTrue(callable(legacy_callable(delegate)))

    def test_domain_facades_do_not_claim_partial_defect_filtering(self) -> None:
        full_stage = {
            reasoning_shape.LEGACY_DELEGATE,
            claim_graph.LEGACY_DELEGATE,
            decision_main.LEGACY_DELEGATE,
            decision_maker.LEGACY_DELEGATE,
            risk_math.LEGACY_DELEGATE,
        }
        self.assertTrue(all(item.coverage == "full_stage" for item in full_stage))


if __name__ == "__main__":
    unittest.main()
