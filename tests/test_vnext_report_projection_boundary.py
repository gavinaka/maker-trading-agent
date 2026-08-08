from __future__ import annotations

import ast
import copy
import unittest
from dataclasses import FrozenInstanceError
from decimal import Decimal
from pathlib import Path

from runtime_vnext.domain_ir import (
    CertifiedReportProjectionInput,
    ProjectedReport,
    ReportBindings,
    ReportField,
    ReportMetadata,
    ReportRecord,
    ReportSectionBinding,
    canonical_sha256,
    project_blockbeats_cards_spec,
    project_canonical_report_model,
    project_report_bindings,
    to_plain,
)
from runtime_vnext.domain_ir.registry import REGISTRY
from runtime_vnext.validation.report import (
    build_report_bindings,
    certify_canonical_report_model,
)


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "runtime_vnext" / "domain_ir" / "types.py"
PROJECTION_PATH = ROOT / "runtime_vnext" / "domain_ir" / "projection.py"


def record(*items: tuple[str, object]) -> ReportRecord:
    return ReportRecord(tuple(ReportField(name, value) for name, value in items))


def certified_input() -> CertifiedReportProjectionInput:
    metadata = ReportMetadata(
        schema_version="canonical-report-model-v11",
        presentation_contract_version="gold-report-presentation-v1",
        presentation_contract_sha256="a" * 64,
        run_id="shadow-2026-08-01-midday",
        run_sha256="b" * 64,
        run_mode="shadow",
        execution_authorization=record(
            ("live_execution_allowed", False),
            ("reason_code", "shadow_only"),
        ),
        trading_date="2026-08-01",
        slot="midday",
        methodology_sha256="c" * 64,
        report_contract_sha256="d" * 64,
        evidence_snapshot_sha256="e" * 64,
        reasoning_sha256="f" * 64,
        decision_sha256="0" * 64,
    )
    bindings = ReportBindings(
        schema_version=REGISTRY.report_bindings_schema_version,
        sections=tuple(
            ReportSectionBinding(
                section_id=section_id,
                model_path=model_path,
                claim_ids=(f"{section_id}-claim",),
                observation_ids=(f"{section_id}-observation",),
                evidence_refs=(f"evidence/{section_id}.json",),
            )
            for section_id, model_path in (
                REGISTRY.report_binding_section_model_paths
            )
        ),
    )
    return CertifiedReportProjectionInput(
        metadata=metadata,
        bindings=bindings,
        blockbeats_cards=(
            record(
                ("event_id", "event-1"),
                ("importance", 3),
            ),
        ),
        frontstage=record(
            ("opening_quote", "认证后的开场判断"),
            ("maker_strategy", "认证后的 Maker 策略"),
        ),
        maker_summary=record(
            ("semantic_state", "qualified_candidate"),
            ("entry_reach_probability", Decimal("42.50")),
        ),
        main_summary=record(
            ("direction", "observe"),
            ("action", "wait"),
        ),
        audit=record(
            (
                "reasoning_proof",
                record(("conclusion", "认证后的中文推理结论")),
            ),
            ("risk_scenarios", ()),
        ),
    )


