from __future__ import annotations

import json
import io
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from runtime import session_runner


class SessionRunnerRetentionTests(unittest.TestCase):
    def test_deliver_runs_retention_before_releasing_lease(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "runtime_state" / "2026-07-06"
            state.mkdir(parents=True)
            commit_id = "b" * 64
            (state / "current.json").write_text(
                json.dumps({"slot": "morning", "commit_id": commit_id}),
                encoding="utf-8",
            )
            (state / "transition_morning.json").write_text(
                json.dumps({"slot": "morning"}),
                encoding="utf-8",
            )
            events: list[str] = []

            def fake_cleanup(**kwargs):
                events.append("cleanup")
                return {
                    "mode": "execute",
                    "count": 0,
                    "bytes": 0,
                    "cutoff": "2026-07-05",
                    "keep_days": 2,
                }

            def fake_complete(_token: str, *, artifact: str):
                events.append("complete")
                return {"artifact": artifact}

            argv = [
                "session_runner.py",
                "deliver",
                "--date",
                "2026-07-06",
                "--slot",
                "morning",
                "--page-id",
                "a" * 32,
                "--lease-token",
                "token",
            ]

            with (
                patch.object(session_runner, "ROOT", root),
                patch.object(
                    session_runner,
                    "assert_lease",
                    return_value={"lease_id": "c" * 64},
                ),
                patch.object(
                    session_runner,
                    "validate_delivery_evidence",
                    return_value={"published_at": "2026-07-06T08:00:00+08:00"},
                ),
                patch.object(session_runner, "append_usage"),
                patch.object(session_runner, "run_retention_cleanup", fake_cleanup),
                patch.object(session_runner, "complete_lease", fake_complete),
                patch.object(sys, "argv", argv),
                patch.object(sys, "stdout", io.StringIO()),
            ):
                self.assertEqual(session_runner.main(), 0)

            self.assertEqual(events, ["cleanup", "complete"])
            self.assertTrue((state / "delivery_morning.json").is_file())


if __name__ == "__main__":
    unittest.main()
