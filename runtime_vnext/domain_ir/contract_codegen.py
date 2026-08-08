"""Materialize or verify code-owned deterministic contract JSON views."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from runtime.golden_methodology import get_methodology_runtime_inventory

from ..methodology import load_scoring_policy
from .projection import (
    projected_report_presentation_contract,
    projected_scoring_contract,
    projected_v6_contract,
)


ROOT = Path(__file__).resolve().parents[2]
REASONING_CONTRACT_PATH = Path("scoring/reasoning_submission_contract.json")
SCORING_CONTRACT_PATH = Path("scoring/scoring_contract.json")
REPORT_PRESENTATION_CONTRACT_PATH = Path(
    "governance/vnext_report_presentation_contract.json"
)


def materialized_reasoning_contract(*, root: Path = ROOT) -> dict[str, object]:
    root = root.resolve()
    path = root / REASONING_CONTRACT_PATH
    current = json.loads(path.read_text(encoding="utf-8"))
    policy = load_scoring_policy(root=root)
    inventory = get_methodology_runtime_inventory(
        policy=policy["gold_methodology"],
        profile="vnext_submission",
    )
    return projected_v6_contract(
        current,
        methodology_leaf_ownership=inventory["leaf_ownership"],
    )


def materialized_report_presentation_contract(
    *, root: Path = ROOT
) -> dict[str, object]:
    root = root.resolve()
    path = root / REPORT_PRESENTATION_CONTRACT_PATH
    current = json.loads(path.read_text(encoding="utf-8"))
    return projected_report_presentation_contract(current)


def contract_is_current(*, root: Path = ROOT) -> bool:
    root = root.resolve()
    current = json.loads(
        (root / REASONING_CONTRACT_PATH).read_text(encoding="utf-8")
    )
    scoring = json.loads((root / SCORING_CONTRACT_PATH).read_text(encoding="utf-8"))
    presentation = json.loads(
        (root / REPORT_PRESENTATION_CONTRACT_PATH).read_text(encoding="utf-8")
    )
    return (
        current == materialized_reasoning_contract(root=root)
        and scoring == projected_scoring_contract(scoring)
        and presentation == materialized_report_presentation_contract(root=root)
    )


def write_materialized_contracts(
    *, root: Path = ROOT
) -> tuple[Path, Path, Path]:
    root = root.resolve()
    path = root / REASONING_CONTRACT_PATH
    payload = materialized_reasoning_contract(root=root)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    scoring_path = root / SCORING_CONTRACT_PATH
    scoring = json.loads(scoring_path.read_text(encoding="utf-8"))
    scoring_path.write_text(
        json.dumps(
            projected_scoring_contract(scoring),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    presentation_path = root / REPORT_PRESENTATION_CONTRACT_PATH
    presentation_path.write_text(
        json.dumps(
            materialized_report_presentation_contract(root=root),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path, scoring_path, presentation_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="verify or materialize the vNext registry-owned JSON views"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    if args.check:
        if contract_is_current(root=args.root):
            print("vNext generated contract view is current")
            return 0
        print("vNext generated contract view is stale")
        return 1
    paths = write_materialized_contracts(root=args.root)
    print(
        ", ".join(
            path.relative_to(args.root.resolve()).as_posix() for path in paths
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