class VNextReportProjectionBoundaryTests(unittest.TestCase):
    def test_module_has_no_io_network_or_consumer_dependencies(self) -> None:
        trees = [
            ast.parse(path.read_text(encoding="utf-8"))
            for path in (MODULE_PATH, PROJECTION_PATH)
        ]
        imported: set[str] = set()
        for tree in trees:
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)

        banned_imports = {
            "os",
            "pathlib",
            "subprocess",
            "socket",
            "urllib",
            "http",
            "requests",
            "runtime_vnext.gates",
            "runtime_vnext.report_compiler",
        }
        self.assertFalse(
            {
                name
                for name in imported
                if name in banned_imports
                or any(name.startswith(prefix + ".") for prefix in banned_imports)
            }
        )

        called_names = {
            node.func.id
            for tree in trees
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertNotIn("open", called_names)
        called_attributes = {
            node.func.attr
            for tree in trees
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertFalse(
            called_attributes
            & {
                "read_bytes",
                "read_text",
                "write_bytes",
                "write_text",
                "load",
                "loads",
                "dump",
                "run",
                "Popen",
                "request",
                "urlopen",
            }
        )

    def test_boundary_is_deeply_immutable_and_rejects_raw_containers(self) -> None:
        projection_input = certified_input()
        with self.assertRaises(FrozenInstanceError):
            projection_input.metadata = projection_input.metadata  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            projection_input.frontstage.fields = ()  # type: ignore[misc]
        with self.assertRaises(TypeError):
            ReportRecord([])  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            ReportField("raw", {"evidence": "forbidden"})  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            ReportField("nested", ({"decision": "forbidden"},))  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            ReportField("filesystem_handle", MODULE_PATH)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            CertifiedReportProjectionInput(
                metadata=projection_input.metadata,
                bindings=projection_input.bindings,
                blockbeats_cards=[],  # type: ignore[arg-type]
                frontstage=projection_input.frontstage,
                maker_summary=projection_input.maker_summary,
                main_summary=projection_input.main_summary,
                audit=projection_input.audit,
            )

    def test_report_bindings_require_the_exact_canonical_section_paths(self) -> None:
        source = certified_input()
        with self.assertRaisesRegex(ValueError, "exactly cover"):
            ReportBindings(
                schema_version=REGISTRY.report_bindings_schema_version,
                sections=(),
            )
        with self.assertRaisesRegex(ValueError, "exactly cover"):
            ReportBindings(
                schema_version=REGISTRY.report_bindings_schema_version,
                sections=source.bindings.sections[:-1],
            )
        wrong_path = list(source.bindings.sections)
        wrong_path[1] = ReportSectionBinding(
            section_id="frontstage",
            model_path=("frontstage", "unexpected"),
        )
        with self.assertRaisesRegex(ValueError, "exactly cover"):
            ReportBindings(
                schema_version=REGISTRY.report_bindings_schema_version,
                sections=tuple(wrong_path),
            )

    def test_to_plain_is_ordered_deterministic_and_returns_fresh_values(self) -> None:
        projection_input = certified_input()
        first = to_plain(projection_input)
        second = to_plain(projection_input)

        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        self.assertEqual(
            list(first),  # type: ignore[arg-type]
            [
                "metadata",
                "bindings",
                "blockbeats_cards",
                "frontstage",
                "maker_summary",
                "main_summary",
                "audit",
            ],
        )
        self.assertEqual(
            list(first["frontstage"]),  # type: ignore[index]
            ["opening_quote", "maker_strategy"],
        )
        self.assertEqual(
            first["maker_summary"]["entry_reach_probability"],  # type: ignore[index]
            "42.50",
        )

        first["frontstage"]["opening_quote"] = "mutated copy"  # type: ignore[index]
        self.assertEqual(
            second["frontstage"]["opening_quote"],  # type: ignore[index]
            "认证后的开场判断",
        )

    def test_projected_report_contains_only_in_memory_typed_outputs(self) -> None:
        value = ProjectedReport(
            model=record(("schema_version", "canonical-report-model-v11")),
            markdown="# 认证报告\n",
            cards_spec=record(
                ("schema_version", "blockbeats-cards-vnext-v1"),
                ("cards", ()),
            ),
        )
        self.assertEqual(
            to_plain(value),
            {
                "model": {"schema_version": "canonical-report-model-v11"},
                "markdown": "# 认证报告\n",
                "cards_spec": {
                    "schema_version": "blockbeats-cards-vnext-v1",
                    "cards": [],
                },
            },
        )

    def test_pure_projector_round_trips_the_certified_sections_exactly(self) -> None:
        source = certified_input()
        first = project_canonical_report_model(source)
        projected_bindings = project_report_bindings(source)
        certified_again = certify_canonical_report_model(
            first,
            bindings=source.bindings,
        )
        second = project_canonical_report_model(certified_again)
        self.assertEqual(first, second)
        self.assertEqual(
            project_report_bindings(certified_again),
            projected_bindings,
        )
        self.assertEqual(first["model_sha256"], second["model_sha256"])
        self.assertEqual(
            tuple(
                (item["section_id"], tuple(item["model_path"]))
                for item in projected_bindings["sections"]
            ),
            REGISTRY.report_binding_section_model_paths,
        )
        self.assertEqual(first["schema_version"], "canonical-report-model-v11")
        self.assertEqual(
            project_blockbeats_cards_spec(source),
            {
                "schema_version": "blockbeats-cards-vnext-v1",
                "trading_date": "2026-08-01",
                "slot": "midday",
                "evidence_snapshot_sha256": "e" * 64,
                "cards": [{"event_id": "event-1", "importance": 3}],
            },
        )

    def test_certifier_accepts_persisted_sort_order_without_changing_hash(self) -> None:
        original = project_canonical_report_model(certified_input())
        persisted_order = dict(sorted(original.items()))

        projected = project_canonical_report_model(
            certify_canonical_report_model(
                persisted_order,
                bindings=certified_input().bindings,
            )
        )

        self.assertEqual(projected, original)
        self.assertEqual(projected["model_sha256"], original["model_sha256"])

    def test_certifier_rejects_metadata_type_coercion(self) -> None:
        invalid = copy.deepcopy(project_canonical_report_model(certified_input()))
        invalid["run_id"] = 7
        clean = dict(invalid)
        clean.pop("model_sha256")
        invalid["model_sha256"] = canonical_sha256(clean)

        with self.assertRaisesRegex(TypeError, "run_id"):
            certify_canonical_report_model(
                invalid,
                bindings=certified_input().bindings,
            )

    def test_certifier_requires_explicit_current_bindings(self) -> None:
        model = project_canonical_report_model(certified_input())
        with self.assertRaises(TypeError):
            certify_canonical_report_model(model)  # type: ignore[call-arg]
        with self.assertRaisesRegex(ValueError, "schema differs"):
            certify_canonical_report_model(
                model,
                bindings=ReportBindings(
                    schema_version="legacy-report-bindings-v0",
                    sections=certified_input().bindings.sections,
                ),
            )

    def test_report_bindings_cover_section_claim_observation_and_evidence_dag(self) -> None:
        reasoning = {
            "observations": [
                {
                    "id": "obs_bb",
                    "source": "BlockBeats",
                    "evidence_refs": ["capture/blockbeats.json"],
                },
                {
                    "id": "obs_tv",
                    "source": "TradingView",
                    "evidence_refs": ["capture/tradingview.png"],
                },
            ],
            "claims": [
                {
                    "id": "shared_context",
                    "account": "shared",
                    "support_ids": ["obs_bb", "obs_tv"],
                    "counter_ids": [],
                },
                {
                    "id": "main_thesis",
                    "account": "main",
                    "support_ids": ["shared_context"],
                    "counter_ids": [],
                },
                {
                    "id": "maker_thesis",
                    "account": "maker",
                    "support_ids": ["obs_tv"],
                    "counter_ids": [],
                },
            ],
        }

        bindings = build_report_bindings(reasoning)
        by_id = {item.section_id: item for item in bindings.sections}

        self.assertEqual(
            tuple(by_id),
            (
                "blockbeats_cards",
                "frontstage",
                "maker_summary",
                "main_summary",
                "audit",
            ),
        )
        self.assertEqual(
            by_id["main_summary"].claim_ids,
            ("shared_context", "main_thesis"),
        )
        self.assertEqual(
            by_id["main_summary"].observation_ids,
            ("obs_bb", "obs_tv"),
        )
        self.assertEqual(
            by_id["main_summary"].evidence_refs,
            ("capture/blockbeats.json", "capture/tradingview.png"),
        )
        self.assertEqual(by_id["maker_summary"].claim_ids, ("maker_thesis",))
        self.assertEqual(
            by_id["audit"].claim_ids,
            ("shared_context", "main_thesis", "maker_thesis"),
        )


if __name__ == "__main__":
    unittest.main()
