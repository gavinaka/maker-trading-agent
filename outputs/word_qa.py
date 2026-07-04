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


def _export_word_com(docx: Path, pdf: Path, *, timeout: int = 600) -> None:
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / (
        "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    if not powershell.is_file():
        raise RuntimeError(f"Windows PowerShell not found: {powershell}")
    escaped_docx = str(docx).replace("'", "''")
    escaped_pdf = str(pdf).replace("'", "''")
    script = (
        "$ErrorActionPreference='Stop';"
        "$word=$null;$doc=$null;"
        "try{"
        "$word=New-Object -ComObject Word.Application;"
        "$word.Visible=$false;$word.DisplayAlerts=0;"
        f"$doc=$word.Documents.Open('{escaped_docx}',$false,$true);"
        f"$doc.ExportAsFixedFormat('{escaped_pdf}',17);"
        "}finally{"
        "if($doc){$doc.Close($false)};"
        "if($word){$word.Quit()};"
        "}"
    )
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
    if attempts >= 2:
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
        / f"attempt-{attempt}-{uuid.uuid4().hex[:8]}"
    )
    attempt_dir.mkdir(parents=True, exist_ok=False)
    pdf = attempt_dir / f"{trading_date}_{slot}_render.pdf"
    key = f"{docx_hash}:word_export:{attempt}"
    try:
        _export_word_com(docx, pdf, timeout=export_timeout)
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
            "backend": "word_com",
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
                "backend": "word_com",
                "input_sha256": docx_hash,
                "output_sha256": payload["pdf_sha256"],
                "page_count": len(pages),
            },
            root=root,
        )
        return payload
    except BaseException as exc:
        failure = {
            "schema_version": "1.0",
            "status": "failed",
            "visual_qa_pass": False,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "trading_date": trading_date,
            "slot": slot,
            "attempts": attempt,
            "backend": "word_com",
            "docx_path": str(docx),
            "docx_sha256": docx_hash,
            "failure_reason": str(exc),
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
                "backend": "word_com",
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
