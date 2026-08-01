"""Offline verification for the approved 2026-06-22 through 2026-06-26 samples.

The verifier exposes hashes, counts, and structural invariants only.  Historical
prices, directions, scores, and prose never enter a production run context.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MARKERS: dict[str, tuple[str, ...]] = {
    "author_self_check": ("作者自查",),
    "frontstage": ("日报正文",),
    "cannot_do": ("不能做",),
    "fundamental": ("基本面",),
    "orderflow": ("盘口",),
    "chart": ("盘面",),
    "trend": ("趋势确认",),
    "maker": ("Maker 计划", "Maker计划"),
    "risk_reward": ("盈亏比",),
    "take_profit": ("止盈",),
    "stop_loss": ("止损",),
    "defense": ("浮盈防守",),
    "appendix": ("后附",),
    "score_detail": ("评分明细",),
    "score_70_30": ("70+30",),
    "source_support": ("五源支撑",),
    "mechanical_check": ("三问机械自检",),
    "winrate_calibration": ("胜率自估", "胜率自估反下偏自检"),
    "cannot_do_derivation": ("不能做推导",),
    "blockbeats": ("BlockBeats",),
    "exocharts": ("Exocharts",),
    "coinglass": ("Coinglass",),
    "fedwatch": ("FedWatch",),
    "tradingview": ("TradingView",),
    "vrvp": ("VRVP",),
    "liquidation_map": ("清算热力图", "清算地图"),
}
ORDERED_SECTIONS = ("frontstage", "maker", "appendix")
SEMANTIC_INVARIANTS = {
    "maker_entry_is_price_range",
    "defense_first_exact_trigger_price",
    "defense_second_exact_trigger_price",
    "defense_layers_are_not_generic_formula_only",
}

_ARABIC_PRICE = r"(?:\d{1,3}(?:,\d{3})+|\d{2,}(?:\.\d+)?)"


def semantic_invariants(paragraphs: list[str]) -> dict[str, bool]:
    """Return semantic-shape booleans without exposing historical market values."""

    maker_lines = [
        text
        for text in paragraphs
        if re.search(r"(?:反弹空|高空|低多)[:：]", text)
    ]
    first_lines = [text for text in paragraphs if text.startswith("第一层")]
    second_lines = [text for text in paragraphs if text.startswith("第二层")]
    entry_range = re.compile(rf"{_ARABIC_PRICE}\s*[-–—]\s*{_ARABIC_PRICE}")
    first_trigger = re.compile(rf"(?:价格)?触及\s*{_ARABIC_PRICE}.*?1\.5\s*R", re.IGNORECASE)
    second_trigger = re.compile(rf"(?:价格)?触及\s*{_ARABIC_PRICE}.*?2\s*R", re.IGNORECASE)
    generic_only = re.compile(
        r"(?:实际加权成交价|weighted_fill).*?(?:\+/-|±).*?(?:1\.5\s*R|2\s*R)",
        re.IGNORECASE,
    )
    return {
        "maker_entry_is_price_range": any(entry_range.search(text) for text in maker_lines),
        "defense_first_exact_trigger_price": any(first_trigger.search(text) for text in first_lines),
        "defense_second_exact_trigger_price": any(second_trigger.search(text) for text in second_lines),
        "defense_layers_are_not_generic_formula_only": bool(first_lines and second_lines)
        and not any(generic_only.search(text) for text in (*first_lines, *second_lines)),
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _extract_paragraphs(path: Path) -> list[str]:
    try:
        with zipfile.ZipFile(path) as archive:
            document = ElementTree.fromstring(archive.read("word/document.xml"))
    except (KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise ValueError(f"invalid DOCX package: {path.name}") from exc
    paragraphs = []
    for paragraph in document.iter(WORD_NAMESPACE + "p"):
        text = "".join(
            node.text or "" for node in paragraph.iter(WORD_NAMESPACE + "t")
        ).strip()
        if text:
            paragraphs.append(text)
    return paragraphs


def inspect_docx(path: Path) -> dict[str, Any]:
    """Return non-semantic metadata and structural marker results only."""

    path = path.resolve()
    paragraphs = _extract_paragraphs(path)
    joined = "\n".join(paragraphs)
    marker_presence = {
        name: any(marker in joined for marker in markers)
        for name, markers in MARKERS.items()
    }
    positions = {
        name: min(
            (joined.find(marker) for marker in MARKERS[name] if marker in joined),
            default=-1,
        )
        for name in ORDERED_SECTIONS
    }
    order_valid = all(
        positions[left] >= 0 and positions[left] < positions[right]
        for left, right in zip(ORDERED_SECTIONS, ORDERED_SECTIONS[1:])
    )
    return {
        "file": path.name,
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
        "paragraphs": len(paragraphs),
        "markers": marker_presence,
        "section_order_valid": order_valid,
        "semantic_invariants": semantic_invariants(paragraphs),
    }


def load_contract(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "golden-sample-contract-v1":
        raise ValueError("invalid golden sample contract")
    samples = payload.get("samples")
    if not isinstance(samples, list) or len(samples) != payload.get("sample_count"):
        raise ValueError("golden sample count mismatch")
    if sum(item.get("page_count", 0) for item in samples) != payload.get("total_pages"):
        raise ValueError("golden sample page count mismatch")
    return payload


def verify_directory(sample_dir: Path, contract_path: Path) -> dict[str, Any]:
    """Verify exact approved files without exposing their narrative content."""

    contract = load_contract(contract_path)
    required = contract.get("required_markers") or []
    if not isinstance(required, list) or any(name not in MARKERS for name in required):
        raise ValueError("golden sample required_markers is invalid")
    required_semantics = contract.get("required_semantic_invariants") or []
    if (
        not isinstance(required_semantics, list)
        or any(name not in SEMANTIC_INVARIANTS for name in required_semantics)
    ):
        raise ValueError("golden sample required_semantic_invariants is invalid")
    failures: list[dict[str, str]] = []
    for expected in contract["samples"]:
        name = str(expected.get("file", ""))
        if not re.fullmatch(r"[A-Za-z0-9_.-]+\.docx", name):
            raise ValueError("golden sample filename is invalid")
        target = (sample_dir / name).resolve()
        try:
            target.relative_to(sample_dir.resolve())
        except ValueError as exc:
            raise ValueError("golden sample path escapes sample directory") from exc
        if not target.is_file():
            failures.append({"file": name, "code": "file_missing"})
            continue
        actual = inspect_docx(target)
        for field in ("sha256", "bytes", "paragraphs"):
            if actual[field] != expected.get(field):
                failures.append({"file": name, "code": f"{field}_mismatch"})
        for marker in required:
            if not actual["markers"].get(marker):
                failures.append({"file": name, "code": f"marker_missing:{marker}"})
        for invariant in required_semantics:
            if not actual["semantic_invariants"].get(invariant):
                failures.append(
                    {"file": name, "code": f"semantic_invariant_missing:{invariant}"}
                )
        if not actual["section_order_valid"]:
            failures.append({"file": name, "code": "section_order_invalid"})
    visual = contract.get("visual_qa") or {}
    visual_attested = all(
        visual.get(field) is True
        for field in (
            "all_pages_inspected",
            "layout_pass",
            "no_clipping_or_overlap",
            "no_missing_glyphs",
        )
    )
    return {
        "schema_version": "golden-sample-verification-v1",
        "passed": not failures and visual_attested,
        "sample_count": contract["sample_count"],
        "total_pages": contract["total_pages"],
        "content_structure_verified": not failures,
        "visual_qa_attested": visual_attested,
        "failure_count": len(failures),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify approved Word golden samples")
    parser.add_argument("--sample-dir", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    args = parser.parse_args()
    result = verify_directory(args.sample_dir, args.contract)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
