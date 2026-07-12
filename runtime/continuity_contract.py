"""Certify prior-plan/order lifecycle after independent reasoning is locked."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from outputs.daily_payload_builder import parse_daily_text_contract
from runtime.reasoning_lock import validate_reasoning_lock
from runtime.state_store import atomic_json_write


ROOT = Path(__file__).resolve().parents[1]
PAGE_ID = re.compile(r"^[0-9a-fA-F-]{32,36}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
ACTIONS = {"new", "keep", "cancel_replace", "cancel", "observe", "reconcile_filled"}
PRIOR_STATUSES = {"none", "pending", "open", "filled", "cancelled", "stopped", "expired"}
ACTION_TOKENS = {
    "new": ("新建", "挂新"),
    "keep": ("保持", "维持"),
    "cancel_replace": ("撤旧挂新", "撤销并替换"),
    "cancel": ("撤销", "取消"),
    "observe": ("观望", "不挂单"),
    "reconcile_filled": ("成交", "持仓校准"),
}


def _text(value: Any, field: str, minimum: int = 1) -> str:
    result = str(value or "").strip()
    if len(result) < minimum:
        raise ValueError(f"{field} must contain at least {minimum} characters")
    return result


def _timestamp(value: Any, field: str) -> str:
    text = _text(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include timezone")
    return parsed.isoformat(timespec="seconds")


def _hash(payload: dict[str, Any]) -> str:
    clean = dict(payload)
    clean.pop("contract_sha256", None)
    return hashlib.sha256(
        json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def manifest_path(trading_date: str, slot: str, *, root: Path = ROOT) -> Path:
    return root / "runtime_state" / trading_date / f"continuity_contract_{slot}.json"


def build_contract(
    payload: dict[str, Any],
    *,
    reasoning_lock_path: Path,
    trading_date: str,
    slot: str,
    root: Path = ROOT,
) -> dict[str, Any]:
    lock = validate_reasoning_lock(
        reasoning_lock_path, trading_date, slot, root=root
    )
    if payload.get("reasoning_lock_sha256") != lock["manifest_sha256"]:
        raise ValueError("continuity contract is not bound to independent reasoning lock")
    prior = payload.get("prior_plan")
    current = payload.get("current_plan")
    if not isinstance(prior, dict) or not isinstance(current, dict):
        raise ValueError("continuity contract requires prior_plan and current_plan objects")
    source_kind = str(prior.get("source_kind", ""))
    if source_kind not in {"none", "local_artifact", "notion_page"}:
        raise ValueError("prior_plan.source_kind is invalid")
    status = str(prior.get("status", ""))
    if status not in PRIOR_STATUSES:
        raise ValueError("prior_plan.status is invalid")
    reference = str(prior.get("reference") or "").strip()
    source_sha = str(prior.get("source_sha256") or "").lower()
    observed_at = prior.get("observed_at")
    if source_kind == "none":
        if status != "none" or reference or source_sha or observed_at:
            raise ValueError("no prior plan must not fabricate source metadata")
        normalized_observed_at = None
    else:
        normalized_observed_at = _timestamp(observed_at, "prior_plan.observed_at")
        if source_kind == "local_artifact":
            source_path = (root / reference).resolve()
            source_path.relative_to(root.resolve())
            if not source_path.is_file():
                raise ValueError("prior plan local artifact is missing")
            actual = hashlib.sha256(source_path.read_bytes()).hexdigest()
            if source_sha != actual:
                raise ValueError("prior plan local artifact hash mismatch")
        else:
            if not PAGE_ID.fullmatch(reference) or not SHA256.fullmatch(source_sha):
                raise ValueError("Notion prior plan requires page id and extracted-fields hash")
    before = int(prior.get("executable_order_count_before", 0))
    if before not in {0, 1}:
        raise ValueError("at most one executable system Maker order may exist before reconciliation")

    action = str(current.get("action", ""))
    if action not in ACTIONS:
        raise ValueError("current_plan.action is invalid")
    after = int(current.get("executable_order_count_after", 0))
    if after not in {0, 1}:
        raise ValueError("at most one executable system Maker order may remain")
    old_cancelled = current.get("old_order_cancelled") is True
    new_created = current.get("new_order_created") is True
    if current.get("independent_analysis_changed_after_lock") is not False:
        raise ValueError("prior-plan continuity must not change locked analysis")
    if action == "cancel_replace" and not (old_cancelled and new_created and after == 1):
        raise ValueError("cancel_replace requires old cancellation, new order and one active order")
    if action == "keep" and (old_cancelled or new_created or before != 1 or after != 1):
        raise ValueError("keep requires one unchanged prior executable order")
    if action == "new" and (before != 0 or not new_created or after != 1):
        raise ValueError("new requires no prior executable order and one new order")
    if action in {"cancel", "observe"} and after != 0:
        raise ValueError(f"{action} must leave zero executable orders")
    if action == "reconcile_filled" and status not in {"filled", "open"}:
        raise ValueError("reconcile_filled requires filled/open prior status")
    report_text = _text(payload.get("report_text"), "continuity report_text", 40)
    if not any(token in report_text for token in ACTION_TOKENS[action]):
        raise ValueError("continuity report_text does not state the certified lifecycle action")
    section = str(payload.get("projection_section", ""))
    if section not in {"opening_quote", "maker"}:
        raise ValueError("continuity projection_section must be opening_quote or maker")
    result: dict[str, Any] = {
        "schema_version": "post-reasoning-continuity-contract-v1",
        "status": "certified",
        "trading_date": trading_date,
        "slot": slot,
        "reasoning_lock": {
            "path": reasoning_lock_path.resolve().relative_to(root.resolve()).as_posix(),
            "sha256": lock["manifest_sha256"],
        },
        "prior_plan": {
            "source_kind": source_kind,
            "reference": reference or None,
            "source_sha256": source_sha or None,
            "observed_at": normalized_observed_at,
            "status": status,
            "executable_order_count_before": before,
            "summary": _text(prior.get("summary"), "prior_plan.summary", 12),
        },
        "current_plan": {
            "action": action,
            "old_order_cancelled": old_cancelled,
            "new_order_created": new_created,
            "executable_order_count_after": after,
            "independent_analysis_changed_after_lock": False,
            "reason": _text(current.get("reason"), "current_plan.reason", 20),
        },
        "projection_section": section,
        "report_text": report_text,
    }
    result["contract_sha256"] = _hash(result)
    return result


def validate_contract_file(
    path: Path,
    trading_date: str,
    slot: str,
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    resolved = path.resolve()
    resolved.relative_to((root / "runtime_state" / trading_date).resolve())
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if (
        payload.get("schema_version") != "post-reasoning-continuity-contract-v1"
        or payload.get("status") != "certified"
        or payload.get("trading_date") != trading_date
        or payload.get("slot") != slot
        or payload.get("contract_sha256") != _hash(payload)
    ):
        raise ValueError("continuity contract is invalid")
    lock_path = root / str((payload.get("reasoning_lock") or {}).get("path", ""))
    rebuilt = build_contract(
        {
            "reasoning_lock_sha256": (payload.get("reasoning_lock") or {}).get("sha256"),
            "prior_plan": payload.get("prior_plan"),
            "current_plan": payload.get("current_plan"),
            "projection_section": payload.get("projection_section"),
            "report_text": payload.get("report_text"),
        },
        reasoning_lock_path=lock_path,
        trading_date=trading_date,
        slot=slot,
        root=root,
    )
    if rebuilt != payload:
        raise ValueError("continuity contract differs from deterministic rebuild")
    return payload


def validate_report_continuity_projection(
    report: Path,
    continuity_contract: Path,
    trading_date: str,
    slot: str,
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    contract = validate_contract_file(
        continuity_contract, trading_date, slot, root=root
    )
    lines = report.read_text(encoding="utf-8").splitlines()
    visible = parse_daily_text_contract(lines, trading_date, slot)
    section = contract["projection_section"]
    actual = visible["opening_quote"] if section == "opening_quote" else "\n".join(visible["maker_main"])
    if actual.count(contract["report_text"]) != 1:
        raise ValueError("report does not contain exactly one certified continuity statement")
    return {"status": "passed", "contract_sha256": contract["contract_sha256"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--reasoning-lock", required=True, type=Path)
    parser.add_argument("--date", required=True)
    parser.add_argument("--slot", required=True, choices=("morning", "midday", "evening"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    contract = build_contract(
        payload, reasoning_lock_path=args.reasoning_lock,
        trading_date=args.date, slot=args.slot, root=ROOT
    )
    target = args.output or manifest_path(args.date, args.slot)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, target)
    print(json.dumps({"status": "CERTIFIED", "path": str(target), "sha256": contract["contract_sha256"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
