"""Run-local Word export and visual-QA evidence for vNext delivery."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from outputs import render_from_combined as canonical_report_renderer
from outputs import word_qa as canonical_word_qa
from runtime.state_store import atomic_json_write

from .artifacts import ArtifactStore
from .errors import FailureClass, WorkflowFailure
from .methodology import sha256_file


WORD_QA_SCHEMA = "word-qa-vnext-v2"
ALLOWED_BACKENDS = {"word_com", "word_com_interactive_task"}
MAX_DELIVERY_ATTEMPTS = 2
WORD_QA_REVIEW_CHECKLIST_VERSION = "word-qa-semantic-review-v1"
WORD_QA_REVIEW_CHECKLIST_KEYS = (
    "all_pages_inspected",
    "no_clipping_overlap_or_missing_glyphs",
    "no_orphan_semantic_headings",
    "critical_price_blocks_not_split",
    "six_source_sections_readable",
    "arabic_price_digits_preserved",
)
PASSED_WORD_QA_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "visual_qa_pass",
        "created_at",
        "trading_date",
        "slot",
        "run_id",
        "run_sha256",
        "attempts",
        "cache_hit",
        "backend",
        "page_renderer",
        "report_sha256",
        "docx",
        "docx_sha256",
        "pdf",
        "pdf_sha256",
        "page_count",
        "inspected_pages",
        "page_images",
        "reviewer",
        "reviewed_at",
        "review_checklist_version",
        "review_checklist",
    }
)
PREPARED_WORD_QA_FIELDS = PASSED_WORD_QA_FIELDS - {
    "reviewer",
    "reviewed_at",
}
FAILED_WORD_QA_EXPORT_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "visual_qa_pass",
        "created_at",
        "trading_date",
        "slot",
        "run_id",
        "run_sha256",
        "attempts",
        "backend",
        "report_sha256",
        "docx",
        "docx_sha256",
        "failure_reason",
    }
)
REJECTED_WORD_QA_FIELDS = PREPARED_WORD_QA_FIELDS | {
    "failure_reason",
    "reviewed_at",
}


def _review_checklist(*, passed: bool) -> dict[str, bool]:
    return {key: passed for key in WORD_QA_REVIEW_CHECKLIST_KEYS}


def passed_word_qa_checklist_is_valid(payload: dict[str, Any]) -> bool:
    checklist = payload.get("review_checklist")
    return (
        payload.get("review_checklist_version")
        == WORD_QA_REVIEW_CHECKLIST_VERSION
        and isinstance(checklist, dict)
        and set(checklist) == set(WORD_QA_REVIEW_CHECKLIST_KEYS)
        and all(checklist.get(key) is True for key in WORD_QA_REVIEW_CHECKLIST_KEYS)
    )


def _load_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON artifact must contain an object: {path}")
    return payload


def _artifact_record(repo_root: Path, path: Path) -> dict[str, Any]:
    resolved_root = repo_root.resolve()
    resolved = path.resolve()
    relative = resolved.relative_to(resolved_root)
    if not resolved.is_file() or resolved.stat().st_size <= 0:
        raise ValueError(f"delivery artifact is missing or empty: {resolved}")
    return {
        "path": relative.as_posix(),
        "sha256": sha256_file(resolved),
        "bytes": resolved.stat().st_size,
    }


def _record_path(repo_root: Path, record: dict[str, Any]) -> Path:
    resolved_root = repo_root.resolve()
    path = (resolved_root / str(record.get("path", ""))).resolve()
    path.relative_to(resolved_root)
    return path


def _record_is_valid(repo_root: Path, record: Any) -> bool:
    if not isinstance(record, dict):
        return False
    try:
        path = _record_path(repo_root, record)
        return (
            path.is_file()
            and path.stat().st_size == record.get("bytes")
            and sha256_file(path) == record.get("sha256")
        )
    except (FileNotFoundError, OSError, TypeError, ValueError):
        return False


def _manifest_files_valid(repo_root: Path, payload: dict[str, Any]) -> bool:
    pages = payload.get("page_images")
    if not isinstance(pages, list) or not pages:
        return False
    files_valid = (
        _record_is_valid(repo_root, payload.get("docx"))
        and _record_is_valid(repo_root, payload.get("pdf"))
        and all(_record_is_valid(repo_root, page) for page in pages)
        and payload.get("docx_sha256") == payload["docx"]["sha256"]
        and payload.get("pdf_sha256") == payload["pdf"]["sha256"]
        and payload.get("page_count") == len(pages)
    )
    if not files_valid:
        return False
    return payload.get("status") != "passed" or passed_word_qa_checklist_is_valid(payload)


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_attempt_count(value: Any, *, allow_zero: bool = False) -> bool:
    minimum = 0 if allow_zero else 1
    return (
        type(value) is int
        and minimum <= value <= MAX_DELIVERY_ATTEMPTS
    )


def _aware_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _record_shape_is_valid(
    repo_root: Path,
    record: Any,
    *,
    expected_path: Path,
) -> bool:
    if not isinstance(record, dict):
        return False
    try:
        return (
            _record_path(repo_root, record).resolve() == expected_path.resolve()
            and _is_sha256(record.get("sha256"))
            and type(record.get("bytes")) is int
            and record["bytes"] > 0
        )
    except (OSError, TypeError, ValueError):
        return False


def _render_manifest_base_binding_is_valid(
    repo_root: Path,
    run_root: Path,
    run: dict[str, Any],
    report: dict[str, Any],
    payload: dict[str, Any],
) -> bool:
    docx = (
        run_root
        / "delivery_assets"
        / f"{run['trading_date']}_{run['slot']}_render.docx"
    )
    try:
        return (
            payload.get("schema_version") == "1.0"
            and payload.get("status") == "success"
            and payload.get("trading_date") == run.get("trading_date")
            and payload.get("slot") == run.get("slot")
            and _is_attempt_count(payload.get("attempts"))
            and Path(str(payload.get("source_path", ""))).resolve()
            == _record_path(repo_root, report).resolve()
            and payload.get("source_sha256") == report.get("sha256")
            and Path(str(payload.get("docx_path", ""))).resolve()
            == docx.resolve()
            and docx.is_file()
            and sha256_file(docx) == payload.get("docx_sha256")
            and docx.resolve().is_relative_to(repo_root.resolve())
        )
    except (OSError, TypeError, ValueError):
        return False


def _render_manifest_has_refreshable_identity(payload: dict[str, Any]) -> bool:
    return (
        _is_sha256(payload.get("renderer_sha256"))
        and _is_sha256(payload.get("presentation_contract_sha256"))
    )


def _render_manifest_is_valid(
    repo_root: Path,
    run_root: Path,
    run: dict[str, Any],
    report: dict[str, Any],
    payload: dict[str, Any],
) -> bool:
    try:
        return (
            _render_manifest_base_binding_is_valid(
                repo_root,
                run_root,
                run,
                report,
                payload,
            )
            and payload.get("renderer_sha256")
            == canonical_report_renderer.renderer_sha256()
            and payload.get("presentation_contract_sha256")
            == sha256_file(
                repo_root
                / "governance"
                / "vnext_report_presentation_contract.json"
            )
        )
    except (OSError, TypeError, ValueError):
        return False


def _failed_render_manifest_is_valid(
    repo_root: Path,
    run_root: Path,
    run: dict[str, Any],
    report: dict[str, Any],
    payload: dict[str, Any],
) -> bool:
    docx = (
        run_root
        / "delivery_assets"
        / f"{run['trading_date']}_{run['slot']}_render.docx"
    )
    try:
        return (
            payload.get("schema_version") == "1.0"
            and payload.get("status") == "failed"
            and payload.get("trading_date") == run.get("trading_date")
            and payload.get("slot") == run.get("slot")
            and _is_attempt_count(payload.get("attempts"))
            and Path(str(payload.get("source_path", ""))).resolve()
            == _record_path(repo_root, report).resolve()
            and payload.get("source_sha256") == report.get("sha256")
            and _is_sha256(payload.get("renderer_sha256"))
            and _is_sha256(payload.get("presentation_contract_sha256"))
            and Path(str(payload.get("docx_path", ""))).resolve()
            == docx.resolve()
            and isinstance(payload.get("failure_reason"), str)
            and bool(payload["failure_reason"].strip())
        )
    except (OSError, TypeError, ValueError):
        return False


def _word_page_evidence_is_valid(
    repo_root: Path,
    run_root: Path,
    run: dict[str, Any],
    payload: dict[str, Any],
) -> bool:
    pages = payload.get("page_images")
    page_count = payload.get("page_count")
    attempt = payload.get("attempts")
    if (
        type(page_count) is not int
        or page_count <= 0
        or not _is_attempt_count(attempt)
        or not isinstance(pages, list)
        or len(pages) != page_count
        or not _record_is_valid(repo_root, payload.get("pdf"))
        or payload.get("pdf_sha256")
        != (payload.get("pdf") or {}).get("sha256")
    ):
        return False
    try:
        pdf_path = _record_path(repo_root, payload["pdf"]).resolve()
        attempt_dir = pdf_path.parent
        word_qa_root = (
            run_root / "delivery_assets" / "word_qa"
        ).resolve()
        attempt_prefix = f"attempt-{attempt:03d}-"
        attempt_suffix = attempt_dir.name.removeprefix(attempt_prefix)
        if (
            attempt_dir.parent != word_qa_root
            or not attempt_dir.name.startswith(attempt_prefix)
            or len(attempt_suffix) != 8
            or any(character not in "0123456789abcdef" for character in attempt_suffix)
            or pdf_path.name
            != f"{run['trading_date']}_{run['slot']}_render.pdf"
        ):
            return False
    except (OSError, TypeError, ValueError):
        return False
    page_paths: list[str] = []
    for index, page in enumerate(pages, start=1):
        if (
            not isinstance(page, dict)
            or page.get("page") != index
            or not _record_is_valid(repo_root, page)
        ):
            return False
        try:
            page_path = _record_path(repo_root, page).resolve()
            page_suffix = page_path.stem.removeprefix("page-")
            if (
                page_path.parent != attempt_dir
                or not page_path.name.startswith("page-")
                or page_path.suffix.lower() != ".png"
                or not page_suffix.isdigit()
                or int(page_suffix) != index
            ):
                return False
            page_paths.append(str(page_path).casefold())
        except (OSError, TypeError, ValueError):
            return False
    return len(page_paths) == len(set(page_paths))


def passed_word_qa_run_paths_are_valid(
    repo_root: Path,
    run: dict[str, Any],
    payload: dict[str, Any],
) -> bool:
    """Validate that passed Word-QA artifacts belong to this exact v2 run."""
    try:
        store = ArtifactStore(repo_root)
        run_root = store.run_root(
            str(run["trading_date"]),
            str(run["slot"]),
            str(run["run_id"]),
        )
        expected_docx = (
            run_root
            / "delivery_assets"
            / f"{run['trading_date']}_{run['slot']}_render.docx"
        )
        return (
            _record_shape_is_valid(
                repo_root,
                payload.get("docx"),
                expected_path=expected_docx,
            )
            and _word_page_evidence_is_valid(
                repo_root,
                run_root,
                run,
                payload,
            )
        )
    except (KeyError, OSError, TypeError, ValueError):
        return False


def _word_qa_contract_is_valid(
    repo_root: Path,
    run_root: Path,
    run: dict[str, Any],
    report: dict[str, Any],
    render_manifest: dict[str, Any],
    payload: dict[str, Any],
) -> bool:
    status = payload.get("status")
    created_at = _aware_datetime(payload.get("created_at"))
    expected_docx = (
        run_root
        / "delivery_assets"
        / f"{run['trading_date']}_{run['slot']}_render.docx"
    )
    docx_record = payload.get("docx")
    if (
        status not in {"prepared", "passed", "failed"}
        or payload.get("schema_version") != WORD_QA_SCHEMA
        or payload.get("trading_date") != run.get("trading_date")
        or payload.get("slot") != run.get("slot")
        or payload.get("run_id") != run.get("run_id")
        or payload.get("run_sha256") != run.get("run_sha256")
        or payload.get("report_sha256") != report.get("sha256")
        or not _is_attempt_count(payload.get("attempts"))
        or payload.get("backend") not in ALLOWED_BACKENDS
        or created_at is None
        or not _record_shape_is_valid(
            repo_root,
            docx_record,
            expected_path=expected_docx,
        )
        or payload.get("docx_sha256") != docx_record.get("sha256")
    ):
        return False

    if status == "failed" and payload.get("reviewed_at") is None:
        return (
            set(payload) == set(FAILED_WORD_QA_EXPORT_FIELDS)
            and payload.get("visual_qa_pass") is False
            and isinstance(payload.get("failure_reason"), str)
            and bool(payload["failure_reason"].strip())
        )

    expected_fields = (
        PASSED_WORD_QA_FIELDS
        if status == "passed"
        else REJECTED_WORD_QA_FIELDS
        if status == "failed"
        else PREPARED_WORD_QA_FIELDS
    )
    if (
        set(payload) != set(expected_fields)
        or not _word_page_evidence_is_valid(
            repo_root,
            run_root,
            run,
            payload,
        )
        or type(payload.get("cache_hit")) is not bool
        or not isinstance(payload.get("page_renderer"), str)
        or not payload["page_renderer"].strip()
    ):
        return False

    checklist = payload.get("review_checklist")
    if status == "passed":
        reviewed_at = _aware_datetime(payload.get("reviewed_at"))
        return (
            payload.get("visual_qa_pass") is True
            and _record_is_valid(repo_root, docx_record)
            and payload.get("docx_sha256")
            == render_manifest.get("docx_sha256")
            and payload.get("inspected_pages")
            == list(range(1, payload["page_count"] + 1))
            and isinstance(payload.get("reviewer"), str)
            and bool(payload["reviewer"].strip())
            and reviewed_at is not None
            and reviewed_at >= created_at
            and passed_word_qa_checklist_is_valid(payload)
        )

    reviewed_at = (
        _aware_datetime(payload.get("reviewed_at"))
        if status == "failed"
        else None
    )
    return (
        payload.get("visual_qa_pass") is False
        and payload.get("inspected_pages") == []
        and payload.get("review_checklist_version")
        == WORD_QA_REVIEW_CHECKLIST_VERSION
        and isinstance(checklist, dict)
        and set(checklist) == set(WORD_QA_REVIEW_CHECKLIST_KEYS)
        and all(checklist.get(key) is False for key in WORD_QA_REVIEW_CHECKLIST_KEYS)
        and (
            status == "prepared"
            and _record_is_valid(repo_root, docx_record)
            and payload.get("docx_sha256")
            == render_manifest.get("docx_sha256")
            or status == "failed"
            and isinstance(payload.get("failure_reason"), str)
            and bool(payload["failure_reason"].strip())
            and reviewed_at is not None
            and reviewed_at >= created_at
        )
    )


def _base_run_context(
    repo_root: Path,
    run_root: Path,
) -> tuple[ArtifactStore, dict[str, Any], dict[str, Any], dict[str, Any]]:
    repo_root = repo_root.resolve()
    run_root = run_root.resolve()
    store = ArtifactStore(repo_root)
    run = store.load_run(run_root)
    if (
        run.get("schema_version") != "daily-run-vnext-v2"
        or run.get("run_mode") not in {"shadow", "production"}
    ):
        raise ValueError(
            "legacy vNext runs are read-only; Word QA requires an explicitly authorized v2 run mode"
        )
    checkpoint = store.load_checkpoint(run_root)
    if any(
        checkpoint.get(key) != run.get(key)
        for key in ("run_id", "trading_date", "slot")
    ):
        raise ValueError("vNext Word QA run/checkpoint identity differs")
    if checkpoint.get("status") != "running" or checkpoint.get("next_stage") != "delivery":
        raise ValueError("vNext Word QA requires a running delivery checkpoint")
    store._assert_active(run_root)
    report = ((checkpoint.get("completed") or {}).get("report") or {}).get("outputs", {}).get("combined")
    if not isinstance(report, dict) or not _record_is_valid(repo_root, report):
        raise ValueError("vNext Word QA requires the certified report artifact")
    return store, run, checkpoint, report


def _run_context(
    repo_root: Path,
    run_root: Path,
) -> tuple[ArtifactStore, dict[str, Any], dict[str, Any], Path, Path, dict[str, Any]]:
    store, run, checkpoint, report = _base_run_context(repo_root, run_root)
    delivery_assets = run_root / "delivery_assets"
    docx = delivery_assets / f"{run['trading_date']}_{run['slot']}_render.docx"
    render_manifest_path = delivery_assets / "render_manifest.json"
    render_manifest = _load_object(render_manifest_path)
    if not render_manifest or not _render_manifest_is_valid(
        repo_root,
        run_root,
        run,
        report,
        render_manifest,
    ):
        raise ValueError(
            "vNext Word QA requires a current, hash-bound run-local render contract"
        )
    return store, run, checkpoint, docx, delivery_assets / "word_qa.json", report


def _delivery_failure(
    code: str,
    message: str,
    *,
    failure_class: FailureClass = FailureClass.DELIVERY_INTEGRITY,
    path: str = "delivery_assets/render_manifest.json",
) -> WorkflowFailure:
    return WorkflowFailure(
        failure_class,
        message,
        defects=[
            {
                "code": code,
                "message": message,
                "path": path,
                "severity": "hard",
            }
        ],
    )


def _record_delivery_preparation_failure(
    store: ArtifactStore,
    run_root: Path,
    *,
    failure_code: str,
    report_sha256: str,
) -> None:
    store._append_event(
        run_root,
        {
            "event": "delivery_preparation_failed",
            "failure_code": failure_code,
            "report_sha256": report_sha256,
        },
    )


def _ensure_run_render(
    repo_root: Path,
    run_root: Path,
    *,
    store: ArtifactStore,
    run: dict[str, Any],
    report: dict[str, Any],
) -> None:
    manifest_path = run_root / "delivery_assets" / "render_manifest.json"
    try:
        render_manifest = _load_object(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError):
        failure_code = "delivery.render_contract_invalid"
        _record_delivery_preparation_failure(
            store,
            run_root,
            failure_code=failure_code,
            report_sha256=str(report["sha256"]),
        )
        raise _delivery_failure(
            failure_code,
            "run-local render contract is invalid before Word QA",
            failure_class=FailureClass.MANUAL_REVIEW,
        )

    attempts = 0
    if render_manifest:
        render_status = render_manifest.get("status")
        if render_status == "success":
            if _render_manifest_is_valid(
                repo_root,
                run_root,
                run,
                report,
                render_manifest,
            ):
                return
            if not _render_manifest_base_binding_is_valid(
                repo_root,
                run_root,
                run,
                report,
                render_manifest,
            ) or not _render_manifest_has_refreshable_identity(render_manifest):
                failure_code = "delivery.render_contract_invalid"
                _record_delivery_preparation_failure(
                    store,
                    run_root,
                    failure_code=failure_code,
                    report_sha256=str(report["sha256"]),
                )
                raise _delivery_failure(
                    failure_code,
                    "run-local render contract binding is invalid before Word QA",
                    failure_class=FailureClass.MANUAL_REVIEW,
                )
        elif render_status == "failed":
            if not _failed_render_manifest_is_valid(
                repo_root,
                run_root,
                run,
                report,
                render_manifest,
            ):
                failure_code = "delivery.render_contract_invalid"
                _record_delivery_preparation_failure(
                    store,
                    run_root,
                    failure_code=failure_code,
                    report_sha256=str(report["sha256"]),
                )
                raise _delivery_failure(
                    failure_code,
                    "failed run-local render contract is invalid before Word QA",
                    failure_class=FailureClass.MANUAL_REVIEW,
                )
        else:
            failure_code = "delivery.render_contract_invalid"
            _record_delivery_preparation_failure(
                store,
                run_root,
                failure_code=failure_code,
                report_sha256=str(report["sha256"]),
            )
            raise _delivery_failure(
                failure_code,
                "run-local render contract has an unsupported state before Word QA",
                failure_class=FailureClass.MANUAL_REVIEW,
            )
        attempts = int(render_manifest["attempts"])

    if attempts >= MAX_DELIVERY_ATTEMPTS:
        failure_code = "delivery.render_attempt_limit_reached"
        _record_delivery_preparation_failure(
            store,
            run_root,
            failure_code=failure_code,
            report_sha256=str(report["sha256"]),
        )
        raise _delivery_failure(
            failure_code,
            "run-local render attempt limit reached before Word QA",
            failure_class=FailureClass.MANUAL_REVIEW,
        )

    pre_render_manifest_sha256 = (
        sha256_file(manifest_path) if manifest_path.is_file() else None
    )
    try:
        canonical_report_renderer.render_canonical(
            _record_path(repo_root, report),
            str(run["trading_date"]),
            str(run["slot"]),
            root=repo_root,
            vnext_run_root=run_root,
            _vnext_lock_acquired=True,
        )
    except Exception as exc:
        failed_manifest: dict[str, Any] = {}
        manifest_contract_invalid = False
        if manifest_path.is_file():
            try:
                current_manifest_sha256 = sha256_file(manifest_path)
                failed_manifest = _load_object(manifest_path) or {}
            except (OSError, ValueError, json.JSONDecodeError):
                current_manifest_sha256 = None
                manifest_contract_invalid = True
            if (
                not manifest_contract_invalid
                and current_manifest_sha256 != pre_render_manifest_sha256
                and not _failed_render_manifest_is_valid(
                    repo_root,
                    run_root,
                    run,
                    report,
                    failed_manifest,
                )
            ):
                manifest_contract_invalid = True
        elif pre_render_manifest_sha256 is not None:
            manifest_contract_invalid = True
        if manifest_contract_invalid:
            failure_code = "delivery.render_contract_invalid"
            _record_delivery_preparation_failure(
                store,
                run_root,
                failure_code=failure_code,
                report_sha256=str(report["sha256"]),
            )
            raise _delivery_failure(
                failure_code,
                "renderer left an invalid run-local failure contract",
                failure_class=FailureClass.MANUAL_REVIEW,
            ) from exc
        exhausted = (
            _failed_render_manifest_is_valid(
                repo_root,
                run_root,
                run,
                report,
                failed_manifest,
            )
            and failed_manifest.get("attempts") >= MAX_DELIVERY_ATTEMPTS
        )
        failure_code = (
            "delivery.render_attempt_limit_reached"
            if exhausted
            else "delivery.render_failed_before_word_qa"
        )
        _record_delivery_preparation_failure(
            store,
            run_root,
            failure_code=failure_code,
            report_sha256=str(report["sha256"]),
        )
        raise _delivery_failure(
            failure_code,
            (
                "run-local render attempt limit reached before Word QA"
                if exhausted
                else "run-local render failed before Word QA attempt creation"
            ),
            failure_class=(
                FailureClass.MANUAL_REVIEW
                if exhausted
                else FailureClass.DELIVERY_INTEGRITY
            ),
        ) from exc

    try:
        rendered_manifest = _load_object(manifest_path) or {}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        rendered_manifest = {}
        invalid_manifest_error = exc
    else:
        invalid_manifest_error = None
    if not _render_manifest_is_valid(
        repo_root,
        run_root,
        run,
        report,
        rendered_manifest,
    ):
        failure_code = "delivery.render_contract_invalid"
        _record_delivery_preparation_failure(
            store,
            run_root,
            failure_code=failure_code,
            report_sha256=str(report["sha256"]),
        )
        failure = _delivery_failure(
            failure_code,
            "run-local render contract failed validation before Word QA",
            failure_class=FailureClass.MANUAL_REVIEW,
        )
        if invalid_manifest_error is not None:
            raise failure from invalid_manifest_error
        raise failure


def delivery_control_state(repo_root: Path, run_root: Path) -> dict[str, Any]:
    """Return code-owned delivery state without adding a second checkpoint truth."""
    repo_root = Path(repo_root).resolve()
    run_root = Path(run_root).resolve()
    _, run, _, report = _base_run_context(repo_root, run_root)
    assets = run_root / "delivery_assets"
    render_contract_invalid = False
    word_qa_contract_invalid = False
    try:
        render_manifest = _load_object(assets / "render_manifest.json") or {}
    except (OSError, ValueError, json.JSONDecodeError):
        render_manifest = {}
        render_contract_invalid = True
    try:
        word_qa = _load_object(assets / "word_qa.json") or {}
    except (OSError, ValueError, json.JSONDecodeError):
        word_qa = {}
        word_qa_contract_invalid = True
    render_status = str(render_manifest.get("status") or "absent")
    word_qa_status = str(word_qa.get("status") or "absent")
    result: dict[str, Any] = {
        "schema_version": "delivery-control-state-v1",
        "run_id": run["run_id"],
        "report_sha256": report["sha256"],
        "render_status_code": f"delivery.render.{render_status}",
        "word_qa_status_code": f"delivery.word_qa.{word_qa_status}",
    }

    render_refresh_required = False
    if render_manifest and render_status == "absent":
        render_contract_invalid = True
    if render_status not in {"absent", "failed", "success"}:
        render_contract_invalid = True
    elif render_status == "failed":
        render_contract_invalid = not _failed_render_manifest_is_valid(
            repo_root,
            run_root,
            run,
            report,
            render_manifest,
        )
        if (
            not render_contract_invalid
            and render_manifest["attempts"] >= MAX_DELIVERY_ATTEMPTS
        ):
            result.update(
                {
                    "state_code": "delivery.render_attempt_limit_reached",
                    "next_action_code": "delivery.manual_review",
                    "next_command": None,
                }
            )
            return result
    elif render_status == "success":
        if not _render_manifest_is_valid(
            repo_root,
            run_root,
            run,
            report,
            render_manifest,
        ):
            if _render_manifest_base_binding_is_valid(
                repo_root,
                run_root,
                run,
                report,
                render_manifest,
            ) and _render_manifest_has_refreshable_identity(render_manifest):
                if render_manifest["attempts"] >= MAX_DELIVERY_ATTEMPTS:
                    result.update(
                        {
                            "state_code": "delivery.render_attempt_limit_reached",
                            "next_action_code": "delivery.manual_review",
                            "next_command": None,
                        }
                    )
                    return result
                render_refresh_required = True
            else:
                render_contract_invalid = True
    if render_contract_invalid:
        result.update(
            {
                "state_code": "delivery.render_contract_invalid",
                "next_action_code": "delivery.maintenance_required",
                "next_command": None,
            }
        )
        return result
    if word_qa and word_qa_status == "absent":
        word_qa_contract_invalid = True
    if word_qa_status not in {"absent", "prepared", "passed", "failed"}:
        word_qa_contract_invalid = True
    elif word_qa_status != "absent":
        if word_qa_status in {"prepared", "passed"} and (
            render_status != "success" or render_refresh_required
        ):
            word_qa_contract_invalid = True
        elif not _word_qa_contract_is_valid(
            repo_root,
            run_root,
            run,
            report,
            render_manifest,
            word_qa,
        ):
            word_qa_contract_invalid = True
    if word_qa_contract_invalid:
        result.update(
            {
                "state_code": "delivery.word_qa_contract_invalid",
                "next_action_code": "delivery.maintenance_required",
                "next_command": None,
            }
        )
        return result
    if word_qa_status == "prepared":
        result.update(
            {
                "state_code": "delivery.word_qa_review_pending",
                "next_action_code": "delivery.word_qa_visual_review",
                "next_command": None,
            }
        )
        return result
    if word_qa_status == "passed":
        command = "shadow-delivery" if run["run_mode"] == "shadow" else "delivery"
        result.update(
            {
                "state_code": f"delivery.{command.replace('-', '_')}_pending",
                "next_action_code": f"delivery.{command.replace('-', '_')}",
                "next_command": command,
            }
        )
        return result
    if word_qa_status == "failed":
        if (
            word_qa.get("docx_sha256")
            != render_manifest.get("docx_sha256")
        ):
            result.update(
                {
                    "state_code": "delivery.word_qa_contract_invalid",
                    "next_action_code": "delivery.maintenance_required",
                    "next_command": None,
                }
            )
            return result
        if word_qa["attempts"] >= MAX_DELIVERY_ATTEMPTS:
            result.update(
                {
                    "state_code": "delivery.word_qa_attempt_limit_reached",
                    "next_action_code": "delivery.manual_review",
                    "next_command": None,
                }
            )
            return result
        if (
            word_qa.get("reviewed_at")
            and not render_refresh_required
        ):
            result.update(
                {
                    "state_code": "delivery.render_revision_required",
                    "next_action_code": "delivery.render_revision",
                    "next_command": None,
                }
            )
            return result
    if render_refresh_required:
        result.update(
            {
                "state_code": "delivery.render_refresh_pending",
                "next_action_code": "delivery.word_qa_export",
                "next_command": "word-qa-export",
            }
        )
        return result
    result.update(
        {
            "state_code": "delivery.word_qa_export_pending",
            "next_action_code": "delivery.word_qa_export",
            "next_command": "word-qa-export",
        }
    )
    return result


def prepare_run_qa(
    repo_root: Path,
    run_root: Path,
    *,
    pdftoppm: str | None = None,
    export_timeout: int = 600,
) -> dict[str, Any]:
    repo_root = Path(repo_root).resolve()
    run_root = Path(run_root).resolve()
    store = ArtifactStore(repo_root)
    with store.controller_lock(run_root):
        store, run, _, report = _base_run_context(repo_root, run_root)
        render_manifest_path = (
            run_root / "delivery_assets" / "render_manifest.json"
        )
        word_qa_manifest_path = (
            run_root / "delivery_assets" / "word_qa.json"
        )
        try:
            pre_render_manifest = _load_object(render_manifest_path) or {}
        except (OSError, ValueError, json.JSONDecodeError):
            pre_render_manifest = {}
        try:
            pre_word_qa = _load_object(word_qa_manifest_path) or {}
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise _delivery_failure(
                "delivery.word_qa_contract_invalid",
                "run-local Word QA contract is unreadable before render",
                failure_class=FailureClass.MANUAL_REVIEW,
                path="delivery_assets/word_qa.json",
            ) from exc
        if pre_word_qa:
            if (
                not pre_render_manifest
                or not _word_qa_contract_is_valid(
                    repo_root,
                    run_root,
                    run,
                    report,
                    pre_render_manifest,
                    pre_word_qa,
                )
                or (
                    pre_word_qa.get("status") in {"prepared", "passed"}
                    and not _render_manifest_is_valid(
                        repo_root,
                        run_root,
                        run,
                        report,
                        pre_render_manifest,
                    )
                )
                or (
                    pre_word_qa.get("status") == "failed"
                    and pre_word_qa.get("docx_sha256")
                    != pre_render_manifest.get("docx_sha256")
                )
            ):
                raise _delivery_failure(
                    "delivery.word_qa_contract_invalid",
                    "run-local Word QA contract is not bound to the pre-render state",
                    failure_class=FailureClass.MANUAL_REVIEW,
                    path="delivery_assets/word_qa.json",
                )
        _ensure_run_render(
            repo_root,
            run_root,
            store=store,
            run=run,
            report=report,
        )
        try:
            _, run, _, docx, manifest_path, report = _run_context(
                repo_root, run_root
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            failure_code = "delivery.render_contract_invalid"
            _record_delivery_preparation_failure(
                store,
                run_root,
                failure_code=failure_code,
                report_sha256=str(report["sha256"]),
            )
            raise _delivery_failure(
                failure_code,
                "run-local render contract failed validation before Word QA",
                failure_class=FailureClass.MANUAL_REVIEW,
            ) from exc
        docx_record = _artifact_record(repo_root, docx)
        render_manifest = _load_object(render_manifest_path)
        if not render_manifest:
            raise _delivery_failure(
                "delivery.render_contract_invalid",
                "run-local render contract disappeared before Word QA",
                failure_class=FailureClass.MANUAL_REVIEW,
            )
        existing = _load_object(manifest_path) or {}
        if existing and not _word_qa_contract_is_valid(
            repo_root,
            run_root,
            run,
            report,
            render_manifest,
            existing,
        ):
            raise _delivery_failure(
                "delivery.word_qa_contract_invalid",
                "run-local Word QA contract is invalid before export",
                failure_class=FailureClass.MANUAL_REVIEW,
                path="delivery_assets/word_qa.json",
            )
        if existing.get("status") in {"prepared", "passed"}:
            cached = dict(existing)
            cached["cache_hit"] = True
            return cached
        if (
            existing.get("status") == "failed"
            and existing.get("reviewed_at")
            and existing.get("docx_sha256") == docx_record["sha256"]
        ):
            raise _delivery_failure(
                "delivery.render_revision_required",
                "DOCX is unchanged after vNext visual-QA rejection; fix and re-render before export",
                failure_class=FailureClass.MANUAL_REVIEW,
                path="delivery_assets/word_qa.json",
            )

        attempts = int(existing.get("attempts", 0))
        if attempts >= MAX_DELIVERY_ATTEMPTS:
            raise _delivery_failure(
                "delivery.word_qa_attempt_limit_reached",
                "vNext Word export attempt limit reached (2)",
                failure_class=FailureClass.MANUAL_REVIEW,
                path="delivery_assets/word_qa.json",
            )
        attempt = attempts + 1
        attempt_dir = (
            run_root
            / "delivery_assets"
            / "word_qa"
            / f"attempt-{attempt:03d}-{uuid.uuid4().hex[:8]}"
        )
        attempt_dir.mkdir(parents=True, exist_ok=False)
        pdf_path = attempt_dir / f"{run['trading_date']}_{run['slot']}_render.pdf"
        backend = "word_com"
        try:
            backend = canonical_word_qa._export_word(
                docx,
                pdf_path,
                trading_date=run["trading_date"],
                slot=run["slot"],
                docx_sha256=docx_record["sha256"],
                root=repo_root,
                timeout=export_timeout,
            )
            if backend not in ALLOWED_BACKENDS:
                raise RuntimeError(f"unsupported vNext Word export backend: {backend}")
            page_renderer = canonical_word_qa._find_pdftoppm(pdftoppm)
            pages = canonical_word_qa._render_pdf(
                pdf_path,
                attempt_dir / "page",
                page_renderer,
            )
            page_records = []
            for page_number, page in enumerate(pages, start=1):
                record = _artifact_record(repo_root, page)
                record["page"] = page_number
                page_records.append(record)
            pdf_record = _artifact_record(repo_root, pdf_path)
            payload: dict[str, Any] = {
                "schema_version": WORD_QA_SCHEMA,
                "status": "prepared",
                "visual_qa_pass": False,
                "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "trading_date": run["trading_date"],
                "slot": run["slot"],
                "run_id": run["run_id"],
                "run_sha256": run["run_sha256"],
                "attempts": attempt,
                "cache_hit": False,
                "backend": backend,
                "page_renderer": str(page_renderer),
                "report_sha256": report["sha256"],
                "docx": docx_record,
                "docx_sha256": docx_record["sha256"],
                "pdf": pdf_record,
                "pdf_sha256": pdf_record["sha256"],
                "page_count": len(page_records),
                "inspected_pages": [],
                "page_images": page_records,
                "review_checklist_version": WORD_QA_REVIEW_CHECKLIST_VERSION,
                "review_checklist": _review_checklist(passed=False),
            }
            if not _word_qa_contract_is_valid(
                repo_root,
                run_root,
                run,
                report,
                render_manifest,
                payload,
            ):
                raise ValueError(
                    "prepared Word QA output failed its run-local contract"
                )
            atomic_json_write(manifest_path, payload)
            return payload
        except Exception as exc:
            backend = getattr(exc, "backend", backend)
            failure = {
                "schema_version": WORD_QA_SCHEMA,
                "status": "failed",
                "visual_qa_pass": False,
                "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "trading_date": run["trading_date"],
                "slot": run["slot"],
                "run_id": run["run_id"],
                "run_sha256": run["run_sha256"],
                "attempts": attempt,
                "backend": backend,
                "report_sha256": report["sha256"],
                "docx": docx_record,
                "docx_sha256": docx_record["sha256"],
                "failure_reason": str(exc),
            }
            atomic_json_write(manifest_path, failure)
            if attempt >= MAX_DELIVERY_ATTEMPTS:
                raise _delivery_failure(
                    "delivery.word_qa_attempt_limit_reached",
                    "vNext Word export attempt limit reached (2)",
                    failure_class=FailureClass.MANUAL_REVIEW,
                    path="delivery_assets/word_qa.json",
                ) from exc
            raise _delivery_failure(
                "delivery.word_qa_export_failed",
                "vNext Word export failed before visual review",
                path="delivery_assets/word_qa.json",
            ) from exc


def approve_run_qa(
    repo_root: Path,
    run_root: Path,
    *,
    reviewer: str,
    confirm_visual_pass: bool = False,
) -> dict[str, Any]:
    if confirm_visual_pass is not True:
        raise ValueError("vNext Word QA approval requires confirm_visual_pass=True")
    if not reviewer.strip():
        raise ValueError("vNext Word QA reviewer is required")
    repo_root = Path(repo_root).resolve()
    run_root = Path(run_root).resolve()
    store = ArtifactStore(repo_root)
    with store.controller_lock(run_root):
        _, run, _, _, manifest_path, report = _run_context(repo_root, run_root)
        render_manifest = _load_object(
            run_root / "delivery_assets" / "render_manifest.json"
        )
        payload = _load_object(manifest_path)
        if not payload or payload.get("status") not in {"prepared", "passed"}:
            raise ValueError("vNext Word QA approval requires prepared page evidence")
        if not render_manifest or not _word_qa_contract_is_valid(
            repo_root,
            run_root,
            run,
            report,
            render_manifest,
            payload,
        ):
            raise _delivery_failure(
                "delivery.word_qa_contract_invalid",
                "run-local Word QA contract is invalid before approval",
                failure_class=FailureClass.MANUAL_REVIEW,
                path="delivery_assets/word_qa.json",
            )
        if payload.get("status") == "passed":
            return payload
        page_count = int(payload["page_count"])
        payload["status"] = "passed"
        payload["visual_qa_pass"] = True
        payload["inspected_pages"] = list(range(1, page_count + 1))
        payload["reviewer"] = reviewer.strip()
        payload["reviewed_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        payload["review_checklist_version"] = WORD_QA_REVIEW_CHECKLIST_VERSION
        payload["review_checklist"] = _review_checklist(passed=True)
        if not _word_qa_contract_is_valid(
            repo_root,
            run_root,
            run,
            report,
            render_manifest,
            payload,
        ):
            raise _delivery_failure(
                "delivery.word_qa_contract_invalid",
                "run-local Word QA contract is invalid after approval",
                failure_class=FailureClass.MANUAL_REVIEW,
                path="delivery_assets/word_qa.json",
            )
        atomic_json_write(manifest_path, payload)
        return payload


def reject_run_qa(repo_root: Path, run_root: Path, *, reason: str) -> dict[str, Any]:
    if len(reason.strip()) < 8:
        raise ValueError("vNext visual-QA rejection reason must be explicit")
    repo_root = Path(repo_root).resolve()
    run_root = Path(run_root).resolve()
    store = ArtifactStore(repo_root)
    with store.controller_lock(run_root):
        _, run, _, _, manifest_path, report = _run_context(repo_root, run_root)
        render_manifest = _load_object(
            run_root / "delivery_assets" / "render_manifest.json"
        )
        payload = _load_object(manifest_path)
        if not payload or payload.get("status") != "prepared":
            raise ValueError("only prepared vNext Word QA evidence can be rejected")
        if not render_manifest or not _word_qa_contract_is_valid(
            repo_root,
            run_root,
            run,
            report,
            render_manifest,
            payload,
        ):
            raise _delivery_failure(
                "delivery.word_qa_contract_invalid",
                "run-local Word QA contract is invalid before rejection",
                failure_class=FailureClass.MANUAL_REVIEW,
                path="delivery_assets/word_qa.json",
            )
        payload["status"] = "failed"
        payload["visual_qa_pass"] = False
        payload["failure_reason"] = reason.strip()
        payload["reviewed_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        if not _word_qa_contract_is_valid(
            repo_root,
            run_root,
            run,
            report,
            render_manifest,
            payload,
        ):
            raise _delivery_failure(
                "delivery.word_qa_contract_invalid",
                "run-local Word QA contract is invalid after rejection",
                failure_class=FailureClass.MANUAL_REVIEW,
                path="delivery_assets/word_qa.json",
            )
        atomic_json_write(manifest_path, payload)
        return payload
