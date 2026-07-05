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
    def _daily_payload_children(self) -> list[dict]:
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
        blocks = []
        for index, block_type in enumerate(publish_report.DAILY_PAYLOAD_TYPES):
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
