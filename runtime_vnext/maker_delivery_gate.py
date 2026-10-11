"""Certified Maker Telegram delivery boundary without report rendering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .controller import RunController, _load_blockbeats_rows, _load_report_presentation_contract
from .domain_ir import project_canonical_report_model
from .kernel_lock import KernelLockError, assert_kernel_lock
from .maker_telegram import MakerTelegramMessage, evaluate_maker_telegram_template, render_maker_telegram
from .validation.report import certify_report_projection_input, evaluate_human_reasoning_depth


class MakerDeliveryGateBlocked(RuntimeError):
    """A Maker message is not legally eligible for external delivery."""


@dataclass(frozen=True, slots=True)
class CertifiedMakerDelivery:
    message: MakerTelegramMessage
    certificate: dict[str, Any]


def _required_decision_checkpoint(checkpoint: dict[str, Any]) -> None:
    completed = checkpoint.get("completed")
    if (
        checkpoint.get("status") != "running"
        or checkpoint.get("next_stage") not in {"report", "delivery"}
        or not isinstance(completed, dict)
        or not {"evidence", "reasoning", "decision"}.issubset(completed)
    ):
        raise MakerDeliveryGateBlocked("maker_decision_not_final")


def certify_maker_delivery(
    controller: RunController,
    run_root,
) -> CertifiedMakerDelivery:
    """Re-certify the full typed decision and its depth immediately before send.

    This intentionally creates neither Markdown nor Word/PDF/Notion output.
    It reuses the same canonical model solely in memory to retain the original
    six-source, proof-topology, scenario and closure gates.
    """

    try:
        assert_kernel_lock(controller.repo_root)
        controller._assert_preflight(run_root)
        run = controller._execution_run(run_root)
        if run.get("run_mode") != "production":
            raise MakerDeliveryGateBlocked("maker_shadow_run_forbidden")
        checkpoint = controller.store.load_checkpoint(run_root)
        _required_decision_checkpoint(checkpoint)
        methodology = controller._assert_methodology_phase(run_root, "report")
        evidence = controller.store.load_stage_payload(run_root, "evidence", "evidence")
        reasoning = controller.store.load_stage_payload(run_root, "reasoning", "reasoning")
        decision = controller.store.load_stage_payload(run_root, "decision", "decision")
        presentation_contract, presentation_contract_sha256 = _load_report_presentation_contract(
            controller.repo_root
        )
        source = certify_report_projection_input(
            evidence=evidence,
            reasoning=reasoning,
            decision=decision,
            blockbeats_rows=_load_blockbeats_rows(controller.repo_root, evidence),
            presentation_contract=presentation_contract,
            presentation_contract_sha256=presentation_contract_sha256,
            methodology_sha256=methodology["phases"]["reasoning"]["phase_sha256"],
            report_contract_sha256=methodology["phases"]["report"]["phase_sha256"],
        )
        model = project_canonical_report_model(source)
        depth_gate = evaluate_human_reasoning_depth(
            model,
            contract=presentation_contract,
        )
        if not depth_gate["passed"]:
            raise MakerDeliveryGateBlocked("maker_reasoning_depth_failed")
        message = render_maker_telegram(source)
        template_gate = evaluate_maker_telegram_template(source, message)
        if not template_gate["passed"]:
            raise MakerDeliveryGateBlocked("maker_template_contract_failed")
    except MakerDeliveryGateBlocked:
        raise
    except KernelLockError as exc:
        raise MakerDeliveryGateBlocked(str(exc)) from exc
    except Exception as exc:
        raise MakerDeliveryGateBlocked("maker_decision_not_certified") from exc

    return CertifiedMakerDelivery(
        message=message,
        certificate={
            "schema_version": "maker-delivery-certificate-v1",
            "run_id": run["run_id"],
            "trading_date": run["trading_date"],
            "slot": run["slot"],
            "run_mode": run["run_mode"],
            "message_sha256": message.message_sha256,
            "evidence_snapshot_sha256": message.evidence_snapshot_sha256,
            "reasoning_sha256": message.reasoning_sha256,
            "decision_sha256": message.decision_sha256,
            "methodology_sha256": message.methodology_sha256,
            "canonical_model_sha256": model["model_sha256"],
            "human_reasoning_depth": depth_gate["facts"],
            "template_contract": template_gate["facts"],
        },
    )


__all__ = ["CertifiedMakerDelivery", "MakerDeliveryGateBlocked", "certify_maker_delivery"]
