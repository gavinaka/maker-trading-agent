"""Interactive-user Word export broker for sandboxed report producers.

The scheduled task running this module has a fixed repository root and accepts
only hash-bound requests inside the canonical Word-QA attempt directories.  It
is deliberately not a general command or arbitrary-path execution surface.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from outputs.word_qa import _export_word_com, sha256_file
from runtime.state_store import atomic_json_write
from runtime_vnext.artifacts import ArtifactStore


DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
REQUEST_ID_RE = re.compile(r"[0-9a-f]{32}")
SLOTS = ("morning", "midday", "evening")
REQUEST_NAME = "broker_request.json"
RESPONSE_NAME = "broker_response.json"
MAX_REQUEST_AGE = timedelta(minutes=30)
HEARTBEAT_NAME = "word_export_broker_heartbeat.json"
VNEXT_ATTEMPT_RE = re.compile(r"attempt-\d{3}-[0-9a-f]{8}")


def _load_object(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("broker request must contain a JSON object")
    return payload


def _request_context(attempt_dir: Path, *, root: Path) -> dict:
    legacy_state = (root / "runtime_state").resolve()
    try:
        relative = attempt_dir.relative_to(legacy_state)
    except ValueError:
        relative = None
    if relative is not None:
        if len(relative.parts) != 4:
            raise ValueError("broker request directory depth is invalid")
        trading_date, word_qa_dir, slot, attempt = relative.parts
        if not DATE_RE.fullmatch(trading_date):
            raise ValueError("broker request date is invalid")
        if (
            word_qa_dir != "word_qa"
            or slot not in SLOTS
            or not attempt.startswith("attempt-")
        ):
            raise ValueError("broker request is outside a canonical Word-QA attempt")
        return {
            "layout": "legacy",
            "trading_date": trading_date,
            "slot": slot,
            "expected_docx": (
                root / "outputs" / f"{trading_date}_{slot}_render.docx"
            ).resolve(),
        }

    vnext_state = (root / "runtime_state_vnext").resolve()
    try:
        relative = attempt_dir.relative_to(vnext_state)
    except ValueError as exc:
        raise ValueError(
            "broker request is outside runtime_state and runtime_state_vnext"
        ) from exc
    if len(relative.parts) != 6:
        raise ValueError("vNext broker request directory depth is invalid")
    trading_date, slot, run_id, delivery_assets, word_qa_dir, attempt = relative.parts
    if not DATE_RE.fullmatch(trading_date):
        raise ValueError("vNext broker request date is invalid")
    if (
        slot not in SLOTS
        or delivery_assets != "delivery_assets"
        or word_qa_dir != "word_qa"
        or not VNEXT_ATTEMPT_RE.fullmatch(attempt)
    ):
        raise ValueError("broker request is outside a canonical vNext Word-QA attempt")

    run_root = vnext_state / trading_date / slot / run_id
    try:
        run = ArtifactStore(root).load_run(run_root)
    except (RuntimeError, ValueError) as exc:
        raise ValueError("vNext broker run metadata is invalid") from exc
    if (
        run.get("schema_version") != "daily-run-vnext-v2"
        or run.get("trading_date") != trading_date
        or run.get("slot") != slot
        or run.get("run_id") != run_id
    ):
        raise ValueError("vNext broker run identity does not match its directory")
    return {
        "layout": "vnext",
        "trading_date": trading_date,
        "slot": slot,
        "run_id": run_id,
        "expected_docx": (
            run_root
            / "delivery_assets"
            / f"{trading_date}_{slot}_render.docx"
        ).resolve(),
    }


def validate_request(request_path: Path, *, root: Path = ROOT) -> dict:
    root = Path(root).resolve()
    request_path = Path(request_path).resolve()
    attempt_dir = request_path.parent
    if request_path != attempt_dir / REQUEST_NAME:
        raise ValueError("broker request filename is not canonical")

    context = _request_context(attempt_dir, root=root)
    trading_date = context["trading_date"]
    slot = context["slot"]

    payload = _load_object(request_path)
    if payload.get("schema_version") != "1.0":
        raise ValueError("broker request schema_version is invalid")
    request_id = str(payload.get("request_id", ""))
    if not REQUEST_ID_RE.fullmatch(request_id):
        raise ValueError("broker request_id is invalid")
    if payload.get("trading_date") != trading_date or payload.get("slot") != slot:
        raise ValueError("broker request target does not match its directory")

    requested_at = datetime.fromisoformat(str(payload.get("requested_at", "")))
    if requested_at.tzinfo is None:
        raise ValueError("broker requested_at must include a timezone")
    age = datetime.now().astimezone() - requested_at.astimezone()
    if age < -timedelta(minutes=5) or age > MAX_REQUEST_AGE:
        raise ValueError("broker request is outside the allowed time window")

    docx = Path(str(payload.get("docx_path", ""))).resolve()
    expected_docx = context["expected_docx"]
    if docx != expected_docx or not docx.is_file():
        raise ValueError("broker DOCX path is not canonical")
    docx_hash = str(payload.get("docx_sha256", ""))
    if not re.fullmatch(r"[0-9a-f]{64}", docx_hash) or sha256_file(docx) != docx_hash:
        raise ValueError("broker DOCX hash does not match")

    pdf = Path(str(payload.get("pdf_path", ""))).resolve()
    expected_pdf = (attempt_dir / f"{trading_date}_{slot}_render.pdf").resolve()
    if pdf != expected_pdf:
        raise ValueError("broker PDF path is not canonical")
    return {
        "request_id": request_id,
        "trading_date": trading_date,
        "slot": slot,
        "docx": docx,
        "docx_sha256": docx_hash,
        "pdf": pdf,
        "response": attempt_dir / RESPONSE_NAME,
        "layout": context["layout"],
        "run_id": context.get("run_id"),
    }


def _pending_requests(root: Path) -> list[Path]:
    root = Path(root).resolve()
    patterns = (
        (root / "runtime_state").glob(f"*/word_qa/*/attempt-*/{REQUEST_NAME}"),
        (root / "runtime_state_vnext").glob(
            f"*/*/*/delivery_assets/word_qa/attempt-*/{REQUEST_NAME}"
        ),
    )
    return sorted(
        {
            path.resolve()
            for matches in patterns
            for path in matches
            if not (path.parent / RESPONSE_NAME).is_file()
        }
    )


def process_request(request_path: Path, *, root: Path = ROOT) -> dict:
    request_path = Path(request_path).resolve()
    response_path = request_path.parent / RESPONSE_NAME
    request_id: str | None = None
    try:
        validated = validate_request(request_path, root=root)
        request_id = validated["request_id"]
        _export_word_com(validated["docx"], validated["pdf"], timeout=480)
        payload = {
            "schema_version": "1.0",
            "status": "success",
            "backend": "word_com_interactive_task",
            "request_id": request_id,
            "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "trading_date": validated["trading_date"],
            "slot": validated["slot"],
            "docx_path": str(validated["docx"]),
            "docx_sha256": validated["docx_sha256"],
            "pdf_path": str(validated["pdf"]),
            "pdf_sha256": sha256_file(validated["pdf"]),
        }
    except BaseException as exc:
        payload = {
            "schema_version": "1.0",
            "status": "failed",
            "backend": "word_com_interactive_task",
            "request_id": request_id,
            "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "failure_reason": str(exc),
        }
    atomic_json_write(response_path, payload)
    return payload


def run_pending(*, root: Path = ROOT, quiet_seconds: float = 2.0) -> list[dict]:
    root = Path(root).resolve()
    results: list[dict] = []
    quiet_since: float | None = None
    while True:
        pending = _pending_requests(root)
        if pending:
            quiet_since = None
            for request in sorted(pending):
                results.append(process_request(request, root=root))
            continue
        if quiet_since is None:
            quiet_since = time.monotonic()
        elif time.monotonic() - quiet_since >= quiet_seconds:
            break
        time.sleep(0.2)
    return results


def _heartbeat_loop(root: Path, stop: threading.Event) -> None:
    heartbeat_path = root / "runtime_state" / HEARTBEAT_NAME
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    while not stop.is_set():
        atomic_json_write(
            heartbeat_path,
            {
                "schema_version": "1.0",
                "status": "ready",
                "started_at": started_at,
                "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            },
        )
        stop.wait(1.0)
    atomic_json_write(
        heartbeat_path,
        {
            "schema_version": "1.0",
            "status": "stopped",
            "started_at": started_at,
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
    )


def run_watch(*, root: Path = ROOT, poll_seconds: float = 0.25) -> None:
    root = Path(root).resolve()
    stop = threading.Event()
    heartbeat = threading.Thread(
        target=_heartbeat_loop,
        args=(root, stop),
        name="word-export-broker-heartbeat",
        daemon=True,
    )
    heartbeat.start()
    try:
        while True:
            pending = _pending_requests(root)
            for request in sorted(pending):
                process_request(request, root=root)
            time.sleep(poll_seconds)
    finally:
        stop.set()
        heartbeat.join(timeout=3)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()
    if args.watch:
        run_watch(root=args.root)
        return 0
    results = run_pending(root=args.root)
    failed = sum(item.get("status") != "success" for item in results)
    print(json.dumps({"processed": len(results), "failed": failed}, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
