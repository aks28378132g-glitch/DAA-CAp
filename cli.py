#!/usr/bin/env python3
"""Command-line interface for the Huffman file compressor.

Examples:
    python cli.py compress notes.txt
    python cli.py decompress notes.txt.huff -o notes.out.txt
    python cli.py analyze notes.txt --top 20
    python cli.py verify notes.txt notes.txt.huff
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from typing import List, Optional

from huffman import HuffmanError, compress_detailed, decompress_detailed
from huffman.files import compress_file, decompress_file
from huffman.report import build_report


def _fmt_bytes(n: int) -> str:
    return f"{n:,} B"


def _print_summary(r: dict) -> None:
    ratio = f"{r['ratio']:.3f}x" if r["ratio"] else "n/a"
    print(f"  Original size    : {_fmt_bytes(r['original_size'])}")
    print(f"  Compressed size  : {_fmt_bytes(r['compressed_size'])} "
          f"(header {r['header_size']} B + payload {r['payload_size']} B)")
    print(f"  Compression ratio: {ratio} (original / compressed)")
    print(f"  Space saved      : {r['space_saved_percent']:.2f} %")
    print(f"  Unique symbols   : {r['unique_symbols']}")
    print(f"  Avg code length  : {r['avg_code_length']:.4f} bits/symbol "
          f"(entropy {r['entropy']:.4f})")
    if r["encode_ms"] is not None:
        print(f"  Encode time      : {r['encode_ms']:.3f} ms")
    if r["decode_ms"] is not None:
        print(f"  Decode time      : {r['decode_ms']:.3f} ms")
    print(f"  SHA-256          : {r['sha256']}")


def _print_table(r: dict, top: Optional[int]) -> None:
    rows = r["table"][:top] if top else r["table"]
    print(f"\n  {'Symbol':<8}{'Hex':<7}{'Freq':>10}{'%':>9}  {'Len':>3}  Code")
    print("  " + "-" * 60)
    for row in rows:
        print(f"  {row['label']:<8}{row['hex']:<7}{row['freq']:>10,}"
              f"{row['percent']:>8.2f}%  {row['length']:>3}  {row['code']}")
    if top and len(r["table"]) > top:
        print(f"  ... {len(r['table']) - top} more symbols (use --top 0 for all)")


def cmd_compress(args: argparse.Namespace) -> int:
    dst, res = compress_file(args.input, args.output)
    dec = decompress_detailed(res.blob)  # verify + time decode
    with open(args.input, "rb") as fh:
        ok = fh.read() == dec.data
    report = build_report(
        data_size=res.original_size, compressed_size=len(res.blob), freq=res.freq,
        codes=res.codes, root=res.root, header_size=res.header_size,
        padding=res.padding, sha256_hex=res.sha256_hex, encode_ms=res.encode_ms,
        decode_ms=dec.decode_ms, stage_ms=res.stage_ms, verified=ok,
    )
    if args.json:
        report.pop("tree")
        print(json.dumps(report, indent=2))
        return 0 if ok else 2
    print(f"Compressed {args.input} -> {dst}")
    _print_summary(report)
    print(f"  Lossless check   : {'PASSED' if ok else 'FAILED'}")
    if args.table:
        _print_table(report, args.top)
    return 0 if ok else 2


def cmd_decompress(args: argparse.Namespace) -> int:
    dst, res = decompress_file(args.input, args.output)
    print(f"Decompressed {args.input} -> {dst}")
    print(f"  Restored size    : {_fmt_bytes(len(res.data))}")
    print(f"  Decode time      : {res.decode_ms:.3f} ms")
    print("  Integrity        : SHA-256 verified")
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    with open(args.input, "rb") as fh:
        data = fh.read()
    res = compress_detailed(data)
    dec = decompress_detailed(res.blob)
    report = build_report(
        data_size=res.original_size, compressed_size=len(res.blob), freq=res.freq,
        codes=res.codes, root=res.root, header_size=res.header_size,
        padding=res.padding, sha256_hex=res.sha256_hex, encode_ms=res.encode_ms,
        decode_ms=dec.decode_ms, stage_ms=res.stage_ms, verified=dec.data == data,
    )
    print(f"Analysis of {args.input} (nothing is written to disk)")
    _print_summary(report)
    _print_table(report, args.top)
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    with open(args.original, "rb") as fh:
        original = fh.read()
    with open(args.compressed, "rb") as fh:
        blob = fh.read()
    restored = decompress_detailed(blob).data
    same = hashlib.sha256(original).digest() == hashlib.sha256(restored).digest()
    print(f"Original  SHA-256: {hashlib.sha256(original).hexdigest()}")
    print(f"Restored  SHA-256: {hashlib.sha256(restored).hexdigest()}")
    print("Result: IDENTICAL (lossless)" if same else "Result: DIFFERENT")
    return 0 if same else 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="huffman", description="Huffman file compressor")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("compress", help="compress a file into .huff")
    c.add_argument("input")
    c.add_argument("-o", "--output", help="output path (default: INPUT.huff)")
    c.add_argument("--table", action="store_true", help="also print the code table")
    c.add_argument("--top", type=int, default=20, help="rows in the table (0 = all)")
    c.add_argument("--json", action="store_true", help="print the report as JSON")
    c.set_defaults(func=cmd_compress)

    d = sub.add_parser("decompress", help="restore a .huff file")
    d.add_argument("input")
    d.add_argument("-o", "--output", help="output path (default: NAME.restored.EXT)")
    d.set_defaults(func=cmd_decompress)

    a = sub.add_parser("analyze", help="show frequencies, codes and stats (no output file)")
    a.add_argument("input")
    a.add_argument("--top", type=int, default=20, help="rows in the table (0 = all)")
    a.set_defaults(func=cmd_analyze)

    v = sub.add_parser("verify", help="check a .huff file restores to the original")
    v.add_argument("original")
    v.add_argument("compressed")
    v.set_defaults(func=cmd_verify)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except HuffmanError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
