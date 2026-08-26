"""Authenticated tenant gateway supervising one WhatsMeow runtime per identity."""

from __future__ import annotations

import hmac
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import requests

from store_migration import migrate_from_environment
from tenant_context import TENANT_ID_HEADER, normalize_identity, store_root


def bridge_token() -> str:
    token = os.getenv("WHATSAPP_BRIDGE_TOKEN", "").strip()
    if len(token) < 16:
        raise ValueError("WHATSAPP_BRIDGE_TOKEN is required and must be at least 16 characters")
    return token


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@dataclass
class TenantRuntime:
    identity: str
    port: int
    process: subprocess.Popen[bytes]

    @property
    def api_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/api"


class RuntimeRegistry:
    def __init__(self, root: Path, binary: Path, token: str):
        self.root = root
        self.binary = binary
        self.token = token
        self._lock = threading.Lock()
        self._runtimes: dict[str, TenantRuntime] = {}

    def get(self, identity: str) -> TenantRuntime:
        canonical = normalize_identity(identity)
        with self._lock:
            runtime = self._runtimes.get(canonical)
            if runtime is not None and runtime.process.poll() is None:
                return runtime
            if runtime is not None:
                self._runtimes.pop(canonical, None)
            runtime = self._start(canonical)
            self._runtimes[canonical] = runtime
            return runtime

    def _start(self, identity: str) -> TenantRuntime:
        tenant_root = self.root / "tenants" / identity
        (tenant_root / "store").mkdir(parents=True, exist_ok=True)
        port = _free_port()
        env = os.environ.copy()
        env.update(
            {
                "WHATSAPP_BRIDGE_HOST": "127.0.0.1",
                "WHATSAPP_BRIDGE_PORT": str(port),
                "WHATSAPP_BRIDGE_TOKEN": self.token,
            }
        )
        process = subprocess.Popen(
            [str(self.binary)],
            cwd=tenant_root,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        runtime = TenantRuntime(identity=identity, port=port, process=process)
        self._wait_until_ready(runtime)
        return runtime

    @staticmethod
    def _wait_until_ready(runtime: TenantRuntime) -> None:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if runtime.process.poll() is not None:
                raise RuntimeError(f"WhatsApp runtime exited for tenant {runtime.identity}")
            try:
                response = requests.get(f"{runtime.api_url}/status", timeout=0.4)
                if response.status_code == 200:
                    return
            except requests.RequestException:
                pass
            time.sleep(0.1)
        runtime.process.terminate()
        raise RuntimeError(f"WhatsApp runtime did not start for tenant {runtime.identity}")

    def close(self) -> None:
        with self._lock:
            runtimes = list(self._runtimes.values())
            self._runtimes.clear()
        for runtime in runtimes:
            if runtime.process.poll() is None:
                runtime.process.terminate()
        deadline = time.monotonic() + 5
        for runtime in runtimes:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                runtime.process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                runtime.process.kill()


class TenantGatewayHandler(BaseHTTPRequestHandler):
    registry: RuntimeRegistry
    token: str
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        self._proxy()

    def do_POST(self) -> None:
        self._proxy()

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write("whatsapp-gateway: " + format % args + "\n")

    def _proxy(self) -> None:
        if urlsplit(self.path).path == "/healthz":
            self._write(200, b'{"status":"ok"}', "application/json")
            return
        if not urlsplit(self.path).path.startswith("/api/"):
            self._write(404, b"Not found", "text/plain")
            return
        if not self._authorized():
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Bearer realm="whatsapp-gateway"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        try:
            identity = normalize_identity(self.headers.get(TENANT_ID_HEADER))
            runtime = self.registry.get(identity)
            body_size = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(body_size) if body_size else None
            response = requests.request(
                self.command,
                runtime.api_url + urlsplit(self.path).path.removeprefix("/api"),
                data=body,
                headers={"Authorization": f"Bearer {self.token}", "Content-Type": self.headers.get("Content-Type", "")},
                timeout=65,
            )
            self._write(
                response.status_code, response.content, response.headers.get("Content-Type", "application/json")
            )
        except ValueError as exc:
            self._write(400, str(exc).encode(), "text/plain")
        except (RuntimeError, requests.RequestException) as exc:
            self._write(503, str(exc).encode(), "text/plain")

    def _authorized(self) -> bool:
        supplied = self.headers.get("Authorization", "")
        prefix = "Bearer "
        return supplied.startswith(prefix) and hmac.compare_digest(supplied[len(prefix) :].strip(), self.token)

    def _write(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    root = store_root()
    root.mkdir(parents=True, exist_ok=True)
    migrate_from_environment(root)
    token = bridge_token()
    binary = Path(os.getenv("WHATSAPP_BRIDGE_BINARY", "/usr/local/bin/whatsapp-bridge")).resolve()
    if not binary.is_file():
        raise SystemExit(f"WhatsApp bridge binary not found: {binary}")
    registry = RuntimeRegistry(root, binary, token)
    TenantGatewayHandler.registry = registry
    TenantGatewayHandler.token = token
    host = os.getenv("WHATSAPP_GATEWAY_HOST", "0.0.0.0")
    port = int(os.getenv("WHATSAPP_GATEWAY_PORT", "8081"))
    server = ThreadingHTTPServer((host, port), TenantGatewayHandler)

    def stop(_signum: int, _frame: object) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        registry.close()


if __name__ == "__main__":
    main()
