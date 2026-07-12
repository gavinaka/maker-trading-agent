"""Hash-bind the preflight draft so recovery cannot preserve an unknown report."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from runtime.golden_reasoning import validate_golden_reasoning_manifest
from runtime.reasoning_readiness import validate_reasoning_readiness_manifest
from runtime.report_contract import (
    report_contract_required,
    validate_report_contract_manifest,
)
from runtime.state_store import atomic_json_write
from outputs.daily_payload_builder import build_daily_payload
from outputs.report_structure_gate import assert_combined_structure


ROOT = Path(__file__).resolve().parents[1]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file_record(path: Path, root: Path) -> dict[str, Any]:
    resolved = path.resolve()
    resolved.relative_to(root.resolve())
    return {
        "path": resolved.relative_to(root.resolve()).as_posix(),
        "sha256": _sha256_file(resolved),
        "bytes": resolved.stat().st_size,
    }


def manifest_path(trading_date: str, slot: str, *, root: Path = ROOT) -> Path:
    return root / "runtime_state" / trading_date / f"draft_recovery_{slot}.json"


def _expected_output_paths(
    trading_date: str,
    slot: str,
    report: Path,
    cards: Path,
    root: Path,
) -> tuple[Path, Path]:
    expected_report = (root / "outputs" / f"{trading_date}_{slot}_combined.md").resolve()
    expected_cards = (root / "outputs" / f"{trading_date}_{slot}_cards.json").resolve()
    if report.resolve() != expected_report or cards.resolve() != expected_cards:
        raise ValueError("draft report/cards path does not match current date and slot")
    return expected_report, expected_cards


def _card_images(cards: Path, trading_date: str, slot: str, root: Path) -> list[Path]:
    payload = json.loads(cards.read_text(encoding="utf-8"))
    items = payload.get("cards") if isinstance(payload, dict) else None
    if not isinstance(items, list) or len(items) != 3:
        raise ValueError("draft recovery requires exactly three cards")
    images = []
    output_root = (root / "outputs" / "blockbeats").resolve()
    for item in items:
        path = Path(str((item or {}).get("filename", "")))
        if not path.is_absolute():
            path = root / path
        path = path.resolve()
        path.relative_to(output_root)
        if not path.is_file() or not path.name.startswith(f"{trading_date}_{slot}_"):
            raise ValueError("draft recovery card image does not match current slot")
        images.append(path)
    if len({str(path) for path in images}) != 3:
        raise ValueError("draft recovery card images must be unique")
    return images


def validate_draft_eligibility(
    report: Path,
    trading_date: str,
    slot: str,
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Run every deterministic text consumer before certifying recoverable bytes."""
    lines = report.read_text(encoding="utf-8").splitlines()
    assert_combined_structure(lines, trading_date, slot)
    completed = subprocess.run(
        [sys.executable, str(root / "outputs" / "report_lint.py"), str(report)],
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stdout + "\n" + completed.stderr).strip()
        raise ValueError("draft is not eligible for certification: report lint failed:\n" + detail)
    payload = build_daily_payload(report, root=root)
    if len(payload.get("image_paths") or []) != 3:
        raise ValueError("draft is not eligible for certification: payload requires 3 cards")
    return {
        "report_structure": True,
        "report_lint": True,
        "daily_payload_derivation": True,
        "blockbeats_cards": True,
    }


def certify_draft_recovery(
    trading_date: str,
    slot: str,
    *,
    report: Path,
    cards: Path,
    root: Path = ROOT,
) -> tuple[dict[str, Any], Path]:
    report, cards = _expected_output_paths(trading_date, slot, report, cards, root)
    images = _card_images(cards, trading_date, slot, root)
    eligibility = validate_draft_eligibility(
        report, trading_date, slot, root=root
    )
    _, contract_path = validate_report_contract_manifest(
        trading_date, slot, report, root=root
    )
    readiness, readiness_path = validate_reasoning_readiness_manifest(
        trading_date, slot, report, root=root
    )
    _, golden_path = validate_golden_reasoning_manifest(
        trading_date, slot, report, root=root
    )
    if not readiness or readiness_path is None or golden_path is None:
        raise ValueError("draft recovery requires certified reasoning and golden manifests")
    capture_record = readiness.get("capture_manifest") or {}
    capture_path = Path(str(capture_record.get("path", "")))
    if not capture_path.is_absolute():
        capture_path = root / capture_path
    payload: dict[str, Any] = {
        "schema_version": "draft-recovery-manifest-v1",
        "status": "certified",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "trading_date": trading_date,
        "slot": slot,
        "report": _file_record(report, root),
        "cards": _file_record(cards, root),
        "images": [_file_record(path, root) for path in images],
        "capture_manifest": _file_record(capture_path, root),
        "reasoning_readiness": _file_record(readiness_path, root),
        "golden_reasoning_manifest": _file_record(golden_path, root),
        "report_contract": _file_record(contract_path, root) if contract_path else None,
        "draft_eligibility": eligibility,
    }
    target = manifest_path(trading_date, slot, root=root)
    atomic_json_write(target, payload)
    return payload, target


