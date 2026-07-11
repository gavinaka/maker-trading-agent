from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime import session_runner


class RecoveryArtifactGuardTests(unittest.TestCase):
    def _record(self, path: Path, root: Path) -> dict[str, object]:
        return {
            "path": path.relative_to(root).as_posix(),
            "sha256": session_runner.sha256_file(path),
            "bytes": path.stat().st_size,
        }

    def test_preserves_after_certified_same_capture_even_if_lease_rebound(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "runtime_state" / "2026-07-11"
            capture = state / "captures" / "midday" / "run.json"
            work = state / "reasoning_work_midday.md"
            decision_input = state / "decision_input_midday.json"
            decision = state / "decision_contract_midday.json"
            transition = state / "transition_midday.json"
            readiness = state / "reasoning_readiness_midday.json"
            golden = state / "golden_reasoning_midday.json"
            contract = root / "scoring" / "reasoning_depth_checklist.md"
            input_payload = {
                "trading_date": "2026-07-11",
                "slot": "midday",
                "score": {"orderflow": 50, "chart": 19, "total": 69},
                "winrate": {"anchor": 64, "adjustments": [], "final": 64},
                "plan": {"direction": "none"},
            }
            for path, content in (
                (capture, '{"workflow_lease_id":"captured"}\n'),
                (work, "certified work\n"),
                (decision_input, json.dumps(input_payload) + "\n"),
                (
                    decision,
                    json.dumps(session_runner.build_contract(input_payload)) + "\n",
                ),
                (contract, "contract\n"),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            transition.write_text(
                json.dumps(
                    {
                        "trading_date": "2026-07-11",
                        "slot": "midday",
                        "capture_manifest": {
                            "path": capture.relative_to(state).as_posix(),
                            "sha256": session_runner.sha256_file(capture),
                        },
                        "capture_lease_recovery": {
                            "captured_workflow_lease_id": "captured-lease",
                            "active_workflow_lease_id": "new-active-lease",
                        },
                    }
                ),
                encoding="utf-8",
            )
            golden.write_text(
                json.dumps(
                        {
                            "trading_date": "2026-07-11",
                            "slot": "midday",
                            "status": "ready",
                        "policy": (
                            "pre_write_reasoning_alignment_not_posthoc_output_padding"
                        ),
                        "historical_sample_runtime_use": "forbidden",
                            "capture_manifest": self._record(capture, root),
                            "transition": self._record(transition, root),
                            "contract": self._record(contract, root),
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            readiness.write_text(
                json.dumps(
                    {
                        "status": "ready",
                        "trading_date": "2026-07-11",
                        "slot": "midday",
                        "policy": session_runner.REASONING_READINESS_POLICY,
                        "work_file": self._record(work, root),
                        "capture_manifest": self._record(capture, root),
                        "transition": {
                            "path": transition.relative_to(root).as_posix(),
                            "sha256": "old-transition-hash-before-lease-rebind",
                        },
                        "golden_reasoning_manifest": {
                            "path": golden.relative_to(root).as_posix(),
                            "sha256": "old-golden-hash-before-lease-rebind",
                        },
                        "contract": self._record(contract, root),
                        "decision_contract": self._record(decision, root),
                    }
                ),
                encoding="utf-8",
            )
            lease = {
                "recovered_from_workflow_lease": {"lease_id": "captured-lease"}
            }

            with (
                patch.object(session_runner, "ROOT", root),
                patch.object(session_runner, "validate_reasoning_work_file"),
            ):
                self.assertTrue(
                    session_runner._certified_recovery_artifacts_available(
                        "2026-07-11",
                        "midday",
                        capture,
                        lease,
                    )
                )
                decision.write_text('{"changed":true}\n', encoding="utf-8")
                self.assertFalse(
                    session_runner._certified_recovery_artifacts_available(
                        "2026-07-11",
                        "midday",
                        capture,
                        lease,
                    )
                )

    def test_ordinary_session_never_preserves(self):
        self.assertFalse(
            session_runner._certified_recovery_artifacts_available(
                "2026-07-11",
                "midday",
                Path("missing.json"),
                {},
            )
        )


if __name__ == "__main__":
    unittest.main()
