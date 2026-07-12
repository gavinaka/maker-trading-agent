from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.host_capability import build_manifest, manifest_path, validate_manifest


class HostCapabilityTests(unittest.TestCase):
    def session(self, root: Path, effort: str) -> Path:
        path = root / "session.jsonl"
        items = [
            {"type": "session_meta", "payload": {"id": "thread-1", "cwd": str(root)}},
            {"type": "turn_context", "payload": {"turn_id": "turn-1", "cwd": str(root), "model": "gpt-test", "effort": effort}},
        ]
        path.write_text("\n".join(json.dumps(item) for item in items), encoding="utf-8")
        return path

    def test_actual_high_metadata_is_bound(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = build_manifest(
                "2026-07-12", "midday", session_jsonl=self.session(root, "high"), root=root
            )
            target = manifest_path("2026-07-12", "midday", root=root)
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps(payload), encoding="utf-8")
            validated = validate_manifest(target, "2026-07-12", "midday", root=root)
            self.assertEqual(validated["reasoning_effort"], "high")
            self.assertEqual(validated["minimum_effort"], "high")
            self.assertEqual(validated["model"], "gpt-test")

    def test_max_also_satisfies_high_minimum(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = build_manifest(
                "2026-07-12", "midday",
                session_jsonl=self.session(root, "max"), root=root,
            )
            self.assertEqual(payload["reasoning_effort"], "max")
            self.assertEqual(payload["minimum_effort"], "high")

    def test_prompt_claim_cannot_replace_below_high_host(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaisesRegex(ValueError, "actual=medium minimum=high"):
                build_manifest(
                    "2026-07-12", "midday", session_jsonl=self.session(root, "medium"), root=root
                )


if __name__ == "__main__":
    unittest.main()
