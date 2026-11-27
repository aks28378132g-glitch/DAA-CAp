#!/usr/bin/env python3
"""Web UI server (standard library only). Run:  python server.py

Endpoints
    GET  /                 the single-page UI (web/)
    POST /api/compress     body = raw bytes  -> JSON report + base64 .huff
    POST /api/decompress   body = .huff file -> JSON report + base64 original
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict
from urllib.parse import unquote, urlparse

from huffman import HuffmanError, compress_detailed, decompress_detailed
from huffman.core import count_frequencies
from huffman.report import build_report

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
PREVIEW_LIMIT = 100_000  # bytes of restored text returned for on-page preview
DEFAULT_MAX_MB = 16


def compress_api(data: bytes) -> Dict[str, Any]:
    res = compress_detailed(data)
    dec = decompress_detailed(res.blob)  # real decode: timing + verification
    verified = dec.data == data
    report = build_report(
        data_size=res.original_size, compressed_size=len(res.blob), freq=res.freq,
        codes=res.codes, root=res.root, header_size=res.header_size,
        padding=res.padding, sha256_hex=res.sha256_hex, encode_ms=res.encode_ms,
        decode_ms=dec.decode_ms, stage_ms=res.stage_ms, verified=verified,
    )
    report["huff_base64"] = base64.b64encode(res.blob).decode("ascii")
    return report


def decompress_api(blob: bytes) -> Dict[str, Any]:
    dec = decompress_detailed(blob)
    freq = count_frequencies(dec.data)
    report = build_report(
        data_size=len(dec.data), compressed_size=len(blob), freq=freq, codes=dec.codes,
        root=_annotated(dec, freq), header_size=dec.header.size,
        padding=dec.header.padding, sha256_hex=dec.header.sha256.hex(),
        encode_ms=None, decode_ms=dec.decode_ms, stage_ms=None, verified=dec.verified,
    )
    preview = dec.data[:PREVIEW_LIMIT]
    report["text"] = preview.decode("utf-8", errors="replace")
    report["text_truncated"] = len(dec.data) > PREVIEW_LIMIT
    report["data_base64"] = base64.b64encode(dec.data).decode("ascii")
    return report


def _annotated(dec, freq):
    from huffman.core import build_tree_from_codes
    return build_tree_from_codes(dec.codes, freq)


class Handler(BaseHTTPRequestHandler):
    server_version = "HuffmanUI/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # -- helpers ----------------------------------------------------------- #
    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: Dict[str, Any]) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"), "application/json")

    # -- routes ------------------------------------------------------------ #
    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path)
        if path == "/":
            path = "/index.html"
        full = os.path.realpath(os.path.join(WEB_DIR, path.lstrip("/")))
        if os.path.commonpath([full, os.path.realpath(WEB_DIR)]) != os.path.realpath(WEB_DIR) \
                or not os.path.isfile(full):
            self._json(404, {"error": "not found"})
            return
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        with open(full, "rb") as fh:
            self._send(200, fh.read(), ctype)

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        if route not in ("/api/compress", "/api/decompress"):
            self._json(404, {"error": "not found"})
            return
        raw_len = self.headers.get("Content-Length")
        if raw_len is None or not raw_len.isdigit():
            self.close_connection = True
            self._json(411, {"error": "Content-Length required"})
            return
        length = int(raw_len)
        limit = self.server.max_bytes  # type: ignore[attr-defined]
        if length > limit:
            self.close_connection = True
            self._json(413, {"error": f"file too large (limit {limit // (1 << 20)} MB)"})
            return
        body = self.rfile.read(length)
        try:
            if route == "/api/compress":
                self._json(200, compress_api(body))
            else:
                self._json(200, decompress_api(body))
        except HuffmanError as exc:
            self._json(400, {"error": f"Invalid .huff file: {exc}"})
        except Exception as exc:  # pragma: no cover - defensive
            self._json(500, {"error": f"internal error: {exc}"})


def make_server(host: str = "127.0.0.1", port: int = 8000,
                max_bytes: int = DEFAULT_MAX_MB << 20) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.max_bytes = max_bytes  # type: ignore[attr-defined]
    return httpd


def main() -> int:
    ap = argparse.ArgumentParser(description="Huffman compressor web UI")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--max-mb", type=int, default=DEFAULT_MAX_MB, help="upload limit in MB")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    httpd = make_server(args.host, args.port, args.max_mb << 20)
    url = f"http://{args.host}:{httpd.server_address[1]}/"
    print(f"Huffman Compressor running at {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
