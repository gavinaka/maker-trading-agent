from __future__ import annotations

import unittest
from decimal import Decimal

from runtime_vnext.plan_semantics import (
    DIRECTIONAL_THESIS_ONLY,
    NON_DIRECTIONAL_OBSERVATION,
    QUALIFIED_CANDIDATE,
    REJECTED_SUBMITTED_CANDIDATE,
    assess_candidate,
    assess_order_lifecycle,
    cancel_precedes_any_fill,
    classify_evidence_polarity,
    classify_maker_semantic_state,
    cannot_do_conflicts,
    expected_reach_direction,
    resting_maker_order_valid,
    structure_zone_role_valid,
)


class MakerPlanSemanticFoundationTests(unittest.TestCase):
    @staticmethod
    def semantic_state(**overrides):
        payload = {
            "plan_state": "observe",
            "direction": "short",
            "plan_constructible": False,
            "threshold_eligible": True,
            "risk_plan": {},
            "defense_plan": {},
            "position_notional_usdt": None,
            "entry_type": "not_applicable",
            "order_lifecycle_state": "not_applicable_no_candidate_geometry",
            "entry_reach_probability_applicability": (
                "not_applicable_no_certified_entry_geometry"
            ),
            "constructibility_reason": "no_certified_entry_zone",
        }
        payload.update(overrides)
        return classify_maker_semantic_state(**payload)

    def test_maker_four_state_classifier_uses_real_candidate_submission(self):
        self.assertEqual(
            self.semantic_state(
                plan_state="qualified",
                plan_constructible=True,
                risk_plan={"entries": [101, 102]},
                defense_plan={"prefill_anchor": {}},
                position_notional_usdt=750,
                entry_type="left",
                order_lifecycle_state="fillable",
                entry_reach_probability_applicability="applicable",
                constructibility_reason="constructible",
            ),
            QUALIFIED_CANDIDATE,
        )
        self.assertEqual(
            self.semantic_state(
                risk_plan={"entries": [101, 102]},
                entry_type="left",
                order_lifecycle_state="entry_before_cancel",
                entry_reach_probability_applicability="applicable",
                constructibility_reason="order_lifecycle_invalid",
            ),
            REJECTED_SUBMITTED_CANDIDATE,
        )
        self.assertEqual(
            self.semantic_state(),
            DIRECTIONAL_THESIS_ONLY,
        )
        self.assertEqual(
            self.semantic_state(
                direction="observe",
                threshold_eligible=False,
                constructibility_reason="non_directional_thesis",
            ),
            NON_DIRECTIONAL_OBSERVATION,
        )

    def test_direction_does_not_promote_an_empty_risk_input_to_candidate(self):
        for direction in ("long", "short"):
            with self.subTest(direction=direction):
                self.assertEqual(
                    self.semantic_state(direction=direction),
                    DIRECTIONAL_THESIS_ONLY,
                )

    def test_empty_risk_input_rejects_every_candidate_only_ghost_field(self):
        mutations = (
            {"position_notional_usdt": 750},
            {"defense_plan": {"prefill_anchor": {}}},
            {"entry_type": "left"},
            {"order_lifecycle_state": "fillable"},
            {"entry_reach_probability_applicability": "applicable"},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                with self.assertRaisesRegex(ValueError, "candidate-only fields"):
                    self.semantic_state(**mutation)

    def test_fully_eligible_submitted_candidate_cannot_hide_as_observe(self):
        with self.assertRaisesRegex(ValueError, "cannot remain observe"):
            self.semantic_state(
                plan_constructible=True,
                threshold_eligible=True,
                risk_plan={"entries": [101, 102]},
                entry_type="left",
                order_lifecycle_state="fillable",
                entry_reach_probability_applicability="applicable",
                constructibility_reason="constructible",
            )

    def test_a5_short_below_market_support_candidate_exposes_all_early_failures(self):
        reference = Decimal("63981.99")
        entries = tuple(Decimal(value) for value in ("62800", "62850", "62900"))

        resting = resting_maker_order_valid(
            direction="short",
            reference_price=reference,
            entries=entries,
        )
        self.assertFalse(resting)
        self.assertEqual(
            expected_reach_direction(reference, entries[0]),
            "down_to_entry",
        )
        self.assertFalse(
            structure_zone_role_valid(
                direction="short",
                zone_kind="structure_zone",
                zone_role="support",
                allowed_roles={
                    "short": ("resistance", "breakdown_retest"),
                    "long": ("support", "breakout_retest"),
                },
            )
        )
        self.assertTrue(
            cannot_do_conflicts(
                cannot_do_code="追空",
                direction="short",
                entry_type="left",
                resting_order_valid=resting,
            )
        )
        self.assertFalse(
            cancel_precedes_any_fill(
                reference_price=reference,
                cancel_price=Decimal("62500"),
                entries=entries,
            )
        )

        assessment = assess_candidate(
            failed_checks={
                "entry_zone_role_invalid",
                "maker_order_marketable",
                "entry_semantics_invalid",
                "cannot_do_conflict",
                "order_lifecycle_invalid",
                "risk_math_invalid",
            }
        )
        self.assertEqual(
            assessment.failure_codes,
            (
                "entry_zone_role_invalid",
                "maker_order_marketable",
                "entry_semantics_invalid",
                "cannot_do_conflict",
                "order_lifecycle_invalid",
                "risk_math_invalid",
            ),
        )
        self.assertEqual(assessment.primary_reason_code, "entry_zone_role_invalid")

    def test_resting_left_short_with_opposite_side_cancel_is_not_chasing(self):
        reference = Decimal("97")
        entries = (Decimal("99.8"), Decimal("100"))
        resting = resting_maker_order_valid(
            direction="short",
            reference_price=reference,
            entries=entries,
        )
        self.assertTrue(resting)
        self.assertFalse(
            cannot_do_conflicts(
                cannot_do_code="追空",
                direction="short",
                entry_type="left",
                resting_order_valid=resting,
            )
        )
        self.assertTrue(
            cancel_precedes_any_fill(
                reference_price=reference,
                cancel_price=Decimal("96.5"),
                entries=entries,
            )
        )

    def test_right_side_pursuit_prohibitions_are_independent_of_resting_geometry(self):
        self.assertTrue(
            cannot_do_conflicts(
                cannot_do_code="追空",
                direction="short",
                entry_type="right",
                resting_order_valid=True,
            )
        )

    def test_order_lifecycle_matrix_is_long_short_symmetric(self):
        cases = (
            ("short", Decimal("97"), (Decimal("99"), Decimal("100")), Decimal("96")),
            ("long", Decimal("103"), (Decimal("101"), Decimal("100")), Decimal("104")),
        )
        for direction, reference, entries, opposite_cancel in cases:
            with self.subTest(direction=direction, state="fillable"):
                result = assess_order_lifecycle(
                    reference_price=reference,
                    cancel_price=opposite_cancel,
                    entries=entries,
                )
                self.assertEqual(result.state, "fillable")
                self.assertTrue(result.legal_fill_path_exists)
                self.assertTrue(result.legal_cancel_path_exists)
                self.assertIsNone(result.fill_probability)

            same_side_near = (
                reference + Decimal("1")
                if direction == "short"
                else reference - Decimal("1")
            )
            with self.subTest(direction=direction, state="cancel_blocks_all_entries"):
                result = assess_order_lifecycle(
                    reference_price=reference,
                    cancel_price=same_side_near,
                    entries=entries,
                )
                self.assertEqual(result.state, "cancel_blocks_all_entries")
                self.assertFalse(result.legal_fill_path_exists)

            same_side_far = (
                reference + Decimal("4")
                if direction == "short"
                else reference - Decimal("4")
            )
            with self.subTest(direction=direction, state="entry_before_cancel"):
                result = assess_order_lifecycle(
                    reference_price=reference,
                    cancel_price=same_side_far,
                    entries=entries,
                )
                self.assertEqual(result.state, "entry_before_cancel")
                self.assertTrue(result.legal_fill_path_exists)
                self.assertFalse(result.legal_cancel_path_exists)

    def test_a5r1i_cancel_preempts_every_long_entry(self):
        result = assess_order_lifecycle(
            reference_price=Decimal("66034.1"),
            cancel_price=Decimal("65850"),
            entries=(Decimal("65600"), Decimal("65500")),
        )
        self.assertEqual(result.state, "cancel_blocks_all_entries")
        self.assertEqual(
            result.fill_probability_applicability,
            "not_applicable_no_legal_fill_path",
        )

    def test_nonpositive_cancel_and_entry_prices_are_invalid_for_both_sides(self):
        cases = (
            (Decimal("97"), (Decimal("99"), Decimal("100")), Decimal("96")),
            (Decimal("103"), (Decimal("101"), Decimal("100")), Decimal("104")),
        )
        for reference, valid_entries, valid_cancel in cases:
            for invalid_cancel in (Decimal("0"), Decimal("-1")):
                with self.subTest(
                    reference=reference,
                    invalid_cancel=invalid_cancel,
                ):
                    self.assertEqual(
                        assess_order_lifecycle(
                            reference_price=reference,
                            cancel_price=invalid_cancel,
                            entries=valid_entries,
                        ).state,
                        "invalid_geometry",
                    )
            for invalid_entry in (Decimal("0"), Decimal("-1")):
                with self.subTest(
                    reference=reference,
                    invalid_entry=invalid_entry,
                ):
                    self.assertEqual(
                        assess_order_lifecycle(
                            reference_price=reference,
                            cancel_price=valid_cancel,
                            entries=(invalid_entry, valid_entries[1]),
                        ).state,
                        "invalid_geometry",
                    )

    def test_evidence_polarity_is_direction_symmetric(self):
        expected = {
            ("long", "long"): "support",
            ("long", "short"): "counter",
            ("short", "short"): "support",
            ("short", "long"): "counter",
            ("long", "neutral"): "neutral",
            ("short", "neutral"): "neutral",
            ("neutral", "long"): "counter",
            ("neutral", "short"): "counter",
            ("neutral", "neutral"): "support",
            ("observe", "long"): "counter",
            ("observe", "short"): "counter",
            ("observe", "neutral"): "support",
        }
        for (subject, evidence), effect in expected.items():
            with self.subTest(subject=subject, evidence=evidence):
                self.assertEqual(
                    classify_evidence_polarity(
                        subject_direction=subject,
                        evidence_direction=evidence,
                    ).effect,
                    effect,
                )
        self.assertTrue(
            cannot_do_conflicts(
                cannot_do_code="追多空",
                direction="long",
                entry_type="right",
                resting_order_valid=True,
            )
        )


if __name__ == "__main__":
    unittest.main()
