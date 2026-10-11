"""Hash-bound, fail-closed outbox for one Maker Telegram message per run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from .maker_telegram import MakerTelegramMessage
from .telegram_delivery import TelegramDeliveryError


class TelegramOutbox:
    """Persist delivery identity before an external send and never guess after it."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.manifest_path = directory / "telegram_delivery.json"

    def send_once(
        self,
        message: MakerTelegramMessage,
        sender: Callable[[MakerTelegramMessage], dict[str, object]],
    ) -> dict[str, object]:
        if type(message) is not MakerTelegramMessage:
            raise TypeError("Telegram outbox accepts only MakerTelegramMessage")
        existing = self._load()
        if existing is not None:
            self._validate_identity(existing, message)
            status = existing.get("status")
            if status == "delivered":
                return {
                    "status": "already_delivered",
                    "message_sha256": message.message_sha256,
                    "message_id": existing.get("message_id"),
                }
            if status in {"sending", "outcome_unknown"}:
                raise TelegramDeliveryError("telegram_delivery_outcome_unknown")
        self._write(self._record("sending", message))
        try:
            receipt = sender(message)
        except TelegramDeliveryError as exc:
            status = "outcome_unknown" if exc.outcome_unknown else "failed"
            self._write(self._record(status, message, error_code=exc.code))
            raise
        message_id = receipt.get("message_id")
        if type(message_id) is not int:
            self._write(
                self._record(
                    "outcome_unknown",
                    message,
                    error_code="telegram_sender_missing_message_id",
                )
            )
            raise TelegramDeliveryError("telegram_sender_missing_message_id")
        self._write(self._record("delivered", message, message_id=message_id))
        return {
            "status": "delivered",
            "message_sha256": message.message_sha256,
            "message_id": message_id,
        }

    def delivered_receipt(self, message: MakerTelegramMessage) -> dict[str, object]:
        """Return only a hash-bound known delivery; never retry or infer one."""

        if type(message) is not MakerTelegramMessage:
            raise TypeError("Telegram outbox accepts only MakerTelegramMessage")
        existing = self._load()
        if existing is None:
            raise TelegramDeliveryError("telegram_delivery_receipt_missing")
        self._validate_identity(existing, message)
        if existing.get("status") != "delivered" or type(existing.get("message_id")) is not int:
            raise TelegramDeliveryError("telegram_delivery_outcome_unknown")
        return {
            "status": "already_delivered",
            "message_sha256": message.message_sha256,
            "message_id": existing["message_id"],
        }

    def _load(self) -> dict[str, object] | None:
        if not self.manifest_path.is_file():
            return None
        try:
            value = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TelegramDeliveryError("telegram_outbox_manifest_invalid") from exc
        if not isinstance(value, dict):
            raise TelegramDeliveryError("telegram_outbox_manifest_invalid")
        return value

    @staticmethod
    def _validate_identity(record: dict[str, object], message: MakerTelegramMessage) -> None:
        if record.get("message_sha256") != message.message_sha256:
            raise TelegramDeliveryError("telegram_outbox_identity_conflict")

    @staticmethod
    def _record(
        status: str,
        message: MakerTelegramMessage,
        *,
        message_id: int | None = None,
        error_code: str | None = None,
    ) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": "maker-telegram-outbox-v1",
            "status": status,
            "message_sha256": message.message_sha256,
            "evidence_snapshot_sha256": message.evidence_snapshot_sha256,
            "reasoning_sha256": message.reasoning_sha256,
            "decision_sha256": message.decision_sha256,
            "methodology_sha256": message.methodology_sha256,
        }
        if message_id is not None:
            result["message_id"] = message_id
        if error_code is not None:
            result["error_code"] = error_code
        return result

    def _write(self, value: dict[str, object]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.manifest_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.manifest_path)
