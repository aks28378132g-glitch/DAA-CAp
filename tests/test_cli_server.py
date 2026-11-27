import base64
import http.client
import json
import os
import sys
import tempfile
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import cli
import server


class CliTests(unittest.TestCase):
    def test_compress_decompress_verify(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "a.txt")
            text = "Hello, Huffman! café 日本語\n" * 200
            with open(src, "w", encoding="utf-8") as fh:
                fh.write(text)
            self.assertEqual(cli.main(["compress", src]), 0)
            huff = src + ".huff"
            self.assertLess(os.path.getsize(huff), os.path.getsize(src))
            self.assertEqual(cli.main(["decompress", huff]), 0)
            restored = os.path.join(d, "a.restored.txt")
            with open(restored, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), text)
            self.assertEqual(cli.main(["verify", src, huff]), 0)
            self.assertEqual(cli.main(["analyze", src, "--top", "5"]), 0)

    def test_bad_file_returns_error(self):
        with tempfile.TemporaryDirectory() as d:
            bad = os.path.join(d, "bad.huff")
            with open(bad, "wb") as fh:
                fh.write(b"not a huff file at all, sorry" * 3)
            self.assertEqual(cli.main(["decompress", bad]), 1)

    def test_refuses_same_in_out(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.txt")
            open(p, "w").write("abc")
            self.assertEqual(cli.main(["compress", p, "-o", p]), 1)


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.make_server("127.0.0.1", 0, max_bytes=1 << 20)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def request(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request(method, path, body=body)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data

    def test_index(self):
        status, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Huffman Compressor", body)

    def test_path_traversal_blocked(self):
        status, _ = self.request("GET", "/..%2fserver.py")
        self.assertEqual(status, 404)

    def test_api_roundtrip(self):
        text = ("Unicode ✓ café 日本語 " * 100).encode("utf-8")
        status, body = self.request("POST", "/api/compress", text)
        self.assertEqual(status, 200)
        rep = json.loads(body)
        self.assertTrue(rep["verified"])
        self.assertLess(rep["compressed_size"], rep["original_size"])
        self.assertIsNotNone(rep["tree"])
        huff = base64.b64decode(rep["huff_base64"])
        status, body = self.request("POST", "/api/decompress", huff)
        self.assertEqual(status, 200)
        rep2 = json.loads(body)
        self.assertEqual(base64.b64decode(rep2["data_base64"]), text)

    def test_api_empty(self):
        status, body = self.request("POST", "/api/compress", b"")
        self.assertEqual(status, 200)
        rep = json.loads(body)
        self.assertIsNone(rep["tree"])
        self.assertTrue(rep["verified"])

    def test_api_invalid_huff(self):
        status, body = self.request("POST", "/api/decompress", b"garbage" * 20)
        self.assertEqual(status, 400)
        self.assertIn("error", json.loads(body))

    def test_too_large(self):
        status, _ = self.request("POST", "/api/compress", b"a" * ((1 << 20) + 1))
        self.assertEqual(status, 413)


if __name__ == "__main__":
    unittest.main()
