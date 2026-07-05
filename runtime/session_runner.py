"""CLI orchestration for incremental evidence and full-session analysis."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.context_pack import ensure_context_pack
from runtime.delivery_evidence import validate_delivery_evidence
from runtime.golden_reasoning import (
    build_golden_reasoning_manifest,
    validate_golden_reasoning_manifest,
)
from runtime.report_state_extract import extract_report_state, validate_report_state
from runtime.state_store import (
    atomic_json_write,
    commit_transition,
    load_json,
    prepare_transition,
)
from runtime.usage_logger import append_usage
from runtime.workflow_lease import (
    abandon_lease,
    assert_lease,
    begin_lease,
    complete_lease,
    recover_lease,
)
from outputs.report_structure_gate import assert_combined_structure


PAGE_ID = re.compile(
    r"^(?:[0-9a-f]{32}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$",
    re.I,
)


def load_object(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def commit_identifier(
    trading_date: str,
    slot: str,
    state_version: int,
    report_sha256: str,
) -> str:
    raw = f"{trading_date}:{slot}:{state_version}:{report_sha256}"
    return hashlib.sha256(raw.encode("ascii")).hexdigest()


def run_report_lint(report: Path) -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "outputs" / "report_lint.py"), str(report)],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if completed.returncode != 0:
        detail = (completed.stdout + "\n" + completed.stderr).strip()
        raise ValueError("report lint failed before analysis lock:\n" + detail)


def validate_report_structure(report: Path, trading_date: str, slot: str) -> None:
    lines = report.read_text(encoding="utf-8").splitlines()
    assert_combined_structure(lines, trading_date, slot)


def add_usage_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input-tokens", type=int)
    parser.add_argument("--output-tokens", type=int)
    parser.add_argument("--tool-calls", type=int)
    parser.add_argument("--retries", type=int, default=0)


def add_lease_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--lease-token",
        required=True,
        help="token returned by begin-session; held through successful delivery",
    )


def usage_values(args: argparse.Namespace) -> dict:
    return {
        "input_tokens": getattr(args, "input_tokens", None),
        "output_tokens": getattr(args, "output_tokens", None),
        "tool_calls": getattr(args, "tool_calls", None),
        "retries": getattr(args, "retries", 0),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Three-session evidence cache and full-analysis runner"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    begin = sub.add_parser("begin-session")
    begin.add_argument("--date", required=True)
    begin.add_argument("--slot", required=True, choices=("morning", "midday", "evening"))
    begin.add_argument("--skip-prior-delivery-reason")

    abandon = sub.add_parser("abandon-session")
    abandon.add_argument("--date", required=True)
    abandon.add_argument("--slot", required=True, choices=("morning", "midday", "evening"))
    abandon.add_argument("--reason", required=True)
    add_lease_argument(abandon)

    recover = sub.add_parser("recover-session")
    recover.add_argument("--date", required=True)
    recover.add_argument("--slot", required=True, choices=("morning", "midday", "evening"))
    recover.add_argument("--reason", required=True)
    recover.add_argument("--skip-prior-delivery-reason")

    prepare = sub.add_parser("prepare")
    prepare.add_argument("--date", required=True)
    prepare.add_argument(
        "--slot", required=True, choices=("morning", "midday", "evening")
    )
    prepare.add_argument(
        "--max-reasoning-confirmed",
        action="store_true",
        required=True,
        help="attest that the host is on its highest available model and MAX effort",
    )
    prepare.add_argument(
        "--external-change",
        action="append",
        default=[],
        choices=("notion_positions", "notion_gate"),
    )
    prepare.add_argument("--full-recollection-performed", action="store_true")
    prepare.add_argument("--replace-prepared-transition", action="store_true")
    prepare.add_argument("--capture-manifest", required=True, type=Path)
    add_lease_argument(prepare)
    add_usage_arguments(prepare)

    lock_analysis = sub.add_parser("lock-analysis")
    lock_analysis.add_argument("--date", required=True)
    lock_analysis.add_argument(
        "--slot", required=True, choices=("morning", "midday", "evening")
    )
    lock_analysis.add_argument("--report", required=True, type=Path)
    lock_analysis.add_argument(
        "--confirm-five-source-validation",
        action="store_true",
        required=True,
        help=(
            "legacy flag name; confirms all REQUIRED_SOURCES are valid, "
            "including Farside BTC ETF Flow"
        ),
    )
    lock_analysis.add_argument(
        "--confirm-full-analysis", action="store_true", required=True
    )
    lock_analysis.add_argument(
        "--confirm-no-prior-judgment", action="store_true", required=True
    )
    lock_analysis.add_argument(
        "--confirm-max-through-analysis", action="store_true", required=True
    )
    add_lease_argument(lock_analysis)
    add_usage_arguments(lock_analysis)

    finalize = sub.add_parser("finalize-post-lock")
    finalize.add_argument("--date", required=True)
    finalize.add_argument(
        "--slot", required=True, choices=("morning", "midday", "evening")
    )
    finalize.add_argument(
        "--confirm-prior-plan-continuity-reviewed",
        action="store_true",
        required=True,
    )
    finalize.add_argument(
        "--confirm-evening-independent-review",
        action="store_true",
    )
    finalize.add_argument(
        "--confirm-max-through-post-lock",
        action="store_true",
        required=True,
    )
    add_lease_argument(finalize)
    add_usage_arguments(finalize)

    commit = sub.add_parser("commit")
    commit.add_argument("--date", required=True)
    commit.add_argument(
        "--slot", required=True, choices=("morning", "midday", "evening")
    )
    commit_input = commit.add_mutually_exclusive_group(required=True)
    commit_input.add_argument("--report", type=Path)
    commit_input.add_argument("--updates", type=Path)
    commit.add_argument("--analysis-lock", type=Path)
    add_lease_argument(commit)
    add_usage_arguments(commit)

    deliver = sub.add_parser("deliver")
    deliver.add_argument("--date", required=True)
    deliver.add_argument(
        "--slot", required=True, choices=("morning", "midday", "evening")
    )
    deliver.add_argument("--page-id", required=True)
    deliver.add_argument("--published-at")
    deliver.add_argument("--frozen-verifier-pass", action="store_true")
    deliver.add_argument("--word-visual-qa-pass", action="store_true")
    deliver.add_argument("--unique-page-pass", action="store_true")
    add_lease_argument(deliver)
    add_usage_arguments(deliver)

    args = parser.parse_args()
    started = time.perf_counter()

    if args.command == "begin-session":
        lease = begin_lease(
            args.date,
            args.slot,
            skip_prior_delivery_reason=args.skip_prior_delivery_reason,
        )
        print(json.dumps(lease, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "recover-session":
        lease = recover_lease(
            args.date,
            args.slot,
            reason=args.reason,
            skip_prior_delivery_reason=args.skip_prior_delivery_reason,
        )
        print(json.dumps(lease, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "abandon-session":
        assert_lease(args.date, args.slot, args.lease_token)
        closed = abandon_lease(args.lease_token, reason=args.reason)
        print(json.dumps(closed, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    directory = ROOT / "runtime_state" / args.date
    lease = assert_lease(args.date, args.slot, args.lease_token)

    if args.command == "prepare":
        _, context_target, context_reused = ensure_context_pack(args.date, args.slot)
        delta_manifest = load_json(args.capture_manifest.resolve())
        full_recollection_performed = bool(
            args.full_recollection_performed
            or (
                isinstance(delta_manifest, dict)
                and (
                    delta_manifest.get("mode") == "full_recollection"
                    or (
                        delta_manifest.get("full_fallback_used") is True
                        and delta_manifest.get("fallback_code") == 0
                    )
                )
            )
        )
        transition, target = prepare_transition(
            args.date,
            args.slot,
            external_changes=set(args.external_change),
            max_reasoning_confirmed=args.max_reasoning_confirmed,
            full_recollection_performed=full_recollection_performed,
            replace_prepared_transition=args.replace_prepared_transition,
            capture_manifest_path=args.capture_manifest,
            workflow_lease_id=lease["lease_id"],
            prior_state_skip_reason=(
                lease.get("prior_delivery_skip", {}).get("reason")
                if isinstance(lease.get("prior_delivery_skip"), dict)
                else None
            ),
        )
        _, golden_target = build_golden_reasoning_manifest(
            args.date,
            args.slot,
            capture_manifest_path=args.capture_manifest,
            transition_path=target,
        )
        event_id = (
            f"{args.date}:{args.slot}:prepare:{transition['state_version']}:"
            f"{hashlib.sha256(json.dumps(transition['sources'], sort_keys=True).encode()).hexdigest()}"
        )
        append_usage(
            trading_date=args.date,
            slot=args.slot,
            phase="prepare",
            status="success",
            event_id=event_id,
            duration_ms=round((time.perf_counter() - started) * 1000),
            full_fallbacks=int(transition["full_fallback_used"]),
            details={
                "context_pack": str(context_target),
                "context_pack_reused": context_reused,
                "transition": str(target),
                "changed_sources": transition["changed_sources"],
                "source_affected_nodes": transition["source_affected_nodes"],
                "invalidated_nodes": transition["invalidated_nodes"],
                "analysis_policy": transition["analysis_policy"],
                "collection_mode": transition["collection_mode"],
                "golden_reasoning_manifest": str(golden_target),
            },
            **usage_values(args),
        )
        print(json.dumps(transition, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    transition_path = directory / f"transition_{args.slot}.json"
    transition = load_object(transition_path)

    if args.command == "lock-analysis":
        report = args.report.resolve()
        _, golden_target = validate_golden_reasoning_manifest(
            args.date,
            args.slot,
            report,
        )
        validate_report_structure(report, args.date, args.slot)
        run_report_lint(report)
        text = report.read_text(encoding="utf-8")
        updates = extract_report_state(text)
        omissions = validate_report_state(text, updates)
        if omissions:
            raise ValueError(
                "analysis lock blocked by incomplete report: " + ", ".join(omissions)
            )
        report_sha256 = sha256_file(report)
        commit_id = commit_identifier(
            args.date,
            args.slot,
            transition["state_version"],
            report_sha256,
        )
        payload = {
            "schema_version": "1.0",
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "trading_date": args.date,
            "slot": args.slot,
            "state_version": transition["state_version"],
            "report_path": str(report),
            "report_sha256": report_sha256,
            "commit_id": commit_id,
            "five_source_validation_passed": True,
            "full_analysis_confirmed": True,
            "prior_judgment_read_before_lock": False,
            "max_reasoning_confirmed": True,
            "max_through_analysis_confirmed": True,
            "max_through_post_lock_confirmed": False,
            "analysis_validation": {
                "lint_passed": True,
                "report_state_validated": True,
                "report_state_omissions": [],
                "source_coverage_validated": True,
                "position_coupling_absent": True,
                "golden_reasoning_alignment_prepared": True,
                "golden_reasoning_manifest": str(golden_target),
                "golden_reasoning_policy": (
                    "pre_write_reasoning_alignment_not_posthoc_output_padding"
                ),
            },
            "operator_confirmations": {
                "five_source_validation": args.confirm_five_source_validation,
                "full_analysis": args.confirm_full_analysis,
                "no_prior_judgment": args.confirm_no_prior_judgment,
                "max_through_analysis": args.confirm_max_through_analysis,
            },
            "completed_nodes": transition["invalidated_nodes"],
            "post_lock_completed_nodes": [],
        }
        target = directory / f"analysis_lock_{args.slot}.json"
        existing = load_json(target)
        if existing:
            if existing.get("commit_id") != commit_id:
                raise ValueError("a different analysis is already locked for this slot")
            payload = existing
        else:
            atomic_json_write(target, payload)
        append_usage(
            trading_date=args.date,
            slot=args.slot,
            phase="analysis_lock",
            status="success",
            event_id=f"{commit_id}:analysis_lock",
            duration_ms=round((time.perf_counter() - started) * 1000),
            details={
                "analysis_lock": str(target),
                "report_sha256": report_sha256,
                "completed_node_count": len(payload["completed_nodes"]),
                "golden_reasoning_manifest": str(golden_target),
            },
            **usage_values(args),
        )
        print(json.dumps({"analysis_lock": str(target), "commit_id": commit_id}))
        return 0

    if args.command == "finalize-post-lock":
        target = directory / f"analysis_lock_{args.slot}.json"
        analysis_lock = load_object(target)
        required_post_lock = set(transition.get("post_lock_nodes", []))
        completed_post_lock = {"post_lock:prior_plan_continuity"}
        if args.slot == "evening":
            if not args.confirm_evening_independent_review:
                raise ValueError(
                    "evening post-lock finalization requires independent review"
                )
            completed_post_lock.add("post_lock:evening_independent_review")
        if completed_post_lock != required_post_lock:
            raise ValueError(
                "post-lock node mismatch: "
                f"expected={sorted(required_post_lock)}, "
                f"actual={sorted(completed_post_lock)}"
            )
        already_finalized = (
            set(analysis_lock.get("post_lock_completed_nodes", []))
            == completed_post_lock
            and analysis_lock.get("max_through_post_lock_confirmed") is True
        )
        if not already_finalized:
            analysis_lock["post_lock_completed_nodes"] = sorted(completed_post_lock)
            analysis_lock["max_through_post_lock_confirmed"] = True
            analysis_lock["post_lock_finalized_at"] = (
                datetime.now().astimezone().isoformat(timespec="seconds")
            )
            atomic_json_write(target, analysis_lock)
        append_usage(
            trading_date=args.date,
            slot=args.slot,
            phase="post_lock_finalize",
            status="success",
            event_id=f"{analysis_lock['commit_id']}:post_lock_finalize",
            duration_ms=round((time.perf_counter() - started) * 1000),
            details={
                "analysis_lock": str(target),
                "post_lock_completed_nodes": sorted(completed_post_lock),
            },
            **usage_values(args),
        )
        print(json.dumps({"analysis_lock": str(target), "post_lock": "complete"}))
        return 0

    if args.command == "commit":
        lock_path = (
            args.analysis_lock.resolve()
            if args.analysis_lock
            else directory / f"analysis_lock_{args.slot}.json"
        )
        analysis_lock = load_object(lock_path)
        if args.report:
            report = args.report.resolve()
            report_sha256 = sha256_file(report)
            if report_sha256 != analysis_lock.get("report_sha256"):
                raise ValueError("report changed after analysis lock")
            validate_report_structure(report, args.date, args.slot)
            text = report.read_text(encoding="utf-8")
            updates = extract_report_state(text)
            omissions = validate_report_state(text, updates)
            if omissions:
                raise ValueError(
                    "commit blocked by incomplete report: " + ", ".join(omissions)
                )
        else:
            report_value = analysis_lock.get("report_path")
            if not report_value:
                raise ValueError("analysis lock is missing report_path")
            report = Path(str(report_value)).resolve()
            if not report.exists():
                raise ValueError(f"locked report is missing: {report}")
            if sha256_file(report) != analysis_lock.get("report_sha256"):
                raise ValueError("locked report changed after analysis lock")
            validate_report_structure(report, args.date, args.slot)
            updates = load_object(args.updates)
        resolved, target = commit_transition(
            args.date,
            args.slot,
            updates,
            analysis_lock,
            analysis_lock["commit_id"],
        )
        append_usage(
            trading_date=args.date,
            slot=args.slot,
            phase="commit",
            status="success",
            event_id=f"{analysis_lock['commit_id']}:commit",
            duration_ms=round((time.perf_counter() - started) * 1000),
            full_fallbacks=int(resolved["full_fallback_used"]),
            details={
                "resolved_state": str(target),
                "analysis_policy": resolved["analysis_policy"],
                "recomputed_nodes": resolved["recomputed_nodes"],
                "idempotent_reuse": resolved.get("idempotent_reuse", False),
            },
            **usage_values(args),
        )
        print(json.dumps({"resolved_state": str(target)}, ensure_ascii=False))
        return 0

    try:
        if not PAGE_ID.fullmatch(args.page_id):
            raise ValueError("invalid Notion page id")
        current = load_object(directory / "current.json")
        if current.get("slot") != args.slot:
            raise ValueError("final delivery blocked before matching state commit")
        evidence = validate_delivery_evidence(
            args.date,
            args.slot,
            args.page_id,
            current=current,
        )
        if args.published_at:
            datetime.fromisoformat(args.published_at.replace("Z", "+00:00"))
            if args.published_at != evidence["published_at"]:
                raise ValueError("--published-at does not match publish manifest")
    except BaseException as exc:
        reason_hash = hashlib.sha256(str(exc).encode("utf-8")).hexdigest()[:16]
        append_usage(
            trading_date=args.date,
            slot=args.slot,
            phase="delivery",
            status="failed",
            event_id=f"{args.date}:{args.slot}:delivery:failed:{reason_hash}",
            duration_ms=round((time.perf_counter() - started) * 1000),
            details={
                "cache_hit": False,
                "attempt": 1,
                "backend": "local_evidence_gate",
                "page_id": args.page_id,
                "failure_reason": str(exc),
            },
            **usage_values(args),
        )
        raise
    payload = {
        "schema_version": "2.0",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "trading_date": args.date,
        "slot": args.slot,
        "commit_id": current["commit_id"],
        "workflow_lease_id": lease["lease_id"],
        "page_id": args.page_id,
        "published_at": evidence["published_at"],
        "frozen_verifier_pass": True,
        "word_visual_qa_pass": True,
        "unique_page_pass": True,
        "context_log_recorded": True,
        "evidence": evidence,
    }
    target = directory / f"delivery_{args.slot}.json"
    existing = load_json(target)
    if existing:
        if (
            existing.get("page_id") != args.page_id
            or existing.get("commit_id") != current["commit_id"]
        ):
            raise ValueError("a different final page is already recorded for this slot")
        payload = existing
    else:
        atomic_json_write(target, payload)
    append_usage(
        trading_date=args.date,
        slot=args.slot,
        phase="delivery",
        status="success",
        event_id=f"{current['commit_id']}:delivery:{args.page_id}",
        duration_ms=round((time.perf_counter() - started) * 1000),
        details={
            "cache_hit": False,
            "attempt": 1,
            "backend": "local_evidence_gate",
            "delivery_manifest": str(target),
            "page_id": args.page_id,
            "published_at": evidence["published_at"],
            **evidence,
        },
        **usage_values(args),
    )
    complete_lease(args.lease_token, artifact=str(target))
    print(json.dumps({"delivery_manifest": str(target)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
