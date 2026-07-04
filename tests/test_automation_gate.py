import json
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import runtime.automation_gate as gate


class AutomationGateTests(unittest.TestCase):
    def test_claim_blocks_duplicate_and_complete_marks_done(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            gate, "GATE_DIR", Path(directory)
        ):
            args = Namespace(
                key="daily-2026-06-30-morning",
                stale_minutes=240,
                done_file=None,
                require_json_flag=[],
            )
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(gate.claim(args), 0)
            token = json.loads(output.getvalue())["token"]

            with redirect_stdout(StringIO()):
                self.assertEqual(gate.claim(args), gate.EXIT_IN_PROGRESS)
                self.assertEqual(
                    gate.complete(
                        Namespace(
                            key=args.key,
                            token=token,
                            artifact="delivery.json",
                        )
                    ),
                    0,
                )
                self.assertEqual(gate.claim(args), gate.EXIT_DONE)

    def test_external_delivery_requires_all_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            delivery = root / "delivery.json"
            delivery.write_text(
                json.dumps(
                    {
                        "frozen_verifier_pass": True,
                        "unique_page_pass": True,
                    }
                ),
                encoding="utf-8",
            )
            args = Namespace(
                key="daily-2026-06-30-evening",
                stale_minutes=240,
                done_file=str(delivery),
                require_json_flag=[
                    "frozen_verifier_pass",
                    "word_visual_qa_pass",
                ],
            )

            with patch.object(gate, "GATE_DIR", root / "gate"):
                with redirect_stdout(StringIO()):
                    self.assertEqual(gate.claim(args), 0)


if __name__ == "__main__":
    unittest.main()
