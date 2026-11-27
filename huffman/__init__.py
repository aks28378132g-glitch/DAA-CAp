"""Huffman coding file compression, implemented from scratch."""

from .core import (
    HuffmanError,
    MinHeap,
    Node,
    build_huffman_tree,
    canonical_codes,
    code_lengths,
    compress,
    compress_detailed,
    count_frequencies,
    decompress,
    decompress_detailed,
)

__all__ = [
    "HuffmanError",
    "MinHeap",
    "Node",
    "build_huffman_tree",
    "canonical_codes",
    "code_lengths",
    "compress",
    "compress_detailed",
    "count_frequencies",
    "decompress",
    "decompress_detailed",
]
__version__ = "1.0.0"
