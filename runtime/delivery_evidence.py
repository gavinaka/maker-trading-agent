"""Mechanical evidence validation for final report delivery."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SLOT_CN = {"morning": "早间", "midday": "午间", "evening": "晚间"}
STRICT_DELIVERY_CONTRACT_FROM = date(2026, 7, 5)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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


def _relative(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")


def _validate_interactive_word_qa(
    qa: dict,
    *,
    qa_docx: Path,
    qa_pdf: Path,
    trading_date: str,
    slot: str,
    root: Path,
) -> None:
    exception = qa.get("attempt_limit_exception")
    exception = exception if isinstance(exception, dict) else {}
    previous_attempts = exception.get("previous_attempts")
    request_path = qa_pdf.parent / "broker_request.json"
    response_path = qa_pdf.parent / "broker_response.json"
    try:
        request = load_object(request_path)
        response = load_object(response_path)
        request_docx = _resolve_under_root(request.get("docx_path", ""), root)
        request_pdf = _resolve_under_root(request.get("pdf_path", ""), root)
        response_docx = _resolve_under_root(response.get("docx_path", ""), root)
        response_pdf = _resolve_under_root(response.get("pdf_path", ""), root)
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError) as exc:
        raise ValueError("invalid Word QA interactive broker artifacts") from exc

    checks = {
        "recovery_used": qa.get("infrastructure_recovery_used") is True,
        "exception_kind": exception.get("kind")
        == "word_com_logon_session_to_interactive_broker",
        "previous_attempts": isinstance(previous_attempts, int)
        and previous_attempts >= 2,
        "attempt_sequence": isinstance(previous_attempts, int)
        and qa.get("attempts") == previous_attempts + 1,
        "previous_failure": "80070520"
        in str(exception.get("previous_failure_reason", "")),
        "request_schema": request.get("schema_version") == "1.0",
        "request_id": bool(
            re.fullmatch(r"[0-9a-f]{32}", str(request.get("request_id", "")))
        ),
        "request_target": request.get("trading_date") == trading_date
        and request.get("slot") == slot,
        "request_docx": request_docx == qa_docx
        and request.get("docx_sha256") == qa.get("docx_sha256"),
        "request_pdf": request_pdf == qa_pdf,
        "response_schema": response.get("schema_version") == "1.0",
        "response_status": response.get("status") == "success",
        "response_backend": response.get("backend")
        == "word_com_interactive_task",
        "response_nonce": response.get("request_id") == request.get("request_id"),
        "response_target": response.get("trading_date") == trading_date
        and response.get("slot") == slot,
        "response_docx": response_docx == qa_docx
        and response.get("docx_sha256") == qa.get("docx_sha256"),
        "response_pdf": response_pdf == qa_pdf
        and response.get("pdf_sha256") == qa.get("pdf_sha256"),
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    if failed:
        raise ValueError(
            "invalid Word QA interactive broker evidence: " + ", ".join(failed)
        )


def _context_block(text: str, trading_date: str, slot: str, page_id: str) -> str:
    pattern = re.compile(
        rf"^## {re.escape(trading_date)}[^\n]*\n(?P<body>.*?)(?=^## 20\d{{2}}-\d{{2}}-\d{{2}}|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    blocks = [match.group(0) for match in pattern.finditer(text)]
    if not blocks:
        raise ValueError(
            f"context_log.md has no {trading_date} block; append the final page id, "
            "published time, frozen verifier PASS and Word visual QA PASS after "
            "render/Word-QA/publish evidence exists, then rerun deliver"
        )
    for block in blocks:
        if page_id in block and SLOT_CN[slot] in block:
            return block
    raise ValueError(
        "context_log.md has no page-and-slot-specific final evidence block for "
        f"{trading_date} {slot}"
    )


def _parse_time(value: str, label: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"invalid {label}: {value!r}") from exc


def _strict_delivery_contract_active(trading_date: str) -> bool:
    year, month, day = (int(part) for part in trading_date.split("-"))
    return date(year, month, day) >= STRICT_DELIVERY_CONTRACT_FROM


def _validate_strict_publish_quality_evidence(publish: dict, trading_date: str) -> None:
    if not _strict_delivery_contract_active(trading_date):
        return
    shape = publish.get("notion_payload_shape")
    source = publish.get("notion_payload_source")
    colors = publish.get("notion_payload_colors")
    verifier = publish.get("frozen_verifier")
    schema_version = shape.get("schema_version") if isinstance(shape, dict) else None
    visual_contract = shape.get("visual_contract") if isinstance(shape, dict) else None
    expected_payload_count = (
        {"morning": 31, "midday": 31, "evening": 32}
        if schema_version == "daily-publish-payload-v3"
        else {"morning": 25, "midday": 25, "evening": 26}
    ).get(str(publish.get("slot", "")))
    checks = {
        "notion_payload_shape": isinstance(shape, dict),
        "notion_payload_shape_passed": isinstance(shape, dict)
        and shape.get("status") == "passed",
        "notion_payload_expected_slot": expected_payload_count is not None,
        "notion_payload_block_count": isinstance(shape, dict)
        and shape.get("block_count_before_images") == expected_payload_count,
        "notion_payload_image_count": isinstance(shape, dict)
        and shape.get("image_count") == 3,
        "notion_visual_contract": (
            isinstance(visual_contract, dict)
            if schema_version == "daily-publish-payload-v3"
            else visual_contract is None or isinstance(visual_contract, dict)
        ),
        "notion_visual_contract_passed": (
            isinstance(visual_contract, dict)
            and visual_contract.get("status") == "passed"
            if schema_version == "daily-publish-payload-v3"
            else visual_contract is None
            or visual_contract.get("status") in {"passed", "legacy"}
        ),
        "notion_payload_source": isinstance(source, dict),
        "notion_payload_source_passed": isinstance(source, dict)
        and source.get("status") == "passed",
        "notion_payload_source_kind": isinstance(source, dict)
        and source.get("kind") == "combined_md_to_notion_payload",
        "notion_payload_colors": isinstance(colors, dict),
        "notion_payload_colors_passed": isinstance(colors, dict)
        and colors.get("status") == "passed",
        "notion_payload_colors_template": isinstance(colors, dict)
        and colors.get("template")
        == (
            "daily-visual-colors-v3"
            if schema_version == "daily-publish-payload-v3"
            else "daily-gold-run-colors-v1"
        ),
        "frozen_verifier": isinstance(verifier, dict),
        "frozen_verifier_returncode": isinstance(verifier, dict)
        and verifier.get("returncode") == 0,
        "frozen_verifier_script": isinstance(verifier, dict)
        and str(verifier.get("script", "")).endswith("notion_verify_against_yesterday.py"),
        "frozen_verifier_stdout": isinstance(verifier, dict)
        and "[PASS]" in str(verifier.get("stdout", "")),
    }
    if date.fromisoformat(trading_date) >= date(2026, 7, 11):
        preflight = publish.get("payload_preflight")
        checks.update(
            {
                "payload_preflight": isinstance(preflight, dict),
                "payload_preflight_passed": isinstance(preflight, dict)
                and preflight.get("status") == "passed",
                "payload_preflight_hash": isinstance(preflight, dict)
                and bool(
                    re.fullmatch(
                        r"[0-9a-f]{64}",
                        str(preflight.get("payload_preview_sha256", "")),
                    )
                ),
                "payload_preflight_manifest_hash": isinstance(preflight, dict)
                and bool(
                    re.fullmatch(
                        r"[0-9a-f]{64}",
                        str(preflight.get("report_preflight_manifest_sha256", "")),
                    )
                ),
            }
        )
    failed = sorted(name for name, passed in checks.items() if not passed)
    if failed:
        raise ValueError("invalid strict publish quality evidence: " + ", ".join(failed))


def _publish_source_binding(
    publish: dict,
    trading_date: str,
    slot: str,
    root: Path,
) -> dict:
    binding = publish.get("source_binding")
    if isinstance(binding, dict):
        return binding

    payload_path_value = publish.get("payload_path")
    payload_hash = publish.get("payload_sha256")
    if not payload_path_value or not payload_hash:
        raise ValueError("publish manifest is missing source binding and payload evidence")
    payload_path = _resolve_under_root(str(payload_path_value), root)
    _verify_file(payload_path, str(payload_hash), "publish payload")
    payload = load_object(payload_path)
    source_specs = payload.get("source_specs")
    if not isinstance(source_specs, dict):
        raise ValueError("publish payload has no source_specs for source binding reconstruction")

    from outputs.publish_report import validate_publish_source_binding

    return validate_publish_source_binding(
        trading_date,
        slot,
        source_specs,
        root=root,
    )


def validate_delivery_evidence(
    trading_date: str,
    slot: str,
    page_id: str,
    *,
    current: dict,
    root: Path = ROOT,
    require_context: bool = True,
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
        "backend": qa.get("backend")
        in {"word_com", "word_com_interactive_task"},
        "docx_path": qa_docx == canonical_docx,
        "docx_hash": qa.get("docx_sha256") == render["docx_sha256"],
        "pdf_hash": bool(re.fullmatch(r"[0-9a-f]{64}", str(qa.get("pdf_sha256", "")))),
        "pages": isinstance(qa.get("pages"), list) and bool(qa["pages"]),
        "reviewed_at": bool(qa.get("reviewed_at")),
    }
    failed = sorted(name for name, passed in qa_checks.items() if not passed)
    if failed:
        raise ValueError("invalid Word QA evidence: " + ", ".join(failed))
    if qa.get("backend") == "word_com_interactive_task":
        _validate_interactive_word_qa(
            qa,
            qa_docx=qa_docx,
            qa_pdf=qa_pdf,
            trading_date=trading_date,
            slot=slot,
            root=root,
        )
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
    _validate_strict_publish_quality_evidence(publish, trading_date)

    source_binding = _publish_source_binding(publish, trading_date, slot, root)
    current_capture = current.get("capture_manifest")
    source_binding_checks = {
        "present": isinstance(source_binding, dict),
        "current_capture": isinstance(current_capture, dict),
        "capture_manifest_path": (
            isinstance(source_binding, dict)
            and isinstance(current_capture, dict)
            and source_binding.get("capture_manifest_path")
            == f"runtime_state/{trading_date}/{current_capture.get('path')}"
        ),
        "capture_manifest_sha256": (
            isinstance(source_binding, dict)
            and isinstance(current_capture, dict)
            and source_binding.get("capture_manifest_sha256")
            == current_capture.get("sha256")
        ),
        "evidence_snapshot_root": (
            isinstance(source_binding, dict)
            and isinstance(current_capture, dict)
            and isinstance(current_capture.get("evidence_snapshot"), dict)
            and source_binding.get("evidence_snapshot_root")
            == (
                f"runtime_state/{trading_date}/"
                f"{current_capture['evidence_snapshot'].get('root')}"
            )
        ),
    }
    failed = sorted(
        name for name, passed in source_binding_checks.items() if not passed
    )
    if failed:
        raise ValueError("invalid publish source binding: " + ", ".join(failed))

    reviewed_at = _parse_time(qa["reviewed_at"], "reviewed_at")
    published_at = _parse_time(publish["published_at"], "published_at")
    base_evidence = {
        "report_sha256": current["report_sha256"],
        "docx_path": str(canonical_docx),
        "docx_sha256": render["docx_sha256"],
        "render_manifest": str(render_path),
        "render_manifest_sha256": sha256_file(render_path),
        "word_qa_manifest": str(qa_path),
        "word_qa_manifest_sha256": sha256_file(qa_path),
        "publish_manifest": str(publish_path),
        "publish_manifest_sha256": sha256_file(publish_path),
        "source_binding": source_binding,
        "reviewed_at": reviewed_at.isoformat(),
        "published_at": publish["published_at"],
        "notion_visual_contract_pass": (
            isinstance(publish.get("notion_payload_shape"), dict)
            and isinstance(publish["notion_payload_shape"].get("visual_contract"), dict)
            and publish["notion_payload_shape"]["visual_contract"].get("status")
            in {"passed", "legacy"}
        ),
    }
    if not require_context:
        return base_evidence

    context_text = context_path.read_text(encoding="utf-8")
    block = _context_block(context_text, trading_date, slot, page_id)
    render_manifest_rel = _relative(render_path, root)
    qa_manifest_rel = _relative(qa_path, root)
    publish_manifest_rel = _relative(publish_path, root)
    context_checks = {
        "page_id": page_id in block,
        "slot": SLOT_CN[slot] in block,
        "report_sha256": current["report_sha256"] in block,
        "docx_sha256": render["docx_sha256"] in block,
        "render_manifest": render_manifest_rel in block,
        "word_qa_manifest": qa_manifest_rel in block,
        "publish_manifest": publish_manifest_rel in block,
        "word": "Word" in block,
        "visual_qa_pass": "视觉 QA PASS" in block,
        "frozen_verifier_pass": "冻结" in block and "PASS" in block,
    }
    failed = sorted(name for name, passed in context_checks.items() if not passed)
    if failed:
        raise ValueError("context_log final evidence is incomplete: " + ", ".join(failed))

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
        **base_evidence,
        "context_log_sha256": sha256_file(context_path),
        "context_log_block_sha256": sha256_text(block),
    }


def record_delivery_context(
    trading_date: str,
    slot: str,
    page_id: str,
    *,
    current: dict,
    root: Path = ROOT,
) -> dict:
    """Write the mechanical final-evidence block without free-form labels."""
    root = Path(root).resolve()
    evidence = validate_delivery_evidence(
        trading_date,
        slot,
        page_id,
        current=current,
        root=root,
        require_context=False,
    )
    context_path = root / "sessions" / "context_log.md"
    context_path.parent.mkdir(parents=True, exist_ok=True)
    existing = context_path.read_text(encoding="utf-8") if context_path.is_file() else ""
    marker = f"<!-- generated-delivery-evidence:{trading_date}:{slot}:{page_id} -->"
    render_rel = _relative(Path(evidence["render_manifest"]), root)
    qa_rel = _relative(Path(evidence["word_qa_manifest"]), root)
    publish_rel = _relative(Path(evidence["publish_manifest"]), root)
    block = "\n".join(
        [
            f"## {trading_date} {SLOT_CN[slot]}最终交付",
            marker,
            f"- 最终唯一存活页：`{page_id}`",
            f"- 发布时间：`{evidence['published_at']}`",
            f"- report_sha256：`{evidence['report_sha256']}`",
            f"- docx_sha256：`{evidence['docx_sha256']}`",
            f"- render_manifest：`{render_rel}`",
            f"- word_qa_manifest：`{qa_rel}`",
            f"- publish_manifest：`{publish_rel}`",
            "- Word 视觉 QA PASS",
            "- 冻结 verifier PASS",
            "",
        ]
    )
    generated = re.compile(
        rf"^## {re.escape(trading_date)} {re.escape(SLOT_CN[slot])}最终交付\n"
        rf"<!-- generated-delivery-evidence:{re.escape(trading_date)}:"
        rf"{re.escape(slot)}:[^>]+ -->\n.*?(?=^## 20\d{{2}}-\d{{2}}-\d{{2}}|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    remainder = generated.sub("", existing).lstrip("\n")
    updated = block + ("\n" + remainder if remainder else "")
    changed = updated != existing
    if changed:
        temporary = context_path.with_suffix(".md.tmp")
        temporary.write_text(updated, encoding="utf-8")
        os.replace(temporary, context_path)
    verified = validate_delivery_evidence(
        trading_date,
        slot,
        page_id,
        current=current,
        root=root,
        require_context=True,
    )
    return {
        "schema_version": "delivery-context-record-v1",
        "trading_date": trading_date,
        "slot": slot,
        "page_id": page_id,
        "context_log": str(context_path),
        "context_log_sha256": verified["context_log_sha256"],
        "context_log_block_sha256": verified["context_log_block_sha256"],
        "changed": changed,
        "verified": True,
    }
