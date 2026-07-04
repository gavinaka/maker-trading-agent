from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from outputs.render_from_combined import (
    preflight,
    render_canonical,
    sha256_file,
)
from outputs import word_qa
from outputs import publish_report
from runtime.delivery_evidence import validate_delivery_evidence


class RenderPipelineTests(unittest.TestCase):
    def test_canonical_render_is_idempotent_and_single_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "outputs" / "2026-06-30_midday_combined.md"
            source.parent.mkdir(parents=True)
            source.write_text(
                "# 2026-06-30 午间日报（15:30 评分点）\n\n"
                "## ① 日报正文\n\n不能做：追多\n",
                encoding="utf-8",
            )
            first = render_canonical(
                source,
                "2026-06-30",
                "midday",
                root=root,
            )
            second = render_canonical(
                source,
                "2026-06-30",
                "midday",
                root=root,
            )
            self.assertFalse(first["cache_hit"])
            self.assertTrue(second["cache_hit"])
            self.assertEqual(first["attempts"], 1)
            self.assertEqual(
                list((root / "outputs").glob("2026-06-30_midday*.docx")),
                [root / "outputs" / "2026-06-30_midday_render.docx"],
            )

    def test_preflight_blocks_lone_marker_and_bad_title(self):
        with self.assertRaisesRegex(ValueError, "lone blockquote marker"):
            preflight(
                ["# 2026-06-30 午间日报", ">"],
                "2026-06-30",
                "midday",
            )
        with self.assertRaisesRegex(ValueError, "forbidden"):
            preflight(
                ["# 2026-06-30_midday_combined_v2.md 日报"],
                "2026-06-30",
                "midday",
            )

    def test_no_h1_gets_safe_slot_title(self):
        title = preflight(
            ["## ① 晚间日报正文", "不能做：追空"],
            "2026-06-30",
            "evening",
        )
        self.assertEqual(title, "2026-06-30 晚间日报")

    def test_historical_630_samples_cover_original_failures(self):
        root = Path(__file__).resolve().parents[1]
        midday = (
            root / "outputs" / "2026-06-30_midday_combined_v2.md"
        ).read_text(encoding="utf-8").splitlines()
        evening = (
            root / "outputs" / "2026-06-30_evening_combined.md"
        ).read_text(encoding="utf-8").splitlines()
        with self.assertRaisesRegex(ValueError, "lone blockquote marker"):
            preflight(midday, "2026-06-30", "midday")
        self.assertEqual(
            preflight(evening, "2026-06-30", "evening"),
            "2026-06-30 晚间日报",
        )
        with tempfile.TemporaryDirectory() as td:
            test_root = Path(td)
            source = test_root / "outputs" / "2026-06-30_evening_combined.md"
            source.parent.mkdir(parents=True)
            source.write_text("\n".join(evening) + "\n", encoding="utf-8")
            result = render_canonical(
                source,
                "2026-06-30",
                "evening",
                root=test_root,
            )
            from docx import Document

            document = Document(result["docx_path"])
            self.assertEqual(document.paragraphs[0].text, "2026-06-30 晚间日报")

    def test_third_render_attempt_is_hard_stopped(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "outputs" / "2026-06-30_morning_combined.md"
            source.parent.mkdir(parents=True)
            source.write_text(
                "# 2026-06-30 早间日报\n\n## ① 日报正文\n",
                encoding="utf-8",
            )
            state = root / "runtime_state" / "2026-06-30"
            state.mkdir(parents=True)
            (state / "render_morning.json").write_text(
                json.dumps({"status": "failed", "attempts": 2}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "third attempt"):
                render_canonical(source, "2026-06-30", "morning", root=root)

    def test_existing_chinese_named_docx_blocks_duplicate_generation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "outputs" / "2026-06-30_evening_combined.md"
            source.parent.mkdir(parents=True)
            source.write_text(
                "# 2026-06-30 晚间日报\n\n## ① 晚间日报正文\n",
                encoding="utf-8",
            )
            (source.parent / "2026-06-30_晚间日报.docx").write_bytes(b"legacy")
            with self.assertRaisesRegex(ValueError, "non-canonical"):
                render_canonical(source, "2026-06-30", "evening", root=root)


class WordQaTests(unittest.TestCase):
    def _seed_render(self, root: Path) -> Path:
        docx = root / "outputs" / "2026-06-30_morning_render.docx"
        docx.parent.mkdir(parents=True)
        docx.write_bytes(b"docx")
        state = root / "runtime_state" / "2026-06-30"
        state.mkdir(parents=True)
        (state / "render_morning.json").write_text(
            json.dumps(
                {
                    "status": "success",
                    "docx_sha256": word_qa.sha256_file(docx),
                }
            ),
            encoding="utf-8",
        )
        return docx

    def test_export_cache_and_visual_approval_are_hash_bound(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._seed_render(root)

            def fake_export(_docx, pdf, timeout=300):
                pdf.write_bytes(b"pdf")

            def fake_pages(_pdf, prefix, _poppler):
                page = prefix.parent / "page-1.png"
                page.write_bytes(b"png")
                return [page]

            fake_poppler = root / "pdftoppm.exe"
            fake_poppler.write_bytes(b"exe")
            with patch.object(word_qa, "_export_word_com", fake_export), patch.object(
                word_qa, "_render_pdf", fake_pages
            ), patch.object(word_qa, "_find_pdftoppm", return_value=fake_poppler):
                first = word_qa.prepare_qa(
                    "2026-06-30", "morning", root=root
                )
                second = word_qa.prepare_qa(
                    "2026-06-30", "morning", root=root
                )
            self.assertEqual(first["status"], "prepared")
            self.assertTrue(second["cache_hit"])
            passed = word_qa.approve_qa(
                "2026-06-30",
                "morning",
                reviewer="max-model",
                root=root,
            )
            self.assertEqual(passed["status"], "passed")
            self.assertTrue(passed["visual_qa_pass"])

    def test_two_failures_block_third_export(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._seed_render(root)
            with patch.object(
                word_qa,
                "_export_word_com",
                side_effect=RuntimeError("injected COM failure"),
            ):
                for _ in range(2):
                    with self.assertRaisesRegex(RuntimeError, "injected"):
                        word_qa.prepare_qa(
                            "2026-06-30", "morning", root=root
                        )
                with self.assertRaisesRegex(RuntimeError, "third attempt"):
                    word_qa.prepare_qa(
                        "2026-06-30", "morning", root=root
                    )

    def test_visual_rejection_cannot_reexport_unchanged_docx(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._seed_render(root)

            def fake_export(_docx, pdf, timeout=300):
                pdf.write_bytes(b"pdf")

            def fake_pages(_pdf, prefix, _poppler):
                page = prefix.parent / "page-1.png"
                page.write_bytes(b"png")
                return [page]

            fake_poppler = root / "pdftoppm.exe"
            fake_poppler.write_bytes(b"exe")
            with patch.object(word_qa, "_export_word_com", fake_export), patch.object(
                word_qa, "_render_pdf", fake_pages
            ), patch.object(word_qa, "_find_pdftoppm", return_value=fake_poppler):
                word_qa.prepare_qa("2026-06-30", "morning", root=root)
            word_qa.reject_qa(
                "2026-06-30",
                "morning",
                reason="title layout is visibly incorrect",
                root=root,
            )
            with self.assertRaisesRegex(RuntimeError, "unchanged"):
                word_qa.prepare_qa("2026-06-30", "morning", root=root)


class DeliveryEvidenceTests(unittest.TestCase):
    def _seed(self, root: Path) -> tuple[dict, str]:
        date = "2026-06-30"
        slot = "morning"
        page_id = "38ffda35-a098-817d-8e2b-fa12afe16d8c"
        outputs = root / "outputs"
        state = root / "runtime_state" / date
        qa_dir = state / "word_qa" / slot / "attempt-1-test"
        sessions = root / "sessions"
        outputs.mkdir(parents=True)
        qa_dir.mkdir(parents=True)
        sessions.mkdir(parents=True)
        report = outputs / f"{date}_{slot}_combined.md"
        docx = outputs / f"{date}_{slot}_render.docx"
        pdf = qa_dir / f"{date}_{slot}_render.pdf"
        page = qa_dir / "page-1.png"
        report.write_text("# report", encoding="utf-8")
        docx.write_bytes(b"docx")
        pdf.write_bytes(b"pdf")
        page.write_bytes(b"png")
        report_hash = sha256_file(report)
        docx_hash = sha256_file(docx)
        now = datetime.now(timezone.utc) - timedelta(seconds=2)
        (state / f"render_{slot}.json").write_text(
            json.dumps(
                {
                    "status": "success",
                    "trading_date": date,
                    "slot": slot,
                    "source_sha256": report_hash,
                    "docx_path": str(docx),
                    "docx_sha256": docx_hash,
                }
            ),
            encoding="utf-8",
        )
        (state / f"word_qa_{slot}.json").write_text(
            json.dumps(
                {
                    "status": "passed",
                    "visual_qa_pass": True,
                    "trading_date": date,
                    "slot": slot,
                    "backend": "word_com",
                    "docx_path": str(docx),
                    "docx_sha256": docx_hash,
                    "pdf_path": str(pdf),
                    "pdf_sha256": sha256_file(pdf),
                    "pages": [{"path": str(page), "sha256": sha256_file(page)}],
                    "reviewed_at": now.isoformat(),
                }
            ),
            encoding="utf-8",
        )
        (state / f"publish_{slot}.json").write_text(
            json.dumps(
                {
                    "status": "success",
                    "trading_date": date,
                    "slot": slot,
                    "page_id": page_id,
                    "frozen_verifier_pass": True,
                    "unique_page_pass": True,
                    "report_sha256": report_hash,
                    "published_at": now.isoformat(),
                }
            ),
            encoding="utf-8",
        )
        (sessions / "context_log.md").write_text(
            f"## {date}（早间日报）\n"
            f"- Word 逐页视觉 QA PASS。\n"
            f"- Notion 最终页=`{page_id}`，冻结 verifier PASS。\n",
            encoding="utf-8",
        )
        return {"slot": slot, "report_sha256": report_hash}, page_id

    def test_delivery_requires_real_hash_closed_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            current, page_id = self._seed(root)
            evidence = validate_delivery_evidence(
                "2026-06-30",
                "morning",
                page_id,
                current=current,
                root=root,
            )
            self.assertEqual(evidence["docx_sha256"], sha256_file(
                root / "outputs" / "2026-06-30_morning_render.docx"
            ))

    def test_delivery_rejects_pass_recorded_before_qa(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            current, page_id = self._seed(root)
            context = root / "sessions" / "context_log.md"
            old = datetime.now().timestamp() - 3600
            os.utime(context, (old, old))
            with self.assertRaisesRegex(ValueError, "predates"):
                validate_delivery_evidence(
                    "2026-06-30",
                    "morning",
                    page_id,
                    current=current,
                    root=root,
                )


class PublishEvidenceTests(unittest.TestCase):
    def test_publish_manifest_makes_identical_retry_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            outputs = root / "outputs"
            sources = root / "data_sources" / "inbox" / "2026-06-30"
            outputs.mkdir(parents=True)
            sources.mkdir(parents=True)
            report = outputs / "2026-06-30_morning_combined.md"
            report.write_text("# 2026-06-30 早间日报\n", encoding="utf-8")
            image = outputs / "card.png"
            image.write_bytes(b"png")
            labels = publish_report.REQUIRED_SOURCE_LABELS
            source_specs = {}
            for label in labels:
                path = sources / f"{label}.dat"
                path.write_bytes(label.encode("ascii"))
                source_specs[label] = {"path": str(path)}
            payload = outputs / "payload.json"
            payload.write_text(
                json.dumps(
                    {
                        "date": "2026.6.30",
                        "title": "🌅 2026.6.30 早间日报",
                        "title_prefix": "🌅",
                        "verifier_mode": "morning",
                        "report_path": str(report),
                        "source_specs": source_specs,
                        "children": [],
                        "image_after_heading": "基本面",
                        "image_paths": [str(image)],
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(publish_report, "ROOT", root), patch.object(
                publish_report, "assert_source_freshness"
            ), patch.object(publish_report, "run_report_lint"), patch.object(
                publish_report, "ensure_date_page", return_value="parent"
            ), patch.object(
                publish_report,
                "replace_page_transactional",
                return_value=("page-id", []),
            ) as replace:
                first = publish_report.publish(payload)
                second = publish_report.publish(payload)
            self.assertEqual(first["status"], "success")
            self.assertTrue(second["cache_hit"])
            self.assertEqual(replace.call_count, 1)
            manifest = json.loads(
                (
                    root
                    / "runtime_state"
                    / "2026-06-30"
                    / "publish_morning.json"
                ).read_text(encoding="utf-8")
            )
            self.assertTrue(manifest["frozen_verifier_pass"])
            self.assertTrue(manifest["unique_page_pass"])


if __name__ == "__main__":
    unittest.main()
