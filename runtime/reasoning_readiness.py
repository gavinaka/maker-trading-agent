"""Pre-MD reasoning readiness gate for daily reports.

The formal combined report must not be the first place where conclusions
appear. This module records and validates an internal pre-output reasoning work
file before ``combined.md`` can be locked, rendered to Word, or pushed to
Notion.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from runtime.adversarial_review import validate_adversarial_review_file
from runtime.host_capability import required as host_capability_required
from runtime.host_capability import validate_manifest as validate_host_capability_manifest
from runtime.decision_contract import (
    reasoning_bound_contract_required,
    validate_contract_file,
)
from runtime.reasoning_contract import validate_reasoning_contract_file
from runtime.state_store import atomic_json_write


ROOT = Path(__file__).resolve().parents[1]
POLICY = "pre_md_reasoning_depth_certified_no_posthoc_rationale"
STRICT_FROM = date(2026, 7, 6)
REPORT_PREFLIGHT_STRICT_FROM = date(2026, 7, 11)
EXEMPT_SLOT = ("2026-07-06", "morning")
DECISION_CONTRACT_FIRST_SLOT = ("2026-07-10", "evening")
CONTRACT_RELATIVE = "scoring/reasoning_depth_checklist.md"

REQUIRED_SECTIONS = {
    "six_source_accuracy": [
        r"BlockBeats",
        r"Coinglass",
        r"Exocharts",
        r"FedWatch",
        r"Farside",
        r"TradingView",
        r"准确|有效|校验|验真|截图|JSON",
    ],
    "critical_data_calibration": [
        r"pivot|枢轴|摆动|趋势线|突破|未破",
        r"CVD",
        r"SMA20",
        r"VRVP|VAH|VAL|POC",
    ],
    "score_synthesis_chain": [
        r"盘口",
        r"盘面",
        r"总分|总评",
        r"合成|推导|落值|证据|分项",
    ],
    "winrate_rubric_chain": [
        r"胜率",
        r"rubric|winrate_methodology|胜率方法论",
        r"锚|anchor",
        r"次因|微调|上调|下调|[+\-]\s*\d|±",
        r"落值|落点|落到|真实值|估值",
        r"60|门槛|阈值",
    ],
    "refutation_invalidation": [
        r"方向|主判|多空|倾向|路径",
        r"反证",
        r"失效|情景|情形",
    ],
    "risk_math": [
        r"风险|止损",
        r"TP1|止盈",
        r"TP2|清剩余|清仓",
        r"盈亏比|R\b|杠杆|持仓",
    ],
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")


def _file_record(path: Path, root: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"required file is missing: {path}")
    return {
        "path": _relative(path, root),
        "sha256": _sha256_file(path),
        "bytes": path.stat().st_size,
        "mtime": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(
            timespec="seconds"
        ),
    }


def _manifest_path(trading_date: str, slot: str, root: Path) -> Path:
    return root / "runtime_state" / trading_date / f"reasoning_readiness_{slot}.json"


def _golden_manifest_path(trading_date: str, slot: str, root: Path) -> Path:
    return root / "runtime_state" / trading_date / f"golden_reasoning_{slot}.json"


def reasoning_readiness_required(trading_date: str, slot: str) -> bool:
    if (trading_date, slot) == EXEMPT_SLOT:
        return False
    return date.fromisoformat(trading_date) >= STRICT_FROM


def report_preflight_required(trading_date: str) -> bool:
    return date.fromisoformat(trading_date) >= REPORT_PREFLIGHT_STRICT_FROM


def decision_contract_required(trading_date: str, slot: str) -> bool:
    return (trading_date, {"morning": 0, "midday": 1, "evening": 2}[slot]) >= (
        DECISION_CONTRACT_FIRST_SLOT[0],
        {"morning": 0, "midday": 1, "evening": 2}[DECISION_CONTRACT_FIRST_SLOT[1]],
    )


def _assert_inside_runtime_state(path: Path, trading_date: str, root: Path) -> None:
    allowed_root = (root / "runtime_state" / trading_date).resolve()
    try:
        path.resolve().relative_to(allowed_root)
    except ValueError as exc:
        raise ValueError(
            f"reasoning work file must be inside {allowed_root}"
        ) from exc


def validate_reasoning_work_file(work_file: Path) -> dict[str, Any]:
    if not work_file.is_file():
        raise ValueError(f"reasoning work file is missing: {work_file}")
    text = work_file.read_text(encoding="utf-8")
    issues: list[str] = []
    for section, patterns in REQUIRED_SECTIONS.items():
        missing = [pattern for pattern in patterns if not re.search(pattern, text, re.I)]
        if missing:
            issues.append(f"{section} missing {', '.join(missing)}")
    forbidden = [
        (
            r"已(?:经)?(?:后补|补写|补理由|补推理)|"
            r"(?:后补|补写|补理由|补推理)(?:了|完成|完毕)|"
            r"(?:事后|输出后|成稿后)(?:补写|补理由|补推理)",
            "posthoc rationale admission is forbidden",
        ),
        (
            r"(?:先写结论|先出结论|先生成MD|先生成 md).{0,16}(?:再|后).{0,8}(?:推理|补)",
            "conclusion-before-reasoning admission is forbidden",
        ),
    ]
    for pattern, reason in forbidden:
        if re.search(pattern, text, re.I):
            issues.append(f"forbidden_posthoc_mode {reason}")
    if issues:
        raise ValueError("reasoning work file is not ready: " + "; ".join(issues))
    return {
        "sections_checked": sorted(REQUIRED_SECTIONS),
        "bytes": work_file.stat().st_size,
        "sha256": _sha256_file(work_file),
    }


def _validate_capture_matches_transition(
    trading_date: str,
    slot: str,
    capture: Path,
    transition: Path,
    root: Path,
) -> None:
    if not transition.is_file():
        raise ValueError(f"required file is missing: {transition}")
    payload = json.loads(transition.read_text(encoding="utf-8"))
    if payload.get("trading_date") != trading_date:
        raise ValueError("reasoning readiness transition date mismatch")
    if payload.get("slot") != slot:
        raise ValueError("reasoning readiness transition slot mismatch")
    record = payload.get("capture_manifest")
    if not isinstance(record, dict):
        raise ValueError(
            "reasoning readiness transition is missing capture_manifest binding"
        )
    path_text = record.get("path")
    if not isinstance(path_text, str) or not path_text.strip():
        raise ValueError("reasoning readiness transition capture path is missing")
    expected_path = Path(path_text)
    if not expected_path.is_absolute():
        expected_path = transition.parent / expected_path
    expected_path = expected_path.resolve()
    runtime_root = (root / "runtime_state" / trading_date).resolve()
    try:
        expected_path.relative_to(runtime_root)
    except ValueError as exc:
        raise ValueError(
            "reasoning readiness transition capture escapes runtime_state date"
        ) from exc
    if capture.resolve() != expected_path:
        raise ValueError(
            "reasoning readiness capture manifest does not match prepared transition"
        )
    expected_hash = record.get("sha256")
    if expected_hash != _sha256_file(capture):
        raise ValueError(
            "reasoning readiness capture manifest does not match prepared transition"
        )


def build_reasoning_readiness_manifest(
    trading_date: str,
    slot: str,
    *,
    work_file: Path,
    capture_manifest_path: Path,
    transition_path: Path,
    decision_contract_path: Path | None = None,
    reasoning_contract_path: Path | None = None,
    adversarial_review_path: Path | None = None,
    root: Path = ROOT,
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    work = work_file.resolve()
    capture = capture_manifest_path.resolve()
    transition = transition_path.resolve()
    golden = _golden_manifest_path(trading_date, slot, root)
    contract = root / CONTRACT_RELATIVE
    _assert_inside_runtime_state(work, trading_date, root)
    work_validation = validate_reasoning_work_file(work)
    _validate_capture_matches_transition(trading_date, slot, capture, transition, root)
    host_path = None
    if host_capability_required(trading_date, slot):
        transition_payload = json.loads(transition.read_text(encoding="utf-8"))
        host_record = transition_payload.get("host_capability") or {}
        host_path = root / str(host_record.get("path", ""))
        validate_host_capability_manifest(
            host_path, trading_date, slot, root=root
        )
        expected_host_record = _file_record(host_path, root)
        if any(
            host_record.get(key) != expected_host_record.get(key)
            for key in ("path", "sha256", "bytes")
        ):
            raise ValueError("transition host capability binding changed")
    decision_record = None
    reasoning_record = None
    adversarial_record = None
    reasoning_payload = None
    if reasoning_contract_path is not None:
        reasoning = reasoning_contract_path.resolve()
        _assert_inside_runtime_state(reasoning, trading_date, root)
        reasoning_payload = validate_reasoning_contract_file(
            reasoning, trading_date, slot, root=root
        )
        reasoning_record = _file_record(reasoning, root)
    elif reasoning_bound_contract_required(trading_date, slot):
        raise ValueError(
            "structured reasoning contract is required before reasoning certification"
        )
    if adversarial_review_path is not None:
        adversarial = adversarial_review_path.resolve()
        _assert_inside_runtime_state(adversarial, trading_date, root)
        review = validate_adversarial_review_file(
            adversarial, trading_date, slot, root=root
        )
        if reasoning_payload is None or (
            review.get("reasoning_contract") or {}
        ).get("sha256") != reasoning_payload.get("contract_sha256"):
            raise ValueError("adversarial review reasoning binding mismatch")
        adversarial_record = _file_record(adversarial, root)
    elif reasoning_bound_contract_required(trading_date, slot):
        raise ValueError(
            "adversarial review is required before reasoning certification"
        )
    if decision_contract_path is not None:
        decision = decision_contract_path.resolve()
        _assert_inside_runtime_state(decision, trading_date, root)
        validate_contract_file(decision, trading_date, slot, root=root)
        decision_record = _file_record(decision, root)
    elif decision_contract_required(trading_date, slot):
        raise ValueError("decision contract is required before reasoning certification")
    target = _manifest_path(trading_date, slot, root)
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "ready",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "trading_date": trading_date,
        "slot": slot,
        "policy": POLICY,
        "purpose": (
            "block formal combined.md/Word/Notion output until source-accurate "
            "full reasoning depth is completed at verified high-or-above host effort"
        ),
        "phase_order": [
            "six_source_capture_complete",
            "minimum_high_host_capability_verified",
            "source_accuracy_verified",
            "source_specific_judgment_methods_validated",
            "full_reasoning_depth_calibrated",
            "structured_reasoning_contract_validated",
            "isolated_adversarial_review_passed",
            "decision_math_contract_validated",
            "reasoning_readiness_manifest_ready",
            "independent_reasoning_lock_before_prior_plan_read",
            "post_lock_continuity_contract_only",
            "formal_combined_md_drafting",
            "final_analysis_lock",
            "word_render_and_notion_publish",
        ],
        "forbidden_modes": [
            "writing_formal_md_before_reasoning_depth",
            "posthoc_reasoning_backfill",
            "posthoc_rubric_backfill",
            "word_or_notion_from_unlocked_md",
        ],
        "required_sections": sorted(REQUIRED_SECTIONS),
        "work_file": _file_record(work, root),
        "work_file_validation": work_validation,
        "capture_manifest": _file_record(capture, root),
        "transition": _file_record(transition, root),
        "golden_reasoning_manifest": _file_record(golden, root),
        "contract": _file_record(contract, root),
    }
    if host_path is not None:
        payload["host_capability"] = _file_record(host_path, root)
    if decision_record is not None:
        payload["decision_contract"] = decision_record
    if reasoning_record is not None:
        payload["reasoning_contract"] = reasoning_record
    if adversarial_record is not None:
        payload["adversarial_review"] = adversarial_record
    atomic_json_write(target, payload)
    return payload, target


def validate_reasoning_readiness_manifest(
    trading_date: str,
    slot: str,
    report_path: Path | None = None,
    *,
    root: Path = ROOT,
) -> tuple[dict[str, Any] | None, Path | None]:
    if not reasoning_readiness_required(trading_date, slot):
        return None, None
    root = root.resolve()
    target = _manifest_path(trading_date, slot, root)
    if not target.is_file():
        raise ValueError(
            "missing pre-MD reasoning readiness manifest; complete full reasoning "
            "depth before writing combined.md"
        )
    payload = json.loads(target.read_text(encoding="utf-8"))
    if payload.get("status") != "ready":
        raise ValueError("reasoning readiness manifest is not ready")
    if payload.get("trading_date") != trading_date:
        raise ValueError("reasoning readiness manifest date mismatch")
    if payload.get("slot") != slot:
        raise ValueError("reasoning readiness manifest slot mismatch")
    if payload.get("policy") != POLICY:
        raise ValueError("reasoning readiness policy mismatch")
    records: dict[str, Path] = {}
    record_keys = [
        "work_file",
        "capture_manifest",
        "transition",
        "golden_reasoning_manifest",
        "contract",
    ]
    if host_capability_required(trading_date, slot):
        record_keys.append("host_capability")
    if "decision_contract" in payload:
        record_keys.append("decision_contract")
    elif decision_contract_required(trading_date, slot):
        raise ValueError("reasoning readiness missing decision contract")
    if reasoning_bound_contract_required(trading_date, slot):
        for key in ("reasoning_contract", "adversarial_review"):
            if key not in payload:
                raise ValueError(f"reasoning readiness missing {key}")
            record_keys.append(key)
    for key in record_keys:
        record = payload.get(key) or {}
        path_text = record.get("path")
        if not path_text:
            raise ValueError(f"reasoning readiness missing {key} path")
        path = Path(str(path_text))
        if not path.is_absolute():
            path = root / path
        path = path.resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"reasoning readiness {key} escapes repository root") from exc
        if not path.is_file():
            raise ValueError(f"reasoning readiness {key} file missing: {path}")
        if record.get("sha256") != _sha256_file(path):
            raise ValueError(f"reasoning readiness {key} changed after certification")
        records[key] = path
    _validate_capture_matches_transition(
        trading_date,
        slot,
        records["capture_manifest"],
        records["transition"],
        root,
    )
    if "host_capability" in records:
        validate_host_capability_manifest(
            records["host_capability"], trading_date, slot, root=root
        )
    work = records["work_file"]
    validate_reasoning_work_file(work)
    if "decision_contract" in records:
        validate_contract_file(
            records["decision_contract"], trading_date, slot, root=root
        )
    if "reasoning_contract" in records:
        validate_reasoning_contract_file(
            records["reasoning_contract"], trading_date, slot, root=root
        )
    if "adversarial_review" in records:
        validate_adversarial_review_file(
            records["adversarial_review"], trading_date, slot, root=root
        )
    if report_path is not None:
        report = report_path.resolve()
        if not report.is_file():
            raise ValueError(f"report not found for reasoning readiness validation: {report}")
        created_at = datetime.fromisoformat(str(payload["created_at"]))
        report_mtime = datetime.fromtimestamp(
            report.stat().st_mtime,
            tz=created_at.tzinfo,
        )
        work_mtime = datetime.fromtimestamp(work.stat().st_mtime, tz=created_at.tzinfo)
        if created_at.timestamp() > report_mtime.timestamp() + 1:
            raise ValueError(
                "reasoning readiness was certified after the formal report; "
                "posthoc reasoning is forbidden"
            )
        if work_mtime.timestamp() > report_mtime.timestamp() + 1:
            raise ValueError(
                "reasoning work file was modified after the formal report; "
                "posthoc reasoning is forbidden"
            )
    return payload, target


def validate_locked_report_for_output(
    trading_date: str,
    slot: str,
    report_path: Path,
    *,
    root: Path = ROOT,
) -> dict[str, Any] | None:
    if not reasoning_readiness_required(trading_date, slot):
        return None
    root = root.resolve()
    report = report_path.resolve()
    lock_path = root / "runtime_state" / trading_date / f"analysis_lock_{slot}.json"
    if not lock_path.is_file():
        raise ValueError(
            "formal report output blocked: missing analysis lock bound to "
            "pre-MD reasoning readiness"
        )
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if lock.get("trading_date") != trading_date:
        raise ValueError("formal report output blocked: analysis lock date mismatch")
    if lock.get("slot") != slot:
        raise ValueError("formal report output blocked: analysis lock slot mismatch")
    locked_report = lock.get("report_path")
    if locked_report and Path(str(locked_report)).resolve() != report:
        raise ValueError("formal report output blocked: report path mismatch")
    if lock.get("max_through_analysis_confirmed") is not True:
        raise ValueError(
            "formal report output blocked: analysis lock lacks full-depth confirmation"
        )
    if lock.get("report_sha256") != _sha256_file(report):
        raise ValueError("formal report output blocked: report changed after analysis lock")
    validation = lock.get("analysis_validation") or {}
    if validation.get("reasoning_readiness_pre_md") is not True:
        raise ValueError(
            "formal report output blocked: analysis lock lacks pre-MD reasoning readiness"
        )
    if validation.get("reasoning_readiness_policy") != POLICY:
        raise ValueError("formal report output blocked: reasoning readiness policy mismatch")
    validate_reasoning_readiness_manifest(trading_date, slot, report, root=root)
    if report_preflight_required(trading_date):
        if validation.get("report_preflight_required") is not True:
            raise ValueError(
                "formal report output blocked: analysis lock lacks report preflight requirement"
            )
        if validation.get("payload_derivation_pre_lock") is not True:
            raise ValueError(
                "formal report output blocked: payload derivation was not proven pre-lock"
            )
        preflight_path = (
            root / "runtime_state" / trading_date / f"report_preflight_{slot}.json"
        ).resolve()
        recorded_path = validation.get("report_preflight_manifest")
        if not recorded_path or Path(str(recorded_path)).resolve() != preflight_path:
            raise ValueError(
                "formal report output blocked: report preflight path mismatch"
            )
        if not preflight_path.is_file():
            raise ValueError(
                "formal report output blocked: report preflight manifest is missing"
            )
        if validation.get("report_preflight_manifest_sha256") != _sha256_file(
            preflight_path
        ):
            raise ValueError(
                "formal report output blocked: report preflight manifest changed after lock"
            )
        preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
        preflight_checks = preflight.get("checks")
        checks = {
            "schema": preflight.get("schema_version") == "daily-report-preflight-v1",
            "date": preflight.get("trading_date") == trading_date,
            "slot": preflight.get("slot") == slot,
            "report_path": Path(str(preflight.get("report_path", ""))).resolve()
            == report,
            "report_hash": preflight.get("report_sha256") == lock.get("report_sha256"),
            "payload_hash": preflight.get("payload_preview_sha256")
            == validation.get("payload_preview_sha256"),
            "all_preflight_checks": isinstance(preflight_checks, dict)
            and bool(preflight_checks)
            and all(preflight_checks.values()),
        }
        failed = sorted(name for name, passed in checks.items() if not passed)
        if failed:
            raise ValueError(
                "formal report output blocked: invalid report preflight binding: "
                + ", ".join(failed)
            )
    return lock
