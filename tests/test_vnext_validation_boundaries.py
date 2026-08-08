from __future__ import annotations

import ast
import unittest
from pathlib import Path

from runtime_vnext import controller, gates
from runtime_vnext.validation import common, decision, delivery, evidence, reasoning, report


ROOT = Path(__file__).resolve().parents[1]
VALIDATION_ROOT = ROOT / "runtime_vnext" / "validation"


class VNextValidationBoundaryTests(unittest.TestCase):
    def test_controller_enters_stage_owned_validators(self) -> None:
        expected = {
            controller.evaluate_evidence: evidence,
            controller.evaluate_reasoning: reasoning,
            controller.evaluate_decision: decision,
            controller.evaluate_delivery: delivery,
            controller.evaluate_shadow_delivery: delivery,
            controller.certify_report_projection_input: report,
            controller.evaluate_human_reasoning_depth: report,
            controller.evaluate_gold_template_fidelity: report,
            controller.run_compatibility_lint: report,
        }
        for function, module in expected.items():
            with self.subTest(function=function.__name__):
                self.assertEqual(function.__module__, module.__name__)

    def test_gates_is_a_stable_entrypoint_not_an_implementation_owner(self) -> None:
        path = ROOT / "runtime_vnext" / "gates.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        self.assertLessEqual(len(source.splitlines()), 300)
        locally_defined = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertFalse(
            locally_defined
            & {
                "evaluate_evidence",
                "evaluate_reasoning",
                "evaluate_decision",
                "evaluate_shadow_delivery",
                "evaluate_delivery",
            }
        )
        self.assertIs(gates.GateResult, common.GateResult)

    def test_validation_package_has_only_stage_owned_modules(self) -> None:
        self.assertEqual(
            {path.name for path in VALIDATION_ROOT.glob("*.py")},
            {
                "__init__.py",
                "common.py",
                "evidence.py",
                "reasoning.py",
                "decision.py",
                "report.py",
                "delivery.py",
            },
        )

    def test_no_transitional_legacy_delegation_remains(self) -> None:
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in VALIDATION_ROOT.glob("*.py")
        )
        for forbidden in ("LegacyDelegate", "invoke_legacy", "full_stage"):
            self.assertNotIn(forbidden, source)

    def test_report_semantic_compatibility_names_are_validation_owned(self) -> None:
        import runtime_vnext.report_compiler as compiler

        names = (
            "certify_maker_semantic_state",
            "certify_order_lifecycle",
            "order_lifecycle_display",
            "scenario_projection_policy",
            "project_scenario_audit",
            "validate_scenario_projection",
        )
        self.assertTrue(all(hasattr(report, name) for name in names))
        self.assertTrue(all(not hasattr(compiler, name) for name in names))


if __name__ == "__main__":
    unittest.main()
