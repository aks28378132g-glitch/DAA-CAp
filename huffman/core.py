"""Huffman coding engine implemented from scratch.

No compression libraries are used. The only standard-library helpers are
``struct`` (fixed-width header packing), ``hashlib`` (SHA-256 integrity
checksum) and ``time`` (timing).

Symbols are *bytes* (0-255), so any input -- ASCII, UTF-8 Unicode, even
arbitrary binary -- round-trips losslessly. A multi-byte UTF-8 character is
simply several symbols.

``.huff`` file layout (all integers big-endian)::

    offset  size  field
    ------  ----  -------------------------------------------------------
    0       4     magic            b"HUFF"
    4       1     format version   1
    5       1     padding bits     0-7 zero bits appended to the last byte
    6       8     original length  number of symbols (bytes) in the source
    14      2     symbol count K   0-256 distinct symbols
    16      32    SHA-256 of the original data
    48      2*K   table: (symbol, code length) pairs
    48+2K   ...   payload: the packed, MSB-first bitstream

Only code *lengths* are stored. Codes are assigned canonically (sorted by
length, then symbol value), so the decoder rebuilds exactly the same
prefix-free codes and Huffman tree without needing the frequencies.
"""

from __future__ import annotations

import hashlib
import struct
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

MAGIC = b"HUFF"
FORMAT_VERSION = 1
_HEADER = struct.Struct(">4sBBQH32s")
HEADER_FIXED_SIZE = _HEADER.size  # 48 bytes
ENTRY_SIZE = 2  # (symbol, code length)
CHUNK_SIZE = 1 << 16  # bytes encoded per step -> bounded memory while packing
MAX_CODE_LENGTH = 255  # a 256-leaf tree is at most 255 deep


class HuffmanError(Exception):
    """Raised for corrupt, truncated or otherwise invalid ``.huff`` data."""


# --------------------------------------------------------------------------- #
# Tree node and min-heap (priority queue), written from scratch
# --------------------------------------------------------------------------- #
class Node:
    """Huffman tree node. Leaves carry a ``symbol``; internal nodes do not."""

    __slots__ = ("freq", "symbol", "left", "right", "order")

    def __init__(
        self,
        freq: int,
        symbol: Optional[int] = None,
        left: Optional["Node"] = None,
        right: Optional["Node"] = None,
        order: int = 0,
    ) -> None:
        self.freq = freq
        self.symbol = symbol
        self.left = left
        self.right = right
        self.order = order  # deterministic tie-breaker

    @property
    def is_leaf(self) -> bool:
        return self.symbol is not None


