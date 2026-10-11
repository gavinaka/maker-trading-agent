"""Terminal Maker-only delivery lifecycle for the isolated Agent fork.

The inherited ``report`` and ``delivery`` stage slots remain intact for state
machine compatibility.  In this Agent they persist only an immutable typed
Maker certificate and a Telegram receipt; they never render a report.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from .controller import RunController
from .maker_delivery_gate import CertifiedMakerDelivery, certify_maker_delivery
from .maker_telegram import MakerTelegramMessage
from .telegram_delivery import TelegramDeliveryError
from .telegram_outbox import TelegramOutbox


class MakerDeliveryLifecycleError(RuntimeError):
    """A sealed Maker delivery lifecycle transition could not complete."""


def _certificate_payload(certified: CertifiedMakerDelivery) -> dict[str, Any]:
    payload = dict(certified.certificate)
    required = {
        "schema_version",
        "run_id",
        "trading_date",
        "slot",
        "run_mode",
        "message_sha256",
        "evidence_snapshot_sha256",
        "reasoning_sha256",
        "decision_sha256",
        "methodology_sha256",
        "canonical_model_sha256",
        "human_reasoning_depth",
        "template_contract",
    }
    if set(payload) != required or payload["schema_version"] != "maker-delivery-certificate-v1":
        raise MakerDeliveryLifecycleError("maker_certificate_invalid")
    return payload


def _prepared_certificate(
    controller: RunController,
    run_root,
) -> dict[str, Any]:
    try:
        output = controller.store.load_stage_output_record(
            run_root,
            "report",
            "maker_certificate",
        )
        path = controller.repo_root / str(output["path"])
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise MakerDeliveryLifecycleError("maker_certificate_missing") from exc
    if not isinstance(payload, dict):
        raise MakerDeliveryLifecycleError("maker_certificate_invalid")
    return payload


def _certificate_matches(
    stored: dict[str, Any],
    certified: CertifiedMakerDelivery,
) -> None:
    if stored != _certificate_payload(certified):
        raise MakerDeliveryLifecycleError("maker_certificate_binding_changed")


def _fail_stage(
    controller: RunController,
    run_root,
    stage: str,
    attempt: int,
    *,
    code: str,
) -> None:
    try:
        controller.store.fail_attempt(
            run_root,
            stage,
            attempt,
            failure_class="delivery_integrity",
            retryable=False,
            retry_scope="none",
            needs_manual_review=True,
            defects=[
                {
                    "code": code,
                    "message": "Maker Telegram delivery lifecycle stopped safely",
                    "path": stage,
                    "severity": "hard",
                }
            ],
        )
    except Exception:
        # Preserve the primary exception; a later process will orphan-recover
        # the still-open stage instead of assuming a delivery result.
        pass


def prepare_maker_delivery(
    controller: RunController,
    run_root,
) -> CertifiedMakerDelivery:
    """Seal a typed Maker certificate in the inherited report stage.

    No report text, document, image, Notion page or Telegram request is
    created by this operation.
    """

    certified = certify_maker_delivery(controller, run_root)
    attempt, attempt_root = controller.store.begin_attempt(run_root, "report")
    try:
        certificate = _certificate_payload(certified)
        record = controller.store.write_payload(
            attempt_root,
            "maker_certificate.json",
            certificate,
        )
        controller.store.complete_attempt(
            run_root,
            "report",
            attempt,
            {"maker_certificate": record},
            gate={
                "gate": "maker_typed_delivery_certification",
                "passed": True,
                "defects": [],
                "facts": certificate,
            },
        )
    except Exception as exc:
        _fail_stage(
            controller,
            run_root,
            "report",
            attempt,
            code="maker_delivery_certificate_persist_failed",
        )
        raise MakerDeliveryLifecycleError("maker_delivery_certificate_persist_failed") from exc
    return certified


def _begin_verified_delivery(
    controller: RunController,
    run_root,
) -> tuple[CertifiedMakerDelivery, int, Any]:
    certified = certify_maker_delivery(controller, run_root)
    stored = _prepared_certificate(controller, run_root)
    _certificate_matches(stored, certified)
    attempt, attempt_root = controller.store.begin_attempt(run_root, "delivery")
    return certified, attempt, attempt_root


def _complete_delivery(
    controller: RunController,
    run_root,
    *,
    certified: CertifiedMakerDelivery,
    attempt: int,
    attempt_root,
    receipt: dict[str, object],
) -> dict[str, Any]:
    message_id = receipt.get("message_id")
    if type(message_id) is not int or receipt.get("message_sha256") != certified.message.message_sha256:
        raise MakerDeliveryLifecycleError("maker_telegram_receipt_invalid")
    receipt_record = controller.store.write_payload(
        attempt_root,
        "telegram_receipt.json",
        {
            "schema_version": "maker-telegram-receipt-v1",
            "message_sha256": certified.message.message_sha256,
            "message_id": message_id,
        },
    )
    return controller.store.complete_attempt(
        run_root,
        "delivery",
        attempt,
        {"telegram_receipt": receipt_record},
        gate={
            "gate": "maker_telegram_sendMessage",
            "passed": True,
            "defects": [],
            "facts": {
                "message_sha256": certified.message.message_sha256,
                "message_id": message_id,
                "certificate": _certificate_payload(certified),
            },
        },
        terminal_metadata={
            "completion_mode": "maker_telegram",
            "notion_published": False,
        },
    )


def send_prepared_maker_delivery(
    controller: RunController,
    run_root,
    sender: Callable[[MakerTelegramMessage], dict[str, object]],
) -> dict[str, Any]:
    """Send exactly the pre-certified Maker message, then seal completion."""

    certified, attempt, attempt_root = _begin_verified_delivery(controller, run_root)
    try:
        receipt = TelegramOutbox(run_root / "telegram").send_once(
            certified.message,
            sender,
        )
        return _complete_delivery(
            controller,
            run_root,
            certified=certified,
            attempt=attempt,
            attempt_root=attempt_root,
            receipt=receipt,
        )
    except TelegramDeliveryError as exc:
        _fail_stage(controller, run_root, "delivery", attempt, code=exc.code)
        raise
    except Exception as exc:
        _fail_stage(
            controller,
            run_root,
            "delivery",
            attempt,
            code="maker_telegram_completion_failed",
        )
        raise MakerDeliveryLifecycleError("maker_telegram_completion_failed") from exc


def finalize_delivered_maker_delivery(
    controller: RunController,
    run_root,
) -> dict[str, Any]:
    """Recover only a known-delivered outbox record without another send."""

    certified, attempt, attempt_root = _begin_verified_delivery(controller, run_root)
    try:
        receipt = TelegramOutbox(run_root / "telegram").delivered_receipt(
            certified.message
        )
        return _complete_delivery(
            controller,
            run_root,
            certified=certified,
            attempt=attempt,
            attempt_root=attempt_root,
            receipt=receipt,
        )
    except Exception as exc:
        _fail_stage(
            controller,
            run_root,
            "delivery",
            attempt,
            code="maker_telegram_finalize_failed",
        )
        raise MakerDeliveryLifecycleError("maker_telegram_finalize_failed") from exc


__all__ = [
    "MakerDeliveryLifecycleError",
    "finalize_delivered_maker_delivery",
    "prepare_maker_delivery",
    "send_prepared_maker_delivery",
]
