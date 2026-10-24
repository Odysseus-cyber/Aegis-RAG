"""Temporary localhost helper that archives browser snapshots before migration.

Stop the application occupying the chosen port. This server exposes only the
migration page and its modules; it never serves archive files or application data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "frontend" / "public"
MAX_BODY = 32 * 1024 * 1024
ASSETS = {
    "/storage-migration.html": "text/html; charset=utf-8",
    "/storage-migration.mjs": "text/javascript; charset=utf-8",
    "/storage-migration-ui.mjs": "text/javascript; charset=utf-8",
    "/storage-migration-backup.mjs": "text/javascript; charset=utf-8",
}


def archive_directory(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.is_relative_to(ROOT):
        raise ValueError("Archive directory must be outside the project")
    return path


def validate_request(path: str, headers, port: int) -> tuple[int, str]:
    if path != "/migration-backup":
        raise ValueError("Unknown route")
    host = headers.get("Host", "")
    if host not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
        raise ValueError("Invalid local host")
    origin = f"http://{host}"
    if headers.get("Origin") != origin:
        raise ValueError("Same-origin request required")
    if headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise ValueError("JSON content type required")
    if headers.get("Transfer-Encoding"):
        raise ValueError("Transfer encoding is not supported")
    try:
        length = int(headers.get("Content-Length", ""))
    except ValueError:
        raise ValueError("Content length required") from None
    if not 0 < length <= MAX_BODY:
        raise ValueError("Snapshot exceeds supported size")
    return length, origin


def save_snapshot(raw: bytes, origin: str, archive: Path) -> dict:
    if not 0 < len(raw) <= MAX_BODY:
        raise ValueError("Snapshot exceeds supported size")
    snapshot = json.loads(raw)
    if not isinstance(snapshot, dict) or snapshot.get("format") != 1 or snapshot.get("origin") != origin:
        raise ValueError("Snapshot format or origin mismatch")
    for key in ("source", "target", "sourceKeys"):
        fields = snapshot.get(key)
        if not isinstance(fields, dict) or set(fields) != {"conversations", "active"}:
            raise ValueError("Incomplete snapshot")
        if any(not isinstance(value, str) and value is not None for value in fields.values()):
            raise ValueError("Invalid snapshot fields")
    archive = archive_directory(archive)
    archive.mkdir(parents=True, exist_ok=True, mode=0o700)
    receipt = f"browser-snapshot-{uuid.uuid4().hex}.json"
    destination = archive / receipt
    fd, temporary = tempfile.mkstemp(prefix=".snapshot-", dir=archive)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        # Hard-link publication is atomic and refuses an existing destination.
        os.link(temporary, destination)
        restored = destination.read_bytes()
        if restored != raw or json.loads(restored) != snapshot:
            raise OSError("Archived snapshot read-back verification failed")
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {"status": "saved", "receipt": receipt, "sha256": hashlib.sha256(restored).hexdigest(),
            "bytes": len(restored), "origin": origin}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Do not put source keys or chat contents into access logs.

    def respond(self, code: int, payload: bytes, content_type="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        host = self.headers.get("Host", "")
        if host not in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}:
            self.respond(403, b'{"error":"Invalid local host"}')
            return
        path = urlsplit(self.path).path
        asset = "/storage-migration.html" if path == "/" else path
        if asset not in ASSETS:
            self.respond(404, b'{"error":"Not found"}')
            return
        self.respond(200, (PUBLIC / asset.lstrip("/")).read_bytes(), ASSETS[asset])

    def do_POST(self):
        if self.path != "/migration-backup":
            self.respond(404, b'{"error":"Not found"}')
            return
        try:
            length, origin = validate_request(self.path, self.headers, self.server.server_port)
            self.connection.settimeout(15)
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("Incomplete snapshot body")
            receipt = save_snapshot(raw, origin, self.server.archive_dir)
            self.respond(200, json.dumps(receipt).encode())
        except (ValueError, UnicodeDecodeError):
            self.respond(400, b'{"error":"Invalid snapshot request"}')
        except (OSError, TimeoutError):
            self.respond(500, b'{"error":"Private archive write or verification failed"}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, choices=(5173, 15173), required=True)
    parser.add_argument("--archive-dir", type=Path, required=True)
    args = parser.parse_args()
    archive = archive_directory(args.archive_dir)
    with HTTPServer(("127.0.0.1", args.port), Handler) as server:
        server.archive_dir = archive
        print(f"Migration helper: http://127.0.0.1:{args.port}/storage-migration.html", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
