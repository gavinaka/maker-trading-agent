"""Schedule-safe delivery of a same-day, sealed Maker Telegram strategy."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .cli import ROOT
from .controller import RunController
from .maker_delivery_gate import certify_maker_delivery
from .maker_delivery_lifecycle import send_prepared_maker_delivery
from .maker_telegram import MakerTelegramMessage
from .telegram_delivery import TelegramCredentials, send_maker_message
from .telegram_outbox import TelegramOutbox


SCHEDULE_TIMEZONE = "Asia/Shanghai"
SLOTS = ("morning", "midday", "evening")


class MakerScheduleBlocked(RuntimeError):
    """A schedule trigger cannot legally send a strategy for this slot."""


def _current_run_id(root: Path, trading_date: str, slot: str) -> str:
    current_path = root / "runtime_state_vnext" / trading_date / slot / "current.json"
    if not current_path.is_file():
        raise MakerScheduleBlocked("maker_current_run_missing")
    try:
        payload: Any = json.loads(current_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MakerScheduleBlocked("maker_current_run_invalid") from exc
    if not isinstance(payload, dict) or type(payload.get("run_id")) is not str:
        raise MakerScheduleBlocked("maker_current_run_invalid")
    run_id = payload["run_id"].strip()
    if not run_id:
        raise MakerScheduleBlocked("maker_current_run_invalid")
    return run_id


def same_day_maker_message(
    *, root: Path, trading_date: str, slot: str
) -> tuple[MakerTelegramMessage, Path]:
    """Build only a same-slot strategy that has all three sealed inputs."""

    if slot not in SLOTS:
        raise MakerScheduleBlocked("maker_slot_invalid")
    controller = RunController(root)
    run_id = _current_run_id(root, trading_date, slot)
    run_root = controller.store.run_root(trading_date, slot, run_id)
    try:
        run = controller.store.load_run(run_root)
        checkpoint = controller.store.load_checkpoint(run_root)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        raise MakerScheduleBlocked("maker_sealed_run_invalid") from exc
    if run.get("trading_date") != trading_date or run.get("slot") != slot:
        raise MakerScheduleBlocked("maker_current_run_identity_mismatch")
    if (
        checkpoint.get("status") != "running"
        or checkpoint.get("next_stage") != "delivery"
        or not isinstance(checkpoint.get("completed"), dict)
        or "report" not in checkpoint["completed"]
    ):
        raise MakerScheduleBlocked("maker_run_not_sendable")
    try:
        message = certify_maker_delivery(controller, run_root).message
    except Exception as exc:
        raise MakerScheduleBlocked("maker_decision_not_certified") from exc
    return message, run_root


def _today_shanghai() -> str:
    return datetime.now(ZoneInfo(SCHEDULE_TIMEZONE)).date().isoformat()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slot", required=True, choices=SLOTS)
    parser.add_argument("--root", default=str(ROOT), help="Maker Trading Agent root")
    parser.add_argument("--send", action="store_true", help="perform one hash-bound Telegram send")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    trading_date = _today_shanghai()
    try:
        message, run_root = same_day_maker_message(
            root=root, trading_date=trading_date, slot=args.slot
        )
    except MakerScheduleBlocked as exc:
        print(json.dumps({"status": "blocked", "reason_code": str(exc), "sent": False}, ensure_ascii=False))
        return 4
    if not args.send:
        print(message.text)
        return 0
    try:
        credentials = TelegramCredentials.from_environment()
        manifest = send_prepared_maker_delivery(
            RunController(root),
            run_root,
            lambda sealed_message: send_maker_message(sealed_message, credentials),
        )
    except Exception as exc:  # never expose token, chat id, or Telegram body
        code = getattr(exc, "code", type(exc).__name__)
        print(json.dumps({"status": "blocked", "reason_code": str(code), "sent": False}, ensure_ascii=False))
        return 5
    print(
        json.dumps(
            {
                "status": "delivered",
                "message_sha256": manifest["gate"]["facts"]["message_sha256"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by the task runner
    raise SystemExit(main())
