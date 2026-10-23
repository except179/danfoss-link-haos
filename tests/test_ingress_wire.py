"""Docker-only TCP checks. Supervisor/admin behavior still needs a HAOS check."""
import asyncio
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

import ingress
from storage import atomic_json
from test_app import OPTIONS
from test_pairing_lifecycle import save_peer


class SyntheticProxyWriter:
    """Test-only proxy peer simulation; production has no peer override option."""
    def __init__(self, writer):
        self.writer = writer

    def get_extra_info(self, name):
        return (ingress.PROXY, 12345) if name == "peername" else self.writer.get_extra_info(name)

    def __getattr__(self, name):
        return getattr(self.writer, name)


class IngressTCPTests(unittest.IsolatedAsyncioTestCase):
    async def exchange(self, simulate_proxy):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            atomic_json(state / "settings.json", dict(OPTIONS, operation="setup"))
            app = ingress.IngressServer(state)
            async def handle(reader, writer):
                await app.handle(reader, SyntheticProxyWriter(writer) if simulate_proxy else writer)
            server = await asyncio.start_server(handle, "127.0.0.1", 0)
            try:
                port = server.sockets[0].getsockname()[1]
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                if simulate_proxy:
                    writer.write(b"GET / HTTP/1.1\r\nHost: app\r\nX-Remote-User-Id: synthetic-admin\r\nX-Ingress-Path: /api/hassio_ingress/synthetic-path\r\n\r\n")
                    await writer.drain()
                # A real non-proxy peer is denied before sending any headers.
                response = await asyncio.wait_for(reader.read(), 5)
                writer.close()
                await writer.wait_closed()
                return response
            finally:
                server.close()
                await server.wait_closed()
                if app.tasks:
                    await asyncio.gather(*app.tasks, return_exceptions=True)

    async def test_real_non_proxy_tcp_peer_is_denied(self):
        response = await self.exchange(False)
        self.assertTrue(response.startswith(b"HTTP/1.1 403"))
        self.assertNotIn(b"Connect your controller safely", response)

    async def test_http_over_tcp_with_synthetic_proxy_identity(self):
        response = await self.exchange(True)
        self.assertTrue(response.startswith(b"HTTP/1.1 200"))
        self.assertIn(b"Connect your controller safely", response)
        self.assertIn(b"/api/hassio_ingress/synthetic-path/mqtt", response)

    async def test_pair_redirect_and_refresh_over_tcp_survive_original_client_close(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            atomic_json(state / "settings.json", dict(OPTIONS, operation="setup"))
            app = ingress.IngressServer(state)
            prefix = "/api/hassio_ingress/synthetic-path"
            started, finish = asyncio.Event(), asyncio.Event()
            async def pair(*args, **kwargs):
                started.set()
                await finish.wait()
                await save_peer(*args, **kwargs)
            async def handle(reader, writer):
                await app.handle(reader, SyntheticProxyWriter(writer))
            server = await asyncio.start_server(handle, "127.0.0.1", 0)
            async def request(method, route, fields=None):
                reader, writer = await asyncio.open_connection("127.0.0.1", server.sockets[0].getsockname()[1])
                body = urlencode(fields or {}).encode() if method == "POST" else b""
                headers = f"Host: app\r\nX-Remote-User-Id: synthetic-admin\r\nX-Ingress-Path: {prefix}\r\n"
                if method == "POST":
                    headers += f"Content-Type: application/x-www-form-urlencoded\r\nContent-Length: {len(body)}\r\n"
                writer.write(f"{method} {route} HTTP/1.1\r\n{headers}\r\n".encode() + body)
                await writer.drain()
                response = await asyncio.wait_for(reader.read(), 5)
                writer.close()
                await writer.wait_closed()
                return response
            try:
                with patch("pair_cc.pair", side_effect=pair):
                    token = app.csrf.issue("synthetic-admin", prefix, "/pairing/pair", ingress.time.monotonic())
                    response = await request("POST", "/pairing/pair", {"csrf_token": token, "code": "123456789", "approval": "yes"})
                    self.assertTrue(response.startswith(b"HTTP/1.1 303"))
                    self.assertIn(("Location: " + prefix + "/diagnostics").encode(), response)
                    await asyncio.wait_for(started.wait(), 5)
                    self.assertTrue(app.pairing_running())
                    self.assertIn(b"Completion is not yet confirmed", await request("GET", "/diagnostics"))
                    finish.set()
                    await asyncio.wait_for(app.pair_task, 5)
                    self.assertIn(b"Pairing is complete", await request("GET", "/diagnostics"))
            finally:
                server.close()
                await server.wait_closed()
                if app.pairing_running():
                    app.pair_task.cancel()
                    await asyncio.gather(app.pair_task, return_exceptions=True)
                if app.tasks:
                    await asyncio.gather(*app.tasks, return_exceptions=True)
