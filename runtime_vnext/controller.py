"""Thin vNext controller: gate, checkpoint, retry only the failed stage."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .artifacts import ArtifactStore
from .effort_policy import (
    REQUESTED_EFFORT,
    REQUESTED_MODEL,
    satisfies_requested_effort,
)
from .errors import FailureClass, RetryScope, WorkflowFailure
from .gates import GateResult
from .domain_ir.report_projection import (
    project_blockbeats_cards_spec,
    project_canonical_report_model,
    project_report_bindings,
)
from .methodology import (
    build_methodology_manifest,
    canonical_sha256,
    load_scoring_policy,
    validate_run_authority_binding,
    validate_run_authority_profile,
    verify_manifest_files,
)
from .reasoning_submission import (
    assemble_reasoning_submission,
    build_reasoning_submission_scaffold,
    load_reasoning_submission_contract,
    validate_contract_runtime_compatibility,
)
from .report_compiler import (
    load_presentation_contract,
    render_blockbeats_cards,
    render_combined_markdown,
)
from .validation.decision_main import validate_main_decision as evaluate_decision
from .validation.delivery import (
    validate_delivery as evaluate_delivery,
    validate_shadow_delivery as evaluate_shadow_delivery,
)
from .validation.evidence import validate_evidence as evaluate_evidence
from .validation.reasoning_shape import (
    validate_reasoning_shape as evaluate_reasoning,
)
from .validation.report_quality import (
    evaluate_gold_template_fidelity,
    evaluate_human_reasoning_depth,
    run_compatibility_lint,
)
from .validation.report_projection import certify_report_projection_input
from .legacy_capture_adapter import adapt_legacy_capture


DEFAULT_AUTOMATIC_ATTEMPT_LIMIT = 2
AUTOMATIC_ATTEMPT_LIMIT_BY_STAGE = {
    "reasoning": 3,
}
SAFE_CAPTURE_DEFECT_CODE = re.compile(r"^capture\.exocharts\.[A-Za-z0-9_.-]{1,96}$")
REPLAY_AUTHORIZATION_REF = re.compile(
    r"(?:test|replay):[A-Za-z0-9][A-Za-z0-9._-]{7,127}"
)


class RunController:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root.resolve()
        self.store = ArtifactStore(
            self.repo_root,
            authority_root=self.repo_root,
        )

    def _load_methodology(self, run_root: Path) -> dict[str, Any]:
        run = self.store.load_run(run_root)
        try:
            payload = json.loads(
                (run_root / "methodology_manifest.json").read_text(encoding="utf-8")
            )
            validate_run_authority_binding(run, payload)
            verify_manifest_files(
                payload,
                root=self.repo_root,
                include_control=True,
            )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise WorkflowFailure(
                FailureClass.MANUAL_REVIEW,
                "methodology manifest changed or is invalid",
            ) from exc
        return payload

    def _capture_failure_defect_code(
        self,
        manifest_match: re.Match[str] | None,
        *,
        run: dict[str, Any],
        capture_id: str,
    ) -> str:
        fallback = "capture.failed"
        if manifest_match is None:
            return fallback
        try:
            manifest_path = Path(manifest_match.group(1).strip()).resolve()
            expected_root = (
                self.repo_root
                / "runtime_state"
                / str(run["trading_date"])
                / "captures"
                / str(run["slot"])
            ).resolve()
            manifest_path.relative_to(expected_root)
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            expected_mode = (
                "full_base" if run.get("slot") == "morning" else "full_recollection"
            )
            source_failure = (payload.get("source_failures") or {}).get(
                "capture_exo.js"
            )
            code = str((source_failure or {}).get("defect_code", ""))
            valid = (
                manifest_path.parent == expected_root
                and manifest_path.name == f"{expected_mode}_{capture_id}.json"
                and payload.get("schema_version") == "1.0"
                and payload.get("date") == run.get("trading_date")
                and payload.get("slot") == run.get("slot")
                and payload.get("mode") == expected_mode
                and payload.get("run_id") == capture_id
                and payload.get("vnext_active_run_id") == run.get("run_id")
                and payload.get("success") is False
                and (payload.get("results") or {}).get("capture_exo.js") != 0
                and SAFE_CAPTURE_DEFECT_CODE.fullmatch(code) is not None
            )
            return code if valid else fallback
        except (OSError, ValueError, json.JSONDecodeError, TypeError):
            return fallback

    def _assert_methodology_phase(self, run_root: Path, phase: str) -> dict[str, Any]:
        payload = self._load_methodology(run_root)
        try:
            verify_manifest_files(
                payload,
                root=self.repo_root,
                phase=phase,
                include_control=False,
            )
        except ValueError as exc:
            raise WorkflowFailure(
                FailureClass.MANUAL_REVIEW,
                f"methodology phase changed during the run: {phase}",
            ) from exc
        return payload

    def _assert_reasoning_contract_compatibility(
        self,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        full_policy = load_scoring_policy(root=self.repo_root)
        contract = load_reasoning_submission_contract(root=self.repo_root)
        issues = validate_contract_runtime_compatibility(
            contract,
            full_policy=full_policy,
        )
        if issues:
            raise WorkflowFailure(
                FailureClass.MANUAL_REVIEW,
                "reasoning submission contract is incompatible with the runtime",
                defects=[
                    {
                        "code": item.code,
                        "message": item.message,
                        "path": item.path,
                    }
                    for item in issues
                ],
            )
        return contract, full_policy

    def reasoning_contract_preflight(self, run_root: Path) -> dict[str, Any]:
        """Check static producer-contract compatibility without a model or attempt."""

        self._assert_preflight(run_root)
        self.store.load_stage_payload(run_root, "evidence", "evidence")
        methodology = self._assert_methodology_phase(run_root, "reasoning")
        contract, _ = self._assert_reasoning_contract_compatibility()
        return {
            "status": "reasoning_contract_ready",
            "schema_version": contract["schema_version"],
            "certified_schema_version": contract["certified_schema_version"],
            "claim_topology_schema_version": contract["claim_topology"][
                "schema_version"
            ],
            "claim_topology_sha256": canonical_sha256(
                contract["claim_topology"]
            ),
            "typed_narrative_ownership_sha256": canonical_sha256(
                contract["typed_narrative_ownership"]
            ),
            "reasoning_authority_sha256": methodology["phases"]["reasoning"][
                "phase_sha256"
            ],
            "business_semantics_checked": False,
            "model_called": False,
            "attempt_created": False,
        }

    def reasoning_scaffold(self, run_root: Path) -> dict[str, Any]:
        """Return the run-bound producer scaffold without writing run state."""

        self._assert_preflight(run_root)
        evidence = self.store.load_stage_payload(run_root, "evidence", "evidence")
        methodology = self._assert_methodology_phase(run_root, "reasoning")
        contract, full_policy = self._assert_reasoning_contract_compatibility()
        return build_reasoning_submission_scaffold(
            evidence=evidence,
            reasoning_authority_sha256=methodology["phases"]["reasoning"][
                "phase_sha256"
            ],
            contract=contract,
            full_policy=full_policy,
        )

    def begin(
        self,
        trading_date: str,
        slot: str,
        *,
        requested_model: str = REQUESTED_MODEL,
        requested_effort: str = REQUESTED_EFFORT,
        run_mode: str,
        authorization_ref: str,
        run_id: str | None = None,
        allow_shadow_repeat: bool = False,
    ) -> Path:
        methodology = build_methodology_manifest(root=self.repo_root)
        run = self.store.create_run(
            trading_date,
            slot,
            methodology_manifest=methodology,
            requested_model=requested_model,
            requested_effort=requested_effort,
            run_mode=run_mode,
            authorization_ref=authorization_ref,
            run_id=run_id,
            allow_shadow_repeat=allow_shadow_repeat,
        )
        return self.store.run_root(trading_date, slot, run["run_id"])

    def record_host_capability(self, run_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
        run = self._execution_run(run_root)
        clean = dict(payload)
        manifest_sha = clean.get("manifest_sha256")
        actual_effort = clean.get("reasoning_effort")
        requested_effort = run.get("requested_effort")
        valid = (
            clean.get("schema_version") == "codex-host-capability-v2"
            and clean.get("status") == "verified"
            and clean.get("trading_date") == run["trading_date"]
            and clean.get("slot") == run["slot"]
            and clean.get("model") == run["requested_model"]
            and satisfies_requested_effort(actual_effort, requested_effort)
            and clean.get("minimum_effort") == requested_effort
            and clean.get("effort_policy") == "at_least_minimum"
            and bool(clean.get("thread_id"))
            and manifest_sha == canonical_sha256(clean)
        )
        if not valid:
            raise WorkflowFailure(
                FailureClass.MANUAL_REVIEW,
                "host capability is not verified at the requested model/effort",
            )
        target = run_root / "host_capability.json"
        if target.exists():
            existing = json.loads(target.read_text(encoding="utf-8"))
            if existing != clean:
                raise WorkflowFailure(FailureClass.MANUAL_REVIEW, "host capability binding changed")
            return existing
        from .artifacts import _exclusive_json

        _exclusive_json(target, clean)
        return clean

    def record_pretrade_gate(self, run_root: Path, **kwargs: Any) -> dict[str, Any]:
        run = self._execution_run(run_root)
        if run.get("run_mode") != "production":
            raise WorkflowFailure(
                FailureClass.MANUAL_REVIEW,
                "shadow runs must not read or record a pretrade gate",
            )
        return self.store.record_pretrade_gate(run_root, **kwargs)

    def _execution_run(self, run_root: Path) -> dict[str, Any]:
        run = self.store.load_run(run_root)
        try:
            authority_profile = validate_run_authority_profile(run)
        except ValueError as exc:
            raise WorkflowFailure(
                FailureClass.MANUAL_REVIEW,
                "vNext run authority binding is invalid",
            ) from exc
        if (
            run.get("schema_version") != "daily-run-vnext-v2"
            or authority_profile != "semantic-release-v3"
        ):
            checkpoint = self.store.load_checkpoint(run_root)
            status = checkpoint.get("status")
            detail = (
                "legacy terminal runs remain read-only"
                if status in {"complete", "shadow_complete", "retired"}
                else "legacy non-terminal runs require explicit retirement; run mode cannot be inferred"
            )
            raise WorkflowFailure(FailureClass.MANUAL_REVIEW, detail)
        return run

    def _assert_preflight(self, run_root: Path) -> None:
        self._execution_run(run_root)
        target = run_root / "host_capability.json"
        if not target.is_file():
            raise WorkflowFailure(
                FailureClass.MANUAL_REVIEW,
                "host capability must be verified before evidence acceptance",
            )
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkflowFailure(
                FailureClass.MANUAL_REVIEW,
                "host capability record is unreadable or invalid",
            ) from exc
        self.record_host_capability(run_root, payload)

    def authorize_manual_review(
        self,
        run_root: Path,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self._assert_preflight(run_root)
        run = self.store.load_run(run_root)
        clean = dict(payload)
        reviewed_at = clean.get("reviewed_at")
        try:
            parsed_reviewed_at = datetime.fromisoformat(
                str(reviewed_at).replace("Z", "+00:00")
            )
            valid_time = parsed_reviewed_at.tzinfo is not None
        except (TypeError, ValueError):
            valid_time = False
        valid = (
            clean.get("schema_version") == "manual-review-authorization-v1"
            and clean.get("approved") is True
            and clean.get("run_id") == run.get("run_id")
            and clean.get("trading_date") == run.get("trading_date")
            and clean.get("slot") == run.get("slot")
            and clean.get("retry_stage") in {"evidence", "reasoning", "decision", "report", "delivery"}
            and len(str(clean.get("reason", "")).strip()) >= 8
            and bool(str(clean.get("reviewer_reference", "")).strip())
            and bool(str(clean.get("approval_reference", "")).strip())
            and valid_time
            and clean.get("manifest_sha256") == canonical_sha256(clean)
        )
        if not valid:
            raise WorkflowFailure(
                FailureClass.MANUAL_REVIEW,
                "manual review authorization is invalid or not bound to this run",
            )
        return self.store.resume_after_manual_review(run_root, clean)

    def retire_run(
        self,
        run_root: Path,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        run = self.store.load_run(run_root)
        clean = dict(payload)
        try:
            retired_at = datetime.fromisoformat(
                str(clean.get("retired_at")).replace("Z", "+00:00")
            )
            valid_time = retired_at.tzinfo is not None
        except (TypeError, ValueError):
            valid_time = False
        valid = (
            clean.get("schema_version") == "run-retirement-authorization-v1"
            and clean.get("approved") is True
            and clean.get("run_id") == run.get("run_id")
            and clean.get("trading_date") == run.get("trading_date")
            and clean.get("slot") == run.get("slot")
            and len(str(clean.get("reason", "")).strip()) >= 8
            and bool(str(clean.get("reviewer_reference", "")).strip())
            and bool(str(clean.get("approval_reference", "")).strip())
            and valid_time
            and clean.get("manifest_sha256") == canonical_sha256(clean)
        )
        if not valid:
            raise WorkflowFailure(
                FailureClass.MANUAL_REVIEW,
                "run retirement requires an explicit hash-bound authorization",
            )
        return self.store.retire_run(run_root, clean)

    @staticmethod
    def _defects(gate: GateResult) -> list[dict[str, Any]]:
        return [
            {
                "code": item.code,
                "message": item.message,
                "path": item.path,
                "severity": item.severity,
            }
            for item in gate.defects
        ]

    def _gate_failure(
        self,
        run_root: Path,
        stage: str,
        attempt: int,
        gate: GateResult,
        failure_class: FailureClass,
    ) -> None:
        failure = WorkflowFailure(
            failure_class,
            f"{gate.gate} failed with {len(gate.defects)} defect(s)",
            defects=self._defects(gate),
        )
        self._bounded_failure(run_root, stage, attempt, failure)

    def _bounded_failure(
        self,
        run_root: Path,
        stage: str,
        attempt: int,
        failure: WorkflowFailure,
    ) -> None:
        """Apply the stage-specific automatic attempt budget.

        Reasoning gets two same-input corrections (three total attempts).
        Every other stage keeps one correction (two total attempts). Orphaned
        attempts are not counted because failure_count validates only sealed
        failure records.
        """

        attempt_limit = AUTOMATIC_ATTEMPT_LIMIT_BY_STAGE.get(
            stage,
            DEFAULT_AUTOMATIC_ATTEMPT_LIMIT,
        )
        if self.store.failure_count(run_root, stage) >= attempt_limit - 1:
            failure = WorkflowFailure(
                FailureClass.MANUAL_REVIEW,
                f"{stage} failed {attempt_limit} times; automatic retry budget is exhausted",
                defects=failure.defects,
            )
        self.store.fail_attempt(
            run_root,
            stage,
            attempt,
            failure_class=failure.failure_class.value,
            retryable=failure.policy.retryable,
            retry_scope=failure.policy.retry_scope.value,
            defects=failure.defects,
            needs_manual_review=failure.policy.needs_manual_review,
        )
        raise failure

    def accept_evidence(
        self,
        run_root: Path,
        payload: dict[str, Any],
        *,
        evidence_files_root: Path | None = None,
    ) -> dict[str, Any]:
        """Certify an in-process evidence payload.

        This is the trusted certification primitive retained for internal
        adapters and deterministic tests.  It is deliberately not exposed as
        a general CLI command.  External payload replay must enter through
        ``accept_replay_evidence`` so production and ordinary shadow runs
        cannot bypass the immutable capture path.
        """
        self._assert_preflight(run_root)
        methodology = self._assert_methodology_phase(run_root, "evidence")
        evidence_root = (
            self.repo_root
            if evidence_files_root is None
            else evidence_files_root.resolve()
        )
        try:
            relative_root = evidence_root.relative_to(self.repo_root).as_posix()
        except ValueError as exc:
            raise ValueError("evidence files root must stay inside the repository") from exc
        attempt, attempt_root = self.store.begin_attempt(run_root, "evidence")
        return self._certify_evidence_attempt(
            run_root,
            payload,
            attempt=attempt,
            attempt_root=attempt_root,
            evidence_root=evidence_root,
            relative_root=relative_root,
            methodology=methodology,
        )

    def accept_replay_evidence(
        self,
        run_root: Path,
        payload: dict[str, Any],
        *,
        replay_authorization_ref: str,
        evidence_files_root: Path | None = None,
    ) -> dict[str, Any]:
        """Accept external evidence only for a sealed test/replay shadow run.

        The raw reference is never persisted here.  Its normalized value must
        use the explicit ``test:`` or ``replay:`` namespace and reproduce the
        SHA-256 already sealed into ``run.json`` at ``begin`` time.
        """

        run = self._execution_run(run_root)
        authorization_value = replay_authorization_ref.strip()
        sealed_sha256 = str(run.get("authorization_ref_sha256", ""))
        presented_sha256 = hashlib.sha256(
            authorization_value.encode("utf-8")
        ).hexdigest()
        if run.get("run_mode") != "shadow":
            raise WorkflowFailure(
                FailureClass.MANUAL_REVIEW,
                "production runs must use the immutable capture command",
            )
        if REPLAY_AUTHORIZATION_REF.fullmatch(authorization_value) is None:
            raise WorkflowFailure(
                FailureClass.MANUAL_REVIEW,
                "external evidence requires an explicit test or replay shadow authorization",
            )
        if not hmac.compare_digest(presented_sha256, sealed_sha256):
            raise WorkflowFailure(
                FailureClass.MANUAL_REVIEW,
                "replay authorization does not match the reference sealed at run begin",
            )
        return self.accept_evidence(
            run_root,
            payload,
            evidence_files_root=evidence_files_root,
        )

    def _certify_evidence_attempt(
        self,
        run_root: Path,
        payload: dict[str, Any],
        *,
        attempt: int,
        attempt_root: Path,
        evidence_root: Path,
        relative_root: str,
        methodology: dict[str, Any],
    ) -> dict[str, Any]:
        candidate = dict(payload)
        candidate.pop("snapshot_sha256", None)
        candidate["evidence_contract_sha256"] = methodology["phases"]["evidence"]["phase_sha256"]
        candidate["artifact_root"] = relative_root
        gate = evaluate_evidence(
            candidate,
            root=evidence_root,
            expected_contract_sha256=methodology["phases"]["evidence"]["phase_sha256"],
        )
        if not gate.passed:
            self.store.write_payload(attempt_root, "rejected.json", candidate)
            self._gate_failure(
                run_root,
                "evidence",
                attempt,
                gate,
                FailureClass.EVIDENCE_INTEGRITY,
            )
        certified = candidate
        certified["snapshot_sha256"] = gate.facts["snapshot_sha256"]
        record = self.store.write_payload(attempt_root, "evidence.json", certified)
        return self.store.complete_attempt(
            run_root,
            "evidence",
            attempt,
            {"evidence": record},
            gate=gate.to_dict(),
        )

    def capture(self, run_root: Path) -> dict[str, Any]:
        self._assert_preflight(run_root)
        methodology = self._assert_methodology_phase(run_root, "evidence")
        run = self._execution_run(run_root)
        attempt, attempt_root = self.store.begin_attempt(run_root, "evidence")
        capture_id = str(uuid.uuid4())
        command = [
            "node",
            str(self.repo_root / "tools" / "browser_capture" / "capture_all.js"),
            "--slot",
            run["slot"],
            "--run-id",
            capture_id,
            "--vnext-run-id",
            run["run_id"],
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                env={
                    **os.environ,
                    "VNEXT_CAPTURE_ATTEMPT_ROOT": str(attempt_root),
                    "VNEXT_PYTHON_EXECUTABLE": sys.executable,
                },
            )
            combined_output = "\n".join(
                part for part in (completed.stdout, completed.stderr) if part
            )
        except OSError as exc:
            completed = None
            combined_output = str(exc)
        manifest_match = re.search(r"FULL_CAPTURE_MANIFEST=(.+)", combined_output)
        if completed is None or completed.returncode != 0 or manifest_match is None:
            self.store.write_text(attempt_root, "capture.log", combined_output)
            defect_code = self._capture_failure_defect_code(
                manifest_match,
                run=run,
                capture_id=capture_id,
            )
            failure = WorkflowFailure(
                FailureClass.INFRASTRUCTURE_TRANSIENT,
                "six-source capture did not produce a successful immutable manifest",
                defects=[
                    {
                        "code": defect_code,
                        "message": "capture command failed or omitted a successful manifest",
                        "path": (
                            "evidence.Exocharts"
                            if defect_code.startswith("capture.exocharts.")
                            else "evidence"
                        ),
                        "severity": "hard",
                    }
                ],
                retry_scope=RetryScope.CAPTURE,
            )
            self._bounded_failure(run_root, "evidence", attempt, failure)
        try:
            manifest_path = Path(manifest_match.group(1).strip()).resolve()
            evidence = adapt_legacy_capture(manifest_path, root=self.repo_root)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.store.write_text(
                attempt_root,
                "capture.log",
                f"{type(exc).__name__}: {exc}",
            )
            failure = WorkflowFailure(
                FailureClass.EVIDENCE_INTEGRITY,
                "immutable capture manifest could not be certified",
                defects=[
                    {
                        "code": "capture.manifest_invalid",
                        "message": "capture manifest or snapshot failed certification",
                        "path": "evidence",
                        "severity": "hard",
                    }
                ],
            )
            self._bounded_failure(run_root, "evidence", attempt, failure)
        return self._certify_evidence_attempt(
            run_root,
            evidence,
            attempt=attempt,
            attempt_root=attempt_root,
            evidence_root=self.repo_root,
            relative_root=".",
            methodology=methodology,
        )

    def accept_reasoning(self, run_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
        self._assert_preflight(run_root)
        evidence = self.store.load_stage_payload(run_root, "evidence", "evidence")
        methodology = self._assert_methodology_phase(run_root, "reasoning")
        # Static schema/handler compatibility is checked before an attempt is
        # opened.  The candidate itself is deliberately not previewed here:
        # all candidate shape and business defects remain inside the sealed
        # reasoning attempt and its normal retry telemetry.
        contract, full_policy = self._assert_reasoning_contract_compatibility()
        attempt, attempt_root = self.store.begin_attempt(run_root, "reasoning")
        gate: GateResult | None = None
        record: dict[str, Any] | None = None
        try:
            # Preserve the exact producer submission separately from the
            # authority-projected candidate used for certification.
            self.store.write_payload(attempt_root, "submitted.json", payload)
            attempt_record = self.store.load_open_attempt_record(
                run_root,
                "reasoning",
                attempt,
            )
            try:
                visual_review_not_after = datetime.fromisoformat(
                    str(attempt_record["started_at"]).replace("Z", "+00:00")
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise WorkflowFailure(
                    FailureClass.MANUAL_REVIEW,
                    "sealed reasoning-attempt start time is invalid",
                ) from exc
            if visual_review_not_after.tzinfo is None:
                raise WorkflowFailure(
                    FailureClass.MANUAL_REVIEW,
                    "sealed reasoning-attempt start time is not timezone-aware",
                )

            # Identity, structural wrappers and deterministic projections are
            # controller-owned. Projection happens only after the normal sealed
            # attempt opens, so no candidate preview or hidden retry is introduced.
            candidate = assemble_reasoning_submission(
                payload,
                evidence=evidence,
                reasoning_authority_sha256=methodology["phases"]["reasoning"][
                    "phase_sha256"
                ],
                contract=contract,
                full_policy=full_policy,
            )
            gate = evaluate_reasoning(
                candidate,
                evidence=evidence,
                reasoning_authority_sha256=methodology["phases"]["reasoning"][
                    "phase_sha256"
                ],
                evidence_root=(
                    self.repo_root / str(evidence.get("artifact_root", "."))
                ).resolve(),
                methodology_root=self.repo_root,
                visual_review_not_after=visual_review_not_after,
            )
            if not gate.passed:
                self.store.write_payload(attempt_root, "rejected.json", candidate)
            else:
                certified = dict(candidate)
                certified["reasoning_sha256"] = gate.facts["reasoning_sha256"]
                record = self.store.write_payload(
                    attempt_root,
                    "reasoning.json",
                    certified,
                )
        except WorkflowFailure as failure:
            self._bounded_failure(
                run_root,
                "reasoning",
                attempt,
                failure,
            )
        except Exception as exc:
            self._bounded_failure(
                run_root,
                "reasoning",
                attempt,
                WorkflowFailure(
                    FailureClass.MANUAL_REVIEW,
                    "reasoning validation aborted before certification",
                    defects=[
                        {
                            "code": "reasoning.internal_validation_error",
                            "message": (
                                "sealed reasoning validation raised "
                                f"{type(exc).__name__}"
                            ),
                            "path": "reasoning",
                            "severity": "hard",
                        }
                    ],
                ),
            )
        if gate is None:
            self._bounded_failure(
                run_root,
                "reasoning",
                attempt,
                WorkflowFailure(
                    FailureClass.MANUAL_REVIEW,
                    "reasoning gate did not return a certification result",
                    defects=[
                        {
                            "code": "reasoning.internal_validation_error",
                            "message": "sealed reasoning gate returned no result",
                            "path": "reasoning",
                            "severity": "hard",
                        }
                    ],
                ),
            )
        if not gate.passed:
            failure_class = (
                FailureClass.EVIDENCE_INTEGRITY
                if any(
                    item.code == "binding.evidence_drift"
                    for item in gate.defects
                )
                else FailureClass.REASONING_CONSISTENCY
            )
            self._gate_failure(
                run_root,
                "reasoning",
                attempt,
                gate,
                failure_class,
            )
        if record is None:
            self._bounded_failure(
                run_root,
                "reasoning",
                attempt,
                WorkflowFailure(
                    FailureClass.MANUAL_REVIEW,
                    "reasoning certification record is missing",
                    defects=[
                        {
                            "code": "reasoning.internal_validation_error",
                            "message": "sealed reasoning output record is missing",
                            "path": "reasoning",
                            "severity": "hard",
                        }
                    ],
                ),
            )
        return self.store.complete_attempt(
            run_root,
            "reasoning",
            attempt,
            {"reasoning": record},
            gate=gate.to_dict(),
        )

    def accept_decision(self, run_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
        self._assert_preflight(run_root)
        self._assert_methodology_phase(run_root, "reasoning")
        reasoning = self.store.load_stage_payload(run_root, "reasoning", "reasoning")
        run = self._execution_run(run_root)
        pretrade_gate = (
            self.store.load_pretrade_gate(run_root)
            if run.get("run_mode") == "production"
            else None
        )
        attempt, attempt_root = self.store.begin_attempt(run_root, "decision")
        gate = evaluate_decision(
            payload,
            reasoning=reasoning,
            run=run,
            pretrade_gate=pretrade_gate,
            root=self.repo_root,
        )
        if not gate.passed:
            self.store.write_payload(attempt_root, "rejected.json", payload)
            self._gate_failure(
                run_root,
                "decision",
                attempt,
                gate,
                FailureClass.RISK_EXECUTION,
            )
        certified = dict(payload)
        certified["decision_sha256"] = gate.facts["decision_sha256"]
        record = self.store.write_payload(attempt_root, "decision.json", certified)
        continuity_record = self.store.write_payload(
            attempt_root,
            "continuity.json",
            certified["continuity_contract"],
        )
        return self.store.complete_attempt(
            run_root,
            "decision",
            attempt,
            {"decision": record, "continuity": continuity_record},
            gate=gate.to_dict(),
        )

    def compile_report(
        self,
        run_root: Path,
    ) -> dict[str, Any]:
        self._assert_preflight(run_root)
        evidence = self.store.load_stage_payload(run_root, "evidence", "evidence")
        reasoning = self.store.load_stage_payload(run_root, "reasoning", "reasoning")
        decision = self.store.load_stage_payload(run_root, "decision", "decision")
        methodology = self._assert_methodology_phase(run_root, "report")
        attempt, attempt_root = self.store.begin_attempt(run_root, "report")
        try:
            projection_input = certify_report_projection_input(
                evidence=evidence,
                reasoning=reasoning,
                decision=decision,
                methodology_sha256=methodology["phases"]["reasoning"]["phase_sha256"],
                report_contract_sha256=methodology["phases"]["report"]["phase_sha256"],
                root=self.repo_root,
            )
            model = project_canonical_report_model(projection_input)
            report_bindings = project_report_bindings(projection_input)
            markdown = render_combined_markdown(model)
            presentation_contract = load_presentation_contract(self.repo_root)
            depth_gate = evaluate_human_reasoning_depth(
                model,
                contract=presentation_contract,
            )
            template_gate = evaluate_gold_template_fidelity(
                markdown,
                contract=presentation_contract,
            )
            presentation_defects = [
                *depth_gate["defects"],
                *template_gate["defects"],
            ]
            if presentation_defects:
                self._bounded_failure(
                    run_root,
                    "report",
                    attempt,
                    WorkflowFailure(
                        FailureClass.COMPILATION,
                        f"report presentation failed with {len(presentation_defects)} defect(s)",
                        defects=presentation_defects,
                    ),
                )
            model_record = self.store.write_payload(attempt_root, "canonical_report.json", model)
            report_bindings_record = self.store.write_payload(
                attempt_root,
                "report_bindings.json",
                report_bindings,
            )
            report_filename = f"{decision['trading_date']}_{decision['slot']}_combined.md"
            report_record = self.store.write_text(attempt_root, report_filename, markdown)
            cards_spec = project_blockbeats_cards_spec(projection_input)
            cards_spec_record = self.store.write_payload(
                attempt_root,
                "blockbeats_cards.json",
                cards_spec,
            )
            card_records = render_blockbeats_cards(
                model,
                attempt_root=attempt_root,
                repo_root=self.repo_root,
            )
            lint = run_compatibility_lint(
                self.repo_root / report_record["path"], root=self.repo_root
            )
            if not lint["passed"]:
                raise ValueError("legacy compatibility lint failed:\n" + lint["output"])
        except WorkflowFailure:
            raise
        except Exception as exc:
            defect = {"code": "report.compile", "message": str(exc), "path": "report", "severity": "hard"}
            failure = WorkflowFailure(FailureClass.COMPILATION, str(exc), defects=[defect])
            self._bounded_failure(run_root, "report", attempt, failure)
        gate = {
            "gate": "report_compilation",
            "passed": True,
            "defects": [],
            "facts": {
                "canonical_model_sha256": model["model_sha256"],
                "report_bindings_sha256": report_bindings_record["sha256"],
                "report_sha256": report_record["sha256"],
                "cards_spec_sha256": cards_spec_record["sha256"],
                "card_sha256s": [record["sha256"] for record in card_records],
                "compatibility_lint_exit_code": lint["exit_code"],
                "human_reasoning_depth": depth_gate,
                "gold_template_fidelity": template_gate,
            },
        }
        return self.store.complete_attempt(
            run_root,
            "report",
            attempt,
            {
                "canonical_report": model_record,
                "report_bindings": report_bindings_record,
                "combined": report_record,
                "cards_spec": cards_spec_record,
                **{
                    f"card_{index}": record
                    for index, record in enumerate(card_records, start=1)
                },
            },
            gate=gate,
        )

    def accept_delivery(self, run_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
        self._assert_preflight(run_root)
        run = self._execution_run(run_root)
        if run.get("run_mode") != "production":
            raise WorkflowFailure(
                FailureClass.DELIVERY_INTEGRITY,
                "production delivery is forbidden for a shadow run",
            )
        self._assert_methodology_phase(run_root, "report")
        report_outputs = self.store.load_checkpoint(run_root)["completed"]["report"]["outputs"]
        self.store.load_stage_output_record(
            run_root,
            "report",
            "report_bindings",
        )
        expected_report = report_outputs["combined"]
        expected_cards = {
            name: report_outputs[name]
            for name in ("cards_spec", "card_1", "card_2", "card_3")
        }
        attempt, attempt_root = self.store.begin_attempt(run_root, "delivery")
        gate = evaluate_delivery(
            payload,
            root=self.repo_root,
            run=run,
            expected_report=expected_report,
            expected_cards=expected_cards,
        )
        if not gate.passed:
            self.store.write_payload(attempt_root, "rejected.json", payload)
            self._gate_failure(
                run_root,
                "delivery",
                attempt,
                gate,
                FailureClass.DELIVERY_INTEGRITY,
            )
        record = self.store.write_payload(attempt_root, "delivery.json", payload)
        return self.store.complete_attempt(
            run_root,
            "delivery",
            attempt,
            {"delivery": record},
            gate=gate.to_dict(),
        )

    def accept_shadow_delivery(
        self,
        run_root: Path,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Seal a local-only shadow sample without weakening production delivery."""

        self._assert_preflight(run_root)
        run = self._execution_run(run_root)
        if run.get("run_mode") != "shadow":
            raise WorkflowFailure(
                FailureClass.DELIVERY_INTEGRITY,
                "shadow delivery is forbidden for a production run",
            )
        self._assert_methodology_phase(run_root, "report")
        report_outputs = self.store.load_checkpoint(run_root)["completed"]["report"]["outputs"]
        self.store.load_stage_output_record(
            run_root,
            "report",
            "report_bindings",
        )
        expected_report = report_outputs["combined"]
        expected_cards = {
            name: report_outputs[name]
            for name in ("cards_spec", "card_1", "card_2", "card_3")
        }
        attempt, attempt_root = self.store.begin_attempt(run_root, "delivery")
        gate = evaluate_shadow_delivery(
            payload,
            root=self.repo_root,
            run=run,
            expected_report=expected_report,
            expected_cards=expected_cards,
        )
        if not gate.passed:
            self.store.write_payload(attempt_root, "rejected.json", payload)
            self._gate_failure(
                run_root,
                "delivery",
                attempt,
                gate,
                FailureClass.DELIVERY_INTEGRITY,
            )
        record = self.store.write_payload(attempt_root, "shadow_delivery.json", payload)
        return self.store.complete_attempt(
            run_root,
            "delivery",
            attempt,
            {"shadow_delivery": record},
            gate=gate.to_dict(),
            terminal_status="shadow_complete",
            terminal_metadata={
                "completion_mode": "shadow",
                "notion_published": False,
            },
        )

    def status(self, run_root: Path) -> dict[str, Any]:
        return self.store.safe_status(run_root)
