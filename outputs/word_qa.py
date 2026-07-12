"""Deterministic Word export and hash-bound visual-QA evidence.

The mechanical export is always Windows Word COM on this host.  Visual review
remains a separate MAX-reasoning action: ``approve`` records the decision only
after every rendered page has actually been inspected.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.state_store import atomic_json_write
from runtime.usage_logger import append_usage


SLOTS = ("morning", "midday", "evening")
BROKER_REQUEST = "broker_request.json"
BROKER_RESPONSE = "broker_response.json"
BROKER_HEARTBEAT = "word_export_broker_heartbeat.json"
INTERACTIVE_SESSION_ERROR_MARKERS = (
    "80070520",
    "a specified logon session does not exist",
    "指定的登录会话不存在",
)


class WordExportError(RuntimeError):
    def __init__(self, message: str, *, backend: str):
        super().__init__(message)
        self.backend = backend


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_object(path: Path) -> dict | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def canonical_docx(root: Path, trading_date: str, slot: str) -> Path:
    return root / "outputs" / f"{trading_date}_{slot}_render.docx"


def manifest_path(root: Path, trading_date: str, slot: str) -> Path:
    return root / "runtime_state" / trading_date / f"word_qa_{slot}.json"


def _find_pdftoppm(explicit: str | None = None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    env_value = os.environ.get("PDFTOPPM_EXE")
    if env_value:
        candidates.append(Path(env_value))
    cache = Path.home() / ".cache" / "codex-runtimes"
    if cache.is_dir():
        candidates.extend(cache.glob("**/pdftoppm.exe"))
    discovered = shutil.which("pdftoppm")
    if discovered and Path(discovered).suffix.lower() == ".exe":
        candidates.append(Path(discovered))
    for candidate in candidates:
        if candidate.is_file() and candidate.suffix.lower() == ".exe":
            return candidate.resolve()
    raise RuntimeError("pdftoppm.exe not found; set PDFTOPPM_EXE to the real binary")


def _word_com_export_script(docx: Path, pdf: Path) -> str:
    escaped_docx = str(docx).replace("'", "''")
    escaped_pdf = str(pdf).replace("'", "''")
    return (
        "$ErrorActionPreference='Stop';"
        "$word=$null;$candidate=$null;$doc=$null;"
        "$ownsWord=$false;$previousDisplayAlerts=$null;"
        "try{"
        "try{$candidate=[Runtime.InteropServices.Marshal]::GetActiveObject('Word.Application')}"
        "catch [Runtime.InteropServices.COMException]{$candidate=$null};"
        "if($candidate){"
        "$isHiddenIdle=((-not [bool]$candidate.Visible) -and ($candidate.Documents.Count -eq 0));"
        "if($isHiddenIdle){$word=$candidate;$candidate=$null}"
        "else{[void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($candidate);$candidate=$null};"
        "};"
        "if(-not $word){"
        "$word=New-Object -ComObject Word.Application;$ownsWord=$true;$word.Visible=$false;"
        "};"
        "$previousDisplayAlerts=$word.DisplayAlerts;$word.DisplayAlerts=0;"
        f"$doc=$word.Documents.Open('{escaped_docx}',$false,$true);"
        f"$doc.ExportAsFixedFormat('{escaped_pdf}',17);"
        "}finally{"
        "if($doc){try{$doc.Close($false)}finally{[void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($doc);$doc=$null}};"
        "if($word){"
        "if($ownsWord){$word.Quit()}"
        "elseif($null -ne $previousDisplayAlerts){$word.DisplayAlerts=$previousDisplayAlerts};"
        "[void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($word);$word=$null;"
        "};"
        "[GC]::Collect();[GC]::WaitForPendingFinalizers();"
        "}"
    )


def _export_word_com(docx: Path, pdf: Path, *, timeout: int = 600) -> None:
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / (
        "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    if not powershell.is_file():
        raise RuntimeError(f"Windows PowerShell not found: {powershell}")
    script = _word_com_export_script(docx, pdf)
    completed = subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-NonInteractive",
            "-STA",
            "-Command",
            script,
        ],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        detail = (completed.stdout + "\n" + completed.stderr).strip()
        raise RuntimeError("Word COM export failed: " + detail)
    if not pdf.is_file() or pdf.stat().st_size == 0:
        raise RuntimeError("Word COM returned success without a PDF")


def _assert_interactive_broker_ready(root: Path, *, max_age_seconds: int = 5) -> dict:
    heartbeat_path = Path(root).resolve() / "runtime_state" / BROKER_HEARTBEAT
    heartbeat = load_object(heartbeat_path)
    if not heartbeat or heartbeat.get("schema_version") != "1.0":
        raise WordExportError(
            "interactive Word export broker heartbeat is missing",
            backend="word_com_interactive_task",
        )
    try:
        updated_at = datetime.fromisoformat(str(heartbeat["updated_at"]))
        if updated_at.tzinfo is None:
            raise ValueError("timezone missing")
        age = (datetime.now().astimezone() - updated_at.astimezone()).total_seconds()
    except (KeyError, TypeError, ValueError) as exc:
        raise WordExportError(
            "interactive Word export broker heartbeat is invalid",
            backend="word_com_interactive_task",
        ) from exc
    if heartbeat.get("status") != "ready" or age < -5 or age > max_age_seconds:
        raise WordExportError(
            "interactive Word export broker heartbeat is stale",
            backend="word_com_interactive_task",
        )
    return heartbeat


def _export_word_via_interactive_task(
    docx: Path,
    pdf: Path,
    *,
    trading_date: str,
    slot: str,
    docx_sha256: str,
    root: Path,
    timeout: int = 600,
) -> None:
    _assert_interactive_broker_ready(root)
    request_path = pdf.parent / BROKER_REQUEST
    response_path = pdf.parent / BROKER_RESPONSE
    if request_path.exists() or response_path.exists():
        raise WordExportError(
            "interactive Word export request/response already exists",
            backend="word_com_interactive_task",
        )
    request_id = uuid.uuid4().hex
    atomic_json_write(
        request_path,
        {
            "schema_version": "1.0",
            "request_id": request_id,
            "requested_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "trading_date": trading_date,
            "slot": slot,
            "docx_path": str(docx.resolve()),
            "docx_sha256": docx_sha256,
            "pdf_path": str(pdf.resolve()),
        },
    )
    started = time.monotonic()
    last_heartbeat_check = started
    while time.monotonic() - started < timeout:
        if response_path.is_file():
            response = load_object(response_path) or {}
            if response.get("request_id") != request_id:
                raise WordExportError(
                    "interactive Word export response nonce does not match",
                    backend="word_com_interactive_task",
                )
            if response.get("status") != "success":
                raise WordExportError(
                    "interactive Word export failed: "
                    + str(response.get("failure_reason", "unknown broker failure")),
                    backend="word_com_interactive_task",
                )
            if (
                Path(str(response.get("docx_path", ""))).resolve() != docx.resolve()
                or response.get("docx_sha256") != docx_sha256
                or Path(str(response.get("pdf_path", ""))).resolve() != pdf.resolve()
            ):
                raise WordExportError(
                    "interactive Word export response binding does not match",
                    backend="word_com_interactive_task",
                )
            if not pdf.is_file() or pdf.stat().st_size == 0:
                raise WordExportError(
                    "interactive Word export returned success without a PDF",
                    backend="word_com_interactive_task",
                )
            if response.get("pdf_sha256") != sha256_file(pdf):
                raise WordExportError(
                    "interactive Word export PDF hash does not match",
                    backend="word_com_interactive_task",
                )
            return
        if time.monotonic() - last_heartbeat_check >= 5:
            _assert_interactive_broker_ready(root)
            last_heartbeat_check = time.monotonic()
        time.sleep(0.5)
    raise WordExportError(
        "interactive Word export timed out waiting for a response",
        backend="word_com_interactive_task",
    )


def _export_word(
    docx: Path,
    pdf: Path,
    *,
    trading_date: str,
    slot: str,
    docx_sha256: str,
    root: Path,
    timeout: int = 600,
) -> str:
    try:
        _export_word_com(docx, pdf, timeout=timeout)
        return "word_com"
    except RuntimeError as exc:
        normalized = str(exc).lower()
        if not any(marker in normalized for marker in INTERACTIVE_SESSION_ERROR_MARKERS):
            raise
        _export_word_via_interactive_task(
            docx,
            pdf,
            trading_date=trading_date,
            slot=slot,
            docx_sha256=docx_sha256,
            root=root,
            timeout=timeout,
        )
        return "word_com_interactive_task"


def _infrastructure_recovery_eligible(existing: dict, *, root: Path) -> bool:
    if (
        existing.get("status") != "failed"
        or int(existing.get("attempts", 0)) < 2
        or existing.get("reviewed_at")
        or existing.get("infrastructure_recovery_used")
    ):
        return False
    failure = str(existing.get("failure_reason", "")).lower()
    if not any(marker in failure for marker in INTERACTIVE_SESSION_ERROR_MARKERS):
        return False
    try:
        _assert_interactive_broker_ready(root)
    except WordExportError:
        return False
    return True


def _render_pdf(pdf: Path, output_prefix: Path, pdftoppm: Path) -> list[Path]:
    completed = subprocess.run(
        [
            str(pdftoppm),
            "-png",
            "-r",
            "150",
            str(pdf),
            str(output_prefix),
        ],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=180,
    )
    if completed.returncode != 0:
        detail = (completed.stdout + "\n" + completed.stderr).strip()
        raise RuntimeError("Poppler page rendering failed: " + detail)
    pages = sorted(
        output_prefix.parent.glob(output_prefix.name + "-*.png"),
        key=lambda path: int(path.stem.rsplit("-", 1)[-1]),
    )
    if not pages:
        raise RuntimeError("Poppler returned success without page images")
    return pages


def _evidence_files_valid(payload: dict) -> bool:
    try:
        docx = Path(payload["docx_path"])
        pdf = Path(payload["pdf_path"])
        if sha256_file(docx) != payload["docx_sha256"]:
            return False
        if sha256_file(pdf) != payload["pdf_sha256"]:
            return False
        return all(
            sha256_file(Path(page["path"])) == page["sha256"]
            for page in payload["pages"]
        )
    except (KeyError, FileNotFoundError, OSError):
        return False


def prepare_qa(
    trading_date: str,
    slot: str,
    *,
    root: Path = ROOT,
    pdftoppm: str | None = None,
    export_timeout: int = 600,
) -> dict:
    root = Path(root).resolve()
    target = manifest_path(root, trading_date, slot)
    docx = canonical_docx(root, trading_date, slot).resolve()
    render_manifest = load_object(
        root / "runtime_state" / trading_date / f"render_{slot}.json"
    )
    if not render_manifest or render_manifest.get("status") != "success":
        raise ValueError("Word QA requires a successful render manifest")
    if not docx.is_file():
        raise ValueError(f"canonical DOCX is missing: {docx}")
    docx_hash = sha256_file(docx)
    if render_manifest.get("docx_sha256") != docx_hash:
        raise ValueError("canonical DOCX does not match render manifest")

    existing = load_object(target) or {}
    if (
        existing.get("status") in {"prepared", "passed"}
        and existing.get("docx_sha256") == docx_hash
        and _evidence_files_valid(existing)
    ):
        append_usage(
            trading_date=trading_date,
            slot=slot,
            phase="word_export",
            status="success",
            event_id=f"{docx_hash}:word_export:cache",
            retries=max(int(existing.get("attempts", 1)) - 1, 0),
            details={
                "cache_hit": True,
                "attempt": existing.get("attempts", 1),
                "backend": "word_com",
                "input_sha256": docx_hash,
                "output_sha256": existing["pdf_sha256"],
            },
            root=root,
        )
        result = dict(existing)
        result["cache_hit"] = True
        return result
    if (
        existing.get("status") == "failed"
        and existing.get("reviewed_at")
        and existing.get("docx_sha256") == docx_hash
    ):
        append_usage(
            trading_date=trading_date,
            slot=slot,
            phase="word_export",
            status="blocked",
            event_id=f"{docx_hash}:word_export:unchanged-after-rejection",
            retries=max(int(existing.get("attempts", 1)) - 1, 0),
            details={
                "cache_hit": False,
                "attempt": existing.get("attempts", 1),
                "backend": "word_com",
                "input_sha256": docx_hash,
                "failure_reason": "DOCX unchanged after visual QA rejection",
            },
            root=root,
        )
        raise RuntimeError(
            "DOCX is unchanged after visual QA rejection; fix the source/render "
            "before another Word export"
        )

    attempts = int(existing.get("attempts", 0))
    infrastructure_recovery = _infrastructure_recovery_eligible(existing, root=root)
    if attempts >= 2 and not infrastructure_recovery:
        append_usage(
            trading_date=trading_date,
            slot=slot,
            phase="word_export",
            status="blocked",
            event_id=f"{docx_hash}:word_export:attempt-limit",
            retries=1,
            details={
                "cache_hit": False,
                "attempt": attempts,
                "backend": "word_com",
                "input_sha256": docx_hash,
                "failure_reason": "Word export attempt limit reached; third attempt forbidden",
            },
            root=root,
        )
        raise RuntimeError(
            "Word export attempt limit reached (2); third attempt is forbidden"
        )
    attempt = attempts + 1
    started = time.perf_counter()
    attempt_dir = (
        root
        / "runtime_state"
        / trading_date
        / "word_qa"
        / slot
        / (
            f"attempt-{attempt}-infra-{uuid.uuid4().hex[:8]}"
            if infrastructure_recovery
            else f"attempt-{attempt}-{uuid.uuid4().hex[:8]}"
        )
    )
    attempt_dir.mkdir(parents=True, exist_ok=False)
    pdf = attempt_dir / f"{trading_date}_{slot}_render.pdf"
    key = f"{docx_hash}:word_export:{attempt}"
    backend = "word_com"
    try:
        backend = _export_word(
            docx,
            pdf,
            trading_date=trading_date,
            slot=slot,
            docx_sha256=docx_hash,
            root=root,
            timeout=export_timeout,
        )
        poppler = _find_pdftoppm(pdftoppm)
        pages = _render_pdf(pdf, attempt_dir / "page", poppler)
        payload = {
            "schema_version": "1.0",
            "status": "prepared",
            "visual_qa_pass": False,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "trading_date": trading_date,
            "slot": slot,
            "attempts": attempt,
            "cache_hit": False,
            "backend": backend,
            "page_renderer": str(poppler),
            "docx_path": str(docx),
            "docx_sha256": docx_hash,
            "pdf_path": str(pdf),
            "pdf_sha256": sha256_file(pdf),
            "pages": [
                {"path": str(page), "sha256": sha256_file(page)}
                for page in pages
            ],
        }
        if infrastructure_recovery:
            payload["infrastructure_recovery_used"] = True
            payload["attempt_limit_exception"] = {
                "kind": "word_com_logon_session_to_interactive_broker",
                "previous_attempts": attempts,
                "previous_failure_reason": str(existing.get("failure_reason", "")),
            }
        atomic_json_write(target, payload)
        append_usage(
            trading_date=trading_date,
            slot=slot,
            phase="word_export",
            status="success",
            event_id=key,
            duration_ms=round((time.perf_counter() - started) * 1000),
            retries=attempt - 1,
            details={
                "cache_hit": False,
                "attempt": attempt,
                "backend": backend,
                "input_sha256": docx_hash,
                "output_sha256": payload["pdf_sha256"],
                "page_count": len(pages),
            },
            root=root,
        )
        return payload
    except BaseException as exc:
        backend = getattr(exc, "backend", backend)
        failure = {
            "schema_version": "1.0",
            "status": "failed",
            "visual_qa_pass": False,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "trading_date": trading_date,
            "slot": slot,
            "attempts": attempt,
            "backend": backend,
            "docx_path": str(docx),
            "docx_sha256": docx_hash,
            "failure_reason": str(exc),
        }
        if infrastructure_recovery:
            failure["infrastructure_recovery_used"] = True
            failure["attempt_limit_exception"] = {
                "kind": "word_com_logon_session_to_interactive_broker",
                "previous_attempts": attempts,
                "previous_failure_reason": str(existing.get("failure_reason", "")),
            }
        atomic_json_write(target, failure)
        append_usage(
            trading_date=trading_date,
            slot=slot,
            phase="word_export",
            status="failed",
            event_id=key + ":failed",
            duration_ms=round((time.perf_counter() - started) * 1000),
            retries=attempt - 1,
            details={
                "cache_hit": False,
                "attempt": attempt,
                "backend": backend,
                "input_sha256": docx_hash,
                "failure_reason": str(exc),
            },
            root=root,
        )
        raise


def approve_qa(
    trading_date: str,
    slot: str,
    *,
    reviewer: str,
    root: Path = ROOT,
) -> dict:
    root = Path(root).resolve()
    target = manifest_path(root, trading_date, slot)
    payload = load_object(target)
    if not payload or payload.get("status") not in {"prepared", "passed"}:
        raise ValueError("Word QA approval requires prepared page evidence")
    if not _evidence_files_valid(payload):
        raise ValueError("Word QA files changed after export")
    if payload.get("status") == "passed":
        return payload
    payload["status"] = "passed"
    payload["visual_qa_pass"] = True
    payload["reviewer"] = reviewer
    payload["reviewed_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    atomic_json_write(target, payload)
    append_usage(
        trading_date=trading_date,
        slot=slot,
        phase="visual_qa",
        status="success",
        event_id=f"{payload['docx_sha256']}:visual_qa:pass",
        retries=max(int(payload.get("attempts", 1)) - 1, 0),
        details={
            "cache_hit": False,
            "attempt": payload.get("attempts", 1),
            "backend": payload["backend"],
            "input_sha256": payload["docx_sha256"],
            "pdf_sha256": payload["pdf_sha256"],
            "page_count": len(payload["pages"]),
            "reviewer": reviewer,
        },
        root=root,
    )
    return payload


def reject_qa(
    trading_date: str,
    slot: str,
    *,
    reason: str,
    root: Path = ROOT,
) -> dict:
    if len(reason.strip()) < 8:
        raise ValueError("visual QA rejection reason must be explicit")
    root = Path(root).resolve()
    target = manifest_path(root, trading_date, slot)
    payload = load_object(target)
    if not payload or payload.get("status") != "prepared":
        raise ValueError("only prepared Word QA evidence can be rejected")
    payload["status"] = "failed"
    payload["visual_qa_pass"] = False
    payload["failure_reason"] = reason.strip()
    payload["reviewed_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    atomic_json_write(target, payload)
    append_usage(
        trading_date=trading_date,
        slot=slot,
        phase="visual_qa",
        status="failed",
        event_id=f"{payload['docx_sha256']}:visual_qa:failed:{payload['attempts']}",
        retries=max(int(payload.get("attempts", 1)) - 1, 0),
        details={
            "cache_hit": False,
            "attempt": payload.get("attempts", 1),
            "backend": payload["backend"],
            "input_sha256": payload["docx_sha256"],
            "failure_reason": reason.strip(),
        },
        root=root,
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export")
    approve = sub.add_parser("approve")
    reject = sub.add_parser("reject")
    for item in (export, approve, reject):
        item.add_argument("--date", required=True)
        item.add_argument("--slot", required=True, choices=SLOTS)
    export.add_argument("--pdftoppm")
    export.add_argument("--export-timeout", type=int, default=600)
    approve.add_argument("--confirm-visual-pass", action="store_true", required=True)
    approve.add_argument("--reviewer", required=True)
    reject.add_argument("--reason", required=True)
    args = parser.parse_args()
    if args.command == "export":
        result = prepare_qa(
            args.date,
            args.slot,
            pdftoppm=args.pdftoppm,
            export_timeout=args.export_timeout,
        )
    elif args.command == "approve":
        result = approve_qa(args.date, args.slot, reviewer=args.reviewer)
    else:
        result = reject_qa(args.date, args.slot, reason=args.reason)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
