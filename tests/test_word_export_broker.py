from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from outputs import word_export_broker
from outputs.word_qa import sha256_file
from runtime_vnext.methodology import canonical_sha256


class WordExportBrokerTests(unittest.TestCase):
    @staticmethod
    def _write_request(
        request: Path,
        *,
        trading_date: str,
        slot: str,
        docx: Path,
    ) -> Path:
        request.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "request_id": "a" * 32,
                    "requested_at": datetime.now().astimezone().isoformat(
                        timespec="seconds"
                    ),
                    "trading_date": trading_date,
                    "slot": slot,
                    "docx_path": str(docx.resolve()),
                    "docx_sha256": sha256_file(docx),
                    "pdf_path": str(
                        (request.parent / f"{trading_date}_{slot}_render.pdf").resolve()
                    ),
                }
            ),
            encoding="utf-8",
        )
        return request

    def _legacy_request(self, root: Path) -> Path:
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
        return self._write_request(
            request,
            trading_date="2026-06-30",
            slot="morning",
            docx=docx,
        )

    def _vnext_request(
        self,
        root: Path,
        *,
        run_id: str = "run-word-broker-test",
    ) -> Path:
        trading_date = "2026-07-18"
        slot = "evening"
        run_root = root / "runtime_state_vnext" / trading_date / slot / run_id
        run_root.mkdir(parents=True)
        run = {
            "schema_version": "daily-run-vnext-v2",
            "run_id": run_id,
            "trading_date": trading_date,
            "slot": slot,
            "run_mode": "shadow",
            "authorization_kind": "explicit_shadow_test_approval",
            "authorization_ref_sha256": "b" * 64,
            "methodology_sha256": "c" * 64,
        }
        run["run_sha256"] = canonical_sha256(run)
        (run_root / "run.json").write_text(json.dumps(run), encoding="utf-8")

        docx = run_root / "delivery_assets" / f"{trading_date}_{slot}_render.docx"
        docx.parent.mkdir()
        docx.write_bytes(b"vnext-docx")
        attempt = (
            run_root
            / "delivery_assets"
            / "word_qa"
            / "attempt-001-deadbeef"
        )
        attempt.mkdir(parents=True)
        return self._write_request(
            attempt / word_export_broker.REQUEST_NAME,
            trading_date=trading_date,
            slot=slot,
            docx=docx,
        )

    def test_request_is_bound_to_canonical_docx_and_attempt_pdf(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request = self._legacy_request(root)
            validated = word_export_broker.validate_request(request, root=root)
            self.assertEqual(validated["request_id"], "a" * 32)
            self.assertEqual(validated["slot"], "morning")
            self.assertEqual(validated["layout"], "legacy")
            self.assertIsNone(validated["run_id"])

    def test_request_rejects_arbitrary_output_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request = self._legacy_request(root)
            payload = json.loads(request.read_text(encoding="utf-8"))
            payload["pdf_path"] = str((root / "outside.pdf").resolve())
            request.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "PDF path is not canonical"):
                word_export_broker.validate_request(request, root=root)

    def test_vnext_request_is_bound_to_run_local_docx_and_run_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request = self._vnext_request(root)

            validated = word_export_broker.validate_request(request, root=root)

            self.assertEqual(validated["layout"], "vnext")
            self.assertEqual(validated["run_id"], "run-word-broker-test")
            self.assertEqual(validated["trading_date"], "2026-07-18")
            self.assertEqual(validated["slot"], "evening")
            self.assertEqual(
                validated["docx"],
                request.parents[2] / "2026-07-18_evening_render.docx",
            )

    def test_vnext_request_rejects_non_run_local_docx(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request = self._vnext_request(root)
            outside_docx = root / "outputs" / "2026-07-18_evening_render.docx"
            outside_docx.parent.mkdir()
            outside_docx.write_bytes(b"wrong-docx")
            payload = json.loads(request.read_text(encoding="utf-8"))
            payload["docx_path"] = str(outside_docx.resolve())
            payload["docx_sha256"] = sha256_file(outside_docx)
            request.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "DOCX path is not canonical"):
                word_export_broker.validate_request(request, root=root)

    def test_vnext_request_rejects_docx_hash_or_attempt_local_pdf_mismatch(self):
        mutations = {
            "docx_sha256": "0" * 64,
            "pdf_path": "outside.pdf",
        }
        for field, replacement in mutations.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                request = self._vnext_request(root)
                payload = json.loads(request.read_text(encoding="utf-8"))
                payload[field] = (
                    replacement
                    if field == "docx_sha256"
                    else str((root / replacement).resolve())
                )
                request.write_text(json.dumps(payload), encoding="utf-8")

                expected = (
                    "DOCX hash does not match"
                    if field == "docx_sha256"
                    else "PDF path is not canonical"
                )
                with self.assertRaisesRegex(ValueError, expected):
                    word_export_broker.validate_request(request, root=root)

    def test_vnext_request_rejects_each_run_directory_identity_mismatch(self):
        mutations = {
            "run_id": "run-another-id",
            "trading_date": "2026-07-17",
            "slot": "morning",
        }
        for field, replacement in mutations.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                request = self._vnext_request(root)
                run_path = request.parents[3] / "run.json"
                run = json.loads(run_path.read_text(encoding="utf-8"))
                run.pop("run_sha256")
                run[field] = replacement
                run["run_sha256"] = canonical_sha256(run)
                run_path.write_text(json.dumps(run), encoding="utf-8")

                with self.assertRaisesRegex(ValueError, "run metadata is invalid"):
                    word_export_broker.validate_request(request, root=root)

    def test_vnext_request_rejects_tampered_run_hash(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request = self._vnext_request(root)
            run_path = request.parents[3] / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["run_mode"] = "production"
            run_path.write_text(json.dumps(run), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "run metadata is invalid"):
                word_export_broker.validate_request(request, root=root)

    def test_vnext_request_rejects_nearby_but_noncanonical_attempt_layout(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request = self._vnext_request(root)
            wrong_attempt = request.parents[3] / "word_qa" / "attempt-001-deadbeef"
            wrong_attempt.mkdir(parents=True)
            wrong_request = wrong_attempt / word_export_broker.REQUEST_NAME
            wrong_request.write_bytes(request.read_bytes())

            with self.assertRaisesRegex(ValueError, "directory depth is invalid"):
                word_export_broker.validate_request(wrong_request, root=root)

    def test_pending_scan_processes_only_legacy_and_exact_vnext_patterns(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            legacy = self._legacy_request(root)
            vnext = self._vnext_request(root)
            decoy = (
                vnext.parents[3]
                / "delivery_assets"
                / "not_word_qa"
                / "attempt-001-deadbeef"
                / word_export_broker.REQUEST_NAME
            )
            decoy.parent.mkdir(parents=True)
            decoy.write_bytes(vnext.read_bytes())

            def fake_export(_docx: Path, pdf: Path, *, timeout: int) -> None:
                self.assertEqual(timeout, 480)
                pdf.write_bytes(b"pdf")

            with patch.object(
                word_export_broker,
                "_export_word_com",
                side_effect=fake_export,
            ):
                results = word_export_broker.run_pending(
                    root=root,
                    quiet_seconds=0,
                )

            self.assertEqual(len(results), 2)
            self.assertTrue(all(item["status"] == "success" for item in results))
            self.assertTrue((legacy.parent / word_export_broker.RESPONSE_NAME).is_file())
            self.assertTrue((vnext.parent / word_export_broker.RESPONSE_NAME).is_file())
            self.assertFalse((decoy.parent / word_export_broker.RESPONSE_NAME).exists())


if __name__ == "__main__":
    unittest.main()
