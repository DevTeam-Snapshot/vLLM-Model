"""Local HTTP fixture and offline-mode isolation checks."""

from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
from threading import Thread

import pytest
from PIL import Image
from test_v2_draft import request

from v2.draft import DraftEngine


@contextmanager
def provider(reply: bytes, status: int = 200) -> Iterator[tuple[str, list[bytes]]]:
    received: list[bytes] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path != "/v1/responses":
                self.send_error(404)
                return
            received.append(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

        def log_message(self, format: str, *args: str) -> None:
            return

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/v1", received
        finally:
            server.shutdown()
            thread.join(timeout=2)


@pytest.mark.parametrize("status", [200, 400, 429, 500])
def test_offline_render_ignores_provider_when_unavailable(
    status: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: an image API endpoint that would fail or return corrupt output.
    with provider(b'{"data":[{"b64_json":"!bad!"}]}', status) as (url, received):
        monkeypatch.setenv("OPENAI_API_KEY", "local-test-only")
        monkeypatch.setenv("OPENAI_BASE_URL", url)
        # When: an explicitly offline draft is generated from its original photo.
        result = DraftEngine(fake=True).generate(request())
    # Then: no photo is sent to the provider, regardless of provider status.
    assert received == []
    with Image.open(BytesIO(result.image_bytes)) as rendered:
        assert rendered.size == (1024, 768)
        assert rendered.format == "PNG"
