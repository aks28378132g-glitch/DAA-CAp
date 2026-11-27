#!/usr/bin/env python3
"""Automated benchmark: generates sample files, compresses, decompresses, verifies.

    python benchmark.py                 # Small / Medium / Large English-like text
    python benchmark.py --extended      # + repetitive, random, Unicode, single-char, empty
    python benchmark.py --repeat 5 --markdown --output benchmark_results.md
"""

from __future__ import annotations

import argparse
import hashlib
import os
import random
import sys
from typing import Callable, Dict, List, Tuple

from huffman import compress_detailed, decompress_detailed

WORDS = (
    "the of and to in is that it was for on are as with his they at be this from "
    "have or by one had not but what all were when we there can an your which their "
    "said if do will each about how up out them then she many some so these would "
    "other into has more her two like him see time could no make than first been "
    "its who now people my made over did down only way find use may water long little "
    "very after words called just where most know get through back much before go good "
    "new write our used me man too any day same right look think also around another "
    "came come work three word must because does part even place well such here take "
    "why help put different away again off went old number great tell men say small "
    "every found still between name should home big give air line set own under read "
    "last never us left end along while might next sound below saw something thought "
    "both few those always show large often together asked house don't world going want "
    "school important until form food keep children feet land side without boy once "
    "animal life enough took sometimes four head above kind began almost live page got "
    "earth need far hand high year mother light country father let night picture being "
    "study second soon story since white ever paper hard near sentence better best across "
    "during today however sure knew try told young sun thing whole hear example heard "
    "several change answer room sea against top turned learn point city play toward five "
    "using himself usually money seen didn't car morning body upon family later turn "
    "move face door cut done group true leave color red friend pull dark compress huffman "
    "algorithm tree symbol frequency encode decode binary storage"
).split()

UNICODE_WORDS = [
    "héllo", "wörld", "naïve", "façade", "señor", "こんにちは", "世界", "日本語", "привет",
    "мир", "спасибо", "مرحبا", "שלום", "你好", "谢谢", "안녕하세요", "γειά", "σου",
    "🙂", "🚀", "✨", "→", "€", "—", "“quoted”",
]


def gen_english(size: int, seed: int = 42) -> bytes:
    rng = random.Random(seed)
    weights = [1.0 / (i + 1) for i in range(len(WORDS))]  # Zipf-like word frequencies
    out: List[str] = []
    total = 0
    sentence_count = 0
    while total < size:
        n = rng.randint(5, 15)
        words = rng.choices(WORDS, weights, k=n)
        words[0] = words[0].capitalize()
        s = " ".join(words) + rng.choice([".", ".", ".", "!", "?"]) + " "
        sentence_count += 1
        if sentence_count % 6 == 0:
            s = s.rstrip() + "\n\n"
        out.append(s)
        total += len(s)
    return "".join(out).encode("ascii")[:size]


