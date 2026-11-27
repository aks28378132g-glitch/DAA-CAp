"""File-level helpers shared by the CLI and benchmark."""

from __future__ import annotations

import os
import tempfile
from typing import Optional, Tuple

from .core import (
    CompressionResult,
    DecompressionResult,
    compress_detailed,
    decompress_detailed,
)


def default_compressed_path(src: str) -> str:
    return src + ".huff"


def default_decompressed_path(src: str) -> str:
    """``notes.txt.huff`` -> ``notes.restored.txt`` (never clobbers the original)."""
    base = src[:-5] if src.lower().endswith(".huff") else src
    root, ext = os.path.splitext(base)
    return f"{root}.restored{ext or '.txt'}"


def _atomic_write(path: str, data: bytes) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".huff-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _check_distinct(src: str, dst: str) -> None:
    if os.path.abspath(src) == os.path.abspath(dst):
        raise ValueError("output path must differ from input path")


def compress_file(src: str, dst: Optional[str] = None) -> Tuple[str, CompressionResult]:
    dst = dst or default_compressed_path(src)
    _check_distinct(src, dst)
    with open(src, "rb") as fh:
        data = fh.read()
    result = compress_detailed(data)
    _atomic_write(dst, result.blob)
    return dst, result


def decompress_file(src: str, dst: Optional[str] = None) -> Tuple[str, DecompressionResult]:
    dst = dst or default_decompressed_path(src)
    _check_distinct(src, dst)
    with open(src, "rb") as fh:
        blob = fh.read()
    result = decompress_detailed(blob)
    _atomic_write(dst, result.data)
    return dst, result