def _verified_record(record: object, root: Path, label: str) -> Path:
    if not isinstance(record, dict) or not record.get("path"):
        raise ValueError(f"draft recovery missing {label}")
    path = (root / str(record["path"])).resolve()
    path.relative_to(root.resolve())
    if not path.is_file() or record.get("sha256") != _sha256_file(path):
        raise ValueError(f"draft recovery {label} changed after certification")
    return path


def validate_recovery_draft_artifacts(
    trading_date: str,
    slot: str,
    capture_manifest_path: Path,
    *,
    root: Path = ROOT,
) -> tuple[dict[str, Any] | None, Path | None]:
    if not report_contract_required(trading_date, slot):
        return None, None
    target = manifest_path(trading_date, slot, root=root)
    payload = json.loads(target.read_text(encoding="utf-8"))
    if (
        payload.get("status") != "certified"
        or payload.get("trading_date") != trading_date
        or payload.get("slot") != slot
    ):
        raise ValueError("draft recovery manifest is invalid")
    report = _verified_record(payload.get("report"), root, "report")
    cards = _verified_record(payload.get("cards"), root, "cards")
    images = [
        _verified_record(record, root, f"image[{index}]")
        for index, record in enumerate(payload.get("images") or [])
    ]
    capture = _verified_record(payload.get("capture_manifest"), root, "capture")
    readiness = _verified_record(
        payload.get("reasoning_readiness"), root, "reasoning readiness"
    )
    golden = _verified_record(
        payload.get("golden_reasoning_manifest"), root, "golden reasoning"
    )
    report_contract = _verified_record(
        payload.get("report_contract"), root, "report contract"
    )
    expected_report, expected_cards = _expected_output_paths(
        trading_date, slot, report, cards, root
    )
    if report != expected_report or cards != expected_cards or len(images) != 3:
        raise ValueError("draft recovery output set is incomplete")
    if capture != capture_manifest_path.resolve():
        raise ValueError("draft recovery capture does not match requested recovery")
    expected_state = (root / "runtime_state" / trading_date).resolve()
    expected_records = {
        readiness: expected_state / f"reasoning_readiness_{slot}.json",
        golden: expected_state / f"golden_reasoning_{slot}.json",
        report_contract: expected_state / f"report_contract_{slot}.json",
    }
    if any(actual != expected.resolve() for actual, expected in expected_records.items()):
        raise ValueError("draft recovery certification path does not match current slot")
    return payload, target


def validate_draft_recovery_manifest(
    trading_date: str,
    slot: str,
    report: Path,
    *,
    root: Path = ROOT,
) -> tuple[dict[str, Any] | None, Path | None]:
    if not report_contract_required(trading_date, slot):
        return None, None
    target = manifest_path(trading_date, slot, root=root)
    payload = json.loads(target.read_text(encoding="utf-8"))
    readiness, readiness_path = validate_reasoning_readiness_manifest(
        trading_date, slot, report, root=root
    )
    _, golden_path = validate_golden_reasoning_manifest(
        trading_date, slot, report, root=root
    )
    _, report_contract_path = validate_report_contract_manifest(
        trading_date, slot, report, root=root
    )
    capture_record = (readiness or {}).get("capture_manifest") or {}
    capture = Path(str(capture_record.get("path", "")))
    if not capture.is_absolute():
        capture = root / capture
    capture = capture.resolve()
    validated, _ = validate_recovery_draft_artifacts(
        trading_date, slot, capture, root=root
    )
    expected_report = (root / str((validated or {}).get("report", {}).get("path", ""))).resolve()
    if report.resolve() != expected_report:
        raise ValueError("preflight report does not match certified recovery draft")
    manifest_records = {
        "reasoning_readiness": readiness_path,
        "golden_reasoning_manifest": golden_path,
        "report_contract": report_contract_path,
    }
    for label, expected in manifest_records.items():
        recorded = _verified_record((validated or {}).get(label), root, label)
        if expected is None or recorded != expected.resolve():
            raise ValueError(f"draft recovery {label} binding changed")
    return validated, target
