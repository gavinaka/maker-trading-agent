from __future__ import annotations

import tempfile
import unittest
import hashlib
import json
from pathlib import Path
from unittest import mock

from outputs import publish_report
from runtime import delivery_evidence
from runtime import reasoning_readiness
from runtime import session_runner
from runtime import state_store


COMPLETE_STATE = {
    "notion_state": {"gate_summary": "可交易"},
    "analysis_archive": {
        "reuse_policy": "post_analysis_audit_only",
        "features": {},
        "scores": {},
        "risk_state": {},
    },
    "decision": {},
}


class ReportPreflightTests(unittest.TestCase):
    def test_preflight_revalidates_reasoning_and_all_mechanical_consumers(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "2026-07-11_morning_combined.md"
            report.write_text("# deterministic fixture\n", encoding="utf-8")
            payload_preview = {
                "image_paths": ["one.png", "two.png", "three.png"],
                "payload_source": {
                    "children_signature_sha256": "1" * 64,
                    "source_specs_sha256": "2" * 64,
                    "image_paths_sha256": "3" * 64,
                },
            }
            with mock.patch.object(
                session_runner,
                "validate_reasoning_readiness_manifest",
                return_value=({}, Path("readiness.json")),
            ) as readiness, mock.patch.object(
                session_runner,
                "validate_golden_reasoning_manifest",
                return_value=({}, Path("golden.json")),
            ) as golden, mock.patch.object(
                session_runner, "validate_report_structure"
            ) as structure, mock.patch.object(
                session_runner, "run_report_lint"
            ) as lint, mock.patch.object(
                session_runner, "extract_report_state", return_value=COMPLETE_STATE
            ) as extract, mock.patch.object(
                session_runner, "validate_report_state", return_value=[]
            ) as state_gate, mock.patch.object(
                session_runner, "build_daily_payload", return_value=payload_preview
            ) as payload_gate:
                manifest, state, _, _ = session_runner.validate_report_preflight(
                    report,
                    "2026-07-11",
                    "morning",
                )

            readiness.assert_called_once()
            golden.assert_called_once()
            structure.assert_called_once()
            lint.assert_called_once()
            extract.assert_called_once_with(
                report.read_text(encoding="utf-8"),
                trading_date="2026-07-11",
                slot="morning",
            )
            state_gate.assert_called_once_with(report.read_text(encoding="utf-8"), COMPLETE_STATE)
            payload_gate.assert_called_once()
            self.assertEqual(state, COMPLETE_STATE)
            self.assertTrue(all(manifest["checks"].values()))
            self.assertEqual(manifest["image_count"], 3)

    def test_preflight_blocks_incomplete_state_before_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "2026-07-11_evening_combined.md"
            report.write_text("# deterministic fixture\n", encoding="utf-8")
            with mock.patch.object(
                session_runner,
                "validate_reasoning_readiness_manifest",
                return_value=({}, Path("readiness.json")),
            ), mock.patch.object(
                session_runner,
                "validate_golden_reasoning_manifest",
                return_value=({}, Path("golden.json")),
            ), mock.patch.object(
                session_runner, "validate_report_structure"
            ), mock.patch.object(
                session_runner, "run_report_lint"
            ), mock.patch.object(
                session_runner, "extract_report_state", return_value=COMPLETE_STATE
            ), mock.patch.object(
                session_runner, "validate_report_state", return_value=["risk"]
            ):
                with self.assertRaisesRegex(ValueError, "incomplete state extraction: risk"):
                    session_runner.validate_report_preflight(
                        report,
                        "2026-07-11",
                        "evening",
                    )

    def test_preflight_binding_rejects_report_or_payload_drift(self):
        expected = {
            key: ({"passed": True} if key == "checks" else "same")
            for key in session_runner.REPORT_PREFLIGHT_BINDING_FIELDS
        }
        session_runner.assert_report_preflight_matches(expected, dict(expected))
        changed = dict(expected)
        changed["payload_preview_sha256"] = "changed"
        with self.assertRaisesRegex(ValueError, "payload_preview_sha256"):
            session_runner.assert_report_preflight_matches(expected, changed)

    def test_preflight_is_mandatory_for_new_production_dates_only(self):
        self.assertFalse(session_runner.report_preflight_required("2026-07-10"))
        self.assertTrue(session_runner.report_preflight_required("2026-07-11"))

    def test_final_payload_must_equal_prelock_payload_preview(self):
        payload = {"schema_version": "fixture", "children": []}
        expected_hash = publish_report.canonical_json_sha256(payload)
        lock = {
            "analysis_validation": {
                "payload_preview_sha256": expected_hash,
                "report_preflight_manifest": "preflight.json",
                "report_preflight_manifest_sha256": "a" * 64,
            }
        }
        evidence = publish_report.validate_payload_preflight_binding(
            payload,
            lock,
            "2026-07-11",
        )
        self.assertEqual(evidence["status"], "passed")
        changed = {"schema_version": "fixture", "children": [{"type": "paragraph"}]}
        with self.assertRaisesRegex(ValueError, "differs from pre-lock derivation"):
            publish_report.validate_payload_preflight_binding(
                changed,
                lock,
                "2026-07-11",
            )

    def test_delivery_requires_preflight_publish_evidence_for_new_dates(self):
        publish = {
            "slot": "morning",
            "notion_payload_shape": {
                "status": "passed",
                "block_count_before_images": 25,
                "image_count": 3,
            },
            "notion_payload_source": {
                "status": "passed",
                "kind": "combined_md_to_notion_payload",
            },
            "notion_payload_colors": {
                "status": "passed",
                "template": "daily-gold-run-colors-v1",
            },
            "frozen_verifier": {
                "returncode": 0,
                "script": "outputs/notion_verify_against_yesterday.py",
                "stdout": "[PASS]",
            },
            "payload_preflight": {
                "status": "passed",
                "payload_preview_sha256": "a" * 64,
                "report_preflight_manifest_sha256": "b" * 64,
            },
        }
        delivery_evidence._validate_strict_publish_quality_evidence(
            publish,
            "2026-07-11",
        )
        publish.pop("payload_preflight")
        with self.assertRaisesRegex(ValueError, "payload_preflight"):
            delivery_evidence._validate_strict_publish_quality_evidence(
                publish,
                "2026-07-11",
            )

    def test_render_and_publish_output_gate_requires_hash_bound_preflight(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "outputs" / "2026-07-11_morning_combined.md"
            report.parent.mkdir(parents=True)
            report.write_text("# locked report\n", encoding="utf-8")
            report_hash = hashlib.sha256(report.read_bytes()).hexdigest()
            state = root / "runtime_state" / "2026-07-11"
            state.mkdir(parents=True)
            preflight_path = state / "report_preflight_morning.json"
            preflight = {
                "schema_version": "daily-report-preflight-v1",
                "trading_date": "2026-07-11",
                "slot": "morning",
                "report_path": str(report.resolve()),
                "report_sha256": report_hash,
                "payload_preview_sha256": "a" * 64,
                "checks": {"all": True},
            }
            preflight_path.write_text(json.dumps(preflight), encoding="utf-8")
            preflight_hash = hashlib.sha256(preflight_path.read_bytes()).hexdigest()
            lock = {
                "trading_date": "2026-07-11",
                "slot": "morning",
                "report_path": str(report.resolve()),
                "report_sha256": report_hash,
                "max_through_analysis_confirmed": True,
                "analysis_validation": {
                    "reasoning_readiness_pre_md": True,
                    "reasoning_readiness_policy": reasoning_readiness.POLICY,
                    "report_preflight_required": True,
                    "payload_derivation_pre_lock": True,
                    "report_preflight_manifest": str(preflight_path.resolve()),
                    "report_preflight_manifest_sha256": preflight_hash,
                    "payload_preview_sha256": "a" * 64,
                },
            }
            lock_path = state / "analysis_lock_morning.json"
            lock_path.write_text(json.dumps(lock), encoding="utf-8")
            with mock.patch.object(
                reasoning_readiness,
                "validate_reasoning_readiness_manifest",
                return_value=({}, state / "reasoning_readiness_morning.json"),
            ):
                validated = reasoning_readiness.validate_locked_report_for_output(
                    "2026-07-11",
                    "morning",
                    report,
                    root=root,
                )
                self.assertEqual(validated["report_sha256"], report_hash)
                preflight["payload_preview_sha256"] = "b" * 64
                preflight_path.write_text(json.dumps(preflight), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "manifest changed after lock"):
                    reasoning_readiness.validate_locked_report_for_output(
                        "2026-07-11",
                        "morning",
                        report,
                        root=root,
                    )

    def test_state_commit_gate_requires_same_preflight_file_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            preflight_path = state / "report_preflight_morning.json"
            preflight_path.write_text("{}", encoding="utf-8")
            preflight_hash = hashlib.sha256(preflight_path.read_bytes()).hexdigest()
            validation = {
                "report_preflight_required": True,
                "payload_derivation_pre_lock": True,
                "report_preflight_manifest": str(preflight_path.resolve()),
                "report_preflight_manifest_sha256": preflight_hash,
                "payload_preview_sha256": "a" * 64,
            }
            self.assertTrue(
                state_store._report_preflight_binding_valid(
                    "2026-07-11",
                    "morning",
                    validation,
                    state,
                )
            )
            preflight_path.write_text('{"changed":true}', encoding="utf-8")
            self.assertFalse(
                state_store._report_preflight_binding_valid(
                    "2026-07-11",
                    "morning",
                    validation,
                    state,
                )
            )


if __name__ == "__main__":
    unittest.main()
