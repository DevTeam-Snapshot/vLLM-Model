"""Exercise the real OpenAI SDK against a local HTTP server, never a paid API."""

import base64
import json
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
from threading import Thread

import grpc
import pytest
from PIL import Image
from test_v2_draft import request

from v2.draft import DraftEngine
from v2.errors import ModelFailure


@contextmanager
def provider(reply: bytes, status: int = 200) -> Iterator[tuple[str, list[bytes]]]:
    received: list[bytes] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
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


def test_sdk_edit_when_provider_returns_png() -> None:
    buffer = BytesIO()
    Image.new("RGB", (1024, 1024), "#557799").save(buffer, "PNG")
    reply = json.dumps(
        {
            "created": 1,
            "data": [{"b64_json": base64.b64encode(buffer.getvalue()).decode()}],
        }
    ).encode()
    with provider(reply) as (url, received):
        result = DraftEngine(api_key="local-test-only", base_url=url).generate(
            request()
        )
    assert result.image_bytes.startswith(b"\x89PNG")
    assert len(received) == 1
    assert b'name="quality"\r\n\r\nmedium' in received[0]
    assert b'name="size"\r\n\r\n1024x1024' in received[0]


@pytest.mark.parametrize(
    "reply",
    [
        b'{"created":1,"data":[{"b64_json":"!bad!"}]}',
        b'{"created":1,"data":[{"b64_json":"YWJj"}]}',
    ],
)
def test_invalid_output_when_provider_returns_corruption(reply: bytes) -> None:
    with provider(reply) as (url, received), pytest.raises(ModelFailure) as failure:
        DraftEngine(api_key="local-test-only", base_url=url).generate(request())
    assert failure.value.reason == "MODEL_OUTPUT_INVALID"
    assert failure.value.code == grpc.StatusCode.INTERNAL
    assert len(received) == 1


@pytest.mark.parametrize(
    "status,reason,retryable",
    [
        (429, "UPSTREAM_RATE_LIMIT", True),
        (500, "RESULT_UNKNOWN", False),
        (400, "GENERATION_REJECTED", False),
    ],
)
def test_provider_error_when_http_fails(
    status: int, reason: str, retryable: bool
) -> None:
    with (
        provider(
            b'{"error":{"message":"private diagnostic","type":"error"}}', status
        ) as (url, received),
        pytest.raises(ModelFailure) as failure,
    ):
        DraftEngine(api_key="local-test-only", base_url=url).generate(request())
    assert failure.value.reason == reason
    assert failure.value.retryable == retryable
    assert len(received) == 1
