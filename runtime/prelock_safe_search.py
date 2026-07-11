"""Search only paths allowed by the daily-report pre-lock policy."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.prelock_read_policy import (
    AUTHORITY_EXACT,
    AUTHORITY_MARKDOWN_PREFIXES,
    assert_prelock_read_allowed,
)

def iter_safe_files(trading_date: str, slot: str, *, root: Path = ROOT):
    candidates: set[Path] = set()
    for relative in AUTHORITY_EXACT:
        candidates.add(root / relative)
    for prefix in AUTHORITY_MARKDOWN_PREFIXES:
        directory = root / prefix
        if directory.is_dir():
            candidates.update(directory.rglob("*.md"))
    agents = root / ".agents"
    if agents.is_dir():
        candidates.update(agents.rglob("*.md"))
    current = root / "runtime_state" / trading_date
    if current.is_dir():
        candidates.update(path for path in current.rglob("*") if path.is_file())
    candidates.add(root / "outputs" / f"{trading_date}_{slot}_combined.md")

    for path in sorted(candidates, key=lambda item: item.as_posix()):
        if not path.is_file():
            continue
        try:
            relative = assert_prelock_read_allowed(
                path,
                trading_date=trading_date,
                slot=slot,
                root=root,
            )
        except Exception:
            continue
        yield path, relative


def search(
    pattern: str,
    *,
    trading_date: str,
    slot: str,
    root: Path = ROOT,
    fixed_strings: bool = False,
    ignore_case: bool = False,
    max_results: int = 200,
) -> list[dict]:
    flags = re.IGNORECASE if ignore_case else 0
    expression = re.compile(re.escape(pattern) if fixed_strings else pattern, flags)
    results: list[dict] = []
    for path, relative in iter_safe_files(trading_date, slot, root=root):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(lines, 1):
            if expression.search(line):
                results.append({"path": relative, "line": number, "text": line})
                if len(results) >= max_results:
                    return results
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    parser.add_argument("--slot", required=True, choices=("morning", "midday", "evening"))
    parser.add_argument("--fixed-strings", action="store_true")
    parser.add_argument("--ignore-case", action="store_true")
    parser.add_argument("--max-results", type=int, default=200)
    parser.add_argument("pattern")
    args = parser.parse_args()
    if args.max_results < 1 or args.max_results > 1000:
        raise SystemExit("--max-results must be between 1 and 1000")
    try:
        matches = search(
            args.pattern,
            trading_date=args.date,
            slot=args.slot,
            fixed_strings=args.fixed_strings,
            ignore_case=args.ignore_case,
            max_results=args.max_results,
        )
    except re.error as exc:
        raise SystemExit(f"invalid regex: {exc}") from exc
    print(json.dumps({"count": len(matches), "matches": matches}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
