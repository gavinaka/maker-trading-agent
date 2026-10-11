"""Narrow Telegram sendMessage client for already-rendered Maker messages."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .maker_telegram import MakerTelegramMessage


class TelegramDeliveryError(RuntimeError):
    """A non-secret-safe Telegram delivery failure."""

    def __init__(self, code: str, *, outcome_unknown: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.outcome_unknown = outcome_unknown


@dataclass(frozen=True, slots=True)
class TelegramCredentials:
    bot_token: str
    chat_id: str

    @classmethod
    def from_environment(cls) -> "TelegramCredentials":
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            raise TelegramDeliveryError("telegram_credentials_missing")
        return cls(bot_token=token, chat_id=chat_id)


def send_maker_message(
    message: MakerTelegramMessage,
    credentials: TelegramCredentials,
    *,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Send exactly one sealed message, with no Telegram parse mode or previews."""

    if type(message) is not MakerTelegramMessage:
        raise TypeError("Telegram delivery accepts only MakerTelegramMessage")
    if type(credentials) is not TelegramCredentials:
        raise TypeError("Telegram delivery accepts only TelegramCredentials")
    body = json.dumps(
        {
            "chat_id": credentials.chat_id,
            "text": message.text,
            "link_preview_options": {"is_disabled": True},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = Request(
        f"https://api.telegram.org/bot{credentials.bot_token}/sendMessage",
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310: fixed Telegram API host
            raw = response.read()
    except HTTPError as exc:
        raise TelegramDeliveryError(f"telegram_http_{exc.code}") from exc
    except URLError as exc:
        raise TelegramDeliveryError("telegram_network_failure", outcome_unknown=True) from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TelegramDeliveryError("telegram_invalid_json", outcome_unknown=True) from exc
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise TelegramDeliveryError("telegram_rejected")
    result = payload.get("result")
    if not isinstance(result, dict) or type(result.get("message_id")) is not int:
        raise TelegramDeliveryError("telegram_missing_message_id", outcome_unknown=True)
    return {"message_id": result["message_id"], "message_sha256": message.message_sha256}
