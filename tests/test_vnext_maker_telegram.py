from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime_vnext.controller import _load_blockbeats_rows, _load_report_presentation_contract
from runtime_vnext.maker_delivery_lifecycle import (
    prepare_maker_delivery,
    send_prepared_maker_delivery,
)
from runtime_vnext.maker_telegram import (
    evaluate_maker_telegram_template,
    render_maker_telegram,
)
from runtime_vnext.maker_schedule import MakerScheduleBlocked, same_day_maker_message
from runtime_vnext.kernel_lock import KernelLockError, assert_kernel_lock
from runtime_vnext.telegram_delivery import TelegramDeliveryError
from runtime_vnext.telegram_outbox import TelegramOutbox
from runtime_vnext.validation.report import certify_report_projection_input
from tests import test_vnext_workflow as workflow_tests


ROOT = Path(__file__).resolve().parents[1]


class MakerTelegramProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = workflow_tests.VNextWorkflowTests(
            methodName="test_shadow_decision_never_loads_pretrade_and_keeps_full_qualified_plan"
        )
        self.fixture.setUp()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def _certified_source(self):
        self.fixture.prepare_through_decision()
        controller = self.fixture.controller
        evidence = controller.store.load_stage_payload(
            self.fixture.run_root, "evidence", "evidence"
        )
        reasoning = controller.store.load_stage_payload(
            self.fixture.run_root, "reasoning", "reasoning"
        )
        decision = controller.store.load_stage_payload(
            self.fixture.run_root, "decision", "decision"
        )
        methodology = json.loads(
            (self.fixture.run_root / "methodology_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        contract, contract_sha256 = _load_report_presentation_contract(
            self.fixture.root
        )
        return certify_report_projection_input(
            evidence=evidence,
            reasoning=reasoning,
            decision=decision,
            blockbeats_rows=_load_blockbeats_rows(self.fixture.root, evidence),
            presentation_contract=contract,
            presentation_contract_sha256=contract_sha256,
            methodology_sha256=methodology["phases"]["reasoning"]["phase_sha256"],
            report_contract_sha256=methodology["phases"]["report"]["phase_sha256"],
        )

    def test_projection_is_deterministic_and_uses_certified_values(self) -> None:
        source = self._certified_source()
        first = render_maker_telegram(source)
        second = render_maker_telegram(source)
        self.assertEqual(first, second)
        self.assertEqual(
            first.text,
            "\n".join(
                (
                    "早09：00新增计划：",
                    "不能做：追空",
                    "BTCUSDT（策略）：执行概率58%　胜率自估64%（计划时置信度，非回测命中率）",
                    "反弹空：99.8–100.0　持仓（计划）750 USDT　OKX　左侧　Maker　杠杆5x",
                    "入场梯度：99.8（50%） / 100.0（50%）",
                    "止盈：TP1 98.0（减仓50%） / TP2 97.0（减仓50%）",
                    "止损：100.35",
                    "盈亏比（TP1，全成交）：1：4.22",
                    "全成交组合校验：1档：1：3.27；2档：1：5.71；1,2档：1：4.22",
                    "防守计划：",
                    "第一层：成交后等待4小时结构极值确认；计划全成交均价99.9；1档→98.975 / 2档→99.475 / 1+2档→99.225",
                    "第二层：仅将止损移至保本；1档→98.7 / 2档→99.3 / 1+2档→99.0",
                    "注意事项：若价格优先触及96.5（未成交取消价），则此策略取消。",
                    "开仓理由：同一小时订单流与Maker阶段偏空，反抽至高质量边缘后计划做空",
                    "最强反证：十五分钟结构已转强，显示Maker空头入场前仍可能出现更强反抽",
                    "失效条件：若一小时重新站稳价值区上沿且订单流同步转强则Maker判断失效",
                )
            ),
        )
        template_gate = evaluate_maker_telegram_template(source, first)
        self.assertTrue(template_gate["passed"], template_gate["defects"])
        self.assertNotIn("Maker｜", first.text)
        self.assertNotIn("执行边界：", first.text)
        self.assertFalse(any(line.startswith("校验：") for line in first.text.splitlines()))
        self.assertFalse(any(line.startswith("订单状态：") for line in first.text.splitlines()))
        self.assertLess(len(first.text), 3900)

    def test_projection_rejects_raw_stage_data(self) -> None:
        with self.assertRaises(TypeError):
            render_maker_telegram({})  # type: ignore[arg-type]

    def test_kernel_lock_rejects_a_changed_trading_kernel_path(self) -> None:
        source_commit = json.loads((ROOT / "KERNEL_LOCK.json").read_text(encoding="utf-8"))["source_commit"]

        def git_output(_root, *args):
            if args[0] == "merge-base":
                return source_commit
            if args[0] == "diff":
                return "runtime_vnext/domain_ir/types.py"
            if args[0] == "ls-files":
                return ""
            self.fail(f"unexpected git args: {args}")

        with patch("runtime_vnext.kernel_lock._run_git", side_effect=git_output):
            with self.assertRaisesRegex(KernelLockError, "maker_kernel_tracked_file_changed"):
                assert_kernel_lock(ROOT)

    def test_kernel_lock_accepts_only_the_approved_integrity_patch(self) -> None:
        payload = assert_kernel_lock(ROOT)
        patch = payload["approved_kernel_integrity_patch"]
        self.assertEqual(patch["path"], "runtime_vnext/validation/decision.py")
        self.assertEqual(
            patch["rationale"],
            "directional_thesis_only_does_not_imply_submitted_candidate",
        )

    def test_handwritten_template_contract_uses_ten_distinct_maker_samples(self) -> None:
        contract = json.loads(
            (ROOT / "config" / "maker_telegram_presentation.json").read_text(
                encoding="utf-8"
            )
        )
        samples = contract["notion_opening_plan_samples_2026"]
        self.assertEqual(contract["schema_version"], "maker-handwritten-notion-telegram-v2")
        self.assertEqual(len(samples), 10)
        self.assertEqual(len({sample["page_id"] for sample in samples}), 10)
        self.assertEqual(contract["qualified_field_order"][:2], ["时段标题", "不能做"])
        self.assertNotIn("审计哈希", contract["qualified_field_order"])
        self.assertIn("审计哈希", contract["surface_forbidden"])

    def test_scheduled_delivery_blocks_without_a_same_slot_current_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(MakerScheduleBlocked, "maker_current_run_missing"):
                same_day_maker_message(
                    root=Path(directory), trading_date="2026-08-08", slot="morning"
                )

    @patch("runtime_vnext.maker_delivery_gate.assert_kernel_lock", return_value={})
    def test_production_lifecycle_seals_only_certificate_then_telegram_receipt(
        self, _assert_kernel_lock
    ) -> None:
        production = workflow_tests.VNextWorkflowTests(
            methodName="test_complete_flow_compiles_from_model_and_finishes"
        )
        production.setUp()
        try:
            production.prepare_through_decision()
            certified = prepare_maker_delivery(production.controller, production.run_root)
            after_prepare = production.controller.store.load_checkpoint(production.run_root)
            self.assertEqual(after_prepare["status"], "running")
            self.assertEqual(after_prepare["next_stage"], "delivery")
            self.assertEqual(
                set(after_prepare["completed"]["report"]["outputs"]),
                {"maker_certificate"},
            )
            self.assertFalse(list(production.run_root.rglob("*.combined.md")))
            self.assertFalse(list(production.run_root.rglob("*.docx")))
            self.assertFalse(list(production.run_root.rglob("*.pdf")))

            sent_hashes: list[str] = []

            def sender(message):
                sent_hashes.append(message.message_sha256)
                return {"message_id": 12345}

            manifest = send_prepared_maker_delivery(
                production.controller, production.run_root, sender
            )
            terminal = production.controller.store.load_checkpoint(production.run_root)
            self.assertEqual(sent_hashes, [certified.message.message_sha256])
            self.assertEqual(terminal["status"], "complete")
            self.assertIsNone(terminal["next_stage"])
            self.assertEqual(terminal["completion_mode"], "maker_telegram")
            self.assertFalse(terminal["notion_published"])
            self.assertEqual(
                set(terminal["completed"]["delivery"]["outputs"]),
                {"telegram_receipt"},
            )
            self.assertEqual(
                manifest["gate"]["facts"]["message_sha256"],
                certified.message.message_sha256,
            )
        finally:
            production.tearDown()

    def test_projection_module_has_no_model_or_io_dependencies(self) -> None:
        tree = ast.parse(
            (ROOT / "runtime_vnext" / "maker_telegram.py").read_text(encoding="utf-8")
        )
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        banned = {"json", "os", "pathlib", "requests", "subprocess", "urllib"}
        self.assertFalse(
            {
                name
                for name in imports
                if name in banned or any(name.startswith(prefix + ".") for prefix in banned)
            }
        )
        self.assertFalse(
            {
                node.func.attr
                for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            }
            & {"read_text", "read_bytes", "write_text", "write_bytes", "run", "Popen"}
        )

    def test_outbox_deduplicates_and_stops_on_unknown_delivery_outcome(self) -> None:
        message = render_maker_telegram(self._certified_source())
        with tempfile.TemporaryDirectory() as directory:
            outbox = TelegramOutbox(Path(directory))
            calls: list[str] = []

            def sender(value):
                calls.append(value.message_sha256)
                return {"message_id": 123}

            self.assertEqual(outbox.send_once(message, sender)["status"], "delivered")
            self.assertEqual(
                outbox.send_once(message, sender)["status"], "already_delivered"
            )
            self.assertEqual(calls, [message.message_sha256])

        with tempfile.TemporaryDirectory() as directory:
            outbox = TelegramOutbox(Path(directory))

            def uncertain_sender(value):
                raise TelegramDeliveryError("network_failure", outcome_unknown=True)

            with self.assertRaisesRegex(TelegramDeliveryError, "network_failure"):
                outbox.send_once(message, uncertain_sender)
            with self.assertRaisesRegex(
                TelegramDeliveryError, "telegram_delivery_outcome_unknown"
            ):
                outbox.send_once(message, lambda value: {"message_id": 124})

        with tempfile.TemporaryDirectory() as directory:
            outbox = TelegramOutbox(Path(directory))
            outbox._write(outbox._record("sending", message))
            with self.assertRaisesRegex(
                TelegramDeliveryError, "telegram_delivery_outcome_unknown"
            ):
                outbox.send_once(message, lambda value: {"message_id": 125})
