from __future__ import annotations

import unittest

from runtime_vnext import controller
from runtime_vnext.validation import (
    claim_graph,
    decision_main,
    decision_maker,
    delivery,
    evidence,
    reasoning_semantics,
    reasoning_shape,
    report_quality,
    risk_math,
)
from runtime_vnext.validation.common import LegacyDelegate, legacy_callable


class VNextValidationBoundaryTests(unittest.TestCase):
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
