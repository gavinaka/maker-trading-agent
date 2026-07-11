from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runtime import delivery_evidence


class DeliveryContextWriterTests(unittest.TestCase):
    def test_writer_preserves_user_content_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sessions = root / "sessions"
            sessions.mkdir(parents=True)
            context = sessions / "context_log.md"
            context.write_text("## 2026-07-10 用户原有记录\n\n保留正文。\n", encoding="utf-8")
            state = root / "runtime_state" / "2026-07-11"
            state.mkdir(parents=True)
            render = state / "render_morning.json"
            qa = state / "word_qa_morning.json"
            publish = state / "publish_morning.json"
            for path in (render, qa, publish):
                path.write_text("{}", encoding="utf-8")
            base = {
                "report_sha256": "1" * 64,
                "docx_sha256": "2" * 64,
                "render_manifest": str(render),
                "word_qa_manifest": str(qa),
                "publish_manifest": str(publish),
                "reviewed_at": "2026-07-11T08:30:00+08:00",
                "published_at": "2026-07-11T08:31:00+08:00",
            }
            verified = {
                **base,
                "context_log_sha256": "3" * 64,
                "context_log_block_sha256": "4" * 64,
            }
            with mock.patch.object(
                delivery_evidence,
                "validate_delivery_evidence",
                side_effect=[base, verified, base, verified],
            ):
                first = delivery_evidence.record_delivery_context(
                    "2026-07-11",
                    "morning",
                    "a" * 32,
                    current={"report_sha256": "1" * 64},
                    root=root,
                )
                snapshot = context.read_text(encoding="utf-8")
                second = delivery_evidence.record_delivery_context(
                    "2026-07-11",
                    "morning",
                    "a" * 32,
                    current={"report_sha256": "1" * 64},
                    root=root,
                )

            self.assertTrue(first["changed"])
            self.assertFalse(second["changed"])
            self.assertEqual(context.read_text(encoding="utf-8"), snapshot)
            self.assertIn("保留正文。", snapshot)
            self.assertIn("Word 视觉 QA PASS", snapshot)
            self.assertIn("冻结 verifier PASS", snapshot)
            self.assertIn("runtime_state/2026-07-11/render_morning.json", snapshot)

    def test_writer_replaces_only_previous_generated_block_for_same_slot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sessions = root / "sessions"
            sessions.mkdir(parents=True)
            context = sessions / "context_log.md"
            context.write_text(
                "## 2026-07-11 早间最终交付\n"
                "<!-- generated-delivery-evidence:2026-07-11:morning:old -->\n"
                "- stale\n\n"
                "## 2026-07-10 用户记录\n- keep\n",
                encoding="utf-8",
            )
            state = root / "runtime_state" / "2026-07-11"
            state.mkdir(parents=True)
            paths = []
            for name in ("render_morning.json", "word_qa_morning.json", "publish_morning.json"):
                path = state / name
                path.write_text("{}", encoding="utf-8")
                paths.append(path)
            base = {
                "report_sha256": "1" * 64,
                "docx_sha256": "2" * 64,
                "render_manifest": str(paths[0]),
                "word_qa_manifest": str(paths[1]),
                "publish_manifest": str(paths[2]),
                "reviewed_at": "2026-07-11T08:30:00+08:00",
                "published_at": "2026-07-11T08:31:00+08:00",
            }
            verified = {
                **base,
                "context_log_sha256": "3" * 64,
                "context_log_block_sha256": "4" * 64,
            }
            with mock.patch.object(
                delivery_evidence,
                "validate_delivery_evidence",
                side_effect=[base, verified],
            ):
                delivery_evidence.record_delivery_context(
                    "2026-07-11",
                    "morning",
                    "b" * 32,
                    current={"report_sha256": "1" * 64},
                    root=root,
                )
            updated = context.read_text(encoding="utf-8")
            self.assertNotIn("stale", updated)
            self.assertNotIn(":old -->", updated)
            self.assertIn("2026-07-10 用户记录", updated)
            self.assertEqual(updated.count("generated-delivery-evidence:2026-07-11:morning"), 1)


if __name__ == "__main__":
    unittest.main()
