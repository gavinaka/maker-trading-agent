"""Shared immutable validation results and dependency-light helpers."""

from __future__ import annotations

import re
import struct
import zlib
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from itertools import combinations
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ..methodology import canonical_sha256, sha256_file


@dataclass(frozen=True)
class Defect:
    code: str
    message: str
    path: str = ""
    severity: str = "hard"


@dataclass(frozen=True)
class GateResult:
    gate: str
    passed: bool
    defects: tuple[Defect, ...]
    facts: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"gate": self.gate, "passed": self.passed, "defects": [asdict(item) for item in self.defects], "facts": self.facts}


def gate_result(gate: str, defects: list[Defect], **facts: Any) -> GateResult:
    return GateResult(gate, not defects, tuple(defects), facts)


@runtime_checkable
class SemanticIssueLike(Protocol):
    code: str
    message: str
    path: str


DefectLike = Defect
GateResultLike = GateResult


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""

def _contains_cjk(value: Any) -> bool:
    return bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", _text(value)))

def _nested_value(payload: Any, field: str) -> tuple[bool, Any]:
    current = payload
    for part in field.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current

def _typed_domain_contains(allowed_values: Any, value: Any) -> bool:
    """Match a closed JSON-domain value without bool/int coercion or hashing."""

    return any(
        type(value) is type(allowed) and value == allowed
        for allowed in allowed_values
    )

def _canonical_closed_string(value: Any) -> bool:
    """Require an exact, non-empty string for closed-schema identifiers."""

    return isinstance(value, str) and bool(value) and value == value.strip()

def _typed_domain_intersection(left: list[Any], right: list[Any]) -> list[Any]:
    """Intersect JSON-domain values without bool/int coercion or hashing."""

    return [value for value in left if _typed_domain_contains(right, value)]

def _reachable_trigger_owners(
    support_ids: list[Any],
    observations: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
) -> set[str]:
    reachable: set[str] = set()
    stack = [_text(item) for item in support_ids if _text(item)]
    while stack:
        node_id = stack.pop()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        if node_id in claims:
            stack.extend(
                _text(item)
                for item in claims[node_id].get("support_ids", [])
                if _text(item)
            )
    return reachable & (set(observations) | set(claims))

def _is_iso_datetime(value: Any) -> bool:
    return _parse_iso_datetime(value) is not None

def _parse_iso_datetime(value: Any) -> datetime | None:
    try:
        result = datetime.fromisoformat(_text(value).replace("Z", "+00:00"))
        return result if result.tzinfo is not None else None
    except (ValueError, TypeError):
        return None

def _number(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() else None

def _json_number(value: Any) -> Decimal | None:
    """Return a finite JSON number without accepting numeric strings/bools."""

    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    return _number(value)

def _canonical_positive_decimal_string(value: Any) -> Decimal | None:
    """Decode the authority's unique, positive fixed-point string encoding."""

    if not isinstance(value, str) or re.fullmatch(
        r"^(0|[1-9][0-9]*)(\.[0-9]*[1-9])?$",
        value,
    ) is None:
        return None
    result = _number(value)
    if result is None or result <= 0:
        return None
    if format(result.normalize(), "f") != value:
        return None
    return result

def _decimal_matches(
    actual: Decimal | None,
    expected: Decimal | None,
    *,
    tolerance: Decimal = Decimal("0.00000001"),
) -> bool:
    return (
        actual is not None
        and expected is not None
        and abs(actual - expected) <= tolerance
    )

def _resolve_concrete_value_path(value: Any, path: str) -> Any:
    """Resolve a closed dotted path with concrete zero-based array indexes."""

    current = value
    for part in path.split("."):
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)(?:\[(\d+)\])?", part)
        if match is None or not isinstance(current, dict):
            raise ValueError("source field is not a concrete certified value path")
        key, raw_index = match.groups()
        if key not in current:
            raise ValueError("source field does not exist in the certified observation")
        current = current[key]
        if raw_index is not None:
            index = int(raw_index)
            if not isinstance(current, list) or index >= len(current):
                raise ValueError("source field array index is outside the certified observation")
            current = current[index]
    return current

def _matches_policy_path(path: str, patterns: list[Any]) -> bool:
    for pattern_value in patterns:
        pattern = re.escape(_text(pattern_value)).replace(r"\[\*\]", r"\[\d+\]")
        if re.fullmatch(pattern, path):
            return True
    return False

def _round_to_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step

