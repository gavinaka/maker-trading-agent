"""Safe, compact CLI for the vNext controller.

The user-facing automation still starts one daily-report task.  This CLI is
the deterministic internal boundary used by that task.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .controller import RunController
from .delivery_renderer import (
    approve_run_qa,
    delivery_control_state,
    prepare_run_qa,
    reject_run_qa,
)
from .errors import WorkflowFailure
from .effort_policy import REQUESTED_EFFORT, REQUESTED_MODEL


ROOT = Path(__file__).resolve().parents[1]


def _json(path: str) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON input must be an object: {path}")
    return payload


def _run_root(controller: RunController, args: argparse.Namespace) -> Path:
    return controller.store.run_root(args.date, args.slot, args.run_id)


def _status(controller: RunController, run_root: Path) -> dict:
    result = controller.status(run_root)
    if result.get("status") == "running" and result.get("next_stage") == "delivery":
        result["delivery_control"] = delivery_control_state(ROOT, run_root)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    begin = commands.add_parser("begin")
    begin.add_argument("--date", required=True)
    begin.add_argument("--slot", required=True, choices=("morning", "midday", "evening"))
    begin.add_argument("--model", default=REQUESTED_MODEL)
    begin.add_argument("--effort", default=REQUESTED_EFFORT, choices=(REQUESTED_EFFORT,))
    begin.add_argument("--run-mode", required=True, choices=("shadow", "production"))
    begin.add_argument(
        "--authorization-ref",
        required=True,
        help="explicit approval reference; only its SHA-256 is persisted",
    )
    begin.add_argument("--run-id")
    begin.add_argument(
        "--allow-shadow-repeat",
        action="store_true",
        help="start another immutable shadow sample after a shadow_complete run in the same slot",
    )

    pretrade = commands.add_parser("pretrade-gate")
    pretrade.add_argument("--date", required=True)
    pretrade.add_argument("--slot", required=True, choices=("morning", "midday", "evening"))
    pretrade.add_argument("--run-id", required=True)
    pretrade.add_argument("--input", required=True)

    for name in (
        "host",
        "capture",
        "replay-evidence",
        "reasoning-contract-preflight",
        "reasoning-scaffold",
        "reasoning",
        "decision",
        "compile",
        "delivery",
        "shadow-delivery",
        "resume-review",
        "retire",
        "status",
    ):
        command = commands.add_parser(name)
        command.add_argument("--date", required=True)
        command.add_argument("--slot", required=True, choices=("morning", "midday", "evening"))
        command.add_argument("--run-id", required=True)
        if name in {"host", "replay-evidence", "reasoning", "decision", "delivery", "shadow-delivery", "resume-review", "retire"}:
            command.add_argument("--input", required=True)
        if name == "replay-evidence":
            command.add_argument("--evidence-files-root")
            command.add_argument(
                "--replay-authorization-ref",
                required=True,
                help="test:<opaque-ref> or replay:<opaque-ref>; must match the reference sealed at begin",
            )
    word_export = commands.add_parser("word-qa-export")
    word_approve = commands.add_parser("word-qa-approve")
    word_reject = commands.add_parser("word-qa-reject")
    for command in (word_export, word_approve, word_reject):
        command.add_argument("--date", required=True)
        command.add_argument("--slot", required=True, choices=("morning", "midday", "evening"))
        command.add_argument("--run-id", required=True)
    word_export.add_argument("--pdftoppm")
    word_export.add_argument("--export-timeout", type=int, default=600)
    word_approve.add_argument("--confirm-visual-pass", action="store_true", required=True)
    word_approve.add_argument("--reviewer", required=True)
    word_reject.add_argument("--reason", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    controller = RunController(ROOT)
    try:
        if args.command == "begin":
            root = controller.begin(
                args.date,
                args.slot,
                requested_model=args.model,
                requested_effort=args.effort,
                run_mode=args.run_mode,
                authorization_ref=args.authorization_ref,
                run_id=args.run_id,
                allow_shadow_repeat=args.allow_shadow_repeat,
            )
            result = {
                "status": "started",
                "run_id": root.name,
                "run_mode": args.run_mode,
                "next_stage": "evidence",
            }
        elif args.command == "pretrade-gate":
            payload = _json(args.input)
            root = _run_root(controller, args)
            result = controller.record_pretrade_gate(root, **payload)
            result = {
                "status": result["status"],
                "trading_date": result["trading_date"],
                "subjective_conclusion": result["subjective_conclusion"],
            }
        else:
            root = _run_root(controller, args)
            if args.command == "host":
                controller.record_host_capability(root, _json(args.input))
                result = {"status": "verified", "run_id": root.name}
            elif args.command == "capture":
                controller.capture(root)
                result = _status(controller, root)
            elif args.command == "replay-evidence":
                controller.accept_replay_evidence(
                    root,
                    _json(args.input),
                    replay_authorization_ref=args.replay_authorization_ref,
                    evidence_files_root=Path(args.evidence_files_root).resolve() if args.evidence_files_root else None,
                )
                result = _status(controller, root)
            elif args.command == "reasoning-contract-preflight":
                result = controller.reasoning_contract_preflight(root)
            elif args.command == "reasoning-scaffold":
                result = controller.reasoning_scaffold(root)
            elif args.command == "reasoning":
                controller.accept_reasoning(root, _json(args.input))
                result = _status(controller, root)
            elif args.command == "decision":
                controller.accept_decision(root, _json(args.input))
                result = _status(controller, root)
            elif args.command == "compile":
                controller.compile_report(root)
                result = _status(controller, root)
            elif args.command == "word-qa-export":
                result = prepare_run_qa(
                    ROOT,
                    root,
                    pdftoppm=args.pdftoppm,
                    export_timeout=args.export_timeout,
                )
            elif args.command == "word-qa-approve":
                result = approve_run_qa(
                    ROOT,
                    root,
                    reviewer=args.reviewer,
                    confirm_visual_pass=args.confirm_visual_pass,
                )
            elif args.command == "word-qa-reject":
                result = reject_run_qa(ROOT, root, reason=args.reason)
            elif args.command == "delivery":
                controller.accept_delivery(root, _json(args.input))
                result = _status(controller, root)
            elif args.command == "shadow-delivery":
                controller.accept_shadow_delivery(root, _json(args.input))
                result = _status(controller, root)
            elif args.command == "resume-review":
                controller.authorize_manual_review(root, _json(args.input))
                result = _status(controller, root)
            elif args.command == "retire":
                controller.retire_run(root, _json(args.input))
                result = _status(controller, root)
            else:
                result = _status(controller, root)
    except WorkflowFailure as exc:
        defect_codes = [
            str(defect["code"])
            for defect in exc.defects
            if isinstance(defect, dict) and defect.get("code")
        ]
        print(
            json.dumps(
                {
                    "status": "failed",
                    "failure_class": exc.failure_class.value,
                    "failure_code": defect_codes[0] if len(defect_codes) == 1 else None,
                    "retryable": exc.policy.retryable,
                    "retry_scope": exc.policy.retry_scope.value,
                    "defect_count": len(exc.defects),
                    "defect_codes": defect_codes,
                },
                ensure_ascii=False,
            )
        )
        return 2
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError):
        print(
            json.dumps(
                {
                    "status": "failed",
                    "failure_class": "invalid_input_or_state",
                    "retryable": False,
                    "retry_scope": "none",
                },
                ensure_ascii=False,
            )
        )
        return 3
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
