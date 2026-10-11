from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime_vnext.cli import build_parser
from runtime_vnext.controller import RunController
from runtime_vnext.errors import FailureClass, WorkflowFailure


class VNextCapturePathBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.controller = RunController(self.root)
        self.run_root = self.root / "runtime_state_vnext" / "2026-07-16" / "evening" / "run-boundary"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def run_metadata(*, mode: str, authorization_ref: str) -> dict:
        return {
            "schema_version": "daily-run-vnext-v2",
            "run_id": "run-boundary",
            "trading_date": "2026-07-16",
            "slot": "evening",
            "run_mode": mode,
            "authorization_ref_sha256": hashlib.sha256(
                authorization_ref.encode("utf-8")
            ).hexdigest(),
        }

    def test_general_evidence_cli_is_not_exposed(self) -> None:
        parser = build_parser()
        subparsers = next(
            action
            for action in parser._actions
            if getattr(action, "choices", None) is not None
        )
        self.assertNotIn("evidence", subparsers.choices)
        self.assertNotIn("compile", subparsers.choices)
        self.assertNotIn("word-qa-export", subparsers.choices)
        self.assertNotIn("word-qa-approve", subparsers.choices)
        self.assertNotIn("word-qa-reject", subparsers.choices)
        self.assertIn("capture", subparsers.choices)
        self.assertIn("replay-evidence", subparsers.choices)

    def test_replay_cli_requires_explicit_authorization_reference(self) -> None:
        args = build_parser().parse_args(
            [
                "replay-evidence",
                "--date",
                "2026-07-16",
                "--slot",
                "evening",
                "--run-id",
                "run-boundary",
                "--input",
                "evidence.json",
                "--replay-authorization-ref",
                "replay:evening-fixture-01",
            ]
        )
        self.assertEqual(args.command, "replay-evidence")
        self.assertEqual(args.replay_authorization_ref, "replay:evening-fixture-01")

    def test_production_cannot_accept_external_replay_payload(self) -> None:
        reference = "replay:evening-fixture-01"
        run = self.run_metadata(mode="production", authorization_ref=reference)
        with (
            patch.object(self.controller, "_execution_run", return_value=run),
            patch.object(self.controller, "accept_evidence") as delegate,
            self.assertRaises(WorkflowFailure) as caught,
        ):
            self.controller.accept_replay_evidence(
                self.run_root,
                {"schema_version": "evidence-snapshot-v1"},
                replay_authorization_ref=reference,
            )
        self.assertEqual(caught.exception.failure_class, FailureClass.MANUAL_REVIEW)
        delegate.assert_not_called()

    def test_ordinary_shadow_cannot_accept_external_payload(self) -> None:
        reference = "approved-real-shadow-sample"
        run = self.run_metadata(mode="shadow", authorization_ref=reference)
        with (
            patch.object(self.controller, "_execution_run", return_value=run),
            patch.object(self.controller, "accept_evidence") as delegate,
            self.assertRaises(WorkflowFailure) as caught,
        ):
            self.controller.accept_replay_evidence(
                self.run_root,
                {"schema_version": "evidence-snapshot-v1"},
                replay_authorization_ref=reference,
            )
        self.assertEqual(caught.exception.failure_class, FailureClass.MANUAL_REVIEW)
        delegate.assert_not_called()

    def test_replay_reference_must_match_sealed_run_hash(self) -> None:
        run = self.run_metadata(
            mode="shadow",
            authorization_ref="replay:sealed-evening-fixture",
        )
        with (
            patch.object(self.controller, "_execution_run", return_value=run),
            patch.object(self.controller, "accept_evidence") as delegate,
            self.assertRaises(WorkflowFailure) as caught,
        ):
            self.controller.accept_replay_evidence(
                self.run_root,
                {"schema_version": "evidence-snapshot-v1"},
                replay_authorization_ref="replay:different-evening-fixture",
            )
        self.assertEqual(caught.exception.failure_class, FailureClass.MANUAL_REVIEW)
        delegate.assert_not_called()

    def test_matching_test_shadow_authorization_delegates_to_certifier(self) -> None:
        reference = "test:evening-fixture-01"
        run = self.run_metadata(mode="shadow", authorization_ref=reference)
        payload = {"schema_version": "evidence-snapshot-v1"}
        expected = {"status": "certified"}
        with (
            patch.object(self.controller, "_execution_run", return_value=run),
            patch.object(
                self.controller,
                "accept_evidence",
                return_value=expected,
            ) as delegate,
        ):
            actual = self.controller.accept_replay_evidence(
                self.run_root,
                payload,
                replay_authorization_ref=reference,
                evidence_files_root=self.root,
            )
        self.assertEqual(actual, expected)
        delegate.assert_called_once_with(
            self.run_root,
            payload,
            evidence_files_root=self.root,
        )


if __name__ == "__main__":
    unittest.main()
