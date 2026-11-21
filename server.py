#!/usr/bin/env python3
"""Small read-only same-origin quote proxy and static file server; no dependencies."""
import argparse
import http.client
import json
import math
import mimetypes
import os
import ipaddress
import threading
import time
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

QUOTES_URL = "https://api.miletrades.site/api/v1/quotes"
UPSTREAM_TIMEOUT = 5  # seconds per socket operation, not a total wall-clock deadline
MAX_UPSTREAM_BYTES = 512 * 1024
MAX_QUOTES = 1000
MAX_TEXT = 200
MAX_STATIC_BYTES = 4 * 1024 * 1024
ASSET_CLASSES = {"synthetic", "forex", "crypto", "indices", "commodities"}
CLIENT_LIMIT = 60
CLIENT_QUOTE_LIMIT = 30
GLOBAL_QUOTE_LIMIT = 60
MAX_CLIENTS = 2048
MAX_CONNECTIONS = 32
MAX_UPSTREAM_INFLIGHT = 3
WINDOW_SECONDS = 60


class Limits:
    """Per-process fixed windows; table saturation fails closed."""
    def __init__(self):
        self.lock = threading.Lock()
        self.clients = {}
        self.global_start = time.monotonic()
        self.global_quotes = 0
        self.upstream = threading.BoundedSemaphore(MAX_UPSTREAM_INFLIGHT)

    def client(self, key, quote=False):
        now = time.monotonic()
        with self.lock:
            expired = [k for k, v in self.clients.items() if now - v[0] >= WINDOW_SECONDS]
            for k in expired:
                del self.clients[k]
            if key not in self.clients:
                if len(self.clients) >= MAX_CLIENTS:
                    return False
                self.clients[key] = [now, 0, 0]
            bucket = self.clients[key]
            if bucket[1] >= CLIENT_LIMIT or (quote and bucket[2] >= CLIENT_QUOTE_LIMIT):
                return False
            bucket[1] += 1
            bucket[2] += int(quote)
            return True

    def quote(self):
        now = time.monotonic()
        with self.lock:
            if now - self.global_start >= WINDOW_SECONDS:
                self.global_start, self.global_quotes = now, 0
            if self.global_quotes >= GLOBAL_QUOTE_LIMIT:
                return False
            self.global_quotes += 1
            return True


class BoundedServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64

    def __init__(self, *args):
        self.connections = threading.BoundedSemaphore(MAX_CONNECTIONS)
        super().__init__(*args)

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(10)  # per socket operation, not total duration
        return request, address

    def process_request(self, request, client_address):
        if not self.connections.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.connections.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connections.release()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def load_quotes():
    request = Request(QUOTES_URL, headers={"Accept": "application/json", "User-Agent": "Futubiz-Practice/1.0"})
    with build_opener(NoRedirect()).open(request, timeout=UPSTREAM_TIMEOUT) as response:
        if response.status != 200:
            raise ValueError("unexpected upstream status")
        declared = response.headers.get("Content-Length")
        if declared is not None:
            try:
                if int(declared) < 0 or int(declared) > MAX_UPSTREAM_BYTES:
                    raise ValueError("upstream body too large")
            except ValueError as exc:
                raise ValueError("invalid or oversized upstream body") from exc
        raw = response.read(MAX_UPSTREAM_BYTES + 1)
    if len(raw) > MAX_UPSTREAM_BYTES:
        raise ValueError("upstream body too large")
    data = json.loads(raw.decode("utf-8"), parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid number")))
    if not isinstance(data, dict) or not isinstance(data.get("quotes"), list) or len(data["quotes"]) > MAX_QUOTES:
        raise ValueError("invalid upstream shape")
    result = []
    for row in data["quotes"]:
        if not isinstance(row, dict):
            raise ValueError("invalid quote")
        symbol, label, category = row.get("symbol"), row.get("label"), row.get("asset_class")
        price, precision = row.get("price"), row.get("precision")
        if (not isinstance(symbol, str) or not symbol or len(symbol) > MAX_TEXT or
                not isinstance(label, str) or not label or len(label) > MAX_TEXT or
                category not in ASSET_CLASSES or isinstance(price, bool) or
                not isinstance(price, (int, float)) or not math.isfinite(price) or price < 0 or
                isinstance(precision, bool) or not isinstance(precision, int) or not 0 <= precision <= 18):
            raise ValueError("invalid quote fields")
        result.append({"symbol": symbol, "label": label, "asset_class": category,
                       "price": price, "precision": precision})
    return result


class Handler(BaseHTTPRequestHandler):
    server_version = "FutubizPractice"
    sys_version = ""

    def client_key(self):
        if not self.server.trust_render_proxy:
            return self.client_address[0]
        # Only safe when all requests pass through an edge that overwrites this header.
        values = self.headers.get_all("CF-Connecting-IP", [])
        if len(values) != 1:
            return "unknown-proxy-client"
        try:
            return str(ipaddress.ip_address(values[0].strip()))
        except ValueError:
            return "unknown-proxy-client"

    def allowed(self, quote=False):
        if not self.server.limits.client(self.client_key(), quote):
            self.json_response(429, {"error": "Request limit reached; try again later"})
            return False
        return True

    def headers_for(self, status, content_type, length):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()

    def json_response(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.headers_for(status, "application/json; charset=utf-8", len(body))
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlsplit(self.path)
        if not self.allowed(quote=parsed.path == "/api/quotes"):
            return
        if parsed.path == "/api/quotes":
            if parsed.query:
                self.json_response(400, {"error": "Query parameters are not supported"})
                return
            if not self.server.limits.upstream.acquire(blocking=False):
                self.json_response(503, {"error": "Quote service busy; try again later"})
                return
            if not self.server.limits.quote():
                self.server.limits.upstream.release()
                self.json_response(503, {"error": "Quote service busy; try again later"})
                return
            try:
                quotes = load_quotes()
            except (TimeoutError, socket.timeout):
                self.json_response(504, {"error": "Quote provider timed out"})
                return
            except HTTPError as exc:
                exc.close()
                self.json_response(502, {"error": "Quote provider unavailable"})
                return
            except URLError as exc:
                if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                    self.json_response(504, {"error": "Quote provider timed out"})
                else:
                    self.json_response(502, {"error": "Quote provider unavailable"})
                return
            except (ValueError, TypeError, OverflowError, UnicodeError, OSError, http.client.HTTPException):
                self.json_response(502, {"error": "Invalid or unavailable quote data"})
                return
            finally:
                self.server.limits.upstream.release()
            self.json_response(200, {"source": "Mile public quotes", "quotes": quotes})
            return
        if parsed.path.startswith("/api/"):
            self.json_response(404, {"error": "Not found"})
            return
        self.serve_static(parsed.path)

    def serve_static(self, raw_path):
        decoded = unquote(raw_path)
        parts = decoded.split("/")
        if any(p in ("..", ".") or p.startswith(".") or "\\" in p or "\x00" in p for p in parts if p):
            self.json_response(404, {"error": "Not found"})
            return
        relative = decoded.lstrip("/") or "index.html"
        root = self.server.static_dir.resolve()
        try:
            file = (root / relative).resolve()
            if not file.is_relative_to(root) or not file.is_file() or file.stat().st_size > MAX_STATIC_BYTES:
                raise ValueError("not a permitted file")
            body = file.read_bytes()
            if len(body) > MAX_STATIC_BYTES:
                raise ValueError("file too large")
        except (OSError, ValueError):
            self.json_response(404, {"error": "Not found"})
            return
        content_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        self.headers_for(200, content_type, len(body))
        self.wfile.write(body)

    def method_not_allowed(self):
        if not self.allowed():
            return
        self.send_response(405)
        self.send_header("Allow", "GET")
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = method_not_allowed


def make_server(host, port, static_dir):
    server = BoundedServer((host, port), Handler)
    server.static_dir = Path(static_dir)
    server.limits = Limits()
    server.trust_render_proxy = os.environ.get("TRUST_RENDER_PROXY") == "1"
    return server


def main():
    parser = argparse.ArgumentParser(description="Futubiz read-only development server")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--static-dir", default=str(Path(__file__).parent / "public"))
    args = parser.parse_args()
    if not Path(args.static_dir).is_dir():
        parser.error("static directory does not exist")
    server = make_server(args.host, args.port, args.static_dir)
    print(f"Listening on http://{args.host}:{server.server_port} (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
