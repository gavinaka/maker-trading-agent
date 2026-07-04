"""Mechanical evidence validation for final report delivery."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SLOT_CN = {"morning": "早间", "midday": "午间", "evening": "晚间"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_object(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _resolve_under_root(value: str, root: Path) -> Path:
    candidate = Path(value)
    path = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"artifact path escapes repository: {path}") from exc
    return path


def _verify_file(path: Path, expected_hash: str, label: str) -> None:
    if not path.is_file():
        raise ValueError(f"{label} is missing: {path}")
    actual = sha256_file(path)
    if actual != expected_hash:
        raise ValueError(f"{label} hash mismatch: expected={expected_hash}, actual={actual}")


def _context_block(text: str, trading_date: str) -> str:
    pattern = re.compile(
        rf"^## {re.escape(trading_date)}[^\n]*\n(?P<body>.*?)(?=^## 20\d{{2}}-\d{{2}}-\d{{2}}|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        raise ValueError(f"context_log.md has no {trading_date} block")
    return match.group(0)


def _parse_time(value: str, label: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"invalid {label}: {value!r}") from exc


def validate_delivery_evidence(
    trading_date: str,
    slot: str,
    page_id: str,
    *,
    current: dict,
    root: Path = ROOT,
) -> dict:
    directory = root / "runtime_state" / trading_date
    canonical_docx = (root / "outputs" / f"{trading_date}_{slot}_render.docx").resolve()
    render_path = directory / f"render_{slot}.json"
    qa_path = directory / f"word_qa_{slot}.json"
    publish_path = directory / f"publish_{slot}.json"
    context_path = root / "sessions" / "context_log.md"

    render = load_object(render_path)
    qa = load_object(qa_path)
    publish = load_object(publish_path)

    render_docx = _resolve_under_root(render.get("docx_path", ""), root)
    render_checks = {
        "status": render.get("status") == "success",
        "date": render.get("trading_date") == trading_date,
        "slot": render.get("slot") == slot,
        "canonical_docx": render_docx == canonical_docx,
        "source_hash": render.get("source_sha256") == current.get("report_sha256"),
        "docx_hash": bool(re.fullmatch(r"[0-9a-f]{64}", str(render.get("docx_sha256", "")))),
    }
    failed = sorted(name for name, passed in render_checks.items() if not passed)
    if failed:
        raise ValueError("invalid render evidence: " + ", ".join(failed))
    _verify_file(canonical_docx, render["docx_sha256"], "canonical DOCX")

    qa_docx = _resolve_under_root(qa.get("docx_path", ""), root)
    qa_pdf = _resolve_under_root(qa.get("pdf_path", ""), root)
    qa_checks = {
        "status": qa.get("status") == "passed",
        "visual_pass": qa.get("visual_qa_pass") is True,
        "date": qa.get("trading_date") == trading_date,
        "slot": qa.get("slot") == slot,
        "backend": qa.get("backend") == "word_com",
        "docx_path": qa_docx == canonical_docx,
        "docx_hash": qa.get("docx_sha256") == render["docx_sha256"],
        "pdf_hash": bool(re.fullmatch(r"[0-9a-f]{64}", str(qa.get("pdf_sha256", "")))),
        "pages": isinstance(qa.get("pages"), list) and bool(qa["pages"]),
        "reviewed_at": bool(qa.get("reviewed_at")),
    }
    failed = sorted(name for name, passed in qa_checks.items() if not passed)
    if failed:
        raise ValueError("invalid Word QA evidence: " + ", ".join(failed))
    _verify_file(qa_pdf, qa["pdf_sha256"], "Word QA PDF")
    for index, page in enumerate(qa["pages"], start=1):
        if not isinstance(page, dict):
            raise ValueError(f"Word QA page {index} is invalid")
        page_path = _resolve_under_root(page.get("path", ""), root)
        _verify_file(page_path, page.get("sha256", ""), f"Word QA page {index}")

    publish_checks = {
        "status": publish.get("status") == "success",
        "date": publish.get("trading_date") == trading_date,
        "slot": publish.get("slot") == slot,
        "page_id": publish.get("page_id") == page_id,
        "frozen_verifier": publish.get("frozen_verifier_pass") is True,
        "unique_page": publish.get("unique_page_pass") is True,
        "report_hash": publish.get("report_sha256") == current.get("report_sha256"),
        "published_at": bool(publish.get("published_at")),
    }
    failed = sorted(name for name, passed in publish_checks.items() if not passed)
    if failed:
        raise ValueError("invalid publish evidence: " + ", ".join(failed))

    context_text = context_path.read_text(encoding="utf-8")
    block = _context_block(context_text, trading_date)
    context_checks = {
        "page_id": page_id in block,
        "slot": SLOT_CN[slot] in block,
        "word": "Word" in block,
        "visual_qa_pass": "视觉 QA PASS" in block,
        "frozen_verifier_pass": "冻结" in block and "PASS" in block,
    }
    failed = sorted(name for name, passed in context_checks.items() if not passed)
    if failed:
        raise ValueError("context_log final evidence is incomplete: " + ", ".join(failed))

    reviewed_at = _parse_time(qa["reviewed_at"], "reviewed_at")
    published_at = _parse_time(publish["published_at"], "published_at")
    context_mtime = datetime.fromtimestamp(
        context_path.stat().st_mtime,
        tz=reviewed_at.tzinfo,
    )
    if context_mtime < reviewed_at or context_mtime < published_at:
        raise ValueError(
            "context_log predates final Word QA or publish evidence; "
            "evidence must exist before PASS is recorded"
        )

    return {
        "report_sha256": current["report_sha256"],
        "docx_path": str(canonical_docx),
        "docx_sha256": render["docx_sha256"],
        "render_manifest": str(render_path),
        "render_manifest_sha256": sha256_file(render_path),
        "word_qa_manifest": str(qa_path),
        "word_qa_manifest_sha256": sha256_file(qa_path),
        "publish_manifest": str(publish_path),
        "publish_manifest_sha256": sha256_file(publish_path),
        "context_log_sha256": sha256_file(context_path),
        "published_at": publish["published_at"],
    }
