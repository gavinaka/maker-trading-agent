"""Delivery-stage production validation owner."""

from __future__ import annotations

import json
import re
import struct
import zipfile
import zlib
from itertools import combinations
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from ..methodology import canonical_sha256, load_scoring_policy, sha256_file
from ..domain_ir.projection import (
    account_current_basis_projection,
    account_trigger_logic_projection,
)
from ..domain_ir.registry import (
    ACCOUNT_CURRENT_BASIS_POLICY_FIELDS,
    ACCOUNT_LOOP_CLAIM_TYPES,
    CANNOT_DO_CODES,
    CLAIM_ACCOUNT_SCOPES,
    CLAIM_TYPES as REQUIRED_CLAIM_TYPES,
    CONTINUITY_ACTIONS,
    CONTINUITY_PRIOR_STATUSES,
    EVIDENCE_SOURCE_ORDER as REQUIRED_SOURCES,
    HIGH_IMPACT_CLAIMS,
    MINIMUM_OBSERVATION_METRICS,
    NON_ACTION_REPORT_SECTIONS,
    NON_TRACEABLE_REPORT_SECTIONS,
    POLICY_SOURCE_KEYS,
    REPORT_SECTIONS as REQUIRED_REPORT_SECTIONS,
    SCENARIO_TYPES as REQUIRED_SCENARIO_TYPES,
    SECTION_REQUIRED_CLAIM_TYPES,
    SOURCE_ROLES,
    SOURCE_ROLE_CLAIM_OWNER,
    TRADINGVIEW_TIMEFRAMES,
    TRIGGER_CONTROL_CLAIM_TYPES,
    TRIGGER_EFFECT_BY_CLAIM_TYPE,
)
from ..plan_semantics import (
    assess_candidate,
    assess_order_lifecycle,
    classify_evidence_polarity,
    classify_maker_semantic_state,
    cannot_do_conflicts,
    expected_reach_direction,
    resting_maker_order_valid,
    structural_noise_stop_is_outside,
    structure_zone_role_valid,
)
from ..pretrade_gate import validate_pretrade_gate_contract
from ..rate_expectation import (
    RateExpectationError,
    canonical_json_sha256 as rate_canonical_sha256,
    normalize_kalshi_payload,
    validate_cme_result,
    validate_rate_provenance,
)
from ..reasoning_pipeline import validate_reasoning_pipeline
from ..reasoning_submission import (
    derive_methodology_trigger_claim_ids,
    load_reasoning_submission_contract,
)
from ..delivery_renderer import (
    ALLOWED_BACKENDS as WORD_QA_ALLOWED_BACKENDS,
    PASSED_WORD_QA_FIELDS,
    WORD_QA_SCHEMA,
    passed_word_qa_checklist_is_valid,
    passed_word_qa_run_paths_are_valid,
)
from outputs.report_lint import coupling_check

from .common import (
    Defect, GateResult, _canonical_closed_string,
    _canonical_positive_decimal_string, _contains_cjk, _decimal_matches,
    _json_number, _matches_policy_path, _nested_value, _number,
    _parse_iso_datetime, _reachable_trigger_owners, _record_paths,
    _resolve_concrete_value_path, _round_to_step, _text,
    _typed_domain_contains, _typed_domain_intersection,
    _valid_png_dimensions, _validate_file_record, gate_result as _result,
    maker_fill_scenarios,
)

