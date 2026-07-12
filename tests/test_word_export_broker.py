from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from outputs import word_export_broker
from outputs.word_qa import sha256_file


class WordExportBrokerTests(unittest.TestCase):
    def _request(self, root: Path) -> Path:
        docx = root / "outputs" / "2026-06-30_morning_render.docx"
        docx.parent.mkdir(parents=True)
        docx.write_bytes(b"docx")
        attempt = (
            root
            / "runtime_state"
            / "2026-06-30"
            / "word_qa"
            / "morning"
            / "attempt-1-test"
        )
        attempt.mkdir(parents=True)
        request = attempt / word_export_broker.REQUEST_NAME
        request.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "request_id": "a" * 32,
                    "requested_at": datetime.now().astimezone().isoformat(
                        timespec="seconds"
                    ),
                    "trading_date": "2026-06-30",
                    "slot": "morning",
                    "docx_path": str(docx.resolve()),
                    "docx_sha256": sha256_file(docx),
                    "pdf_path": str(
                        (attempt / "2026-06-30_morning_render.pdf").resolve()
                    ),
                }
            ),
            encoding="utf-8",
        )
        return request

    def test_request_is_bound_to_canonical_docx_and_attempt_pdf(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request = self._request(root)
            validated = word_export_broker.validate_request(request, root=root)
            self.assertEqual(validated["request_id"], "a" * 32)
            self.assertEqual(validated["slot"], "morning")

    def test_request_rejects_arbitrary_output_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request = self._request(root)
            payload = json.loads(request.read_text(encoding="utf-8"))
            payload["pdf_path"] = str((root / "outside.pdf").resolve())
            request.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "PDF path is not canonical"):
                word_export_broker.validate_request(request, root=root)


if __name__ == "__main__":
    unittest.main()
