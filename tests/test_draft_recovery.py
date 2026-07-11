from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runtime import draft_recovery


class DraftRecoveryTests(unittest.TestCase):
    def fixture(self, root: Path):
        date = "2026-07-11"
        slot = "evening"
        outputs = root / "outputs"
        images_dir = outputs / "blockbeats"
        state = root / "runtime_state" / date
        images_dir.mkdir(parents=True)
        state.mkdir(parents=True)
        report = outputs / f"{date}_{slot}_combined.md"
        cards = outputs / f"{date}_{slot}_cards.json"
        capture = root / "evidence" / "snapshots" / date / slot / "capture_manifest.json"
        capture.parent.mkdir(parents=True)
        report.write_text("# certified draft\n", encoding="utf-8")
        capture.write_text('{"status":"ok"}\n', encoding="utf-8")
        images = []
        for index in range(3):
            image = images_dir / f"{date}_{slot}_{index}.png"
            image.write_bytes(f"image-{index}".encode())
            images.append(image)
        cards.write_text(
            json.dumps(
                {"cards": [{"filename": str(path.relative_to(root))} for path in images]}
            ),
            encoding="utf-8",
        )
        readiness = state / f"reasoning_readiness_{slot}.json"
        golden = state / f"golden_reasoning_{slot}.json"
        contract = state / f"report_contract_{slot}.json"
        for path in (readiness, golden, contract):
            path.write_text("{}\n", encoding="utf-8")
        readiness_payload = {"capture_manifest": {"path": str(capture.relative_to(root))}}
        return date, slot, report, cards, capture, readiness, golden, contract, readiness_payload

    def test_certified_draft_binds_every_recoverable_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            date, slot, report, cards, capture, readiness, golden, contract, ready = self.fixture(root)
            with mock.patch.object(
                draft_recovery,
                "validate_report_contract_manifest",
                return_value=({}, contract),
            ), mock.patch.object(
                draft_recovery,
                "validate_reasoning_readiness_manifest",
                return_value=(ready, readiness),
            ), mock.patch.object(
                draft_recovery,
                "validate_golden_reasoning_manifest",
                return_value=({}, golden),
            ):
                payload, target = draft_recovery.certify_draft_recovery(
                    date, slot, report=report, cards=cards, root=root
                )
                validated, validated_target = draft_recovery.validate_draft_recovery_manifest(
                    date, slot, report, root=root
                )
            self.assertEqual(validated, payload)
            self.assertEqual(validated_target, target)
            self.assertEqual(len(payload["images"]), 3)
            report.write_text("# changed after certification\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "report changed after certification"):
                draft_recovery.validate_recovery_draft_artifacts(
                    date, slot, capture, root=root
                )

    def test_reasoning_manifest_drift_blocks_recovery_preservation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            date, slot, report, cards, capture, readiness, golden, contract, ready = self.fixture(root)
            with mock.patch.object(
                draft_recovery,
                "validate_report_contract_manifest",
                return_value=({}, contract),
            ), mock.patch.object(
                draft_recovery,
                "validate_reasoning_readiness_manifest",
                return_value=(ready, readiness),
            ), mock.patch.object(
                draft_recovery,
                "validate_golden_reasoning_manifest",
                return_value=({}, golden),
            ):
                draft_recovery.certify_draft_recovery(
                    date, slot, report=report, cards=cards, root=root
                )
            readiness.write_text('{"changed":true}\n', encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError, "reasoning readiness changed after certification"
            ):
                draft_recovery.validate_recovery_draft_artifacts(
                    date, slot, capture, root=root
                )


if __name__ == "__main__":
    unittest.main()
