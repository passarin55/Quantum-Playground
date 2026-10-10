"""Zero-dependency local web studio (stdlib ``http.server``).

Security model (the server can hold an IBM token in memory):

* binds to 127.0.0.1 by default;
* every state-changing request must carry ``X-QPlay: 1`` — a custom header a
  cross-site page cannot send without a CORS pre-flight, which is never granted;
* the ``Host`` header must be a loopback name (defeats DNS rebinding);
* tokens are kept in process memory unless the user explicitly saves them to
  Qiskit's own account store; API responses only ever show a masked token.
"""
from __future__ import annotations

import json
import mimetypes
import threading
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from .. import __version__
from . import api

STATIC = Path(__file__).parent / "static"
LOOPBACK = {"127.0.0.1", "localhost", "[::1]", "::1"}
MAX_BODY = 4 * 1024 * 1024


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class Handler(BaseHTTPRequestHandler):
    server_version = f"qplay/{__version__}"
    routes: list[tuple[str, str, Callable]] = []

    def log_message(self, fmt: str, *args: Any) -> None:  # quieter default logging
        if getattr(self.server, "verbose", False):
            super().log_message(fmt, *args)

    # ---------------------------------------------------------------- helpers
    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").strip()
        name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
        allowed = set(LOOPBACK) | set(getattr(self.server, "extra_hosts", set()))
        return name in allowed

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                         "connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, obj: Any) -> None:
        self._send(status, json.dumps(obj, default=str).encode("utf-8"), "application/json; charset=utf-8")

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ApiError(413, "request too large")
        raw = self.rfile.read(n) if n else b"{}"
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            raise ApiError(400, "invalid JSON") from None
        if not isinstance(data, dict):
            raise ApiError(400, "JSON object expected")
        return data

    # ---------------------------------------------------------------- dispatch
    def _dispatch(self, method: str) -> None:
        if not self._host_ok():
            self._json(403, {"error": "forbidden host"})
            return
        path = urlparse(self.path).path
        if not path.startswith("/api/"):
            if method != "GET":
                self._json(405, {"error": "method not allowed"})
                return
            self._static(path)
            return
        if method != "GET" and self.headers.get("X-QPlay") != "1":
            self._json(403, {"error": "missing X-QPlay header"})
            return
        for m, pattern, fn in api.ROUTES:
            if m != method:
                continue
            args = _match(pattern, path)
            if args is None:
                continue
            try:
                body = self._body() if method in ("POST", "PUT") else {}
                status, payload = fn(body, *args)
                self._json(status, payload)
            except ApiError as exc:
                self._json(exc.status, {"error": str(exc)})
            except (ValueError, KeyError) as exc:
                self._json(400, {"error": str(exc).strip("'\"")})
            except PermissionError as exc:
                self._json(409, {"error": str(exc)})
            except Exception as exc:  # pragma: no cover - surfaced to the UI
                self._json(500, {"error": f"{type(exc).__name__}: {exc}",
                                 "trace": traceback.format_exc(limit=6)})
            return
        self._json(404, {"error": f"no route for {method} {path}"})

    def _static(self, path: str) -> None:
        if path in ("", "/"):
            path = "/index.html"
        target = (STATIC / path.lstrip("/")).resolve()
        if STATIC.resolve() not in target.parents or not target.is_file():
            self._send(404, b"not found", "text/plain")
            return
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch("DELETE")


def _match(pattern: str, path: str) -> Optional[list[str]]:
    p_parts, parts = pattern.strip("/").split("/"), path.strip("/").split("/")
    if len(p_parts) != len(parts):
        return None
    args = []
    for a, b in zip(p_parts, parts):
        if a.startswith("{") and a.endswith("}"):
            if not b:
                return None
            args.append(b)
        elif a != b:
            return None
    return args


def make_server(host: str = "127.0.0.1", port: int = 8765, verbose: bool = False) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    srv.verbose = verbose  # type: ignore[attr-defined]
    srv.extra_hosts = set() if host in LOOPBACK else {host}  # type: ignore[attr-defined]
    return srv


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False) -> None:
    srv = make_server(host, port, verbose=True)
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{srv.server_address[1]}/"
    print(f"Quantum Playground Studio v{__version__} — {url}  (Ctrl+C to stop)")
    if host not in LOOPBACK:
        print("WARNING: listening on a non-loopback address; anyone on the network can use your cloud quota.")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        srv.server_close()
