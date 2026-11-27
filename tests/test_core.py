import hashlib
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from huffman import (HuffmanError, MinHeap, Node, build_huffman_tree, canonical_codes,
                     code_lengths, compress, compress_detailed, count_frequencies,
                     decompress, decompress_detailed)
from huffman.core import HEADER_FIXED_SIZE, code_string


class HeapTests(unittest.TestCase):
    def test_pops_in_sorted_order(self):
        rng = random.Random(1)
        values = [rng.randrange(1000) for _ in range(500)]
        heap = MinHeap()
        for i, v in enumerate(values):
            heap.push(Node(v, symbol=i % 256, order=i))
        out = [heap.pop().freq for _ in range(len(values))]
        self.assertEqual(out, sorted(values))

    def test_heapify_constructor(self):
        nodes = [Node(f, symbol=i, order=i) for i, f in enumerate([9, 3, 7, 1, 8, 2])]
        heap = MinHeap(nodes)
        self.assertEqual([heap.pop().freq for _ in range(6)], [1, 2, 3, 7, 8, 9])

    def test_empty_pop_raises(self):
        with self.assertRaises(IndexError):
            MinHeap().pop()


class TreeTests(unittest.TestCase):
    def test_frequencies(self):
        self.assertEqual(count_frequencies(b"aabbbc"), {97: 2, 98: 3, 99: 1})

    def test_clrs_optimal_cost(self):
        # Classic CLRS example: optimal weighted path length is 224.
        freq = {ord("a"): 5, ord("b"): 9, ord("c"): 12, ord("d"): 13, ord("e"): 16, ord("f"): 45}
        lengths = code_lengths(build_huffman_tree(freq))
        self.assertEqual(sum(freq[s] * l for s, l in lengths.items()), 224)
        self.assertEqual(lengths[ord("f")], 1)

    def test_prefix_free(self):
        data = os.urandom(5000) + b"hello world " * 100
        codes = canonical_codes(code_lengths(build_huffman_tree(count_frequencies(data))))
        strings = [code_string(c, l) for c, l in codes.values()]
        for i, a in enumerate(strings):
            for j, b in enumerate(strings):
                if i != j:
                    self.assertFalse(b.startswith(a))

    def test_frequent_symbols_get_shorter_codes(self):
        lengths = code_lengths(build_huffman_tree(count_frequencies(b"a" * 100 + b"b" * 10 + b"c")))
        self.assertLessEqual(lengths[ord("a")], lengths[ord("b")])
        self.assertLessEqual(lengths[ord("b")], lengths[ord("c")])

    def test_deterministic(self):
        data = b"deterministic output please " * 20
        self.assertEqual(compress(data), compress(data))


class RoundTripTests(unittest.TestCase):
    def check(self, data: bytes):
        blob = compress(data)
        self.assertEqual(decompress(blob), data)
        return blob

    def test_empty(self):
        blob = self.check(b"")
        self.assertEqual(len(blob), HEADER_FIXED_SIZE)

    def test_single_symbol(self):
        blob = self.check(b"a" * 1000)
        self.assertEqual(len(blob), HEADER_FIXED_SIZE + 2 + 125)  # 1000 bits -> 125 bytes

    def test_single_byte(self):
        self.check(b"x")

    def test_two_symbols(self):
        self.check(b"ab" * 33 + b"a")

    def test_unicode(self):
        text = "héllo wörld — 日本語 привет مرحبا 🙂🚀\n" * 50
        self.check(text.encode("utf-8"))

    def test_all_byte_values(self):
        self.check(bytes(range(256)) * 10)

    def test_random_binary(self):
        self.check(os.urandom(20000))

    def test_padding_lengths(self):
        for n in range(1, 40):
            self.check((b"abracadabra!" * 4)[:n])

    def test_skewed_fibonacci_deep_tree(self):
        data = bytearray()
        a, b = 1, 1
        for sym in range(25):
            data += bytes([sym]) * a
            a, b = b, a + b
        self.check(bytes(data))

    def test_crosses_chunk_boundary(self):
        rng = random.Random(3)
        self.check(bytes(rng.choice(b"etaoin shrdlu") for _ in range(200_000)))

    def test_text_is_actually_smaller(self):
        text = ("the quick brown fox jumps over the lazy dog. " * 200).encode()
        blob = self.check(text)
        self.assertLess(len(blob), len(text))

    def test_sha_matches(self):
        data = b"integrity" * 100
        res = compress_detailed(data)
        self.assertEqual(res.sha256_hex, hashlib.sha256(data).hexdigest())
        self.assertTrue(decompress_detailed(res.blob).verified)


class CorruptionTests(unittest.TestCase):
    def setUp(self):
        self.blob = compress(b"some reasonably long text to compress " * 30)

    def test_bad_magic(self):
        with self.assertRaises(HuffmanError):
            decompress(b"XXXX" + self.blob[4:])

    def test_not_huff(self):
        with self.assertRaises(HuffmanError):
            decompress(b"hello")

    def test_bad_version(self):
        with self.assertRaises(HuffmanError):
            decompress(self.blob[:4] + b"\x09" + self.blob[5:])

    def test_truncated_payload(self):
        with self.assertRaises(HuffmanError):
            decompress(self.blob[:-3])

    def test_truncated_table(self):
        with self.assertRaises(HuffmanError):
            decompress(self.blob[: HEADER_FIXED_SIZE + 3])

    def test_trailing_garbage(self):
        with self.assertRaises(HuffmanError):
            decompress(self.blob + b"\xff\xff")

    def test_every_payload_bit_flip_is_detected(self):
        start = len(self.blob) - 6
        for i in range(start, len(self.blob)):
            for bit in range(8):
                bad = bytearray(self.blob)
                bad[i] ^= 1 << bit
                with self.assertRaises(HuffmanError):
                    decompress(bytes(bad))

    def test_invalid_kraft(self):
        blob = bytearray(self.blob)
        blob[HEADER_FIXED_SIZE + 1] = 1  # force an impossible length
        with self.assertRaises(HuffmanError):
            decompress(bytes(blob))


if __name__ == "__main__":
    unittest.main()