def maker_fill_scenarios(
    *,
    entries: list[Decimal],
    allocations: list[Decimal],
    direction: str,
    stop: Decimal,
    tp1: Decimal,
    tp2: Decimal,
    leverage: Decimal,
) -> list[dict[str, str]]:
    scenarios: list[dict[str, str]] = []
    for size in range(1, len(entries) + 1):
        for indexes in combinations(range(len(entries)), size):
            weight = sum((allocations[index] for index in indexes), Decimal("0"))
            weighted_entry = sum(
                (entries[index] * allocations[index] for index in indexes),
                Decimal("0"),
            ) / weight
            risk = (
                weighted_entry - stop
                if direction == "long"
                else stop - weighted_entry
            )
            reward = (
                tp1 - weighted_entry
                if direction == "long"
                else weighted_entry - tp1
            )
            reward_tp2 = (
                tp2 - weighted_entry
                if direction == "long"
                else weighted_entry - tp2
            )
            if risk <= 0 or reward <= 0 or reward_tp2 <= reward:
                raise ValueError(
                    "entry/stop/tp1/tp2 geometry conflicts with direction"
                )
            scenarios.append(
                {
                    "risk_scenario_id": "fill-" + "-".join(
                        str(index + 1) for index in indexes
                    ),
                    "filled_level_indexes": [index + 1 for index in indexes],
                    "filled_levels": ",".join(str(index + 1) for index in indexes),
                    "entry": format(weighted_entry.normalize(), "f"),
                    "rr_to_tp1": format((reward / risk).normalize(), "f"),
                    "rr_to_tp2": format((reward_tp2 / risk).normalize(), "f"),
                    "nominal_risk_pct": format(
                        (risk / weighted_entry * leverage * Decimal("100")).normalize(),
                        "f",
                    ),
                }
            )
    return scenarios

def _record_paths(source_payload: dict[str, Any]) -> list[dict[str, Any]]:
    records = source_payload.get("artifacts")
    if not isinstance(records, list):
        single = source_payload.get("artifact")
        records = [single] if isinstance(single, dict) else []
    return [item for item in records if isinstance(item, dict)]

def _validate_file_record(
    record: dict[str, Any],
    *,
    path: str,
    defects: list[Defect],
    root: Path | None,
) -> None:
    relative = _text(record.get("path"))
    digest = _text(record.get("sha256"))
    size = record.get("bytes")
    if not relative:
        defects.append(Defect("artifact.path_missing", "artifact path is required", path))
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        defects.append(Defect("artifact.hash_invalid", "artifact sha256 is invalid", path))
    if not isinstance(size, int) or size <= 0:
        defects.append(Defect("artifact.bytes_invalid", "artifact byte count must be positive", path))
    if root is None or not relative:
        return
    try:
        target = (root / relative).resolve()
        target.relative_to(root.resolve())
    except (ValueError, OSError):
        defects.append(Defect("artifact.path_escape", "artifact path escapes the evidence root", path))
        return
    if not target.is_file():
        defects.append(Defect("artifact.file_missing", "artifact file is missing", path))
        return
    if re.fullmatch(r"[0-9a-f]{64}", digest) and sha256_file(target) != digest:
        defects.append(Defect("artifact.hash_mismatch", "artifact bytes differ from recorded sha256", path))
    if isinstance(size, int) and target.stat().st_size != size:
        defects.append(Defect("artifact.size_mismatch", "artifact bytes differ from recorded size", path))

def _valid_png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("invalid PNG signature")
    offset = 8
    width = height = 0
    saw_ihdr = saw_idat = saw_iend = False
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        data_start = offset + 8
        data_end = data_start + length
        crc_end = data_end + 4
        if crc_end > len(data):
            raise ValueError("truncated PNG chunk")
        chunk_data = data[data_start:data_end]
        recorded_crc = struct.unpack(">I", data[data_end:crc_end])[0]
        calculated_crc = zlib.crc32(chunk_type)
        calculated_crc = zlib.crc32(chunk_data, calculated_crc) & 0xFFFFFFFF
        if recorded_crc != calculated_crc:
            raise ValueError("invalid PNG chunk CRC")
        if chunk_type == b"IHDR":
            if saw_ihdr or length != 13 or offset != 8:
                raise ValueError("invalid PNG IHDR")
            width, height = struct.unpack(">II", chunk_data[:8])
            saw_ihdr = True
        elif chunk_type == b"IDAT":
            saw_idat = True
        elif chunk_type == b"IEND":
            if length != 0:
                raise ValueError("invalid PNG IEND")
            saw_iend = True
            offset = crc_end
            break
        offset = crc_end
    if not (saw_ihdr and saw_idat and saw_iend and width > 0 and height > 0):
        raise ValueError("incomplete PNG")
    if any(byte not in b"\x00\t\n\r " for byte in data[offset:]):
        raise ValueError("unexpected bytes after PNG IEND")
    return width, height

__all__ = ["Defect", "DefectLike", "GateResult", "GateResultLike", "SemanticIssueLike", "gate_result", "maker_fill_scenarios"]
