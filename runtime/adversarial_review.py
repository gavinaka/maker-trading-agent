"""Validate an isolated second-pass challenge of a frozen reasoning contract.

This is not represented as an independent statistical oracle.  It is a
hash-ordered adversarial pass whose purpose is to make omitted counterevidence,
source-transcription uncertainty and score contamination fail closed before a
decision contract can be certified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.reasoning_contract import (
    HIGH_IMPACT_CLAIM_TYPES,
    validate_reasoning_contract_file,
)


REQUIRED_CHECKS = {
    "source_integrity",
    "claim_support",
    "competing_interpretation",
    "score_contamination",
    "risk_semantics",
}
ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{2,79}$")


def _hash(payload: dict[str, Any]) -> str:
    clean = dict(payload)
    clean.pop("review_sha256", None)
    return hashlib.sha256(
        json.dumps(
            clean,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _text(value: Any, field: str, minimum: int = 1) -> str:
    normalized = str(value or "").strip()
    if len(normalized) < minimum:
        raise ValueError(f"{field} must contain at least {minimum} characters")
    return normalized


def build_adversarial_review(
    payload: dict[str, Any],
    *,
    reasoning_contract_path: Path,
    trading_date: str,
    slot: str,
    root: Path = ROOT,
) -> dict[str, Any]:
    reasoning = validate_reasoning_contract_file(
        reasoning_contract_path, trading_date, slot, root=root
    )
    if payload.get("reasoning_contract_sha256") != reasoning["contract_sha256"]:
        raise ValueError("adversarial review is not bound to reasoning contract")
    if payload.get("reviewer_mode") != "isolated_second_pass":
        raise ValueError("adversarial review requires isolated_second_pass mode")

    observations = {item["id"]: item for item in reasoning["observations"]}
    claims = {item["id"]: item for item in reasoning["claims"]}
    nodes = set(observations) | set(claims)
    high_impact = {
        item["id"]
        for item in reasoning["claims"]
        if item["claim_type"] in HIGH_IMPACT_CLAIM_TYPES
    }
    reviewed = payload.get("reviewed_claim_ids")
    if not isinstance(reviewed, list):
        raise ValueError("reviewed_claim_ids must be an array")
    reviewed_ids = {str(value) for value in reviewed}
    missing = sorted(high_impact - reviewed_ids)
    unknown = sorted(reviewed_ids - set(claims))
    if missing or unknown:
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if unknown:
            details.append("unknown=" + ",".join(unknown))
        raise ValueError("adversarial review claim coverage invalid: " + "; ".join(details))

    verdicts = payload.get("claim_verdicts")
    if not isinstance(verdicts, list):
        raise ValueError("adversarial review claim_verdicts must be an array")
    normalized_verdicts: list[dict[str, Any]] = []
    verdict_ids: set[str] = set()
    for index, item in enumerate(verdicts):
        if not isinstance(item, dict):
            raise ValueError(f"claim_verdicts[{index}] must be an object")
        claim_id = str(item.get("claim_id", ""))
        if claim_id not in high_impact or claim_id in verdict_ids:
            raise ValueError(f"claim_verdicts[{index}] has invalid or duplicate claim_id")
        verdict_ids.add(claim_id)
        claim = claims[claim_id]
        status = str(item.get("status", ""))
        if status not in {"uphold", "reject"}:
            raise ValueError(f"claim verdict {claim_id} status must be uphold or reject")
        support_ids = {str(value) for value in item.get("challenged_support_ids") or []}
        counter_ids = {str(value) for value in item.get("challenged_counter_ids") or []}
        if not support_ids or not support_ids.issubset(set(claim["support_ids"])):
            raise ValueError(f"claim verdict {claim_id} must challenge concrete support nodes")
        if not counter_ids or not counter_ids.issubset(set(claim["counter_ids"])):
            raise ValueError(f"claim verdict {claim_id} must challenge concrete counter nodes")
        resolution_ids = {str(value) for value in item.get("resolution_node_ids") or []}
        if not resolution_ids or not resolution_ids.issubset(nodes):
            raise ValueError(f"claim verdict {claim_id} requires valid resolution nodes")
        if not resolution_ids.intersection(set(claim["support_ids"])):
            raise ValueError(f"claim verdict {claim_id} resolution must return to claim support")
        if status == "reject":
            raise ValueError(f"adversarial review rejected frozen reasoning claim: {claim_id}")
        normalized_verdicts.append(
            {
                "claim_id": claim_id,
                "status": "uphold",
                "challenged_support_ids": sorted(support_ids),
                "challenged_counter_ids": sorted(counter_ids),
                "resolution_node_ids": sorted(resolution_ids),
                "why_counter_does_not_flip": _text(
                    item.get("why_counter_does_not_flip"),
                    f"claim verdict {claim_id}.why_counter_does_not_flip",
                    20,
                ),
                "residual_uncertainty": _text(
                    item.get("residual_uncertainty"),
                    f"claim verdict {claim_id}.residual_uncertainty",
                    12,
                ),
            }
        )
    if verdict_ids != high_impact:
        raise ValueError(
            "adversarial review claim_verdicts coverage invalid: missing="
            + ",".join(sorted(high_impact - verdict_ids))
        )

    checks = payload.get("checks")
    if not isinstance(checks, list):
        raise ValueError("adversarial review checks must be an array")
    normalized_checks: list[dict[str, Any]] = []
    check_types: set[str] = set()
    checked_nodes: set[str] = set()
    rejected: list[str] = []
    for index, item in enumerate(checks):
        if not isinstance(item, dict):
            raise ValueError(f"adversarial review checks[{index}] must be an object")
        check_id = _text(item.get("id"), f"review check {index}.id")
        if not ID_RE.fullmatch(check_id):
            raise ValueError(f"review check {index}.id has invalid syntax")
        if any(existing["id"] == check_id for existing in normalized_checks):
            raise ValueError(f"duplicate adversarial review check id: {check_id}")
        check_type = str(item.get("check_type", ""))
        if check_type not in REQUIRED_CHECKS:
            raise ValueError(f"unsupported adversarial review check: {check_type}")
        status = str(item.get("status", ""))
        if status not in {"pass", "reject"}:
            raise ValueError(f"review check {check_id} status must be pass or reject")
        refs = item.get("node_ids")
        if not isinstance(refs, list) or not refs:
            raise ValueError(f"review check {check_id} requires node_ids")
        clean_refs: list[str] = []
        for ref in refs:
            node_id = str(ref)
            if node_id not in nodes:
                raise ValueError(f"review check {check_id} references missing node")
            if node_id not in clean_refs:
                clean_refs.append(node_id)
        record = {
            "id": check_id,
            "check_type": check_type,
            "status": status,
            "node_ids": clean_refs,
            "challenge": _text(item.get("challenge"), f"review check {check_id}.challenge", 12),
            "resolution": _text(item.get("resolution"), f"review check {check_id}.resolution", 12),
            "residual_risk": _text(
                item.get("residual_risk"), f"review check {check_id}.residual_risk", 8
            ),
        }
        normalized_checks.append(record)
        check_types.add(check_type)
        checked_nodes.update(clean_refs)
        if status == "reject":
            rejected.append(check_id)
    missing_checks = sorted(REQUIRED_CHECKS - check_types)
    if missing_checks:
        raise ValueError(
            "adversarial review missing checks: " + ", ".join(missing_checks)
        )
    missing_checked_claims = sorted(high_impact - checked_nodes)
    if missing_checked_claims:
        raise ValueError(
            "adversarial review high-impact claims lack concrete checks: "
            + ", ".join(missing_checked_claims)
        )
    if rejected:
        raise ValueError(
            "adversarial review rejected frozen reasoning: " + ", ".join(rejected)
        )
    normalized: dict[str, Any] = {
        "schema_version": "trading-adversarial-review-v1",
        "status": "passed",
        "trading_date": trading_date,
        "slot": slot,
        "reviewer_mode": "isolated_second_pass",
        "independence_claim": "process_isolated_not_external_independent_oracle",
        "reasoning_contract": {
            "path": reasoning_contract_path.resolve().relative_to(root.resolve()).as_posix(),
            "sha256": reasoning["contract_sha256"],
        },
        "reviewed_claim_ids": sorted(reviewed_ids),
        "claim_verdicts": sorted(normalized_verdicts, key=lambda item: item["claim_id"]),
        "checks": normalized_checks,
        "conclusion": _text(payload.get("conclusion"), "review conclusion", 16),
    }
    normalized["review_sha256"] = _hash(normalized)
    return normalized


def validate_adversarial_review_file(
    path: Path,
    trading_date: str,
    slot: str,
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    resolved = path.resolve()
    resolved.relative_to(root.resolve())
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "trading-adversarial-review-v1":
        raise ValueError("unsupported adversarial review version")
    if payload.get("trading_date") != trading_date or payload.get("slot") != slot:
        raise ValueError("adversarial review date/slot mismatch")
    if payload.get("status") != "passed" or payload.get("review_sha256") != _hash(payload):
        raise ValueError("adversarial review hash or status invalid")
    reasoning_path = root / str((payload.get("reasoning_contract") or {}).get("path", ""))
    rebuilt = build_adversarial_review(
        {
            "reasoning_contract_sha256": (payload.get("reasoning_contract") or {}).get("sha256"),
            "reviewer_mode": payload.get("reviewer_mode"),
            "reviewed_claim_ids": payload.get("reviewed_claim_ids"),
            "claim_verdicts": payload.get("claim_verdicts"),
            "checks": payload.get("checks"),
            "conclusion": payload.get("conclusion"),
        },
        reasoning_contract_path=reasoning_path,
        trading_date=trading_date,
        slot=slot,
        root=root,
    )
    if rebuilt != payload:
        raise ValueError("adversarial review differs from deterministic rebuild")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--reasoning-contract", required=True, type=Path)
    parser.add_argument("--date", required=True)
    parser.add_argument("--slot", required=True, choices=("morning", "midday", "evening"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    contract = build_adversarial_review(
        payload,
        reasoning_contract_path=args.reasoning_contract,
        trading_date=args.date,
        slot=args.slot,
        root=ROOT,
    )
    target = args.output or (
        ROOT / "runtime_state" / args.date / f"adversarial_review_{args.slot}.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, target)
    print(json.dumps({"status": "PASSED", "output": str(target)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
