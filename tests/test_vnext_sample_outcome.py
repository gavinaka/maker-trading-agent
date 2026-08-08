from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.host_capability import (
    build_manifest as build_host_capability_manifest,
    validate_manifest as validate_host_capability_manifest,
)
from runtime_vnext.artifacts import ArtifactStore
from runtime_vnext.controller import RunController
from runtime_vnext.errors import WorkflowFailure
from runtime_vnext.methodology import build_methodology_manifest, canonical_sha256
from runtime_vnext.sample_outcome import (
    STAGES,
    validate_sample_outcome,
    write_sample_outcome,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


class VNextSampleOutcomeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = ArtifactStore(
            self.root,
            authority_root=REPO_ROOT,
        )
        self.current_methodology = build_methodology_manifest()
        self.store.create_run(
            "2026-07-14",
            "midday",
            methodology_manifest=self.current_methodology,
            run_mode="shadow",
            authorization_ref="test-shadow-sample-outcome-approval",
            run_id="run-sample-outcome",
        )
        self.run_root = self.store.run_root(
            "2026-07-14", "midday", "run-sample-outcome"
        )

        legacy_methodology = {
            "schema_version": "methodology-manifest-v2",
            "policy": "test-authority-epoch",
            "phases": {},
        }
        legacy_methodology["manifest_sha256"] = canonical_sha256(
            legacy_methodology
        )
        self.authority_epoch = legacy_methodology["manifest_sha256"]
        run_path = self.run_root / "run.json"
        run = json.loads(run_path.read_text(encoding="utf-8"))
        for field in (
            "semantic_contract_sha256",
            "release_sha256",
            "methodology_manifest_sha256",
        ):
            run.pop(field)
        run["methodology_sha256"] = self.authority_epoch
        run.pop("run_sha256")
        run["run_sha256"] = canonical_sha256(run)
        run_path.write_text(
            json.dumps(run, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (self.run_root / "methodology_manifest.json").write_text(
            json.dumps(
                legacy_methodology,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _pass_stage(self, stage: str, *, terminal_status: str = "complete") -> None:
        attempt, attempt_root = self.store.begin_attempt(self.run_root, stage)
        output = (
            self.store.write_payload(
                attempt_root,
                "evidence.json",
                {
                    "schema_version": getattr(
                        self,
                        "evidence_schema_version",
                        "evidence-snapshot-v2",
                    ),
                    "capture_mode": getattr(
                        self,
                        "evidence_capture_mode",
                        "full_recollection",
                    ),
                    "sources": {
                        "FedWatch": {
                            "meta": getattr(
                                self,
                                "rate_expectation_meta",
                                {
                                    "provider_id": "cme_fedwatch_ui",
                                    "method_class": "cme_target_rate_probability",
                                    "sample_source_class": "cme_canonical",
                                },
                            )
                        }
                    },
                },
            )
            if stage == "evidence"
            else self.store.write_text(attempt_root, f"{stage}.txt", stage)
        )
        facts = {}
        if stage == "report":
            facts = {
                "human_reasoning_depth": {"passed": True},
                "gold_template_fidelity": {"passed": True},
            }
        metadata = (
            {"completion_mode": "shadow", "notion_published": False}
            if terminal_status == "shadow_complete"
            else None
        )
        self.store.complete_attempt(
            self.run_root,
            stage,
            attempt,
            {stage: output},
            gate={"gate": stage, "passed": True, "defects": [], "facts": facts},
            terminal_status=terminal_status,
            terminal_metadata=metadata,
        )

    def _complete(self, *, shadow: bool = False) -> None:
        for stage in STAGES[:-1]:
            self._pass_stage(stage)
        self._pass_stage(STAGES[-1], terminal_status="shadow_complete" if shadow else "complete")

    def test_terminal_run_emits_immutable_mechanical_outcome(self) -> None:
        self._complete(shadow=True)
        path = self.run_root / "sample_outcome.json"
        self.assertTrue(path.is_file())
        payload = json.loads(path.read_text(encoding="utf-8"))
        validate_sample_outcome(payload)
        self.assertEqual(payload["schema_version"], "vnext-sample-outcome-v5")
        self.assertEqual(payload["run"]["requested_effort"], "xhigh")
        self.assertEqual(
            payload["bindings"]["authority_epoch_sha256"],
            self.authority_epoch,
        )
        self.assertEqual(payload["run"]["terminal_status"], "shadow_complete")
        self.assertEqual(payload["process"]["total_attempts"], 5)
        self.assertEqual(payload["process"]["local_retry_count"], 0)
        self.assertEqual(
            payload["evidence_provenance"],
            {
                "mode": "fresh_full_recollection",
                "provider_id": "cme_fedwatch_ui",
                "method_class": "cme_target_rate_probability",
                "sample_source_class": "cme_canonical",
            },
        )
        self.assertTrue(payload["quality_contracts"]["human_reasoning_depth_passed"])
        self.assertFalse(payload["observer_boundary"]["blocking"])
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("test-shadow-sample-outcome-approval", serialized)
        self.assertNotIn("authorization_ref", serialized)
        self.assertNotIn("run_mode", serialized)

        original = path.read_bytes()
        self.assertEqual(
            write_sample_outcome(repo_root=self.root, run_root=self.run_root),
            payload,
        )
        self.assertEqual(path.read_bytes(), original)

    def test_v3_manifest_emits_v6_authority_triple_without_legacy_alias(self) -> None:
        v3_root = self.root / "v3"
        self.store = ArtifactStore(
            v3_root,
            authority_root=REPO_ROOT,
        )
        methodology = self.current_methodology
        self.store.create_run(
            "2026-07-15",
            "midday",
            methodology_manifest=methodology,
            run_mode="shadow",
            authorization_ref="test-shadow-v6-outcome-approval",
            run_id="run-sample-outcome-v6",
        )
        self.run_root = self.store.run_root(
            "2026-07-15", "midday", "run-sample-outcome-v6"
        )
        self._complete(shadow=True)

        payload = json.loads(
            (self.run_root / "sample_outcome.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["schema_version"], "vnext-sample-outcome-v6")
        self.assertEqual(
            payload["bindings"],
            {
                "run_sha256": payload["bindings"]["run_sha256"],
                "checkpoint_sha256": payload["bindings"]["checkpoint_sha256"],
                "semantic_contract_sha256": methodology[
                    "semantic_contract_sha256"
                ],
                "release_sha256": methodology["release_sha256"],
                "methodology_manifest_sha256": methodology["manifest_sha256"],
            },
        )
        self.assertNotIn("authority_epoch_sha256", payload["bindings"])

        tampered = json.loads(json.dumps(payload))
        tampered["bindings"]["release_sha256"] = "c" * 64
        tampered["sample_outcome_sha256"] = hashlib.sha256(
            json.dumps(
                {
                    key: value
                    for key, value in tampered.items()
                    if key != "sample_outcome_sha256"
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        (self.run_root / "sample_outcome.json").write_text(
            json.dumps(tampered, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "authority triple differs"):
            write_sample_outcome(repo_root=v3_root, run_root=self.run_root)

    def test_morning_full_base_is_fresh_full_recollection(self) -> None:
        self.evidence_capture_mode = "full_base"
        self._complete(shadow=True)
        payload = json.loads(
            (self.run_root / "sample_outcome.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            payload["evidence_provenance"],
            {
                "mode": "fresh_full_recollection",
                "provider_id": "cme_fedwatch_ui",
                "method_class": "cme_target_rate_probability",
                "sample_source_class": "cme_canonical",
            },
        )

    def test_unknown_capture_mode_remains_fail_safe_unknown(self) -> None:
        self.evidence_capture_mode = "unexpected_capture_mode"
        self._complete(shadow=True)
        payload = json.loads(
            (self.run_root / "sample_outcome.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            payload["evidence_provenance"],
            {
                "mode": "unknown",
                "provider_id": "cme_fedwatch_ui",
                "method_class": "cme_target_rate_probability",
                "sample_source_class": "cme_canonical",
            },
        )

    def test_plan_c_provider_is_exported_as_observation_only_source_class(self) -> None:
        self.rate_expectation_meta = {
            "provider_id": "kalshi_public_market_data_api",
            "method_class": "independent_event_contract_market",
            "sample_source_class": "kalshi_plan_c_observation",
        }
        self._complete(shadow=True)
        payload = json.loads(
            (self.run_root / "sample_outcome.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            payload["evidence_provenance"],
            {
                "mode": "fresh_full_recollection",
                "provider_id": "kalshi_public_market_data_api",
                "method_class": "independent_event_contract_market",
                "sample_source_class": "kalshi_plan_c_observation",
            },
        )

    def test_current_v2_unrecognized_provider_combination_fails_closed(self) -> None:
        self.rate_expectation_meta = {
            "provider_id": "cme_fedwatch_ui",
            "method_class": "independent_event_contract_market",
            "sample_source_class": "cme_canonical",
        }
        self._complete(shadow=True)
        self.assertFalse((self.run_root / "sample_outcome.json").exists())
        self.assertIn(
            "sample_outcome_observer_failed",
            (self.run_root / "events.jsonl").read_text(encoding="utf-8"),
        )

    def test_legacy_v1_provider_unbound_is_exported_as_unknown_observation(self) -> None:
        self.evidence_schema_version = "evidence-snapshot-v1"
        self.rate_expectation_meta = {}
        self._complete(shadow=True)
        payload = json.loads(
            (self.run_root / "sample_outcome.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            payload["evidence_provenance"],
            {
                "mode": "fresh_full_recollection",
                "provider_id": "unknown",
                "method_class": "unknown",
                "sample_source_class": "unknown",
            },
        )

    def test_failure_is_fingerprinted_without_free_text(self) -> None:
        attempt, _ = self.store.begin_attempt(self.run_root, "evidence")
        self.store.fail_attempt(
            self.run_root,
            "evidence",
            attempt,
            failure_class="evidence_integrity",
            retryable=True,
            retry_scope="evidence",
            defects=[{
                "code": "source.missing",
                "message": "sensitive free text must not leave the run",
                "path": "sources",
                "severity": "hard",
            }],
        )
        self._complete()
        payload = json.loads((self.run_root / "sample_outcome.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["process"]["local_retry_count"], 1)
        self.assertEqual(payload["process"]["stage_failure_counts"]["evidence"], 1)
        self.assertEqual(payload["failure_clusters"][0]["defect_code"], "source.missing")
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("sensitive free text", serialized)
        self.assertNotIn("message", serialized)

    def test_retirement_emits_outcome_without_business_quality_claims(self) -> None:
        authorization = {
            "schema_version": "run-retirement-authorization-v1",
            "run_id": "run-sample-outcome",
            "trading_date": "2026-07-14",
            "slot": "midday",
            "reviewer": "Technical expert",
            "approval_reference": "approved-test",
            "reason": "test",
            "authorized_at": "2026-07-14T12:00:00+08:00",
            "manifest_sha256": "b" * 64,
        }
        self.store.retire_run(self.run_root, authorization)
        payload = json.loads((self.run_root / "sample_outcome.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["run"]["terminal_status"], "retired")
        self.assertIsNone(payload["quality_contracts"]["report_compilation_passed"])
        self.assertEqual(
            set(payload),
            {
                "schema_version", "run", "bindings", "process", "quality_contracts",
                "evidence_provenance", "failure_clusters", "observer_boundary",
                "sample_outcome_sha256",
            },
        )

    def test_replay_provenance_is_exported_without_business_evidence(self) -> None:
        self.evidence_capture_mode = "immutable_evidence_replay"
        self._complete(shadow=True)
        payload = json.loads(
            (self.run_root / "sample_outcome.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            payload["evidence_provenance"],
            {
                "mode": "immutable_replay",
                "provider_id": "cme_fedwatch_ui",
                "method_class": "cme_target_rate_probability",
                "sample_source_class": "cme_canonical",
            },
        )
        self.assertNotIn("replay_source", payload)

    def test_existing_v1_outcome_remains_immutable_and_is_not_upgraded(self) -> None:
        self._complete(shadow=True)
        path = self.run_root / "sample_outcome.json"
        legacy = json.loads(path.read_text(encoding="utf-8"))
        legacy["schema_version"] = "vnext-sample-outcome-v1"
        legacy["run"]["requested_effort"] = "high"
        legacy["bindings"].pop("authority_epoch_sha256")
        legacy.pop("evidence_provenance")
        legacy.pop("sample_outcome_sha256")
        encoded = json.dumps(
            legacy,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        legacy["sample_outcome_sha256"] = hashlib.sha256(encoded).hexdigest()
        path.write_text(
            json.dumps(legacy, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        original = path.read_bytes()
        validate_sample_outcome(legacy)
        self.assertEqual(
            write_sample_outcome(repo_root=self.root, run_root=self.run_root),
            legacy,
        )
        self.assertEqual(path.read_bytes(), original)

    def test_existing_v3_outcome_remains_immutable_and_is_not_upgraded(self) -> None:
        self._complete(shadow=True)
        path = self.run_root / "sample_outcome.json"
        legacy = json.loads(path.read_text(encoding="utf-8"))
        legacy["schema_version"] = "vnext-sample-outcome-v3"
        legacy["run"]["requested_effort"] = "high"
        legacy["evidence_provenance"] = {
            "mode": legacy["evidence_provenance"]["mode"]
        }
        legacy.pop("sample_outcome_sha256")
        encoded = json.dumps(
            legacy,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        legacy["sample_outcome_sha256"] = hashlib.sha256(encoded).hexdigest()
        path.write_text(
            json.dumps(legacy, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        original = path.read_bytes()
        validate_sample_outcome(legacy)
        self.assertEqual(
            write_sample_outcome(repo_root=self.root, run_root=self.run_root),
            legacy,
        )
        self.assertEqual(path.read_bytes(), original)

    def test_existing_v4_high_outcome_remains_immutable_and_is_not_upgraded(self) -> None:
        self._complete(shadow=True)
        path = self.run_root / "sample_outcome.json"
        legacy = json.loads(path.read_text(encoding="utf-8"))
        legacy["schema_version"] = "vnext-sample-outcome-v4"
        legacy["run"]["requested_effort"] = "high"
        legacy.pop("sample_outcome_sha256")
        encoded = json.dumps(
            legacy,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        legacy["sample_outcome_sha256"] = hashlib.sha256(encoded).hexdigest()
        path.write_text(
            json.dumps(legacy, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        original = path.read_bytes()
        validate_sample_outcome(legacy)
        self.assertEqual(
            write_sample_outcome(repo_root=self.root, run_root=self.run_root),
            legacy,
        )
        self.assertEqual(path.read_bytes(), original)

    def test_new_vnext_run_requires_exact_xhigh(self) -> None:
        run = self.store.load_run(self.run_root)
        self.assertEqual(run["requested_model"], "gpt-5.6-sol")
        self.assertEqual(run["requested_effort"], "xhigh")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ArtifactStore(root, authority_root=REPO_ROOT)
            for stale_effort in ("high", "max", "ultra"):
                with self.subTest(stale_effort=stale_effort):
                    with self.assertRaisesRegex(ValueError, "xhigh reasoning effort"):
                        store.create_run(
                            "2026-07-15",
                            "midday",
                            methodology_manifest=self.current_methodology,
                            requested_effort=stale_effort,
                            run_mode="shadow",
                            authorization_ref="test-xhigh-request-policy",
                            run_id=f"run-stale-{stale_effort}",
                        )

    def test_vnext_host_capability_accepts_xhigh_or_above_and_rejects_high(self) -> None:
        for actual_effort in ("xhigh", "max", "ultra"):
            with self.subTest(actual_effort=actual_effort):
                payload = {
                    "schema_version": "codex-host-capability-v2",
                    "status": "verified",
                    "trading_date": "2026-07-14",
                    "slot": "midday",
                    "model": "gpt-5.6-sol",
                    "reasoning_effort": actual_effort,
                    "minimum_effort": "xhigh",
                    "effort_policy": "at_least_minimum",
                    "thread_id": f"thread-{actual_effort}",
                }
                payload["manifest_sha256"] = canonical_sha256(payload)
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    local_store = ArtifactStore(
                        root,
                        authority_root=REPO_ROOT,
                    )
                    local_store.create_run(
                        "2026-07-14",
                        "midday",
                        methodology_manifest=self.current_methodology,
                        run_mode="shadow",
                        authorization_ref="test-xhigh-host-policy",
                        run_id=f"run-host-{actual_effort}",
                    )
                    local_controller = RunController(root)
                    local_controller.record_host_capability(
                        local_store.run_root(
                            "2026-07-14", "midday", f"run-host-{actual_effort}"
                        ),
                        payload,
                    )

        below = {
            "schema_version": "codex-host-capability-v2",
            "status": "verified",
            "trading_date": "2026-07-14",
            "slot": "midday",
            "model": "gpt-5.6-sol",
            "reasoning_effort": "high",
            "minimum_effort": "xhigh",
            "effort_policy": "at_least_minimum",
            "thread_id": "thread-high",
        }
        below["manifest_sha256"] = canonical_sha256(below)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local_store = ArtifactStore(
                root,
                authority_root=REPO_ROOT,
            )
            local_store.create_run(
                "2026-07-14",
                "midday",
                methodology_manifest=self.current_methodology,
                run_mode="shadow",
                authorization_ref="test-below-xhigh-host-policy",
                run_id="run-host-high",
            )
            with self.assertRaisesRegex(
                WorkflowFailure,
                "host capability is not verified at the requested model/effort",
            ):
                RunController(root).record_host_capability(
                    local_store.run_root(
                        "2026-07-14", "midday", "run-host-high"
                    ),
                    below,
                )

    def test_new_run_rejects_legacy_methodology_manifest(self) -> None:
        legacy = {
            "schema_version": "methodology-manifest-v2",
            "policy": "historical-test-envelope",
            "phases": {},
        }
        legacy["manifest_sha256"] = canonical_sha256(legacy)
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(
                Path(directory),
                authority_root=REPO_ROOT,
            )
            with self.assertRaisesRegex(ValueError, "methodology-manifest-v3"):
                store.create_run(
                    "2026-07-15",
                    "midday",
                    methodology_manifest=legacy,
                    run_mode="shadow",
                    authorization_ref="test-legacy-authority-rejected",
                    run_id="run-legacy-authority-rejected",
                )

    def test_host_capability_v2_extends_effort_domain_without_changing_legacy_default(self) -> None:
        for actual_effort, minimum_effort in (
            ("high", "high"),
            ("xhigh", "xhigh"),
            ("max", "xhigh"),
            ("ultra", "xhigh"),
        ):
            with self.subTest(
                actual_effort=actual_effort,
                minimum_effort=minimum_effort,
            ):
                session_path = self.root / f"session-{actual_effort}.jsonl"
                records = [
                    {
                        "type": "session_meta",
                        "payload": {"id": f"thread-{actual_effort}", "cwd": str(self.root)},
                    },
                    {
                        "type": "turn_context",
                        "payload": {
                            "turn_id": "turn-1",
                            "cwd": str(self.root),
                            "model": "gpt-5.6-sol",
                            "effort": actual_effort,
                        },
                    },
                ]
                session_path.write_text(
                    "\n".join(json.dumps(item) for item in records) + "\n",
                    encoding="utf-8",
                )
                payload = build_host_capability_manifest(
                    "2026-07-14",
                    "midday",
                    session_jsonl=session_path,
                    minimum_effort=minimum_effort,
                    root=self.root,
                )
                self.assertEqual(payload["schema_version"], "codex-host-capability-v2")
                self.assertEqual(payload["reasoning_effort"], actual_effort)
                self.assertEqual(payload["minimum_effort"], minimum_effort)
                target = (
                    self.root
                    / "runtime_state"
                    / "2026-07-14"
                    / "host_capability_midday.json"
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    json.dumps(payload, ensure_ascii=False),
                    encoding="utf-8",
                )
                validated = validate_host_capability_manifest(
                    target,
                    "2026-07-14",
                    "midday",
                    root=self.root,
                    minimum_effort=minimum_effort,
                )
                self.assertEqual(validated, payload)

    def test_observer_failure_does_not_block_terminal_or_active_release(self) -> None:
        for stage in STAGES[:-1]:
            self._pass_stage(stage)
        with patch(
            "runtime_vnext.sample_outcome.write_sample_outcome",
            side_effect=OSError("observer unavailable"),
        ):
            self._pass_stage("delivery")
        checkpoint = self.store.load_checkpoint(self.run_root)
        self.assertEqual(checkpoint["status"], "complete")
        self.assertFalse((self.root / "runtime_state_vnext" / "active_run.json").exists())
        self.assertFalse((self.run_root / "sample_outcome.json").exists())
        events = (self.run_root / "events.jsonl").read_text(encoding="utf-8")
        self.assertIn("sample_outcome_observer_failed", events)

    def test_tampered_methodology_epoch_cannot_be_exported_as_v2_binding(self) -> None:
        for stage in STAGES[:-1]:
            self._pass_stage(stage)
        methodology_path = self.run_root / "methodology_manifest.json"
        methodology = json.loads(methodology_path.read_text(encoding="utf-8"))
        methodology["policy"] = "tampered-after-run-start"
        methodology_path.write_text(
            json.dumps(methodology, ensure_ascii=False),
            encoding="utf-8",
        )
        self._pass_stage("delivery")
        self.assertEqual(self.store.load_checkpoint(self.run_root)["status"], "complete")
        self.assertFalse((self.run_root / "sample_outcome.json").exists())
        self.assertIn(
            "sample_outcome_observer_failed",
            (self.run_root / "events.jsonl").read_text(encoding="utf-8"),
        )

    def test_nonterminal_run_has_no_outcome(self) -> None:
        self._pass_stage("evidence")
        self.assertFalse((self.run_root / "sample_outcome.json").exists())

    def test_governance_contract_keeps_observer_external_and_nonblocking(self) -> None:
        contract_path = Path(__file__).resolve().parents[1] / "governance" / "vnext_sample_outcome_contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        self.assertEqual(contract["schema_version"], "vnext-sample-outcome-contract-v6")
        self.assertEqual(contract["emitted_schema"], "vnext-sample-outcome-v6")
        self.assertEqual(
            contract["accepted_legacy_schemas"],
            [
                "vnext-sample-outcome-v5",
                "vnext-sample-outcome-v4",
                "vnext-sample-outcome-v3",
                "vnext-sample-outcome-v2",
                "vnext-sample-outcome-v1",
            ],
        )
        self.assertFalse(contract["emission"]["blocking"])
        self.assertFalse(contract["consumer_boundary"]["production_context_may_read"])
        self.assertFalse(contract["consumer_boundary"]["may_modify_code_or_methodology_automatically"])
        self.assertTrue(
            contract["consumer_boundary"][
                "v6_run_attestation_requires_complete_triple"
            ]
        )
        self.assertEqual(
            contract["consumer_boundary"]["clean_cohort_key"],
            "semantic_contract_sha256",
        )
        self.assertFalse(
            contract["consumer_boundary"][
                "release_sha256_may_partition_clean_cohort"
            ]
        )
        self.assertFalse(
            contract["consumer_boundary"][
                "methodology_manifest_sha256_may_partition_clean_cohort"
            ]
        )
        self.assertFalse(
            contract["consumer_boundary"][
                "presentation_or_metadata_change_creates_semantic_epoch"
            ]
        )
        self.assertFalse(
            contract["consumer_boundary"]["fourth_identity_allowed"]
        )
        self.assertFalse(
            contract["consumer_boundary"]["legacy_without_authority_epoch_may_count_as_clean"]
        )
        self.assertFalse(
            contract["consumer_boundary"][
                "legacy_combined_identity_may_count_as_current_semantic_clean"
            ]
        )
        self.assertFalse(contract["consumer_boundary"]["cross_epoch_clean_accumulation"])
        self.assertFalse(
            contract["consumer_boundary"]["kalshi_plan_c_may_count_as_clean"]
        )


if __name__ == "__main__":
    unittest.main()