def _load_delivery_manifest(record: Any, *, root: Path) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {}
    try:
        target = (root / str(record.get("path", ""))).resolve()
        target.relative_to(root.resolve())
        value = json.loads(target.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
        return {}

def _evaluate_local_delivery_artifacts(
    payload: dict[str, Any],
    *,
    root: Path,
    run: dict[str, Any],
    expected_report: dict[str, Any] | None,
    expected_cards: dict[str, dict[str, Any]] | None,
) -> tuple[list[Defect], dict[str, Any], list[Any], str]:
    defects: list[Defect] = []
    render = payload.get("render") if isinstance(payload.get("render"), dict) else {}
    cards = payload.get("cards") if isinstance(payload.get("cards"), dict) else {}
    records = {
        "report": payload.get("report"),
        "docx": render.get("docx"),
        "pdf": render.get("pdf"),
        "word_qa": render.get("word_qa"),
        "cards_spec": cards.get("spec"),
    }
    for name, record in records.items():
        if not isinstance(record, dict):
            defects.append(Defect("delivery.artifact_missing", f"delivery artifact missing: {name}", name))
            continue
        _validate_file_record(record, path=name, defects=defects, root=root)

    card_images = cards.get("images")
    if not isinstance(card_images, list) or len(card_images) != 3:
        defects.append(Defect("delivery.cards_missing", "delivery requires exactly three BlockBeats card images", "cards.images"))
        card_images = []
    for index, record in enumerate(card_images, start=1):
        if not isinstance(record, dict):
            defects.append(Defect("delivery.card_invalid", "BlockBeats card record must be an object", f"cards.images[{index - 1}]"))
            continue
        _validate_file_record(record, path=f"cards.images[{index - 1}]", defects=defects, root=root)

    def artifact_path(name: str) -> Path | None:
        record = records.get(name)
        if not isinstance(record, dict):
            return None
        try:
            target = (root / str(record.get("path", ""))).resolve()
            target.relative_to(root.resolve())
            return target if target.is_file() else None
        except (ValueError, OSError):
            return None

    docx_path = artifact_path("docx")
    if docx_path is not None:
        try:
            with zipfile.ZipFile(docx_path) as archive:
                names = set(archive.namelist())
                content_types = ElementTree.fromstring(archive.read("[Content_Types].xml"))
                relationships = ElementTree.fromstring(archive.read("_rels/.rels"))
                document = ElementTree.fromstring(archive.read("word/document.xml"))
            if not {"[Content_Types].xml", "_rels/.rels", "word/document.xml"} <= names:
                raise ValueError("required DOCX parts missing")
            if not content_types.tag.endswith("Types") or not relationships.tag.endswith("Relationships") or not document.tag.endswith("document"):
                raise ValueError("required DOCX XML roots are invalid")
        except (KeyError, ValueError, zipfile.BadZipFile, OSError, ElementTree.ParseError):
            defects.append(Defect("delivery.docx_invalid", "DOCX artifact is not a valid Word package", "render.docx"))
    pdf_path = artifact_path("pdf")
    if pdf_path is not None:
        data = pdf_path.read_bytes()
        page_objects = len(re.findall(rb"/Type\s*/Page\b", data))
        if (
            not data.startswith(b"%PDF-")
            or b"startxref" not in data[-4096:]
            or b"%%EOF" not in data[-1024:]
            or page_objects <= 0
        ):
            defects.append(Defect("delivery.pdf_invalid", "PDF artifact has an invalid signature", "render.pdf"))
    report_hash = _text((records.get("report") or {}).get("sha256"))
    if expected_report is not None and records.get("report") != expected_report:
        defects.append(Defect("delivery.report_record_drift", "delivery report record differs from the certified report stage", "report"))
    if expected_cards is not None:
        if records.get("cards_spec") != expected_cards.get("cards_spec"):
            defects.append(Defect("delivery.cards_spec_drift", "delivery card spec differs from the certified report stage", "cards.spec"))
        expected_image_records = [expected_cards.get(f"card_{index}") for index in range(1, 4)]
        if card_images != expected_image_records:
            defects.append(Defect("delivery.cards_drift", "delivery card images differ from the certified report stage", "cards.images"))

    word = _load_delivery_manifest(records.get("word_qa"), root=root)
    if set(word) != set(PASSED_WORD_QA_FIELDS):
        defects.append(
            Defect(
                "delivery.word_schema",
                "passed Word QA must use the exact v2 field set",
                "render.word_qa",
            )
        )
    if (
        word.get("schema_version") != WORD_QA_SCHEMA
        or word.get("status") != "passed"
        or word.get("visual_qa_pass") is not True
        or word.get("report_sha256") != report_hash
        or word.get("docx") != records.get("docx")
        or word.get("pdf") != records.get("pdf")
        or word.get("docx_sha256") != _text((records.get("docx") or {}).get("sha256"))
        or word.get("pdf_sha256") != _text((records.get("pdf") or {}).get("sha256"))
    ):
        defects.append(Defect("delivery.word_manifest", "Word QA manifest is invalid or not hash-bound", "render.word_qa"))
    if not passed_word_qa_checklist_is_valid(word):
        defects.append(
            Defect(
                "delivery.word_review_checklist",
                "passed Word QA must carry the exact semantic review checklist with every item confirmed",
                "render.word_qa.review_checklist",
            )
        )
    if (
        run.get("schema_version") != "daily-run-vnext-v2"
        or word.get("run_id") != run.get("run_id")
        or word.get("run_sha256") != run.get("run_sha256")
        or word.get("trading_date") != run.get("trading_date")
        or word.get("slot") != run.get("slot")
    ):
        defects.append(
            Defect(
                "delivery.word_identity",
                "Word QA must bind the current v2 run id/hash/date/slot",
                "render.word_qa",
            )
        )
    if not passed_word_qa_run_paths_are_valid(root, run, word):
        defects.append(
            Defect(
                "delivery.word_run_locality",
                "Word QA DOCX, PDF, and page evidence must belong to the current run and exact attempt",
                "render.word_qa",
            )
        )
    if word.get("backend") not in WORD_QA_ALLOWED_BACKENDS:
        defects.append(
            Defect(
                "delivery.word_backend",
                "Word QA backend is outside the approved Microsoft Word backends",
                "render.word_qa.backend",
            )
        )
    created_at = _parse_iso_datetime(word.get("created_at"))
    reviewed_at = _parse_iso_datetime(word.get("reviewed_at"))
    if (
        not _text(word.get("reviewer"))
        or reviewed_at is None
        or created_at is None
        or (reviewed_at is not None and created_at is not None and reviewed_at < created_at)
    ):
        defects.append(
            Defect(
                "delivery.word_review",
                "Word QA requires a named reviewer and timezone-aware review after export",
                "render.word_qa",
            )
        )
    if (
        not isinstance(word.get("attempts"), int)
        or isinstance(word.get("attempts"), bool)
        or word.get("attempts") <= 0
        or type(word.get("cache_hit")) is not bool
        or not _text(word.get("page_renderer"))
    ):
        defects.append(
            Defect(
                "delivery.word_metadata",
                "Word QA export metadata is incomplete or invalid",
                "render.word_qa",
            )
        )
    page_count = word.get("page_count")
    inspected = word.get("inspected_pages")
    page_images = word.get("page_images")
    if (
        not isinstance(page_count, int)
        or page_count <= 0
        or not isinstance(inspected, list)
        or inspected != list(range(1, page_count + 1))
        or not isinstance(page_images, list)
        or len(page_images) != page_count
    ):
        defects.append(Defect("delivery.word_pages", "every rendered page must have inspected image evidence", "render.word_qa"))
    elif isinstance(page_images, list):
        page_paths: list[str] = []
        for index, record in enumerate(page_images):
            if isinstance(record, dict):
                _validate_file_record(record, path=f"render.word_qa.page_images[{index}]", defects=defects, root=root)
                try:
                    image_path = (root / str(record.get("path", ""))).resolve()
                    image_path.relative_to(root.resolve())
                    width, height = _valid_png_dimensions(image_path)
                    if width <= 0 or height <= 0:
                        raise ValueError("invalid PNG")
                    if record.get("page") != index + 1:
                        raise ValueError("page index mismatch")
                    page_paths.append(str(image_path).casefold())
                except (FileNotFoundError, OSError, ValueError, struct.error):
                    defects.append(Defect("delivery.page_image_format", "page image is not a valid PNG", f"render.word_qa.page_images[{index}]"))
            else:
                defects.append(Defect("delivery.page_image_invalid", "page image record must be an object", f"render.word_qa.page_images[{index}]"))
        if len(page_paths) != len(set(page_paths)):
            defects.append(Defect("delivery.page_image_duplicate", "each rendered page must have a unique PNG artifact", "render.word_qa.page_images"))

    card_paths: list[str] = []
    for index, record in enumerate(card_images):
        if not isinstance(record, dict):
            continue
        try:
            card_path = (root / str(record.get("path", ""))).resolve()
            card_path.relative_to(root.resolve())
            _valid_png_dimensions(card_path)
            card_paths.append(str(card_path).casefold())
        except (FileNotFoundError, OSError, ValueError, struct.error):
            defects.append(Defect("delivery.card_format", "BlockBeats card is not a complete PNG", f"cards.images[{index}]"))
    if len(card_paths) != len(set(card_paths)):
        defects.append(Defect("delivery.card_duplicate", "BlockBeats card images must be unique", "cards.images"))

    return defects, records, card_images, report_hash

def evaluate_shadow_delivery(
    payload: dict[str, Any],
    *,
    root: Path,
    run: dict[str, Any],
    expected_report: dict[str, Any] | None = None,
    expected_cards: dict[str, dict[str, Any]] | None = None,
) -> GateResult:
    defects, records, card_images, report_hash = _evaluate_local_delivery_artifacts(
        payload,
        root=root,
        run=run,
        expected_report=expected_report,
        expected_cards=expected_cards,
    )
    if payload.get("schema_version") != "shadow-delivery-model-v1":
        defects.append(
            Defect("schema.invalid", "expected shadow-delivery-model-v1", "schema_version")
        )
    allowed_top_level = {"schema_version", "report", "render", "cards", "publish"}
    for key in sorted(set(payload) - allowed_top_level):
        defects.append(
            Defect(
                "delivery.shadow_field_unexpected",
                f"shadow delivery contains an unexpected top-level field: {key}",
                key,
            )
        )
    publish = payload.get("publish")
    if not isinstance(publish, dict):
        defects.append(
            Defect(
                "delivery.shadow_publish_boundary",
                "shadow delivery must explicitly record that Notion publishing was not attempted",
                "publish",
            )
        )
        publish = {}
    if publish.get("status") != "not_attempted":
        defects.append(
            Defect(
                "delivery.shadow_publish_boundary",
                "shadow delivery publish status must be not_attempted",
                "publish.status",
            )
        )
    if publish.get("reason") != "shadow_mode_forbids_notion":
        defects.append(
            Defect(
                "delivery.shadow_publish_boundary",
                "shadow delivery must use the governance reason shadow_mode_forbids_notion",
                "publish.reason",
            )
        )
    forbidden_publish_fields = sorted(set(publish) - {"status", "reason"})
    for key in forbidden_publish_fields:
        defects.append(
            Defect(
                "delivery.shadow_publish_claim",
                f"shadow delivery must not contain Notion publish evidence or claims: {key}",
                f"publish.{key}",
            )
        )
    return _result(
        "shadow_delivery_integrity",
        defects,
        report_sha256=report_hash,
        artifact_count=(
            sum(isinstance(value, dict) for value in records.values())
            + sum(isinstance(value, dict) for value in card_images)
        ),
        completion_mode="shadow",
        notion_published=False,
    )

def evaluate_delivery(
    payload: dict[str, Any],
    *,
    root: Path,
    run: dict[str, Any],
    expected_report: dict[str, Any] | None = None,
    expected_cards: dict[str, dict[str, Any]] | None = None,
) -> GateResult:
    defects, records, card_images, report_hash = _evaluate_local_delivery_artifacts(
        payload,
        root=root,
        run=run,
        expected_report=expected_report,
        expected_cards=expected_cards,
    )
    if payload.get("schema_version") != "delivery-model-v1":
        defects.append(Defect("schema.invalid", "expected delivery-model-v1", "schema_version"))
    publish_section = (
        payload.get("publish") if isinstance(payload.get("publish"), dict) else {}
    )
    publish_records = {
        "publish": publish_section.get("manifest"),
        "notion_verify": publish_section.get("verification"),
    }
    for name, record in publish_records.items():
        if not isinstance(record, dict):
            defects.append(Defect("delivery.artifact_missing", f"delivery artifact missing: {name}", name))
            continue
        _validate_file_record(record, path=name, defects=defects, root=root)

    publish = _load_delivery_manifest(publish_records.get("publish"), root=root)
    required_publish = {
        "schema_version": "publish-vnext-v1",
        "status": "passed",
        "structure_pass": True,
        "visual_contract_pass": True,
        "unique_page_count": 1,
        "report_sha256": report_hash,
        "cards_spec_sha256": _text((records.get("cards_spec") or {}).get("sha256")),
        "card_sha256s": [
            _text(record.get("sha256"))
            for record in card_images
            if isinstance(record, dict)
        ],
    }
    for key, value in required_publish.items():
        if publish.get(key) != value:
            defects.append(Defect("delivery.publish_manifest", f"publish manifest {key} must be {value!r}", "publish.manifest"))
    page_id = _text(publish.get("page_id"))
    if not re.fullmatch(r"(?:[0-9a-f]{32}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})", page_id, re.IGNORECASE):
        defects.append(Defect("delivery.page_id_missing", "published page id must be a Notion UUID", "publish.manifest"))
    if not re.fullmatch(r"[0-9a-f]{64}", _text(publish.get("children_signature_sha256"))):
        defects.append(Defect("delivery.children_signature", "Notion children signature is invalid", "publish.manifest"))
    published_at = _parse_iso_datetime(publish.get("published_at"))
    if published_at is None:
        defects.append(Defect("delivery.publish_time", "publish manifest requires a timezone-aware published_at", "publish.manifest"))
    verification = _load_delivery_manifest(publish_records.get("notion_verify"), root=root)
    required_verification = {
        "schema_version": "notion-verification-vnext-v1",
        "status": "passed",
        "structure_pass": True,
        "visual_contract_pass": True,
        "unique_page_count": 1,
        "report_sha256": report_hash,
        "page_id": page_id,
        "children_signature_sha256": publish.get("children_signature_sha256"),
        "cards_spec_sha256": publish.get("cards_spec_sha256"),
        "card_sha256s": publish.get("card_sha256s"),
    }
    for key, value in required_verification.items():
        if verification.get(key) != value:
            defects.append(Defect("delivery.notion_verification", f"Notion verification {key} must match the published artifact", "publish.verification"))
    readback_at = _parse_iso_datetime(verification.get("readback_at"))
    if readback_at is None:
        defects.append(Defect("delivery.notion_readback_time", "Notion verification requires a timezone-aware readback_at", "publish.verification"))
    elif published_at is not None and readback_at < published_at:
        defects.append(Defect("delivery.notion_readback_order", "Notion readback must occur after publish", "publish.verification"))
    return _result(
        "delivery_integrity",
        defects,
        report_sha256=report_hash,
        artifact_count=(
            sum(isinstance(value, dict) for value in records.values())
            + sum(isinstance(value, dict) for value in publish_records.values())
        ),
        page_id=_text(publish.get("page_id")),
    )

__all__ = ["evaluate_delivery", "evaluate_shadow_delivery"]
