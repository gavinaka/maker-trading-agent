"""Versioned methodology manifest without runtime document concatenation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from runtime.golden_methodology import get_methodology_runtime_inventory

from .domain_ir.projection import (
    deterministic_projection_drift,
    report_presentation_projection_drift,
    scoring_projection_drift,
)
from .domain_ir.registry import REGISTRY, DomainRegistry
from .domain_ir.types import canonical_json_bytes
from .reasoning_submission import (
    load_reasoning_submission_contract,
    validate_contract_runtime_compatibility,
)


ROOT = Path(__file__).resolve().parents[1]
REPORT_PRESENTATION_CONTRACT_PATH = Path(
    "governance/vnext_report_presentation_contract.json"
)

PHASE_FILES: dict[str, tuple[str, ...]] = {
    "evidence": (
        "data_sources/required_sources.md",
        "data_sources/source_rules.md",
        "data_sources/freshness_rules.md",
        "data_sources/blockbeats_rules.md",
        "data_sources/collectors/blockbeats.md",
        "data_sources/collectors/coinglass.md",
        "data_sources/collectors/exocharts.md",
        "data_sources/collectors/farside_btc_etf.md",
        "data_sources/collectors/fedwatch.md",
        "data_sources/rate_expectation_provider_contract.json",
        "data_sources/collectors/tradingview.md",
        "scoring/scoring_contract.json",
    ),
    "reasoning": (
        "constitution/trading_constitution.md",
        "constitution/cannot_do_mapping.md",
        "constitution/maker_principles.md",
        "execution/main_account.md",
        "execution/maker_execution.md",
        "execution/entry_models.md",
        "scoring/reasoning_submission_contract.json",
        "scoring/golden_report_reasoning_alignment.md",
        "scoring/scoring_contract.json",
        "scoring/orderflow_methodology.md",
        "scoring/orderflow_scoring.md",
        "scoring/chart_methodology.md",
        "scoring/chart_scoring.md",
        "scoring/reasoning_depth_checklist.md",
        "scoring/score_thresholds.md",
        "scoring/winrate_methodology.md",
        "risk/risk_checklist.md",
        "risk/entry_exit_rules.md",
        "risk/floating_defense.md",
    ),
    "report": (
        "governance/vnext_golden_sample_contract.json",
        "governance/vnext_report_presentation_contract.json",
        "governance/vnext_report_language_contract.md",
    ),
}

# Exact phase inventory remains the run-time authority boundary.  Evidence and
# reasoning are wholly semantic; report is intentionally mixed because its
# golden/language contracts govern report meaning while the generated
# presentation contract governs display only.
PHASE_AUTHORITY_CLASS: dict[str, str] = {
    "evidence": "semantic",
    "reasoning": "semantic",
    "report": "mixed",
}
PHASE_SEMANTIC_FILES: dict[str, tuple[str, ...]] = {
    "evidence": PHASE_FILES["evidence"],
    "reasoning": PHASE_FILES["reasoning"],
    "report": (
        "governance/vnext_golden_sample_contract.json",
        "governance/vnext_report_language_contract.md",
    ),
}

EXPLICIT_CONTROL_PLANE_FILES: tuple[str, ...] = (
    "AGENTS.md",
    ".agents/skills/daily-report/SKILL.md",
    "governance/vnext_daily_workflow.md",
    "governance/vnext_sample_outcome_contract.json",
    "runtime/golden_methodology.py",
    "runtime/host_capability.py",
    "tools/browser_capture/capture_all.js",
    "tools/browser_capture/capture_delta.js",
    "tools/browser_capture/capture_blockbeats.js",
    "tools/browser_capture/blockbeats_priority.js",
    "tools/browser_capture/capture_coinglass.js",
    "tools/browser_capture/capture_exo.js",
    "tools/browser_capture/exocharts_ui_state.js",
    "tools/browser_capture/capture_farside_btc_etf.js",
    "tools/browser_capture/capture_fedwatch.js",
    "tools/browser_capture/capture_kalshi_feddecision.js",
    "tools/browser_capture/capture_rate_expectation.js",
    "tools/browser_capture/capture_liqheatmap.js",
    "tools/browser_capture/capture_lock.js",
    "tools/browser_capture/capture_tv.js",
    "tools/browser_capture/rate_expectation_state.js",
    "tools/browser_capture/tradingview_profile_state.js",
    "tools/browser_capture/cleanup.js",
    "tools/browser_capture/farside_row_policy.js",
    "tools/browser_capture/package.json",
    "tools/browser_capture/package-lock.json",
    "schemas/capture_run_manifest_schema.json",
    "outputs/daily_publish_contract.py",
    "outputs/daily_payload_builder.py",
    "outputs/blockbeats_card.py",
    "outputs/report_structure_gate.py",
    "outputs/report_lint.py",
    "outputs/word_qa.py",
    "outputs/render_from_combined.py",
)


def discover_control_plane_files(*, root: Path = ROOT) -> tuple[str, ...]:
    """Return the exact release inventory without hand-listing package modules."""

    root = root.resolve()
    runtime_root = (root / "runtime_vnext").resolve()
    try:
        runtime_root.relative_to(root)
    except ValueError as exc:
        raise ValueError("runtime_vnext control-plane root escapes repository") from exc
    if not runtime_root.is_dir():
        raise ValueError("runtime_vnext control-plane root is missing")

    discovered: set[str] = set(EXPLICIT_CONTROL_PLANE_FILES)
    for candidate in runtime_root.rglob("*.py"):
        resolved = candidate.resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                f"runtime_vnext control-plane file escapes repository: {candidate}"
            ) from exc
        if not resolved.is_file():
            continue
        discovered.add(relative.as_posix())
    return tuple(sorted(discovered))


# Compatibility import surface for tests and tools that inspect the current
# release inventory.  Manifest construction calls discovery again against its
# supplied root, so an added package module cannot be hidden by import timing.
CONTROL_PLANE_FILES: tuple[str, ...] = discover_control_plane_files(root=ROOT)

# Exact runtime files that can change business interpretation, validation,
# decision certification or clean-sample classification.  They are also part
# of the release inventory; this subset additionally closes semantic identity.
# Pure display projection in report_compiler.py is deliberately release-only.
SEMANTIC_RUNTIME_FILES: tuple[str, ...] = (
    "outputs/report_lint.py",
    "outputs/report_structure_gate.py",
    "runtime/golden_methodology.py",
    "runtime_vnext/artifacts.py",
    "runtime_vnext/controller.py",
    "runtime_vnext/delivery_renderer.py",
    "runtime_vnext/domain_ir/__init__.py",
    "runtime_vnext/domain_ir/projection.py",
    "runtime_vnext/domain_ir/types.py",
    "runtime_vnext/effort_policy.py",
    "runtime_vnext/errors.py",
    "runtime_vnext/gates.py",
    "runtime_vnext/golden_samples.py",
    "runtime_vnext/legacy_capture_adapter.py",
    "runtime_vnext/methodology.py",
    "runtime_vnext/plan_semantics.py",
    "runtime_vnext/pretrade_gate.py",
    "runtime_vnext/rate_expectation.py",
    "runtime_vnext/reasoning_pipeline.py",
    "runtime_vnext/reasoning_submission.py",
    "runtime_vnext/sample_outcome.py",
    "runtime_vnext/validation/__init__.py",
    "runtime_vnext/validation/common.py",
    "runtime_vnext/validation/decision.py",
    "runtime_vnext/validation/delivery.py",
    "runtime_vnext/validation/evidence.py",
    "runtime_vnext/validation/reasoning.py",
    "runtime_vnext/validation/report.py",
)

ADDITIVE_METHOD_MARKERS = {
    "scoring/chart_methodology.md": ("VRVP", "流动性猎杀"),
    "scoring/scoring_contract.json": ("liquidation", "etf"),
}

MANIFEST_V2_SCHEMA = "methodology-manifest-v2"
MANIFEST_V3_SCHEMA = "methodology-manifest-v3"
SEMANTIC_CONTRACT_SCHEMA = "vnext-semantic-contract-v2"
RELEASE_IDENTITY_SCHEMA = "vnext-runtime-release-v2"
MANIFEST_V3_POLICY = "phase-runtime-scoped-semantic-plus-release-authority-v2"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class MethodologyIdentity:
    manifest_schema_version: str
    semantic_contract_sha256: str | None
    release_sha256: str | None
    manifest_sha256: str
    legacy_combined_identity: bool


LEGACY_RUN_AUTHORITY_FIELD = "methodology_sha256"
V3_RUN_AUTHORITY_FIELDS = (
    "semantic_contract_sha256",
    "release_sha256",
    "methodology_manifest_sha256",
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_sha256(payload: dict[str, Any]) -> str:
    clean = dict(payload)
    clean.pop("manifest_sha256", None)
    return sha256_bytes(
        json.dumps(
            clean,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _semantic_file_record(path: Path, relative: str) -> dict[str, str]:
    if path.suffix.lower() == ".json":
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"semantic JSON authority is invalid: {relative}") from exc
        digest = sha256_bytes(canonical_json_bytes(value))
        normalization = "canonical-json-v1"
    else:
        digest = sha256_file(path)
        normalization = "exact-utf8-bytes-v1"
    return {
        "path": relative,
        "normalization": normalization,
        "semantic_sha256": digest,
    }


def _semantic_contract_sha256(
    domain_registry_sha256: str,
    phases: Mapping[str, Mapping[str, Any]],
    semantic_runtime_sha256: str,
) -> str:
    return canonical_sha256(
        {
            "schema_version": SEMANTIC_CONTRACT_SCHEMA,
            "domain_registry_sha256": domain_registry_sha256,
            "phase_semantic_sha256": {
                phase: value["semantic_phase_sha256"]
                for phase, value in sorted(phases.items())
            },
            "semantic_runtime_sha256": semantic_runtime_sha256,
        }
    )


def _release_sha256(
    control_sha256: str,
    phases: Mapping[str, Mapping[str, Any]],
) -> str:
    """Bind executable code plus exact presentation authority to one release."""

    return canonical_sha256(
        {
            "schema_version": RELEASE_IDENTITY_SCHEMA,
            "control_sha256": control_sha256,
            "presentation_phase_sha256": {
                phase: value["phase_sha256"]
                for phase, value in sorted(phases.items())
                if PHASE_AUTHORITY_CLASS[phase] != "semantic"
            },
        }
    )


def build_methodology_manifest(
    *,
    root: Path = ROOT,
    registry: DomainRegistry = REGISTRY,
) -> dict[str, Any]:
    root = root.resolve()
    phases: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    marker_failures: list[str] = []
    for phase, relatives in PHASE_FILES.items():
        semantic_relatives = set(PHASE_SEMANTIC_FILES[phase])
        records: list[dict[str, Any]] = []
        semantic_records: list[dict[str, str]] = []
        for relative in relatives:
            path = (root / relative).resolve()
            path.relative_to(root)
            if not path.is_file():
                missing.append(relative)
                continue
            text = path.read_text(encoding="utf-8")
            for marker in ADDITIVE_METHOD_MARKERS.get(relative, ()):
                if marker.lower() not in text.lower():
                    marker_failures.append(f"{relative}:{marker}")
            records.append(
                {
                    "path": relative,
                    "sha256": sha256_file(path),
                    "bytes": path.stat().st_size,
                }
            )
            if relative in semantic_relatives:
                semantic_records.append(_semantic_file_record(path, relative))
        phase_payload = {
            "files": records,
            "semantic_files": semantic_records,
        }
        phase_payload["phase_sha256"] = canonical_sha256({"files": records})
        phase_payload["semantic_phase_sha256"] = canonical_sha256(
            {"files": semantic_records}
        )
        phases[phase] = phase_payload
    if missing:
        raise ValueError("methodology files missing: " + ", ".join(sorted(missing)))
    if marker_failures:
        raise ValueError(
            "additive methodology markers missing: "
            + ", ".join(sorted(marker_failures))
        )
    full_policy = load_scoring_policy(root=root)
    if scoring_projection_drift(full_policy):
        raise ValueError(
            "scoring contract deterministic views differ from the domain registry"
        )
    submission_contract = load_reasoning_submission_contract(root=root)
    methodology_inventory = get_methodology_runtime_inventory(
        policy=full_policy["gold_methodology"],
        profile="vnext_submission",
    )
    if deterministic_projection_drift(
        submission_contract,
        methodology_leaf_ownership=methodology_inventory["leaf_ownership"],
    ):
        raise ValueError(
            "reasoning submission contract deterministic views differ from "
            "the domain registry"
        )
    report_presentation_contract = json.loads(
        (root / REPORT_PRESENTATION_CONTRACT_PATH).read_text(encoding="utf-8")
    )
    if report_presentation_projection_drift(report_presentation_contract):
        raise ValueError(
            "report presentation contract deterministic views differ from "
            "the domain registry"
        )
    contract_issues = validate_contract_runtime_compatibility(
        submission_contract,
        full_policy=full_policy,
    )
    if contract_issues:
        raise ValueError(
            "reasoning submission contract is incompatible: "
            + "; ".join(
                f"{item.code}@{item.path}:{item.message}"
                for item in contract_issues
            )
        )
    control_records: list[dict[str, Any]] = []
    for relative in discover_control_plane_files(root=root):
        path = (root / relative).resolve()
        path.relative_to(root)
        if not path.is_file():
            raise ValueError(f"control-plane file missing: {relative}")
        control_records.append(
            {
                "path": relative,
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
    control_plane: dict[str, Any] = {"files": control_records}
    control_plane["control_sha256"] = canonical_sha256(control_plane)
    semantic_runtime_records: list[dict[str, str]] = []
    for relative in SEMANTIC_RUNTIME_FILES:
        path = (root / relative).resolve()
        path.relative_to(root)
        if not path.is_file():
            raise ValueError(f"semantic runtime file missing: {relative}")
        semantic_runtime_records.append(_semantic_file_record(path, relative))
    semantic_runtime: dict[str, Any] = {"files": semantic_runtime_records}
    semantic_runtime["semantic_runtime_sha256"] = canonical_sha256(
        semantic_runtime
    )
    domain_registry_sha256 = registry.semantic_contract_sha256
    payload: dict[str, Any] = {
        "schema_version": MANIFEST_V3_SCHEMA,
        "policy": MANIFEST_V3_POLICY,
        "domain_registry_sha256": domain_registry_sha256,
        "phases": phases,
        "control_plane": control_plane,
        "semantic_runtime": semantic_runtime,
        "semantic_contract_sha256": _semantic_contract_sha256(
            domain_registry_sha256,
            phases,
            semantic_runtime["semantic_runtime_sha256"],
        ),
        "release_sha256": _release_sha256(
            control_plane["control_sha256"],
            phases,
        ),
    }
    payload["manifest_sha256"] = canonical_sha256(payload)
    validate_methodology_manifest(payload)
    return payload


def _validate_file_records(
    records: object,
    *,
    semantic: bool,
    label: str,
    allow_empty: bool = False,
) -> list[str]:
    if not isinstance(records, list) or (not records and not allow_empty):
        raise ValueError(f"{label} file inventory is missing")
    paths: list[str] = []
    expected_fields = (
        {"path", "normalization", "semantic_sha256"}
        if semantic
        else {"path", "sha256", "bytes"}
    )
    for record in records:
        if not isinstance(record, dict) or set(record) != expected_fields:
            raise ValueError(f"{label} file record shape is invalid")
        relative = record.get("path")
        if (
            not isinstance(relative, str)
            or not relative
            or "\\" in relative
            or relative.startswith("/")
            or ".." in Path(relative).parts
        ):
            raise ValueError(f"{label} file path is invalid")
        if semantic:
            expected_normalization = (
                "canonical-json-v1"
                if Path(relative).suffix.lower() == ".json"
                else "exact-utf8-bytes-v1"
            )
            if (
                record.get("normalization") != expected_normalization
                or not SHA256_RE.fullmatch(
                    str(record.get("semantic_sha256", ""))
                )
            ):
                raise ValueError(f"{label} semantic file record is invalid")
        elif (
            not SHA256_RE.fullmatch(str(record.get("sha256", "")))
            or not isinstance(record.get("bytes"), int)
            or isinstance(record.get("bytes"), bool)
            or record["bytes"] < 0
        ):
            raise ValueError(f"{label} exact file record is invalid")
        paths.append(relative)
    if len(paths) != len(set(paths)):
        raise ValueError(f"{label} file inventory contains duplicate paths")
    return paths


def validate_methodology_manifest(
    payload: Mapping[str, Any],
) -> MethodologyIdentity:
    """Validate a sealed v3 identity or an immutable legacy v2 envelope.

    The v2 branch deliberately does not invent semantic/release identities.  It
    verifies the historical combined seal and any inner hashes that are present,
    allowing old terminal runs to remain readable without being upgraded.
    """

    if not isinstance(payload, Mapping):
        raise ValueError("methodology manifest must be an object")
    manifest = dict(payload)
    manifest_sha256 = manifest.get("manifest_sha256")
    if (
        not isinstance(manifest_sha256, str)
        or not SHA256_RE.fullmatch(manifest_sha256)
        or manifest_sha256 != canonical_sha256(manifest)
    ):
        raise ValueError("methodology manifest hash is invalid")

    schema_version = manifest.get("schema_version")
    if schema_version == MANIFEST_V2_SCHEMA:
        phases = manifest.get("phases")
        if isinstance(phases, dict):
            for phase, value in phases.items():
                if not isinstance(phase, str) or not isinstance(value, dict):
                    raise ValueError("legacy methodology phase is invalid")
                if "phase_sha256" in value and value.get(
                    "phase_sha256"
                ) != canonical_sha256({"files": value.get("files")}):
                    raise ValueError("legacy methodology phase hash is invalid")
        control_plane = manifest.get("control_plane")
        if isinstance(control_plane, dict) and "control_sha256" in control_plane:
            if control_plane.get("control_sha256") != canonical_sha256(
                {"files": control_plane.get("files")}
            ):
                raise ValueError("legacy methodology control hash is invalid")
        return MethodologyIdentity(
            manifest_schema_version=MANIFEST_V2_SCHEMA,
            semantic_contract_sha256=None,
            release_sha256=None,
            manifest_sha256=manifest_sha256,
            legacy_combined_identity=True,
        )

    if schema_version != MANIFEST_V3_SCHEMA:
        raise ValueError("methodology manifest schema is unsupported")
    expected_top = {
        "schema_version",
        "policy",
        "domain_registry_sha256",
        "phases",
        "control_plane",
        "semantic_runtime",
        "semantic_contract_sha256",
        "release_sha256",
        "manifest_sha256",
    }
    if set(manifest) != expected_top or manifest.get("policy") != MANIFEST_V3_POLICY:
        raise ValueError("methodology manifest v3 shape or policy is invalid")
    domain_registry_sha256 = manifest.get("domain_registry_sha256")
    semantic_contract_sha256 = manifest.get("semantic_contract_sha256")
    release_sha256 = manifest.get("release_sha256")
    if any(
        not isinstance(value, str) or not SHA256_RE.fullmatch(value)
        for value in (
            domain_registry_sha256,
            semantic_contract_sha256,
            release_sha256,
        )
    ):
        raise ValueError("methodology manifest v3 identities are invalid")

    phases = manifest.get("phases")
    if (
        not isinstance(phases, dict)
        or set(phases) != set(PHASE_FILES)
        or set(PHASE_AUTHORITY_CLASS) != set(PHASE_FILES)
        or set(PHASE_SEMANTIC_FILES) != set(PHASE_FILES)
    ):
        raise ValueError("methodology manifest v3 phase inventory is invalid")
    for phase, value in phases.items():
        if not isinstance(value, dict) or set(value) != {
            "files",
            "semantic_files",
            "phase_sha256",
            "semantic_phase_sha256",
        }:
            raise ValueError(f"methodology manifest v3 phase is invalid: {phase}")
        exact_paths = _validate_file_records(
            value.get("files"), semantic=False, label=f"phase {phase}"
        )
        semantic_paths = _validate_file_records(
            value.get("semantic_files"),
            semantic=True,
            label=f"phase {phase}",
            allow_empty=not PHASE_SEMANTIC_FILES[phase],
        )
        expected_semantic_paths = list(PHASE_SEMANTIC_FILES[phase])
        if semantic_paths != expected_semantic_paths:
            raise ValueError(
                f"methodology phase semantic ownership differs: {phase}"
            )
        if value.get("phase_sha256") != canonical_sha256(
            {"files": value["files"]}
        ):
            raise ValueError(f"methodology exact phase hash is invalid: {phase}")
        if value.get("semantic_phase_sha256") != canonical_sha256(
            {"files": value["semantic_files"]}
        ):
            raise ValueError(f"methodology semantic phase hash is invalid: {phase}")

    semantic_runtime = manifest.get("semantic_runtime")
    if not isinstance(semantic_runtime, dict) or set(semantic_runtime) != {
        "files",
        "semantic_runtime_sha256",
    }:
        raise ValueError("methodology semantic runtime shape is invalid")
    semantic_runtime_paths = _validate_file_records(
        semantic_runtime.get("files"),
        semantic=True,
        label="semantic runtime",
    )
    if semantic_runtime_paths != list(SEMANTIC_RUNTIME_FILES):
        raise ValueError("methodology semantic runtime ownership differs")
    if semantic_runtime.get("semantic_runtime_sha256") != canonical_sha256(
        {"files": semantic_runtime["files"]}
    ):
        raise ValueError("methodology semantic runtime hash is invalid")

    control_plane = manifest.get("control_plane")
    if not isinstance(control_plane, dict) or set(control_plane) != {
        "files",
        "control_sha256",
    }:
        raise ValueError("methodology control-plane shape is invalid")
    control_paths = _validate_file_records(
        control_plane.get("files"), semantic=False, label="control plane"
    )
    if control_paths != sorted(control_paths):
        raise ValueError("methodology control-plane inventory is not sorted")
    if not set(semantic_runtime_paths).issubset(control_paths):
        raise ValueError("methodology semantic runtime escapes control plane")
    if control_plane.get("control_sha256") != canonical_sha256(
        {"files": control_plane["files"]}
    ):
        raise ValueError("methodology control-plane hash is invalid")
    if semantic_contract_sha256 != _semantic_contract_sha256(
        str(domain_registry_sha256),
        phases,
        str(semantic_runtime["semantic_runtime_sha256"]),
    ):
        raise ValueError("methodology semantic contract hash is invalid")
    if release_sha256 != _release_sha256(
        str(control_plane["control_sha256"]),
        phases,
    ):
        raise ValueError("methodology release hash is invalid")

    return MethodologyIdentity(
        manifest_schema_version=MANIFEST_V3_SCHEMA,
        semantic_contract_sha256=str(semantic_contract_sha256),
        release_sha256=str(release_sha256),
        manifest_sha256=manifest_sha256,
        legacy_combined_identity=False,
    )


def validate_current_methodology_manifest(
    payload: Mapping[str, Any],
    *,
    root: Path = ROOT,
    registry: DomainRegistry = REGISTRY,
) -> MethodologyIdentity:
    """Require the exact authority generated by the currently imported release.

    ``validate_methodology_manifest`` is deliberately a versioned envelope
    reader so immutable v2 runs remain readable.  New run creation has a
    stronger contract: it must bind the exact current registry, phase
    inventories, file bytes and dynamically discovered control plane.  Keeping
    this distinction explicit prevents a self-consistent subset manifest or a
    random registry identity from opening a new authority epoch.
    """

    identity = validate_methodology_manifest(payload)
    if identity.legacy_combined_identity:
        raise ValueError(
            "new vNext runs require a methodology-manifest-v3 authority profile"
        )
    expected = build_methodology_manifest(root=root, registry=registry)
    if dict(payload) != expected:
        raise ValueError(
            "new vNext run methodology differs from the current release authority"
        )
    return identity


def validate_run_authority_profile(
    run: Mapping[str, Any],
) -> str:
    """Validate the all-or-none run authority profile without reading files."""

    if not isinstance(run, Mapping):
        raise ValueError("vNext run authority binding must be an object")
    has_legacy = LEGACY_RUN_AUTHORITY_FIELD in run
    present_v3 = {field for field in V3_RUN_AUTHORITY_FIELDS if field in run}
    if has_legacy and present_v3:
        raise ValueError("vNext run mixes legacy and v3 authority bindings")
    if has_legacy:
        value = run.get(LEGACY_RUN_AUTHORITY_FIELD)
        if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
            raise ValueError("vNext legacy run authority binding is invalid")
        return "legacy-v2"
    if present_v3 != set(V3_RUN_AUTHORITY_FIELDS):
        raise ValueError("vNext run v3 authority binding is incomplete")
    if any(
        not isinstance(run.get(field), str)
        or not SHA256_RE.fullmatch(str(run.get(field)))
        for field in V3_RUN_AUTHORITY_FIELDS
    ):
        raise ValueError("vNext run v3 authority binding is invalid")
    return "semantic-release-v3"


def validate_run_authority_binding(
    run: Mapping[str, Any],
    methodology_manifest: Mapping[str, Any],
) -> MethodologyIdentity:
    """Bind one sealed run to either a legacy v2 or current v3 manifest."""

    identity = validate_methodology_manifest(methodology_manifest)
    profile = validate_run_authority_profile(run)
    if identity.legacy_combined_identity:
        if (
            profile != "legacy-v2"
            or run.get(LEGACY_RUN_AUTHORITY_FIELD) != identity.manifest_sha256
        ):
            raise ValueError("legacy run methodology binding differs from manifest")
        return identity
    if profile != "semantic-release-v3":
        raise ValueError("v3 methodology requires the semantic/release run profile")
    expected = {
        "semantic_contract_sha256": identity.semantic_contract_sha256,
        "release_sha256": identity.release_sha256,
        "methodology_manifest_sha256": identity.manifest_sha256,
    }
    if any(run.get(field) != value for field, value in expected.items()):
        raise ValueError("v3 run authority binding differs from manifest")
    return identity


def verify_manifest_files(
    payload: Mapping[str, Any],
    *,
    root: Path,
    phase: str | None = None,
    include_control: bool = True,
) -> None:
    """Verify exact sealed files against the current repository without mutation."""

    validate_methodology_manifest(payload)
    root = root.resolve()
    inventories: list[tuple[str, object]] = []
    phases = payload.get("phases")
    if phase is not None:
        phase_payload = phases.get(phase) if isinstance(phases, Mapping) else None
        if not isinstance(phase_payload, Mapping):
            raise ValueError(f"methodology phase is missing: {phase}")
        inventories.append((f"phase {phase}", phase_payload.get("files")))
    if include_control:
        control = payload.get("control_plane")
        if not isinstance(control, Mapping):
            raise ValueError("methodology control-plane inventory is missing")
        inventories.append(("control plane", control.get("files")))

    changed: list[str] = []
    for label, records in inventories:
        if not isinstance(records, list):
            raise ValueError(f"{label} exact file inventory is missing")
        for record in records:
            if not isinstance(record, Mapping):
                raise ValueError(f"{label} exact file record is invalid")
            relative = str(record.get("path", ""))
            path = (root / relative).resolve()
            try:
                path.relative_to(root)
            except ValueError:
                changed.append(relative)
                continue
            if (
                not path.is_file()
                or path.stat().st_size != record.get("bytes")
                or sha256_file(path) != record.get("sha256")
            ):
                changed.append(relative)
    if changed:
        raise ValueError(
            "methodology files changed after run start: "
            + ", ".join(sorted(set(changed)))
        )


def load_scoring_policy(*, root: Path = ROOT) -> dict[str, Any]:
    path = root / "scoring" / "scoring_contract.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "maker_score" not in payload:
        raise ValueError("scoring contract is invalid")
    maker = payload.get("maker_score") or {}
    chart = (maker.get("chart") or {}).get("components")
    if (
        not isinstance(maker.get("threshold"), int)
        or not isinstance(chart, dict)
        or not chart
        or any(not isinstance(value, int) or value <= 0 for value in chart.values())
    ):
        raise ValueError("scoring contract maker score is invalid")
    source_roles = ((payload.get("gold_methodology") or {}).get("source_roles") or {})
    required_roles = {
        "blockbeats",
        "coinglass",
        "exocharts",
        "fedwatch",
        "farside_btc_etf",
        "tradingview",
    }
    if set(source_roles) != required_roles:
        raise ValueError("scoring contract source role set is invalid")
    for name, role in source_roles.items():
        paths = role.get("required_value_paths") if isinstance(role, dict) else None
        if not isinstance(paths, list) or not paths:
            raise ValueError(f"scoring contract source role is incomplete: {name}")
    profile_policy = payload.get("tradingview_profile_policy") or {}
    if (
        profile_policy.get("source_mode") != "user_drawn_manual_only"
        or profile_policy.get("platform_indicator_policy") != "hide_and_never_use"
        or profile_policy.get("automated_numeric_values_allowed") is not False
        or profile_policy.get("coinglass_substitution_allowed") is not False
        or profile_policy.get("directional_use") is not False
        or profile_policy.get("insufficient_liquidity_hunt_score") != 0
        or profile_policy.get("state_sidecar_filename") != "tradingview_profile_state.json"
        or profile_policy.get("state_sidecar_schema_version") != "tradingview-profile-state-v2"
        or profile_policy.get("state_sidecar_binding_schema_version")
        != "tradingview-profile-capture-binding-v1"
        or profile_policy.get("state_sidecar_identity_fields")
        != ["capture_run_id", "capture_nonce"]
        or set(profile_policy.get("allowed_certification_bases") or [])
        != {"profile_control", "certified_legend_inventory", "unverified"}
        or profile_policy.get("certified_absence_basis")
        != "certified_legend_inventory"
        or profile_policy.get("state_sidecar_write_failure_behavior")
        != "profile_dimension_insufficient_non_blocking"
        or profile_policy.get("uncertified_platform_indicator_behavior")
        != "profile_dimension_insufficient"
        or set(profile_policy.get("allowed_statuses") or []) != {"readable", "insufficient"}
        or set(profile_policy.get("allowed_platform_indicator_states") or [])
        != {"hidden", "absent", "visible", "unknown"}
        or set(profile_policy.get("readable_platform_indicator_states") or []) != {"hidden", "absent"}
        or set(profile_policy.get("allowed_zone_timeframes") or [])
        != {"1d", "4h", "1h", "15m"}
        or set(profile_policy.get("allowed_zone_roles") or [])
        != {"value_area", "poc_zone", "hvn_zone", "lvn_zone"}
        or profile_policy.get("unreadable_manual_profile_behavior")
        != "profile_dimension_insufficient_no_inference"
    ):
        raise ValueError("TradingView manual profile policy is invalid")
    risk = payload.get("risk_execution") or {}
    instruments = risk.get("maker_instruments")
    right_entry_policy = risk.get("right_entry_confirmation_policy") or {}
    entry_reach_probability_policy = (
        risk.get("entry_reach_probability_applicability") or {}
    )
    if (
        risk.get("maker_exchange") != "OKX"
        or risk.get("maker_order_method") != "Maker"
        or risk.get("maker_fixed_leverage") != 5
        or risk.get("maker_entry_types") != ["left", "right"]
        or risk.get("maker_non_directional_entry_type") != "not_applicable"
        or right_entry_policy
        != {
            "status": "fail_closed_until_typed_confirmation_basis",
            "constructible_in_decision_model_v7": False,
            "authority": "execution/entry_models.md",
        }
        or entry_reach_probability_policy
        != {
            "allowed_statuses": [
                "applicable",
                "not_applicable_no_certified_entry_geometry",
            ],
            "applicable_requires": [
                "certified_tradingview_entry_zone",
                "at_least_one_typed_candidate_entry_within_zone",
                "complete_tradingview_1h_reach_geometry",
            ],
            "not_applicable_probability_value": None,
            "not_applicable_geometry_fields_must_be_null": [
                "reference_entry",
                "entry_distance",
                "reach_direction",
            ],
            "numeric_zero_is_not_a_null_sentinel": True,
            "compiler_may_infer_or_coerce": False,
        }
        or not isinstance(instruments, dict)
        or set(instruments) != {"BTCUSDT", "ETHUSDT"}
        or set(risk.get("cannot_do_codes") or []) != {"做多", "追多", "做空", "追空", "追多空"}
    ):
        raise ValueError("scoring contract Maker execution policy is invalid")
    lifecycle_policy = risk.get("maker_order_lifecycle") or {}
    if (
        lifecycle_policy.get("schema_version")
        != REGISTRY.maker_order_lifecycle_schema_version
        or lifecycle_policy.get("gate_derives_exact_object") is not True
        or lifecycle_policy.get("actual_fill_probability_is_not_estimated") is not True
        or lifecycle_policy.get("compiler_may_infer_or_rewrite") is not False
    ):
        raise ValueError("scoring contract Maker order lifecycle policy is invalid")
    for instrument, limits in instruments.items():
        if (
            not isinstance(limits, dict)
            or not isinstance(limits.get("minimum_position_notional_usdt"), (int, float))
            or not isinstance(limits.get("maximum_position_notional_usdt"), (int, float))
            or limits["minimum_position_notional_usdt"] > limits["maximum_position_notional_usdt"]
        ):
            raise ValueError(f"scoring contract Maker notional range is invalid: {instrument}")
    liquidation_ownership = (
        (payload.get("gold_methodology") or {}).get(
            "liquidation_confirmation_ownership"
        )
        or {}
    )
    if liquidation_ownership != {
        "raw_liquidation_map_owner": "Coinglass observation",
        "confirmation_result_owner": "liquidation_confirmation claim",
        "required_direct_observation_sources": ["Coinglass"],
        "required_direct_claim_types": ["chart_interpretation"],
        "raw_tradingview_observation_bypass_forbidden": True,
        "insufficient_manual_profile_result": "neutral",
    }:
        raise ValueError("scoring contract liquidation ownership policy is invalid")
    return payload
