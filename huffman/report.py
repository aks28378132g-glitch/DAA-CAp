"""Turns engine results into JSON-friendly reports (used by the CLI and web UI)."""

from __future__ import annotations

import math
from typing import Any, Dict, Optional, Tuple

from .core import Node, code_string


def symbol_label(b: int) -> str:
    """Human-readable label for a byte symbol."""
    special = {0x20: "SPACE", 0x0A: "\\n", 0x0D: "\\r", 0x09: "\\t"}
    if b in special:
        return special[b]
    if 0x21 <= b <= 0x7E:
        return chr(b)
    return f"0x{b:02X}"


def entropy(freq: Dict[int, int]) -> float:
    """Shannon entropy in bits per symbol (the theoretical lower bound)."""
    total = sum(freq.values())
    if not total:
        return 0.0
    return -sum((f / total) * math.log2(f / total) for f in freq.values())


def tree_to_dict(node: Optional[Node], bit: Optional[int] = None) -> Optional[Dict[str, Any]]:
    if node is None:
        return None
    d: Dict[str, Any] = {
        "freq": node.freq,
        "symbol": node.symbol,
        "label": symbol_label(node.symbol) if node.symbol is not None else None,
        "bit": bit,
    }
    children = []
    if node.left is not None:
        children.append(tree_to_dict(node.left, 0))
    if node.right is not None:
        children.append(tree_to_dict(node.right, 1))
    d["children"] = children
    return d


def build_report(
    *,
    data_size: int,
    compressed_size: int,
    freq: Dict[int, int],
    codes: Dict[int, Tuple[int, int]],
    root: Optional[Node],
    header_size: int,
    padding: int,
    sha256_hex: str,
    encode_ms: Optional[float],
    decode_ms: Optional[float],
    stage_ms: Optional[Dict[str, float]],
    verified: bool,
) -> Dict[str, Any]:
    total = sum(freq.values())
    table = []
    for symbol, (code, length) in codes.items():
        f = freq.get(symbol, 0)
        table.append(
            {
                "symbol": symbol,
                "label": symbol_label(symbol),
                "hex": f"0x{symbol:02X}",
                "freq": f,
                "percent": (f / total * 100.0) if total else 0.0,
                "code": code_string(code, length),
                "length": length,
            }
        )
    table.sort(key=lambda r: (-r["freq"], r["symbol"]))
    avg_len = sum(freq.get(s, 0) * l for s, (_, l) in codes.items()) / total if total else 0.0
    return {
        "original_size": data_size,
        "compressed_size": compressed_size,
        "header_size": header_size,
        "payload_size": compressed_size - header_size,
        "padding_bits": padding,
        "ratio": (data_size / compressed_size) if compressed_size and data_size else None,
        "space_saved_percent": (1 - compressed_size / data_size) * 100.0 if data_size else 0.0,
        "encode_ms": encode_ms,
        "decode_ms": decode_ms,
        "stage_ms": stage_ms,
        "unique_symbols": len(codes),
        "avg_code_length": avg_len,
        "entropy": entropy(freq),
        "sha256": sha256_hex,
        "verified": verified,
        "table": table,
        "tree": tree_to_dict(root),
    }