class MinHeap:
    """Binary min-heap of :class:`Node`, ordered by ``(freq, order)``.

    ``MinHeap(items)`` runs bottom-up heapify in O(K); ``push``/``pop`` are
    O(log K).
    """

    def __init__(self, items: Optional[Iterable[Node]] = None) -> None:
        self._a: List[Node] = list(items) if items else []
        for i in range(len(self._a) // 2 - 1, -1, -1):
            self._sift_down(i)

    def __len__(self) -> int:
        return len(self._a)

    @staticmethod
    def _lt(x: Node, y: Node) -> bool:
        return (x.freq, x.order) < (y.freq, y.order)

    def peek(self) -> Node:
        if not self._a:
            raise IndexError("peek at empty heap")
        return self._a[0]

    def push(self, node: Node) -> None:
        a = self._a
        a.append(node)
        i = len(a) - 1
        while i > 0:
            parent = (i - 1) >> 1
            if self._lt(a[i], a[parent]):
                a[i], a[parent] = a[parent], a[i]
                i = parent
            else:
                break

    def pop(self) -> Node:
        a = self._a
        if not a:
            raise IndexError("pop from empty heap")
        top = a[0]
        last = a.pop()
        if a:
            a[0] = last
            self._sift_down(0)
        return top

    def _sift_down(self, i: int) -> None:
        a = self._a
        n = len(a)
        while True:
            left = 2 * i + 1
            right = left + 1
            smallest = i
            if left < n and self._lt(a[left], a[smallest]):
                smallest = left
            if right < n and self._lt(a[right], a[smallest]):
                smallest = right
            if smallest == i:
                return
            a[i], a[smallest] = a[smallest], a[i]
            i = smallest


# --------------------------------------------------------------------------- #
# Step 1-3: frequencies, tree, codes
# --------------------------------------------------------------------------- #
def count_frequencies(data: bytes) -> Dict[int, int]:
    """Return ``{symbol: count}`` for every symbol that occurs. O(N)."""
    counts = [0] * 256
    for b in data:
        counts[b] += 1
    return {s: c for s, c in enumerate(counts) if c}


def build_huffman_tree(freq: Dict[int, int]) -> Optional[Node]:
    """Build the Huffman tree with a min-heap. O(K log K). ``None`` if empty."""
    if not freq:
        return None
    heap = MinHeap(Node(f, symbol=s, order=s) for s, f in sorted(freq.items()))
    counter = 256
    while len(heap) > 1:
        a = heap.pop()
        b = heap.pop()
        heap.push(Node(a.freq + b.freq, left=a, right=b, order=counter))
        counter += 1
    return heap.pop()


def code_lengths(root: Optional[Node]) -> Dict[int, int]:
    """Depth of every leaf (iterative DFS, O(K)). A lone symbol gets length 1."""
    if root is None:
        return {}
    if root.is_leaf:
        return {root.symbol: 1}  # type: ignore[dict-item]
    lengths: Dict[int, int] = {}
    stack: List[Tuple[Node, int]] = [(root, 0)]
    while stack:
        node, depth = stack.pop()
        if node.is_leaf:
            lengths[node.symbol] = depth  # type: ignore[index]
        else:
            if node.right is not None:
                stack.append((node.right, depth + 1))
            if node.left is not None:
                stack.append((node.left, depth + 1))
    return lengths


def validate_lengths(lengths: Dict[int, int]) -> None:
    """Check the lengths describe a complete prefix code (Kraft sum == 1)."""
    if not lengths:
        return
    if any(not (1 <= l <= MAX_CODE_LENGTH) for l in lengths.values()):
        raise HuffmanError("invalid code length in table")
    if len(lengths) == 1:
        return  # single symbol: one-bit code, tree is intentionally incomplete
    longest = max(lengths.values())
    if sum(1 << (longest - l) for l in lengths.values()) != 1 << longest:
        raise HuffmanError("code lengths do not form a valid prefix code")


def canonical_codes(lengths: Dict[int, int]) -> Dict[int, Tuple[int, int]]:
    """Assign canonical codes: ``{symbol: (code_value, bit_length)}``."""
    codes: Dict[int, Tuple[int, int]] = {}
    code = 0
    prev = 0
    for symbol, length in sorted(lengths.items(), key=lambda kv: (kv[1], kv[0])):
        code <<= length - prev
        codes[symbol] = (code, length)
        code += 1
        prev = length
    return codes


def code_string(code: int, length: int) -> str:
    """Render a code as a '0'/'1' string of exactly ``length`` characters."""
    return format(code, "b").zfill(length)


def build_tree_from_codes(
    codes: Dict[int, Tuple[int, int]], freq: Optional[Dict[int, int]] = None
) -> Optional[Node]:
    """Rebuild the Huffman tree from canonical codes (decoder side).

    If ``freq`` is given, node weights are filled in for visualisation.
    """
    if not codes:
        return None
    root = Node(0)
    for symbol, (code, length) in codes.items():
        node = root
        for i in range(length - 1, -1, -1):
            if node.is_leaf:
                raise HuffmanError("code table is not prefix-free")
            bit = (code >> i) & 1
            child = node.right if bit else node.left
            if child is None:
                child = Node(0)
                if bit:
                    node.right = child
                else:
                    node.left = child
            node = child
        if node.left is not None or node.right is not None or node.is_leaf:
            raise HuffmanError("code table is not prefix-free")
        node.symbol = symbol
        node.freq = freq.get(symbol, 0) if freq else 0
    if freq:
        _fill_weights(root)
    return root


def _fill_weights(node: Node) -> int:
    if node.is_leaf:
        return node.freq
    total = 0
    for child in (node.left, node.right):
        if child is not None:
            total += _fill_weights(child)
    node.freq = total
    return total


def flatten_tree(root: Optional[Node]) -> Tuple[List[int], List[int], List[int]]:
    """Flatten to parallel arrays ``(left, right, symbol)``; root is index 0.

    Missing children are ``-1``; internal nodes have ``symbol == -1``.
    """
    if root is None:
        return [], [], []
    nodes: List[Node] = [root]
    left: List[int] = []
    right: List[int] = []
    sym: List[int] = []
    i = 0
    while i < len(nodes):  # BFS: a node's index is its position in `nodes`
        node = nodes[i]
        i += 1
        sym.append(node.symbol if node.symbol is not None else -1)
        for side, child in ((left, node.left), (right, node.right)):
            if child is None:
                side.append(-1)
            else:
                side.append(len(nodes))
                nodes.append(child)
    return left, right, sym


# --------------------------------------------------------------------------- #
# Bit packing
# --------------------------------------------------------------------------- #
def encode_payload(data: bytes, table: List[Optional[str]]) -> Tuple[bytes, int]:
    """Pack the concatenated codes into bytes. Returns ``(payload, padding)``.

    Works in chunks so memory stays O(chunk) instead of O(total bits).
    """
    out = bytearray()
    carry = ""
    for start in range(0, len(data), CHUNK_SIZE):
        bits = carry + "".join([table[b] for b in data[start : start + CHUNK_SIZE]])  # type: ignore[misc]
        full = len(bits) & ~7
        if full:
            out += int(bits[:full], 2).to_bytes(full >> 3, "big")
        carry = bits[full:]
    padding = 0
    if carry:
        padding = 8 - len(carry)
        out.append(int(carry + "0" * padding, 2))
    return bytes(out), padding


def _walk(left, right, sym, state: int, value: int, nbits: int):
    """Feed ``nbits`` bits (MSB first) of ``value`` through the tree."""
    chunk = bytearray()
    for i in range(nbits - 1, -1, -1):
        node = right[state] if (value >> i) & 1 else left[state]
        if node < 0:
            return None
        s = sym[node]
        if s >= 0:
            chunk.append(s)
            state = 0
        else:
            state = node
    return state, bytes(chunk)


def decode_payload(
    payload: bytes,
    padding: int,
    flat: Tuple[List[int], List[int], List[int]],
    original_length: int,
) -> bytes:
    """Decode the bitstream by walking the Huffman tree.

    To avoid a Python-level loop per *bit*, the walk is memoised per
    ``(tree state, input byte)``: each distinct transition is walked bit by
    bit once, then reused. The final byte is walked bit by bit so padding bits
    are never decoded.
    """
    if not payload:
        if original_length != 0:
            raise HuffmanError("payload is empty but data was expected")
        return b""
    left, right, sym = flat
    if not left:
        raise HuffmanError("payload present but code table is empty")
    tail = payload[-1]
    if padding and tail & ((1 << padding) - 1):
        raise HuffmanError("non-zero padding bits")

    cache: Dict[int, Optional[Tuple[int, bytes]]] = {}
    out = bytearray()
    state = 0
    for b in payload[:-1]:
        key = (state << 8) | b
        try:
            entry = cache[key]
        except KeyError:
            entry = cache[key] = _walk(left, right, sym, state, b, 8)
        if entry is None:
            raise HuffmanError("invalid bit sequence in payload")
        state, chunk = entry
        out += chunk
    last = _walk(left, right, sym, state, tail >> padding, 8 - padding)
    if last is None:
        raise HuffmanError("invalid bit sequence in payload")
    state, chunk = last
    out += chunk
    if state != 0:
        raise HuffmanError("payload ends in the middle of a code")
    if len(out) != original_length:
        raise HuffmanError(
            f"decoded length {len(out)} does not match header ({original_length})"
        )
    return bytes(out)


# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Header:
    version: int
    padding: int
    original_length: int
    symbol_count: int
    sha256: bytes
    lengths: Dict[int, int]
    payload_offset: int

    @property
    def size(self) -> int:
        return self.payload_offset


def serialize_header(
    padding: int, original_length: int, sha256: bytes, lengths: Dict[int, int]
) -> bytes:
    head = _HEADER.pack(
        MAGIC, FORMAT_VERSION, padding, original_length, len(lengths), sha256
    )
    table = bytearray()
    for symbol in sorted(lengths):
        table += bytes((symbol, lengths[symbol]))
    return head + bytes(table)


def parse_header(blob: bytes) -> Header:
    if len(blob) < HEADER_FIXED_SIZE:
        raise HuffmanError("file too short to be a .huff archive")
    magic, version, padding, orig_len, k, sha = _HEADER.unpack_from(blob)
    if magic != MAGIC:
        raise HuffmanError("not a .huff file (bad magic number)")
    if version != FORMAT_VERSION:
        raise HuffmanError(f"unsupported format version {version}")
    if padding > 7:
        raise HuffmanError("invalid padding value")
    if k > 256:
        raise HuffmanError("invalid symbol count")
    end = HEADER_FIXED_SIZE + ENTRY_SIZE * k
    if len(blob) < end:
        raise HuffmanError("truncated code table")
    lengths: Dict[int, int] = {}
    for i in range(k):
        offset = HEADER_FIXED_SIZE + ENTRY_SIZE * i
        symbol, length = blob[offset], blob[offset + 1]
        if symbol in lengths:
            raise HuffmanError("duplicate symbol in code table")
        lengths[symbol] = length
    validate_lengths(lengths)
    if (k == 0) != (orig_len == 0):
        raise HuffmanError("symbol count inconsistent with original length")
    if k == 0 and (len(blob) != end or padding):
        raise HuffmanError("unexpected payload for empty file")
    return Header(version, padding, orig_len, k, sha, lengths, end)


# --------------------------------------------------------------------------- #
# High-level API
# --------------------------------------------------------------------------- #
@dataclass
class CompressionResult:
    blob: bytes
    original_size: int
    freq: Dict[int, int]
    codes: Dict[int, Tuple[int, int]]
    root: Optional[Node]  # canonical tree annotated with frequencies
    header_size: int
    payload_size: int
    padding: int
    sha256_hex: str
    encode_ms: float
    stage_ms: Dict[str, float]


@dataclass
class DecompressionResult:
    data: bytes
    header: Header
    codes: Dict[int, Tuple[int, int]]
    root: Optional[Node]
    decode_ms: float
    verified: bool


def compress_detailed(data: bytes) -> CompressionResult:
    t0 = time.perf_counter()
    freq = count_frequencies(data)
    t1 = time.perf_counter()
    heap_root = build_huffman_tree(freq)
    t2 = time.perf_counter()
    lengths = code_lengths(heap_root)
    codes = canonical_codes(lengths)
    table: List[Optional[str]] = [None] * 256
    for symbol, (code, length) in codes.items():
        table[symbol] = code_string(code, length)
    t3 = time.perf_counter()
    payload, padding = encode_payload(data, table)
    digest = hashlib.sha256(data).digest()
    header = serialize_header(padding, len(data), digest, lengths)
    blob = header + payload
    t4 = time.perf_counter()
    root = build_tree_from_codes(codes, freq)  # for visualisation only
    return CompressionResult(
        blob=blob,
        original_size=len(data),
        freq=freq,
        codes=codes,
        root=root,
        header_size=len(header),
        payload_size=len(payload),
        padding=padding,
        sha256_hex=digest.hex(),
        encode_ms=(t4 - t0) * 1000.0,
        stage_ms={
            "frequency_count": (t1 - t0) * 1000.0,
            "build_tree": (t2 - t1) * 1000.0,
            "generate_codes": (t3 - t2) * 1000.0,
            "pack_bits_and_header": (t4 - t3) * 1000.0,
        },
    )


def decompress_detailed(blob: bytes) -> DecompressionResult:
    t0 = time.perf_counter()
    header = parse_header(blob)
    codes = canonical_codes(header.lengths)
    root = build_tree_from_codes(codes)
    data = decode_payload(
        blob[header.payload_offset :],
        header.padding,
        flatten_tree(root),
        header.original_length,
    )
    if hashlib.sha256(data).digest() != header.sha256:
        raise HuffmanError("SHA-256 mismatch: data is corrupt")
    t1 = time.perf_counter()
    return DecompressionResult(
        data=data,
        header=header,
        codes=codes,
        root=root,
        decode_ms=(t1 - t0) * 1000.0,
        verified=True,
    )


def compress(data: bytes) -> bytes:
    """Compress ``data`` into a ``.huff`` blob."""
    return compress_detailed(data).blob


def decompress(blob: bytes) -> bytes:
    """Decompress a ``.huff`` blob; raises :class:`HuffmanError` if invalid."""
    return decompress_detailed(blob).data
