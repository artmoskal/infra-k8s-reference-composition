#!/usr/bin/env python3
"""Small stateful HTTP fixture for the infra-k8s recovery contract."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import pathlib
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


DATA_PATH = pathlib.Path(os.environ.get("RECOVERY_DATA_PATH", "/data/records.json"))
LISTEN_ADDRESS = os.environ.get("RECOVERY_LISTEN_ADDRESS", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("RECOVERY_LISTEN_PORT", "8080"))
TOKEN = os.environ.get("RECOVERY_TOKEN", "")
DEPLOYMENT_ID = os.environ.get("RECOVERY_DEPLOYMENT_ID", "")
MAX_BODY_BYTES = 4096
LOCK = threading.Lock()


def encode_records(records: dict[str, str]) -> bytes:
    return (json.dumps(records, sort_keys=True, separators=(",", ":")) + "\n").encode()


def read_records(path: pathlib.Path = DATA_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in document.items()
    ):
        raise ValueError("record store is not a string map")
    return document


def write_records(records: dict[str, str], path: pathlib.Path = DATA_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".records-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(encode_records(records))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def require_runtime_identity() -> None:
    if len(TOKEN) < 16 or not DEPLOYMENT_ID:
        raise RuntimeError("RECOVERY_TOKEN and RECOVERY_DEPLOYMENT_ID are required")


class Handler(BaseHTTPRequestHandler):
    server_version = "infra-k8s-recovery-fixture/1"

    def log_message(self, format_: str, *args: object) -> None:
        print(format_ % args, file=sys.stderr, flush=True)

    def send_json(self, status: HTTPStatus, document: object) -> None:
        payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def authorized(self) -> bool:
        supplied = self.headers.get("Authorization", "")
        return hmac.compare_digest(supplied, "Bearer " + TOKEN)

    def record_key(self) -> str | None:
        prefix = "/records/"
        if not self.path.startswith(prefix):
            return None
        key = self.path[len(prefix):]
        if not key or len(key) > 63 or not key.replace("-", "").isalnum():
            return None
        return key

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        if self.path == "/health":
            self.send_json(HTTPStatus.OK, {"status": "ready", "deployment": DEPLOYMENT_ID})
            return
        key = self.record_key()
        if key is None:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "not-found"})
            return
        if not self.authorized():
            self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        with LOCK:
            records = read_records()
        if key not in records:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "record-not-found"})
            return
        self.send_json(HTTPStatus.OK, {"key": key, "value": records[key], "deployment": DEPLOYMENT_ID})

    def do_PUT(self) -> None:  # noqa: N802 - stdlib callback name
        key = self.record_key()
        if key is None:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "not-found"})
            return
        if not self.authorized():
            self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length < 1 or length > MAX_BODY_BYTES:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid-body-size"})
            return
        try:
            payload = json.loads(self.rfile.read(length))
            value = payload["value"]
            if not isinstance(value, str) or not value or len(value) > 2048:
                raise ValueError("invalid value")
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid-record"})
            return
        with LOCK:
            records = read_records()
            records[key] = value
            write_records(records)
        self.send_json(HTTPStatus.OK, {"key": key, "stored": True, "deployment": DEPLOYMENT_ID})


def request(method: str, key: str, value: str | None = None) -> dict[str, object]:
    body = None if value is None else json.dumps({"value": value}).encode()
    call = urllib.request.Request(
        f"http://127.0.0.1:{LISTEN_PORT}/records/{key}",
        data=body,
        method=method,
        headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(call, timeout=10) as response:
        return json.load(response)


def serve() -> int:
    require_runtime_identity()
    with LOCK:
        if not DATA_PATH.exists():
            write_records({})
        else:
            read_records()
    server = ThreadingHTTPServer((LISTEN_ADDRESS, LISTEN_PORT), Handler)
    server.serve_forever()
    return 0


def main(arguments: list[str]) -> int:
    command = arguments[0] if arguments else "serve"
    if command == "serve" and len(arguments) == 1:
        return serve()
    if command == "client-put" and len(arguments) == 3:
        require_runtime_identity()
        response = request("PUT", arguments[1], arguments[2])
        print(json.dumps(response, sort_keys=True, separators=(",", ":")))
        return 0
    if command == "client-get" and len(arguments) == 2:
        require_runtime_identity()
        response = request("GET", arguments[1])
        print(response["value"])
        return 0
    if command == "checksum" and len(arguments) == 2:
        data = pathlib.Path(arguments[1]).read_bytes()
        print(hashlib.sha256(data).hexdigest())
        return 0
    if command == "audit" and len(arguments) == 2:
        path = pathlib.Path(arguments[1])
        records = read_records(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        print(json.dumps({"records": len(records), "sha256": digest}, sort_keys=True))
        return 0
    print("usage: recovery_fixture.py serve|client-put KEY VALUE|client-get KEY|checksum PATH|audit PATH", file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (OSError, RuntimeError, ValueError, urllib.error.URLError) as error:
        print(f"recovery fixture failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
