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
from outputs.report_structure_gate import (
    assert_combined_structure,
    expected_title,
    validate_combined_structure,
)
from outputs import word_qa
from outputs import publish_report
from outputs import notion_push_lib
from outputs import daily_color_template
from outputs import daily_payload_builder
from outputs import review_contract
from outputs import review_payload_builder
from runtime.delivery_evidence import validate_delivery_evidence
from runtime.session_runner import validate_report_structure


class RenderPipelineTests(unittest.TestCase):
    def _strict_valid_report(self, title: str | None = None) -> list[str]:
        title = title or "# 2026.7.5 早间日报"
        return [
            title,
            "",
            "> 北京时间 2026-07-05 08:48-08:58 采集；六源有效。",
            "",
            "## ① 正文",
            "",
            "## 不能做",
            "",
            "不能做：追多。",
            "",
            "### 基本面：中性偏空，价格已兑现部分",
            "",
            "BlockBeats 与 Farside 提供基本面输入。",
            "",
            "### 技术面",
            "",
            "盘口（合约）：CVD上升，价格上升，资金费率上升，持仓横盘。",
            "",
            "### 解读",
            "",
            "盘面：中性偏空。",
            "",
            "### 趋势确认",
            "",
            "趋势确认：震荡结构。",
            "",
            "### 日内支撑/压力",
            "",
            "日内支撑：62,600-62,900。日内压力：63,300-63,800。",
            "",
            "### 策略",
            "",
            "主账户观察。",
            "",
            "## ② Maker 计划",
            "",
            "BTC（策略）：观望·不挂单。",
            "",
            "## ③ 后附",
            "",
            "BlockBeats：有效。",
            "Coinglass：有效。",
            "Exocharts：有效。",
            "FedWatch：有效。",
            "Farside BTC ETF Flow：有效。",
            "TradingView：有效。",
            "胜率：56%。风险：观望日无新单。情景：看多与看空路径均已列出。",
        ]

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

    def test_strict_no_h1_is_blocked(self):
        with self.assertRaisesRegex(ValueError, "title.count"):
            preflight(
                ["## ① 正文", "不能做：追空"],
                "2026-07-05",
                "evening",
            )

    def test_strict_structure_gate_accepts_canonical_skeleton(self):
        lines = self._strict_valid_report()
        self.assertEqual(
            assert_combined_structure(lines, "2026-07-05", "morning"),
            expected_title("2026-07-05", "morning"),
        )

    def test_strict_structure_gate_blocks_iso_title_and_missing_body_root(self):
        bad_title = self._strict_valid_report("# 2026-07-05 早间日报")
        _, issues = validate_combined_structure(bad_title, "2026-07-05", "morning")
        self.assertTrue(any(issue.code == "title.display_date" for issue in issues))

        missing_body = [line for line in self._strict_valid_report() if line != "## ① 正文"]
        _, issues = validate_combined_structure(missing_body, "2026-07-05", "morning")
        self.assertTrue(any(issue.code == "skeleton.h2_missing" for issue in issues))

    def test_strict_structure_gate_blocks_raw_hr_and_legacy_five_sources(self):
        lines = self._strict_valid_report()
        lines.insert(12, "---")
        lines.append("五源旧口径")
        _, issues = validate_combined_structure(lines, "2026-07-05", "morning")
        self.assertTrue(any(issue.code == "markdown.raw_hr" for issue in issues))
        self.assertTrue(any(issue.code == "sources.legacy_five" for issue in issues))

    def test_strict_structure_gate_requires_farside_as_sixth_source(self):
        lines = [line for line in self._strict_valid_report() if "Farside" not in line]
        _, issues = validate_combined_structure(lines, "2026-07-05", "morning")
        self.assertTrue(
            any(
                issue.code == "sources.six_missing" and "Farside" in issue.message
                for issue in issues
            )
        )

    def test_session_runner_blocks_bad_structure_before_lock_or_commit(self):
        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "2026-07-05_morning_combined.md"
            report.write_text(
                "# 2026-07-05 早间日报\n\n"
                "## 不能做：追多\n\n"
                "### 基本面：中性偏空（细节塞进标题）价格已兑现部分\n\n"
                "---\n\n"
                "## ③ 后附\n\n"
                "BlockBeats / Coinglass / Exocharts / FedWatch / Farside / TradingView\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "report structure gate failed"):
                validate_report_structure(report, "2026-07-05", "morning")

    def test_inline_samples_cover_original_630_render_failures(self):
        midday = """
# 2026.6.30 午间日报
>
## ③ 后附
BlockBeats / Coinglass / Exocharts / FedWatch / TradingView
""".splitlines()
        evening = """
# 2026.6.30 晚间日报
## ① 正文
### 基本面
中性。
## ③ 后附
BlockBeats / Coinglass / Exocharts / FedWatch / TradingView
""".splitlines()
        with self.assertRaisesRegex(ValueError, "lone blockquote marker"):
            preflight(midday, "2026-06-30", "midday")
        self.assertEqual(
            preflight(evening, "2026-06-30", "evening"),
            "2026.6.30 晚间日报",
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
            self.assertEqual(document.paragraphs[0].text, "2026.6.30 晚间日报")

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

    def test_word_export_attaches_only_to_hidden_idle_instance(self):
        script = word_qa._word_com_export_script(
            Path("C:/reports/input's.docx"),
            Path("C:/reports/output.pdf"),
        )

        self.assertIn("GetActiveObject('Word.Application')", script)
        self.assertIn("(-not [bool]$candidate.Visible)", script)
        self.assertIn("$candidate.Documents.Count -eq 0", script)
        self.assertIn("$ownsWord=$false", script)
        self.assertIn("New-Object -ComObject Word.Application", script)
        self.assertIn("if($ownsWord){$word.Quit()}", script)
        self.assertNotIn("if($word){$word.Quit()}", script)
        self.assertIn("input''s.docx", script)

    def test_logon_session_failure_falls_back_to_interactive_task(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            docx = root / "outputs" / "2026-06-30_morning_render.docx"
            pdf = (
                root
                / "runtime_state"
                / "2026-06-30"
                / "word_qa"
                / "morning"
                / "attempt-1-test"
                / "2026-06-30_morning_render.pdf"
            )
            with patch.object(
                word_qa,
                "_export_word_com",
                side_effect=RuntimeError("Word COM export failed: 80070520"),
            ), patch.object(word_qa, "_export_word_via_interactive_task") as broker:
                backend = word_qa._export_word(
                    docx,
                    pdf,
                    trading_date="2026-06-30",
                    slot="morning",
                    docx_sha256="a" * 64,
                    root=root,
                )
            self.assertEqual(backend, "word_com_interactive_task")
            broker.assert_called_once()

    def test_non_session_com_failure_does_not_use_interactive_task(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch.object(
                word_qa,
                "_export_word_com",
                side_effect=RuntimeError("Word COM export failed: corrupt document"),
            ), patch.object(word_qa, "_export_word_via_interactive_task") as broker:
                with self.assertRaisesRegex(RuntimeError, "corrupt document"):
                    word_qa._export_word(
                        root / "input.docx",
                        root / "output.pdf",
                        trading_date="2026-06-30",
                        slot="morning",
                        docx_sha256="a" * 64,
                        root=root,
                    )
            broker.assert_not_called()

    def test_interactive_broker_requires_fresh_ready_heartbeat(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            heartbeat = root / "runtime_state" / word_qa.BROKER_HEARTBEAT
            heartbeat.parent.mkdir(parents=True)
            heartbeat.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "status": "ready",
                        "updated_at": datetime.now().astimezone().isoformat(
                            timespec="seconds"
                        ),
                    }
                ),
                encoding="utf-8",
            )
            result = word_qa._assert_interactive_broker_ready(root)
            self.assertEqual(result["status"], "ready")
            heartbeat.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "status": "stopped",
                        "updated_at": datetime.now().astimezone().isoformat(
                            timespec="seconds"
                        ),
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(word_qa.WordExportError, "stale"):
                word_qa._assert_interactive_broker_ready(root)

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

    def test_80070520_failures_allow_one_hash_bound_broker_migration(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            docx = self._seed_render(root)
            state = root / "runtime_state" / "2026-06-30"
            (state / "word_qa_morning.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "status": "failed",
                        "attempts": 2,
                        "docx_sha256": word_qa.sha256_file(docx),
                        "failure_reason": "Word COM export failed: 80070520",
                    }
                ),
                encoding="utf-8",
            )
            (root / "runtime_state" / word_qa.BROKER_HEARTBEAT).write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "status": "ready",
                        "updated_at": datetime.now().astimezone().isoformat(
                            timespec="seconds"
                        ),
                    }
                ),
                encoding="utf-8",
            )

            def fake_broker(_docx, pdf, **_kwargs):
                pdf.write_bytes(b"pdf")

            def fake_pages(_pdf, prefix, _poppler):
                page = prefix.parent / "page-1.png"
                page.write_bytes(b"png")
                return [page]

            fake_poppler = root / "pdftoppm.exe"
            fake_poppler.write_bytes(b"exe")
            with patch.object(
                word_qa,
                "_export_word_com",
                side_effect=RuntimeError("Word COM export failed: 80070520"),
            ), patch.object(
                word_qa, "_export_word_via_interactive_task", fake_broker
            ), patch.object(word_qa, "_render_pdf", fake_pages), patch.object(
                word_qa, "_find_pdftoppm", return_value=fake_poppler
            ):
                result = word_qa.prepare_qa(
                    "2026-06-30", "morning", root=root
                )
            self.assertEqual(result["status"], "prepared")
            self.assertEqual(result["attempts"], 3)
            self.assertEqual(result["backend"], "word_com_interactive_task")
            self.assertTrue(result["infrastructure_recovery_used"])
            self.assertEqual(
                result["attempt_limit_exception"]["previous_attempts"], 2
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
    def _seed(
        self,
        root: Path,
        date: str = "2026-06-30",
        slot: str = "morning",
    ) -> tuple[dict, str]:
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
        capture_manifest = {
            "path": "captures/morning/full_base_run1234567890abcdef.json",
            "sha256": "c" * 64,
            "evidence_snapshot": {
                "root": "evidence/morning/run1234567890abcdef",
            },
        }
        source_binding = {
            "capture_manifest_path": (
                f"runtime_state/{date}/"
                f"captures/{slot}/full_base_run1234567890abcdef.json"
            ),
            "capture_manifest_sha256": "c" * 64,
            "evidence_snapshot_root": (
                f"runtime_state/{date}/evidence/{slot}/run1234567890abcdef"
            ),
            "sources": {},
        }
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
                    "source_binding": source_binding,
                    "published_at": now.isoformat(),
                }
            ),
            encoding="utf-8",
        )
        (sessions / "context_log.md").write_text(
            f"## {date}（早间日报）\n"
            f"- 报告 SHA-256=`{report_hash}`，Word SHA-256=`{docx_hash}`。\n"
            f"- Word 逐页视觉 QA PASS。\n"
            f"- render manifest=`runtime_state/{date}/render_{slot}.json`，"
            f"Word QA manifest=`runtime_state/{date}/word_qa_{slot}.json`，"
            f"publish manifest=`runtime_state/{date}/publish_{slot}.json`。\n"
            f"- Notion 最终页=`{page_id}`，冻结 verifier PASS。\n",
            encoding="utf-8",
        )
        return {
            "slot": slot,
            "report_sha256": report_hash,
            "capture_manifest": capture_manifest,
        }, page_id

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

    def test_delivery_accepts_only_fully_bound_interactive_word_backend(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            current, page_id = self._seed(root)
            qa_path = root / "runtime_state" / "2026-06-30" / "word_qa_morning.json"
            qa = json.loads(qa_path.read_text(encoding="utf-8"))
            qa.update(
                {
                    "backend": "word_com_interactive_task",
                    "attempts": 3,
                    "infrastructure_recovery_used": True,
                    "attempt_limit_exception": {
                        "kind": "word_com_logon_session_to_interactive_broker",
                        "previous_attempts": 2,
                        "previous_failure_reason": "Word COM export failed: 80070520",
                    },
                }
            )
            qa_path.write_text(json.dumps(qa), encoding="utf-8")
            pdf = Path(qa["pdf_path"])
            request_id = "a" * 32
            request = {
                "schema_version": "1.0",
                "request_id": request_id,
                "trading_date": "2026-06-30",
                "slot": "morning",
                "docx_path": qa["docx_path"],
                "docx_sha256": qa["docx_sha256"],
                "pdf_path": qa["pdf_path"],
            }
            response = {
                **request,
                "status": "success",
                "backend": "word_com_interactive_task",
                "pdf_sha256": qa["pdf_sha256"],
            }
            (pdf.parent / "broker_request.json").write_text(
                json.dumps(request), encoding="utf-8"
            )
            (pdf.parent / "broker_response.json").write_text(
                json.dumps(response), encoding="utf-8"
            )
            evidence = validate_delivery_evidence(
                "2026-06-30",
                "morning",
                page_id,
                current=current,
                root=root,
            )
            self.assertEqual(evidence["docx_sha256"], qa["docx_sha256"])

            qa.pop("infrastructure_recovery_used")
            qa_path.write_text(json.dumps(qa), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "recovery_used"):
                validate_delivery_evidence(
                    "2026-06-30",
                    "morning",
                    page_id,
                    current=current,
                    root=root,
                )

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

    def test_delivery_rejects_context_log_without_hash_binding(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            current, page_id = self._seed(root)
            context = root / "sessions" / "context_log.md"
            context.write_text(
                "## 2026-06-30（早间日报）\n"
                f"- Word 逐页视觉 QA PASS。\n"
                f"- Notion 最终页=`{page_id}`，冻结 verifier PASS。\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "report_sha256"):
                validate_delivery_evidence(
                    "2026-06-30",
                    "morning",
                    page_id,
                    current=current,
                    root=root,
                )

    def test_delivery_rejects_publish_without_source_binding(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            current, page_id = self._seed(root)
            publish = root / "runtime_state" / "2026-06-30" / "publish_morning.json"
            payload = json.loads(publish.read_text(encoding="utf-8"))
            payload.pop("source_binding")
            publish.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "source binding"):
                validate_delivery_evidence(
                    "2026-06-30",
                    "morning",
                    page_id,
                    current=current,
                    root=root,
                )

    def test_strict_delivery_requires_gold_verifier_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            current, page_id = self._seed(root, date="2026-07-05")
            with self.assertRaisesRegex(ValueError, "strict publish quality"):
                validate_delivery_evidence(
                    "2026-07-05",
                    "morning",
                    page_id,
                    current=current,
                    root=root,
                )

    def test_strict_delivery_accepts_hash_bound_gold_verifier_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            current, page_id = self._seed(root, date="2026-07-05")
            publish = root / "runtime_state" / "2026-07-05" / "publish_morning.json"
            payload = json.loads(publish.read_text(encoding="utf-8"))
            payload["notion_payload_shape"] = {
                "status": "passed",
                "block_count_before_images": 25,
                "image_count": 3,
            }
            payload["notion_payload_source"] = {
                "status": "passed",
                "kind": "combined_md_to_notion_payload",
                "generator": "daily_payload_builder",
                "generator_version": "1.0",
            }
            payload["notion_payload_colors"] = {
                "status": "passed",
                "template": "daily-gold-run-colors-v1",
            }
            payload["frozen_verifier"] = {
                "script": "C:\\repo\\outputs\\notion_verify_against_yesterday.py",
                "args": [page_id, "morning"],
                "returncode": 0,
                "stdout": "[PASS] ALL CHECKS PASS\n",
                "stderr": "",
            }
            publish.write_text(json.dumps(payload), encoding="utf-8")
            evidence = validate_delivery_evidence(
                "2026-07-05",
                "morning",
                page_id,
                current=current,
                root=root,
            )
            self.assertEqual(evidence["published_at"], payload["published_at"])


class PublishEvidenceTests(unittest.TestCase):
    def _text_block(self, block_type: str, text: str) -> dict:
        return {
            "object": "block",
            "type": block_type,
            block_type: {"rich_text": [{"type": "text", "text": {"content": text}}]},
        }

    def _table_row(self, cells: list[str]) -> dict:
        return {
            "type": "table_row",
            "table_row": {
                "cells": [
                    [{"type": "text", "text": {"content": cell}}]
                    for cell in cells
                ]
            },
        }

    def _table_block(self, rows: list[list[str]]) -> dict:
        return {
            "object": "block",
            "type": "table",
            "table": {
                "table_width": len(rows[0]),
                "has_column_header": True,
                "has_row_header": False,
                "children": [self._table_row(row) for row in rows],
            },
        }

    def _review_payload_children(self) -> list[dict]:
        score_rows = [
            ["维度", "前一晚报", "当天早报", "当天午报", "综合"],
            ["方向判断", "72", "66", "88", "75"],
            ["入场结构", "68", "64", "86", "73"],
            ["风险框架", "70", "76", "84", "77"],
            ["数据精度", "74", "67", "82", "74"],
            ["内在一致性", "71", "69", "85", "75"],
            ["综合", "71", "68", "85", "75"],
        ]
        price_rows = [
            ["区域", "前序段", "当晚含义", "当前计划处理", "审查意见"],
            ["63,650-63,850", "当天午报", "反弹空验证区", "等待反抽确认", "午报节奏最接近后续走势"],
            ["62,940-63,120", "前一晚报", "旧压力带被上刺后失效", "不沿用旧止损", "压力识别有用但宽度不足"],
            ["62,400-62,760", "当天早报", "低多防守区被跌破", "不追随早报方向", "止损框架有效但方向失效"],
        ]
        return [
            self._text_block(
                "callout",
                "审查结论：通过。三段前序计划均已按价格行为倒推评分，当前晚报未复用旧方向。",
            ),
            self._text_block("heading_2", "一、综合评分（去系统逻辑 · 独立打分）"),
            self._table_block(score_rows),
            self._text_block("heading_2", "二、价格阶梯与三段倒推落点"),
            self._table_block(price_rows),
            self._text_block(
                "callout",
                "核心矛盾：价格跌破午报支撑，但基本面没有给出同等强度的新增空头证据。",
            ),
            self._text_block("heading_2", "三、关键发现"),
            self._text_block("paragraph", "发现一：前一晚报识别了压力区，但止损宽度不足。"),
            self._text_block("paragraph", "发现二：当天早报低多方向失效，防守规则仍限制了错误。"),
            self._text_block("paragraph", "发现三：当天午报反弹空与后续回落最一致。"),
            self._text_block("paragraph", "发现四：当前晚报应等待反抽质量，不应在低位追空。"),
            self._text_block("paragraph", "发现五：三段差异来自新价格结构，而不是沿用旧判断。"),
            self._text_block("paragraph", "发现六：当前计划的有效性取决于反抽区的成交反应。"),
            self._text_block(
                "paragraph",
                "审查边界：本审查仅对前一晚报、当天早报、当天午报与当前晚报做价格行为倒推，不判断账户成交或持仓。",
            ),
            self._text_block(
                "paragraph",
                "复盘结论：当前晚报可以作为独立计划进入交付，但后续需记录前两段误差来源。",
            ),
        ]

    def _review_manifest(self, date: str, report_rel: str, report_sha: str) -> dict:
        scores = {
            "方向判断": 70,
            "入场结构": 71,
            "风险框架": 72,
            "数据精度": 73,
            "内在一致性": 74,
            "综合": 72,
        }
        return {
            "schema_version": "evening-independent-review-v2",
            "trading_date": date,
            "slot": "evening",
            "report_path": report_rel,
            "report_sha256": report_sha,
            "inputs": [
                {"label": "前一晚报", "path": "outputs/previous_evening.md"},
                {"label": "当天早报", "path": "outputs/morning.md"},
                {"label": "当天午报", "path": "outputs/midday.md"},
                {"label": "当前晚报", "path": report_rel},
            ],
            "segments": [
                {"label": "前一晚报", "scores": dict(scores), "conclusion": "压力识别有用。"},
                {"label": "当天早报", "scores": dict(scores), "conclusion": "方向失效。"},
                {"label": "当天午报", "scores": dict(scores), "conclusion": "验证最强。"},
            ],
            "page": {
                "intro": "审查结论：通过。三段前序计划均已按价格行为倒推评分，当前晚报未复用旧方向。",
                "core_conflict": "核心矛盾：价格跌破午报支撑，但基本面没有给出同等强度的新增空头证据。",
                "price_ladder": [
                    {
                        "zone": "63,650-63,850",
                        "segment": "当天午报",
                        "meaning": "反弹空验证区",
                        "current_plan": "等待反抽确认",
                        "review": "午报节奏最接近后续走势",
                    },
                    {
                        "zone": "62,940-63,120",
                        "segment": "前一晚报",
                        "meaning": "旧压力带被上刺后失效",
                        "current_plan": "不沿用旧止损",
                        "review": "压力识别有用但宽度不足",
                    },
                    {
                        "zone": "62,400-62,760",
                        "segment": "当天早报",
                        "meaning": "低多防守区被跌破",
                        "current_plan": "不追随早报方向",
                        "review": "止损框架有效但方向失效",
                    },
                ],
                "findings": [
                    "发现一：前一晚报识别了压力区，但止损宽度不足。",
                    "发现二：当天早报低多方向失效，防守规则仍限制了错误。",
                    "发现三：当天午报反弹空与后续回落最一致。",
                    "发现四：当前晚报应等待反抽质量，不应在低位追空。",
                    "发现五：三段差异来自新价格结构，而不是沿用旧判断。",
                    "发现六：当前计划的有效性取决于反抽区的成交反应。",
                ],
                "boundary": "审查边界：本审查仅对前一晚报、当天早报、当天午报与当前晚报做价格行为倒推，不判断账户成交或持仓。",
                "final_conclusion": "复盘结论：当前晚报可以作为独立计划进入交付，但后续需记录前两段误差来源。",
            },
        }

    def _daily_payload_children(self, slot: str = "morning") -> list[dict]:
        texts = {
            0: "北京时间 2026-07-05 08:00 采集；六源有效。",
            1: "不能做：追多",
            2: "基本面：中性偏空（测试）价格已兑现部分",
            3: "技术面",
            4: "盘口（合约）：",
            5: "CVD上升　价格上升　资金费率上升（为正值）　持仓横盘",
            6: "解读：中性偏空（测试）",
            7: "盘面：",
            8: "日线级别：中性偏空。",
            9: "小时级别：中性。",
            10: "趋势确认：震荡结构",
            11: "日内支撑：62,600-62,900　　日内压力：63,300-63,800",
            12: "策略",
            13: "主账户观察。",
            15: "BTC（策略）：观望·不挂单",
            16: "当前不挂单。",
            17: "止盈：今日无新挂单。",
            18: "止损：今日无新挂单。",
            19: "防守计划",
            20: "第一层：无。",
            21: "第二层：无。",
            22: "注意事项：无。",
            23: "取消价≠止损。",
            24: "独立边界：分析锁前未读取实际仓位。",
        }
        if slot == "evening":
            texts[25] = "独立边界：分析锁前未读取实际仓位。"
        blocks = []
        for index, block_type in enumerate(publish_report.DAILY_PAYLOAD_TYPES_BY_SLOT[slot]):
            if block_type == "divider":
                blocks.append({"object": "block", "type": "divider", "divider": {}})
                continue
            blocks.append(
                {
                    "object": "block",
                    "type": block_type,
                    block_type: {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {"content": texts.get(index, "")},
                            }
                        ]
                    },
                }
            )
        return blocks

    def _seed_publish_binding(self, root: Path, date: str = "2026-06-30", slot: str = "morning") -> dict:
        state = root / "runtime_state" / date
        snapshot_root = state / "evidence" / slot / "run1234567890abcdef"
        capture_dir = state / "captures" / slot
        snapshot_root.mkdir(parents=True)
        capture_dir.mkdir(parents=True)
        files = {
            "blockbeats": "blockbeats.png",
            "coinglass": "coinglass.png",
            "exocharts": "exocharts.png",
            "farside_btc_etf": "farside_btc_etf.png",
            "fedwatch": "fedwatch.png",
            "tradingview_1d": "tradingview_btc_1d.png",
            "tradingview_4h": "tradingview_btc_4h.png",
            "tradingview_1h": "tradingview_btc_1h.png",
            "tradingview_15m": "tradingview_btc_15m.png",
        }
        entries = []
        source_specs = {}
        for label, name in files.items():
            path = snapshot_root / name
            path.write_bytes(f"{label}:{name}".encode("ascii"))
            entries.append(
                {
                    "path": name,
                    "sha256": sha256_file(path),
                    "size": path.stat().st_size,
                }
            )
            source_specs[label] = {"path": str(path)}
        for name in ("blockbeats.json", "farside_btc_etf.json", "fedwatch.json"):
            path = snapshot_root / name
            path.write_text(json.dumps({"fixture": name}), encoding="utf-8")
            entries.append(
                {
                    "path": name,
                    "sha256": sha256_file(path),
                    "size": path.stat().st_size,
                }
            )
        capture = capture_dir / "full_base_run1234567890abcdef.json"
        capture_payload = {
            "schema_version": "1.0",
            "date": date,
            "slot": slot,
            "mode": "full_base",
            "run_id": "run1234567890abcdef",
            "success": True,
            "evidence_snapshot": {
                "root": f"evidence/{slot}/run1234567890abcdef",
                "files": entries,
            },
        }
        capture.write_text(json.dumps(capture_payload), encoding="utf-8")
        transition = {
            "schema_version": "3.0",
            "trading_date": date,
            "slot": slot,
            "capture_manifest": {
                "path": f"captures/{slot}/{capture.name}",
                "sha256": sha256_file(capture),
                "evidence_snapshot": capture_payload["evidence_snapshot"],
            },
        }
        (state / f"transition_{slot}.json").write_text(
            json.dumps(transition),
            encoding="utf-8",
        )
        return source_specs

    def test_locked_timepoint_publish_keeps_normal_freshness_hard_stop(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "coinglass.png"
            source.write_bytes(b"immutable evidence")
            stale_ts = datetime.now().timestamp() - 5 * 60 * 60
            os.utime(source, (stale_ts, stale_ts))
            specs = {
                "coinglass": {
                    "path": str(source),
                    "max_age_minutes": 240,
                }
            }

            with self.assertRaisesRegex(SystemExit, "SOURCE FRESHNESS FAILED"):
                publish_report.enforce_source_freshness(specs)

    def test_locked_timepoint_publish_requires_hash_bound_lock(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "coinglass.png"
            source.write_bytes(b"immutable evidence")
            specs = {"coinglass": {"path": str(source)}}

            with self.assertRaisesRegex(ValueError, "hash-bound analysis lock"):
                publish_report.enforce_source_freshness(
                    specs,
                    allow_locked_timepoint_publish=True,
                    locked_timepoint_reason=(
                        "User explicitly requested locked timepoint delivery"
                    ),
                    report_sha256="a" * 64,
                    source_binding={
                        "capture_manifest_sha256": "b" * 64,
                        "evidence_snapshot_root": "runtime_state/evidence/run",
                    },
                )

    def test_locked_timepoint_publish_records_audited_override(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "coinglass.png"
            source.write_bytes(b"immutable evidence")
            stale_ts = datetime.now().timestamp() - 5 * 60 * 60
            os.utime(source, (stale_ts, stale_ts))
            specs = {
                "coinglass": {
                    "path": str(source),
                    "max_age_minutes": 240,
                }
            }
            report_sha = "a" * 64
            capture_sha = "b" * 64

            result = publish_report.enforce_source_freshness(
                specs,
                allow_locked_timepoint_publish=True,
                locked_timepoint_reason=(
                    "User explicitly requested the immutable midday time-slice "
                    "without recapture"
                ),
                analysis_lock={
                    "commit_id": "c" * 64,
                    "report_sha256": report_sha,
                },
                source_binding={
                    "capture_manifest_sha256": capture_sha,
                    "evidence_snapshot_root": "runtime_state/evidence/run",
                },
                report_sha256=report_sha,
            )

            self.assertEqual(result["status"], "authorized_locked_timepoint")
            self.assertFalse(result["freshness_passed"])
            self.assertTrue(result["override_used"])
            self.assertEqual(result["capture_manifest_sha256"], capture_sha)
            self.assertGreater(
                result["source_ages"]["coinglass"]["age_minutes"], 240
            )

    def _strict_daily_combined_text(self, date: str = "2026-07-05", slot: str = "morning") -> str:
        slot_cn = {"morning": "早间", "midday": "午间", "evening": "晚间"}[slot]
        maker_strategy = (
            "反弹空：入场区间 62,940-63,120，持仓 500-1000 刀，Binance Maker，左侧，5x，盈亏比 1:2.5 以上。"
            if slot == "evening"
            else "低多：入场区间 62,560-62,650，挂单价 62,600，持仓 800 刀，OKX，左侧，5x，盈亏比 1:2.5 以上"
        )
        first_layer = (
            "第一层：价格下行至 61,850 后，将止损移动至入场后形成并确认的 4H K线结构性极点高点；同时取消所有加仓。"
            if slot == "evening"
            else "第一层：价格首次触及 63,140 后，将止损移至成交后新形成并确认的 4H 级别 K 线结构性极点低点，并取消所有加仓"
        )
        second_layer = (
            "第二层：价格下行至 61,250 后，设置保本损；不减仓。"
            if slot == "evening"
            else "第二层：价格触及 63,500 附近后，止损保持不低于开仓均价 62,600 的保本损"
        )
        note = (
            "注意事项：若价格未成交前优先跌破 62,300，则此策略取消。"
            if slot == "evening"
            else "注意事项：若价格未回踩入场区前优先触及 63,500，则取消此策略。"
        )
        cancel = (
            "取消价不是止损：62,300 是未成交前撤单价，63,660 是成交后止损价。"
            if slot == "evening"
            else "取消价不等于止损：未成交前触发 63,500 是取消策略；成交后跌破 62,240 才是止损。"
        )
        core = (
            "\n核心：只做反抽失败，不在支撑带追空；62,940-63,120 是 1H SMA20 与 VRVP 供给区。"
            if slot == "evening"
            else ""
        )
        final_boundary = "独立边界：本报告判断仅来自当次六源与开仓前状态门禁。"
        return "\n".join(
            [
                f"# 2026.7.5 {slot_cn}日报",
                "",
                "> 北京时间 2026-07-05 16:05-16:15 锁定采集；六源有效。",
                "",
                "## ① 正文",
                "",
                "### 基本面",
                "",
                "基本面：中性偏多（Farside 最新 Bitcoin ETF Flow 为 +223.5 US$m；FedWatch 未给出降息交易）价格已兑现部分",
                "",
                "### 技术面",
                "",
                "盘口（合约）：",
                "",
                "CVD上升 价格上升 资金费率上升（为正值） 持仓横盘",
                "",
                "### 解读",
                "",
                "解读：中性偏多（主动买盘确认但追涨盈亏比变差）",
                "",
                "盘面：",
                "",
                "日线级别：价格收在 62,948.90，重新站上日线 SMA20 的 62,038.56，但仍远低于 SMA200 的 74,755.74。中性偏多",
                "",
                "小时级别：4H 收 62,966.15，1H 收 63,021.41，重新站上 1H SMA20 的 62,974.20。中性偏多",
                "",
                "### 趋势确认",
                "",
                "趋势确认：多头趋势（短线）+ 震荡结构",
                "",
                "### 日内支撑/压力",
                "",
                "日内支撑：62,540-62,700　　日内压力：63,180-63,520",
                "",
                "### 策略",
                "",
                "策略：",
                "",
                "主账户不在 63,000 上方追高新增，继续等待更清晰的放量突破。",
                "",
                "## 不能做",
                "",
                "不能做：不能在压力下方追涨，不能在支撑带直接追空。",
                "",
                "## ② Maker 计划",
                "",
                "BTC（策略）：执行概率 45%（已执行 0%）　胜率 61%",
                "",
                maker_strategy,
                "",
                "止盈：TP1 63,500 减仓 50%；TP2 63,900 清剩余 50%，全计划 100% 闭合",
                "",
                "止损：62,240",
                "",
                "### 防守计划",
                "",
                first_layer,
                "",
                second_layer,
                "",
                note,
                "",
                cancel + core,
                "",
                final_boundary,
                "",
                "## ③ 后附",
                "",
                "BlockBeats、Coinglass、Exocharts、FedWatch、Farside BTC ETF Flow、TradingView 六源均有效。",
            ]
        )

    def _seed_blockbeat_cards(self, root: Path, date: str, slot: str) -> list[Path]:
        card_dir = root / "outputs" / "blockbeats"
        card_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for index in range(1, 4):
            path = card_dir / f"{date}_{slot}_{index}_fixture.png"
            path.write_bytes(f"card:{slot}:{index}".encode("ascii"))
            paths.append(path)
        return paths

    def test_strict_daily_payload_shape_blocks_notion_render_drift(self):
        payload = {
            "verifier_mode": "morning",
            "title": "🌅 2026.7.5 早间日报（11:00 评分点）",
            "children": self._daily_payload_children(),
            "image_after_heading": "基本面",
            "image_paths": ["a.png", "b.png", "c.png"],
        }
        result = publish_report.validate_daily_payload_shape(
            payload,
            "2026-07-05",
            "morning",
        )
        self.assertEqual(result["status"], "passed")
        bad = dict(payload)
        bad["children"] = list(payload["children"])
        bad["children"][1] = {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": []},
        }
        with self.assertRaisesRegex(ValueError, "block type sequence"):
            publish_report.validate_daily_payload_shape(bad, "2026-07-05", "morning")

    def test_strict_daily_payload_shape_accepts_evening_extra_boundary_block(self):
        payload = {
            "verifier_mode": "evening",
            "title": "🌙 2026.7.5 晚间日报（20:00 评分点）",
            "children": self._daily_payload_children("evening"),
            "image_after_heading": "基本面",
            "image_paths": ["a.png", "b.png", "c.png"],
        }
        result = publish_report.validate_daily_payload_shape(
            payload,
            "2026-07-05",
            "evening",
        )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["block_count_before_images"], 26)

    def test_strict_daily_payload_shape_rejects_incomplete_cannot_do(self):
        children = self._daily_payload_children("evening")
        children[1]["heading_2"]["rich_text"][0]["text"]["content"] = "不能做"
        payload = {
            "verifier_mode": "evening",
            "title": "🌙 2026.7.5 晚间日报（20:00 评分点）",
            "children": children,
            "image_after_heading": "基本面",
            "image_paths": ["a.png", "b.png", "c.png"],
        }
        with self.assertRaisesRegex(ValueError, "text slot drift"):
            publish_report.validate_daily_payload_shape(payload, "2026-07-05", "evening")

    def test_strict_daily_payload_shape_rejects_empty_tail_block(self):
        children = self._daily_payload_children("evening")
        children[-1] = {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": []},
        }
        payload = {
            "verifier_mode": "evening",
            "title": "🌙 2026.7.5 晚间日报（20:00 评分点）",
            "children": children,
            "image_after_heading": "基本面",
            "image_paths": ["a.png", "b.png", "c.png"],
        }
        with self.assertRaisesRegex(ValueError, "is empty"):
            publish_report.validate_daily_payload_shape(payload, "2026-07-05", "evening")

    def test_strict_daily_payload_shape_rejects_critical_text_not_in_report(self):
        children = self._daily_payload_children("evening")
        children[17]["paragraph"]["rich_text"][0]["text"]["content"] = (
            "止盈：99,999（TP1）减仓50%。"
        )
        payload = {
            "verifier_mode": "evening",
            "title": "🌙 2026.7.5 晚间日报（20:00 评分点）",
            "children": children,
            "image_after_heading": "基本面",
            "image_paths": ["a.png", "b.png", "c.png"],
        }
        report_text = "\n".join(
            [
                "不能做：追多",
                "BTC（策略）：观望·不挂单",
                "止盈：今日无新挂单。",
                "止损：今日无新挂单。",
                "第一层：无。",
                "第二层：无。",
                "注意事项：无。",
            ]
        )
        with self.assertRaisesRegex(ValueError, "critical text"):
            publish_report.validate_daily_payload_shape(
                payload,
                "2026-07-05",
                "evening",
                report_text=report_text,
            )

    def test_review_payload_contract_accepts_dimension_three_segment_shape(self):
        payload = {
            "date": "2026-07-05",
            "title": "🔍 2026.7.5 晚间独立审查（倒推）",
            "title_prefix": "🔍",
            "verifier_mode": "review",
            "children": self._review_payload_children(),
            "image_after_heading": "",
            "image_paths": [],
        }
        result = review_contract.validate_review_payload_shape(payload, "2026-07-05")
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["template"], review_contract.CONTRACT_VERSION)
        self.assertEqual(result["segments"], ["前一晚报", "当天早报", "当天午报"])

    def test_review_payload_color_contract_rejects_unstyled_review_payload(self):
        payload = {
            "date": "2026-07-05",
            "title": "🔍 2026.7.5 晚间独立审查（倒推）",
            "title_prefix": "🔍",
            "verifier_mode": "review",
            "children": self._review_payload_children(),
            "image_after_heading": "",
            "image_paths": [],
        }
        with self.assertRaisesRegex(ValueError, "must render"):
            review_contract.validate_review_payload_colors(payload)

    def test_review_payload_contract_rejects_single_score_table_drift(self):
        children = self._review_payload_children()
        children[1] = self._text_block("heading_2", "一、三段倒推评分")
        children[2] = self._table_block(
            [
                ["审查段落", "原计划核心", "后续验证", "评分", "结论"],
                ["前一晚报", "反弹空", "上刺失效", "62", "压力识别有用"],
                ["当天早报", "低多", "方向失效", "58", "止损有保护"],
                ["当天午报", "反弹空", "回落验证", "87", "节奏最强"],
            ]
        )
        payload = {
            "date": "2026-07-05",
            "title": "🔍 2026.7.5 晚间独立审查（倒推）",
            "title_prefix": "🔍",
            "verifier_mode": "review",
            "children": children,
            "image_after_heading": "",
            "image_paths": [],
        }
        with self.assertRaisesRegex(ValueError, "综合评分"):
            review_contract.validate_review_payload_shape(payload, "2026-07-05")

    def test_review_payload_contract_rejects_visible_system_terms(self):
        children = self._review_payload_children()
        children[7] = self._text_block(
            "paragraph",
            "发现一：analysis_lock 后没有回写 combined。",
        )
        payload = {
            "date": "2026-07-05",
            "title": "🔍 2026.7.5 晚间独立审查（倒推）",
            "title_prefix": "🔍",
            "verifier_mode": "review",
            "children": children,
            "image_after_heading": "",
            "image_paths": [],
        }
        with self.assertRaisesRegex(ValueError, "system/process"):
            review_contract.validate_review_payload_shape(payload, "2026-07-05")

    def test_review_payload_source_rejects_old_single_score_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            date = "2026-07-05"
            outputs = root / "outputs"
            outputs.mkdir(parents=True)
            report = outputs / f"{date}_evening_combined.md"
            report.write_text(
                self._strict_daily_combined_text(date, "evening"),
                encoding="utf-8",
            )
            report_rel = "outputs/2026-07-05_evening_combined.md"
            report_sha = sha256_file(report)
            manifest_dir = root / "runtime_state" / date
            manifest_dir.mkdir(parents=True)
            manifest = manifest_dir / "evening_independent_review.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": "evening-independent-review-v1",
                        "trading_date": date,
                        "slot": "evening",
                        "report_path": report_rel,
                        "report_sha256": report_sha,
                        "inputs": [
                            {"label": "前一晚报"},
                            {"label": "当天早报"},
                            {"label": "当天午报"},
                        ],
                        "segments": [
                            {"segment": "前一晚报 -> 今日盘中", "score": 62},
                            {"segment": "当天早报 -> 午后/晚间", "score": 58},
                            {"segment": "当天午报 -> 晚间", "score": 87},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            children = self._review_payload_children()
            payload = {
                "verifier_mode": "review",
                "children": children,
                "payload_source": {
                    "schema_version": review_contract.SOURCE_SCHEMA_VERSION,
                    "kind": review_contract.SOURCE_KIND,
                    "contract_version": review_contract.CONTRACT_VERSION,
                    "review_manifest": "runtime_state/2026-07-05/evening_independent_review.json",
                    "review_manifest_sha256": sha256_file(manifest),
                    "report_path": report_rel,
                    "report_sha256": report_sha,
                    "children_signature_sha256": review_contract.review_children_signature(children),
                },
            }
            with self.assertRaisesRegex(ValueError, "schema_version"):
                review_contract.validate_review_payload_source(
                    payload,
                    report,
                    date,
                    "evening",
                    root=root,
                )

    def test_publish_review_dry_run_records_review_contract_evidence_without_daily_sources(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            date = "2026-07-05"
            outputs = root / "outputs"
            outputs.mkdir(parents=True)
            report = outputs / f"{date}_evening_combined.md"
            report.write_text(
                self._strict_daily_combined_text(date, "evening"),
                encoding="utf-8",
            )
            report_rel = "outputs/2026-07-05_evening_combined.md"
            report_sha = sha256_file(report)
            manifest_dir = root / "runtime_state" / date
            manifest_dir.mkdir(parents=True)
            manifest = manifest_dir / "evening_independent_review.json"
            manifest.write_text(
                json.dumps(
                    self._review_manifest(date, report_rel, report_sha),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            payload_obj = review_payload_builder.build_review_payload(
                manifest,
                root=root,
            )
            color_evidence = review_contract.validate_review_payload_colors(payload_obj)
            self.assertEqual(color_evidence["status"], "passed")
            self.assertEqual(color_evidence["template"], review_contract.REVIEW_FONT_TEMPLATE)
            payload = outputs / "review_payload.json"
            payload.write_text(
                json.dumps(payload_obj, ensure_ascii=False),
                encoding="utf-8",
            )

            with patch.object(publish_report, "ROOT", root), patch.object(
                publish_report,
                "assert_source_freshness",
                side_effect=AssertionError("daily source freshness must not run for review"),
            ), patch.object(
                publish_report,
                "run_report_lint",
                side_effect=AssertionError("daily report lint must not run for review"),
            ):
                result = publish_report.publish(payload, dry_run=True)
            self.assertEqual(result["notion_payload_shape"]["status"], "passed")
            self.assertEqual(
                result["notion_payload_source"]["kind"],
                review_contract.SOURCE_KIND,
            )
            self.assertEqual(
                result["notion_payload_source"]["template"],
                review_contract.CONTRACT_VERSION,
            )
            self.assertEqual(result["notion_payload_colors"]["status"], "passed")
            self.assertEqual(
                result["notion_payload_colors"]["template"],
                review_contract.REVIEW_FONT_TEMPLATE,
            )
            self.assertEqual(result["source_binding"]["status"], "not_applicable")
            self.assertNotIn("source_specs", payload_obj)
            self.assertEqual(payload_obj["image_paths"], [])

    def test_review_builder_rejects_post_retirement_generation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            date = "2026-07-09"
            outputs = root / "outputs"
            outputs.mkdir(parents=True)
            report = outputs / f"{date}_evening_combined.md"
            report.write_text(
                self._strict_daily_combined_text(date, "evening"),
                encoding="utf-8",
            )
            report_rel = f"outputs/{date}_evening_combined.md"
            manifest_dir = root / "runtime_state" / date
            manifest_dir.mkdir(parents=True)
            manifest = manifest_dir / "evening_independent_review.json"
            manifest.write_text(
                json.dumps(
                    self._review_manifest(date, report_rel, sha256_file(report)),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "retired"):
                review_payload_builder.build_review_payload(manifest, root=root)

    def test_daily_payload_builder_derives_payload_from_combined_and_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            date = "2026-07-05"
            slot = "evening"
            outputs = root / "outputs"
            outputs.mkdir(parents=True)
            report = outputs / f"{date}_{slot}_combined.md"
            report.write_text(
                self._strict_daily_combined_text(date, slot),
                encoding="utf-8",
            )
            self._seed_publish_binding(root, date=date, slot=slot)
            self._seed_blockbeat_cards(root, date, slot)

            payload = daily_payload_builder.build_daily_payload(report, root=root)

            self.assertEqual(payload["schema_version"], "daily-publish-payload-v3")
            self.assertEqual(payload["date"], date)
            self.assertEqual(payload["verifier_mode"], slot)
            self.assertEqual(len(payload["children"]), 32)
            self.assertEqual(
                daily_payload_builder.block_plain_text(payload["children"][1]),
                "不能做",
            )
            self.assertEqual(
                daily_payload_builder.block_plain_text(payload["children"][2]),
                "不能做：不能在压力下方追涨，不能在支撑带直接追空。",
            )
            self.assertEqual(
                daily_payload_builder.block_plain_text(payload["children"][3]),
                "基本面",
            )
            self.assertEqual(
                daily_payload_builder.block_plain_text(payload["children"][-1]),
                "独立边界：本报告判断仅来自当次六源与开仓前状态门禁。",
            )
            self.assertEqual(payload["payload_source"]["status"] if "status" in payload["payload_source"] else None, None)
            validated = daily_payload_builder.validate_payload_derivation(
                payload,
                report,
                date,
                slot,
                root=root,
            )
            self.assertEqual(validated["status"], "passed")
            self.assertEqual(validated["kind"], "combined_md_to_notion_payload")

    def test_daily_payload_builder_normalizes_maker_label_subheading(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            date = "2026-07-05"
            slot = "morning"
            outputs = root / "outputs"
            outputs.mkdir(parents=True)
            report = outputs / f"{date}_{slot}_combined.md"
            report.write_text(
                self._strict_daily_combined_text(date, slot).replace(
                    "\nBTC（策略）：", "\n### BTC（策略）：", 1
                ),
                encoding="utf-8",
            )
            self._seed_publish_binding(root, date=date, slot=slot)
            self._seed_blockbeat_cards(root, date, slot)

            payload = daily_payload_builder.build_daily_payload(report, root=root)

            self.assertEqual(
                daily_payload_builder.block_plain_text(payload["children"][21]),
                "BTC（策略）：执行概率 45%（已执行 0%）　胜率 61%",
            )

    def test_visual_v3_shape_separates_labels_and_enforces_density_budget(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            date = "2026-07-05"
            slot = "morning"
            outputs = root / "outputs"
            outputs.mkdir(parents=True)
            report = outputs / f"{date}_{slot}_combined.md"
            report.write_text(self._strict_daily_combined_text(date, slot), encoding="utf-8")
            self._seed_publish_binding(root, date=date, slot=slot)
            self._seed_blockbeat_cards(root, date, slot)
            payload = daily_payload_builder.build_daily_payload(report, root=root)

            result = publish_report.validate_daily_payload_shape(
                payload, date, slot, report_text=report.read_text(encoding="utf-8")
            )

            self.assertEqual(result["schema_version"], "daily-publish-payload-v3")
            self.assertEqual(result["visual_contract"]["status"], "passed")
            self.assertLessEqual(result["visual_contract"]["heading_max_chars"], 12)
            self.assertEqual(payload["children"][2]["type"], "callout")
            self.assertEqual(payload["children"][18]["type"], "callout")

            payload["children"][3]["heading_3"]["rich_text"][0]["text"]["content"] = (
                "基本面标题不允许承载一整段分析"
            )
            with self.assertRaisesRegex(ValueError, "visual label drift|heading exceeds"):
                publish_report.validate_daily_payload_shape(payload, date, slot)

    def test_visual_v3_shape_rejects_oversized_body_without_truncating_report(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            date = "2026-07-05"
            slot = "morning"
            outputs = root / "outputs"
            outputs.mkdir(parents=True)
            report = outputs / f"{date}_{slot}_combined.md"
            report.write_text(self._strict_daily_combined_text(date, slot), encoding="utf-8")
            self._seed_publish_binding(root, date=date, slot=slot)
            self._seed_blockbeat_cards(root, date, slot)
            payload = daily_payload_builder.build_daily_payload(report, root=root)
            payload["children"][4]["paragraph"]["rich_text"][0]["text"]["content"] = "长" * 1801

            with self.assertRaisesRegex(ValueError, "body exceeds visual budget"):
                publish_report.validate_daily_payload_shape(payload, date, slot)

    def test_visual_v3_projection_preserves_deep_analysis_verbatim(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            date = "2026-07-05"
            slot = "morning"
            outputs = root / "outputs"
            outputs.mkdir(parents=True)
            report = outputs / f"{date}_{slot}_combined.md"
            deep_fundamental = "基本面：" + "深度证据链与反证逻辑" * 80
            source = self._strict_daily_combined_text(date, slot)
            source = source.replace(
                "基本面：中性偏多（Farside 最新 Bitcoin ETF Flow 为 +223.5 US$m；FedWatch 未给出降息交易）价格已兑现部分",
                deep_fundamental,
            )
            report.write_text(source, encoding="utf-8")
            self._seed_publish_binding(root, date=date, slot=slot)
            self._seed_blockbeat_cards(root, date, slot)

            payload = daily_payload_builder.build_daily_payload(report, root=root)
            projected = daily_payload_builder.block_plain_text(payload["children"][4])
            self.assertEqual(projected, deep_fundamental)
            self.assertEqual(len(projected), len(deep_fundamental))
            result = publish_report.validate_daily_payload_shape(payload, date, slot)
            self.assertEqual(result["visual_contract"]["status"], "passed")
            self.assertIn("body_density", result["visual_contract"]["warnings"])

    def test_publish_rejects_strict_daily_payload_not_derived_from_combined(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            date = "2026-07-05"
            slot = "midday"
            outputs = root / "outputs"
            outputs.mkdir(parents=True)
            report = outputs / f"{date}_{slot}_combined.md"
            report.write_text(
                self._strict_daily_combined_text(date, slot),
                encoding="utf-8",
            )
            self._seed_publish_binding(root, date=date, slot=slot)
            self._seed_blockbeat_cards(root, date, slot)
            payload_obj = daily_payload_builder.build_daily_payload(report, root=root)
            payload_obj["children"][23]["paragraph"]["rich_text"][0]["text"]["content"] = (
                "取消价不等于止损：这是 combined 里没有的手写漂移。"
            )
            payload = outputs / f"{date}_{slot}_publish_payload.json"
            payload.write_text(
                json.dumps(payload_obj, ensure_ascii=False),
                encoding="utf-8",
            )

            with patch.object(publish_report, "ROOT", root):
                with self.assertRaisesRegex(ValueError, "not derived from combined"):
                    publish_report.publish(payload, dry_run=True)

    def test_publish_rejects_daily_payload_source_signature_drift(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            date = "2026-07-05"
            slot = "morning"
            outputs = root / "outputs"
            outputs.mkdir(parents=True)
            report = outputs / f"{date}_{slot}_combined.md"
            report.write_text(
                self._strict_daily_combined_text(date, slot),
                encoding="utf-8",
            )
            self._seed_publish_binding(root, date=date, slot=slot)
            self._seed_blockbeat_cards(root, date, slot)
            payload_obj = daily_payload_builder.build_daily_payload(report, root=root)
            payload_obj["payload_source"]["children_signature_sha256"] = "tampered"
            payload = outputs / f"{date}_{slot}_publish_payload.json"
            payload.write_text(
                json.dumps(payload_obj, ensure_ascii=False),
                encoding="utf-8",
            )

            with patch.object(publish_report, "ROOT", root):
                with self.assertRaisesRegex(
                    ValueError,
                    "source evidence mismatch for children_signature_sha256",
                ):
                    publish_report.publish(payload, dry_run=True)

    def test_publish_rejects_daily_payload_without_source_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            date = "2026-07-05"
            slot = "morning"
            outputs = root / "outputs"
            outputs.mkdir(parents=True)
            report = outputs / f"{date}_{slot}_combined.md"
            report.write_text(
                self._strict_daily_combined_text(date, slot),
                encoding="utf-8",
            )
            self._seed_publish_binding(root, date=date, slot=slot)
            self._seed_blockbeat_cards(root, date, slot)
            payload_obj = daily_payload_builder.build_daily_payload(report, root=root)
            payload_obj.pop("payload_source")
            payload = outputs / f"{date}_{slot}_publish_payload.json"
            payload.write_text(
                json.dumps(payload_obj, ensure_ascii=False),
                encoding="utf-8",
            )

            with patch.object(publish_report, "ROOT", root):
                with self.assertRaisesRegex(ValueError, "missing payload_source"):
                    publish_report.publish(payload, dry_run=True)

    def test_notion_push_lib_blocks_direct_daily_transaction_without_payload_source(self):
        with self.assertRaisesRegex(RuntimeError, "daily report Notion writes"):
            notion_push_lib.replace_page_transactional(
                parent_id="parent",
                title="🌅 2026.7.5 早间日报（11:00 评分点）",
                title_prefix="🌅",
                children=[],
                image_after_heading="基本面",
                image_paths=[],
                verifier_mode="morning",
            )

    def test_notion_push_lib_blocks_direct_daily_create_without_payload_source(self):
        with self.assertRaisesRegex(RuntimeError, "daily report Notion writes"):
            notion_push_lib.create_page(
                parent="parent",
                title="🌙 2026.7.5 晚间日报（20:00 评分点）",
                children=[],
            )

    def test_frozen_verifier_binds_live_text_to_preflight_children_signature(self):
        expected = "a" * 64
        with patch.object(
            notion_push_lib,
            "run_python_gate",
            return_value={"returncode": 0},
        ) as gate:
            notion_push_lib.run_frozen_verifier("page-id", "morning", expected)
        self.assertEqual(gate.call_args.args[1], ["page-id", "morning", expected])

    def test_daily_color_template_normalizes_gold_run_distribution(self):
        children = self._daily_payload_children()
        children[16]["paragraph"]["rich_text"][0]["text"]["content"] = (
            "低多：入场区间 62,560-62,650，挂单价 62,600"
        )
        for index in (2, 3, 6, 10, 15, 16):
            block = children[index]
            body = block[block["type"]]
            body["rich_text"][0]["annotations"] = {"bold": True, "color": "green"}
        children[17]["paragraph"]["rich_text"][0]["annotations"] = {"color": "green"}
        children[18]["paragraph"]["rich_text"][0]["annotations"] = {"color": "red"}

        violations, before = daily_color_template.audit_daily_blocks(children)
        self.assertEqual(before["status"], "failed")
        self.assertTrue(violations)

        result = daily_color_template.style_daily_payload_children(children)
        self.assertEqual(result["status"], "passed")
        self.assertGreater(result["changed_blocks"], 0)
        violations, after = daily_color_template.audit_daily_blocks(children)
        self.assertEqual(after["status"], "passed")
        self.assertEqual(violations, [])
        self.assertEqual(
            daily_color_template.actual_signature_for_block(children[15]),
            [("BTC（策略）：观望·不挂单", "default", False)],
        )
        self.assertEqual(
            daily_color_template.actual_signature_for_block(children[16]),
            [
                ("低多：", "green", True),
                ("入场区间 62,560-62,650，挂单价 62,600", "default", True),
            ],
        )
        self.assertEqual(
            daily_color_template.actual_signature_for_block(children[17]),
            [("止盈：今日无新挂单。", "green", True)],
        )
        self.assertEqual(
            daily_color_template.actual_signature_for_block(children[18]),
            [("止损：今日无新挂单。", "red", True)],
        )

    def test_daily_color_template_keeps_fundamental_pressure_reason_yellow(self):
        children = self._daily_payload_children()
        children[2]["heading_3"]["rich_text"][0]["text"]["content"] = (
            "基本面：中性偏多（Farside 最新 Bitcoin ETF Flow 为 +223.5 US$m，"
            "和 7/1 以来价格修复方向一致；但 BlockBeats 的周度 ETF 流出与 "
            "FedWatch 加息尾部仍压制右侧追涨）价格已兑现部分"
        )
        children[10]["heading_3"]["rich_text"][0]["text"]["content"] = (
            "趋势确认：多头趋势（短线）+ 震荡结构（中短线压力下）"
        )

        result = daily_color_template.style_daily_payload_children(children)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(
            daily_color_template.actual_signature_for_block(children[2]),
            [
                ("基本面：", "default", False),
                ("中性偏多", "green", True),
                (
                    "（Farside 最新 Bitcoin ETF Flow 为 +223.5 US$m，"
                    "和 7/1 以来价格修复方向一致；但 BlockBeats 的周度 ETF 流出与 "
                    "FedWatch 加息尾部仍压制右侧追涨）",
                    "yellow",
                    True,
                ),
                ("价格已兑现部分", "green", True),
            ],
        )
        self.assertEqual(
            daily_color_template.actual_signature_for_block(children[10]),
            [
                ("趋势确认：", "default", False),
                ("多头趋势（短线）+ 震荡结构（中短线压力下）", "green", True),
            ],
        )

    def test_daily_color_template_colors_technical_signal_clause(self):
        children = self._daily_payload_children()
        children[8]["paragraph"]["rich_text"][0]["text"]["content"] = (
            "日线级别：价格收在 62,948.90，重新站上日线 SMA20 的 62,038.56，"
            "但仍远低于 SMA200 的 74,755.74，且上方 63,600 一带尚未有效突破；"
            "日线属于反弹修复，不是中线反转确认。中性偏多"
        )
        children[9]["paragraph"]["rich_text"][0]["text"]["content"] = (
            "小时级别：4H 收 62,966.15，高 63,104.00，低 62,948.89；"
            "1H 收 63,021.41，重新站上 1H SMA20 的 62,974.20，"
            "但 63,180-63,520 仍是近端成交密集压力，"
            "短线多头结构未破但追涨空间不足。中性偏多"
        )

        daily_color_template.style_daily_payload_children(children)

        self.assertEqual(
            daily_color_template.actual_signature_for_block(children[8]),
            [
                ("日线级别：价格收在 62,948.90，", "default", False),
                ("重新站上日线 SMA20 的 62,038.56", "green", True),
                (
                    "，但仍远低于 SMA200 的 74,755.74，且上方 63,600 一带尚未有效突破；"
                    "日线属于反弹修复，不是中线反转确认。",
                    "default",
                    False,
                ),
                ("中性偏多", "green", True),
            ],
        )
        self.assertEqual(
            daily_color_template.actual_signature_for_block(children[9]),
            [
                (
                    "小时级别：4H 收 62,966.15，高 63,104.00，低 62,948.89；"
                    "1H 收 63,021.41，",
                    "default",
                    False,
                ),
                ("重新站上 1H SMA20 的 62,974.20", "green", True),
                (
                    "，但 63,180-63,520 仍是近端成交密集压力，"
                    "短线多头结构未破但追涨空间不足。",
                    "default",
                    False,
                ),
                ("中性偏多", "green", True),
            ],
        )

    def test_publish_manifest_makes_identical_retry_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            outputs = root / "outputs"
            outputs.mkdir(parents=True)
            report = outputs / "2026-06-30_morning_combined.md"
            report.write_text("# 2026-06-30 早间日报\n", encoding="utf-8")
            image = outputs / "card.png"
            image.write_bytes(b"png")
            source_specs = self._seed_publish_binding(root)
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
                return_value=(
                    "page-id",
                    [],
                    {
                        "label": "FROZEN GOLD VERIFY",
                        "args": ["page-id", "morning"],
                        "returncode": 0,
                        "stdout": "[PASS]\n",
                        "stderr": "",
                    },
                ),
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
            self.assertEqual(manifest["frozen_verifier"]["returncode"], 0)
            self.assertIn("[PASS]", manifest["frozen_verifier"]["stdout"])
            self.assertTrue(manifest["unique_page_pass"])
            self.assertIn("source_binding", manifest)
            self.assertEqual(
                manifest["source_binding"]["capture_manifest_sha256"],
                sha256_file(
                    root
                    / "runtime_state"
                    / "2026-06-30"
                    / "captures"
                    / "morning"
                    / "full_base_run1234567890abcdef.json"
                ),
            )
            attempts = list(
                (
                    root
                    / "runtime_state"
                    / "2026-06-30"
                    / "publish_attempts"
                    / "morning"
                ).glob("*_success_*.json")
            )
            self.assertEqual(len(attempts), 1)
            self.assertEqual(manifest["attempt_manifest_path"], str(attempts[0]))
            attempt = json.loads(attempts[0].read_text(encoding="utf-8"))
            self.assertEqual(attempt["page_id"], "page-id")

    def test_publish_failure_writes_attempt_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            outputs = root / "outputs"
            outputs.mkdir(parents=True)
            report = outputs / "2026-06-30_morning_combined.md"
            report.write_text("# 2026-06-30 早间日报\n", encoding="utf-8")
            image = outputs / "card.png"
            image.write_bytes(b"png")
            source_specs = self._seed_publish_binding(root)
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
                side_effect=RuntimeError("frozen verify failed"),
            ):
                with self.assertRaisesRegex(RuntimeError, "frozen verify failed"):
                    publish_report.publish(payload)
            manifest = json.loads(
                (
                    root
                    / "runtime_state"
                    / "2026-06-30"
                    / "publish_morning.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["status"], "failed")
            self.assertEqual(manifest["failure_class"], "RuntimeError")
            self.assertIn("frozen verify failed", manifest["failure_reason"])
            attempts = list(
                (
                    root
                    / "runtime_state"
                    / "2026-06-30"
                    / "publish_attempts"
                    / "morning"
                ).glob("*_failed_*.json")
            )
            self.assertEqual(len(attempts), 1)
            self.assertEqual(manifest["attempt_manifest_path"], str(attempts[0]))

    def test_publish_rejects_sources_outside_locked_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            outputs = root / "outputs"
            outputs.mkdir(parents=True)
            report = outputs / "2026-06-30_morning_combined.md"
            report.write_text("# 2026-06-30 早间日报\n", encoding="utf-8")
            image = outputs / "card.png"
            image.write_bytes(b"png")
            source_specs = self._seed_publish_binding(root)
            outside = root / "data_sources" / "inbox" / "2026-06-30" / "coinglass.png"
            outside.parent.mkdir(parents=True)
            outside.write_bytes(b"later mutable inbox file")
            source_specs["coinglass"] = {"path": str(outside)}
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
            with patch.object(publish_report, "ROOT", root):
                with self.assertRaisesRegex(ValueError, "locked evidence snapshot"):
                    publish_report.publish(payload)


class NotionDatePageTitleTests(unittest.TestCase):
    def test_date_page_title_normalizes_iso_and_padded_dotted_dates(self):
        self.assertEqual(notion_push_lib._date_page_title("2026-07-05"), "2026.7.5")
        self.assertEqual(notion_push_lib._date_page_title("2026.07.05"), "2026.7.5")
        self.assertEqual(notion_push_lib._date_page_title("2026.7.5"), "2026.7.5")
        self.assertEqual(notion_push_lib._date_page_title("manual title"), "manual title")

    def test_ensure_date_page_renames_legacy_iso_page(self):
        def fake_find(_parent, prefix):
            return "legacy-id" if prefix == "2026-07-05" else None

        with patch.object(
            notion_push_lib, "find_child_page", side_effect=fake_find
        ), patch.object(notion_push_lib, "set_page_title") as rename, patch.object(
            notion_push_lib, "create_page"
        ) as create:
            page_id = notion_push_lib.ensure_date_page("2026-07-05")

        self.assertEqual(page_id, "legacy-id")
        rename.assert_called_once_with("legacy-id", "2026.7.5")
        create.assert_not_called()

    def test_ensure_date_page_creates_with_normalized_title(self):
        with patch.object(
            notion_push_lib, "find_child_page", return_value=None
        ), patch.object(
            notion_push_lib, "create_page", return_value="new-id"
        ) as create:
            page_id = notion_push_lib.ensure_date_page("2026-07-06")

        self.assertEqual(page_id, "new-id")
        create.assert_called_once_with(notion_push_lib.AI_AGENT_PLAN, "2026.7.6", [])


if __name__ == "__main__":
    unittest.main()
