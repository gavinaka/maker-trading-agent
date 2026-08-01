from __future__ import annotations

import json
import hashlib
import re
import unittest
from decimal import Decimal
from pathlib import Path

from runtime_vnext.gates import (
    _future_trigger_clause_polarities,
    _trigger_logic_policy,
    _typed_direction_prose_issue,
)
from runtime_vnext.plan_semantics import (
    assess_candidate,
    assess_order_lifecycle,
    cannot_do_conflicts,
    classify_evidence_polarity,
    expected_reach_direction,
    resting_maker_order_valid,
    structural_noise_stop_is_outside,
    structure_zone_role_valid,
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

    def test_fixture_is_hash_bound_and_closed(self) -> None:
        self.assertEqual(
            self.payload["schema_version"], "vnext-semantic-replays-v3"
        )
        self.assertEqual(
            set(self.payload),
            {"schema_version", "cases", "reasoning_gate_cases"},
        )
        for case in self.cases.values():
            self.assertRegex(case["source_decision_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(case["source_reasoning_sha256"], r"^[0-9a-f]{64}$")
        for case in self.reasoning_gate_cases.values():
            self.assertRegex(case["source_reasoning_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(case["source_evidence_sha256"], r"^[0-9a-f]{64}$")

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