def gen_repetitive(size: int) -> bytes:
    return (b"abcabcabd the quick brown fox\n" * (size // 29 + 1))[:size]


def gen_random(size: int, seed: int = 7) -> bytes:
    rng = random.Random(seed)
    return bytes(rng.randrange(32, 127) for _ in range(size))


def gen_unicode(size: int, seed: int = 11) -> bytes:
    rng = random.Random(seed)
    text = []
    n = 0
    while n < size:
        w = rng.choice(UNICODE_WORDS) + " "
        text.append(w)
        n += len(w.encode("utf-8"))
    return "".join(text).encode("utf-8")[:size].decode("utf-8", "ignore").encode("utf-8")


def gen_single(size: int) -> bytes:
    return b"A" * size


Case = Tuple[str, Callable[[], bytes]]
STANDARD: List[Case] = [
    ("Small (~1 KB)", lambda: gen_english(1024)),
    ("Medium (~50 KB)", lambda: gen_english(50 * 1024)),
    ("Large (~500 KB)", lambda: gen_english(500 * 1024)),
]
EXTENDED: List[Case] = [
    ("Repetitive (~100 KB)", lambda: gen_repetitive(100 * 1024)),
    ("Random ASCII (~100 KB)", lambda: gen_random(100 * 1024)),
    ("Unicode mix (~100 KB)", lambda: gen_unicode(100 * 1024)),
    ("Single char (~10 KB)", lambda: gen_single(10 * 1024)),
    ("Empty file", lambda: b""),
]


def human(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.2f} MB"


def run_case(name: str, data: bytes, directory: str, repeat: int) -> Dict[str, object]:
    slug = "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")
    txt_path = os.path.join(directory, f"{slug}.txt")
    huff_path = os.path.join(directory, f"{slug}.txt.huff")
    with open(txt_path, "wb") as fh:
        fh.write(data)

    with open(txt_path, "rb") as fh:  # read back from disk like a real user would
        source = fh.read()
    enc_times, dec_times = [], []
    for _ in range(repeat):
        res = compress_detailed(source)
        enc_times.append(res.encode_ms)
    with open(huff_path, "wb") as fh:
        fh.write(res.blob)
    with open(huff_path, "rb") as fh:
        blob = fh.read()
    for _ in range(repeat):
        dec = decompress_detailed(blob)
        dec_times.append(dec.decode_ms)

    original_bytes = os.path.getsize(txt_path)
    compressed_bytes = os.path.getsize(huff_path)
    lossless = (
        dec.data == source
        and hashlib.sha256(dec.data).hexdigest() == hashlib.sha256(source).hexdigest()
    )
    saved = (1 - compressed_bytes / original_bytes) * 100 if original_bytes else 0.0
    return {
        "name": name,
        "file_size": human(original_bytes),
        "original": original_bytes,
        "compressed": compressed_bytes,
        "saved": saved,
        "encode_ms": min(enc_times),
        "decode_ms": min(dec_times),
        "lossless": lossless,
    }


HEADERS = ["Case", "File Size", "Original Bytes", "Compressed Bytes",
           "Space Saved (%)", "Encode (ms)", "Decode (ms)", "Lossless"]


def rows_of(results: List[Dict[str, object]]) -> List[List[str]]:
    return [
        [
            str(r["name"]), str(r["file_size"]), f"{r['original']:,}", f"{r['compressed']:,}",
            f"{r['saved']:.2f}", f"{r['encode_ms']:.2f}", f"{r['decode_ms']:.2f}",
            "PASS" if r["lossless"] else "FAIL",
        ]
        for r in results
    ]


def render_text(rows: List[List[str]]) -> str:
    widths = [max(len(HEADERS[i]), *(len(r[i]) for r in rows)) for i in range(len(HEADERS))]
    def fmt(cells: List[str]) -> str:
        return "| " + " | ".join(
            c.ljust(widths[i]) if i == 0 else c.rjust(widths[i]) for i, c in enumerate(cells)
        ) + " |"
    sep = "+-" + "-+-".join("-" * w for w in widths) + "-+"
    return "\n".join([sep, fmt(HEADERS), sep, *(fmt(r) for r in rows), sep])


def render_markdown(rows: List[List[str]]) -> str:
    lines = ["| " + " | ".join(HEADERS) + " |",
             "|:--|" + "|".join("--:" for _ in HEADERS[1:]) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Huffman compression benchmark")
    ap.add_argument("--extended", action="store_true", help="include edge/stress cases")
    ap.add_argument("--repeat", type=int, default=3, help="runs per case; best time is reported")
    ap.add_argument("--dir", default="benchmark_data", help="where sample files are written")
    ap.add_argument("--markdown", action="store_true", help="print a Markdown table")
    ap.add_argument("--output", help="also save the table to this file")
    args = ap.parse_args()

    os.makedirs(args.dir, exist_ok=True)
    cases = STANDARD + (EXTENDED if args.extended else [])
    results = []
    for name, gen in cases:
        print(f"running: {name} ...", file=sys.stderr)
        results.append(run_case(name, gen(), args.dir, max(1, args.repeat)))
    rows = rows_of(results)
    table = render_markdown(rows) if args.markdown else render_text(rows)
    print()
    print(table)
    print(f"\nBest of {max(1, args.repeat)} runs. Sample files + .huff outputs are in ./{args.dir}/")
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(table + "\n")
    return 0 if all(r["lossless"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
