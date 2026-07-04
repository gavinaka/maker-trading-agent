"""Generate BlockBeats cards from a parameter file.

This replaces date-specific executable scripts. The JSON contains content only;
all visual behavior remains in blockbeats_card.make_card.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from blockbeats_card import make_card


def generate(spec_path: Path) -> list[str]:
    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    cards = payload.get("cards")
    if not isinstance(cards, list) or len(cards) != 3:
        raise ValueError("card spec must contain exactly three cards")

    outputs: list[str] = []
    required = {"filename", "time", "title", "body"}
    for index, card in enumerate(cards, start=1):
        if not isinstance(card, dict) or not required.issubset(card):
            missing = sorted(required - set(card if isinstance(card, dict) else {}))
            raise ValueError(f"card {index} missing fields: {missing}")
        outputs.append(
            make_card(
                str(card["filename"]),
                str(card["time"]),
                str(card["title"]),
                str(card["body"]),
            )
        )
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate exactly three BlockBeats cards")
    parser.add_argument("spec", type=Path)
    args = parser.parse_args()
    for output in generate(args.spec.resolve()):
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
