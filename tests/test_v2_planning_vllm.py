"""Live adapter tests across an actual local HTTP socket, no paid requests."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import hotel_ad_v2_pb2 as pb
import pytest

from v2.errors import ModelFailure
from v2.vllm import VllmTurnExtractor


@dataclass(frozen=True, slots=True)
class Provider:
    url: str
    requests: list[tuple[str, str]]


@contextmanager
def provider(content: str, status: int = 200, tokens: int = 100) -> Iterator[Provider]:
    requests: list[tuple[str, str]] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: str) -> None:
            return None

        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                b'{"data":[{"id":"test","object":"model","created":0,"owned_by":"local"}],"object":"list"}'
            )

        def do_POST(self) -> None:
            payload = self.rfile.read(
                int(self.headers.get("Content-Length", 0))
            ).decode("utf-8")
            requests.append((self.path, payload))
            code = 200 if self.path == "/tokenize" else status
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            if self.path == "/tokenize":
                body = json.dumps({"count": tokens})
            else:
                body = json.dumps(
                    {
                        "id": "local",
                        "object": "chat.completion",
                        "created": 0,
                        "model": "test",
                        "choices": [
                            {
                                "index": 0,
                                "finish_reason": "stop",
                                "message": {"role": "assistant", "content": content},
                            }
                        ],
                    }
                )
            self.wfile.write(body.encode())

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            yield Provider(f"http://127.0.0.1:{server.server_port}/v1", requests)
        finally:
            server.shutdown()
            worker.join()


def test_structured_extraction_when_provider_returns_valid_json() -> None:
    given = pb.ProcessTurnRequest(user_message="호텔")
    with provider('{"updates":{"lodging_type":1}}') as url:
        actual = VllmTurnExtractor(url.url, "test").extract(given)
    assert actual.updates.lodging_type == 1


def test_health_when_configured_model_available() -> None:
    with provider("{}") as url:
        actual = VllmTurnExtractor(url.url, "test").healthy()
    assert actual


@pytest.mark.parametrize(
    ("content", "status", "reason"),
    [
        ("not json", 200, "MODEL_OUTPUT_INVALID"),
        ('{"updates":{"lodging_type":99}}', 200, "MODEL_OUTPUT_INVALID"),
        ("{}", 429, "UPSTREAM_RATE_LIMIT"),
        ("{}", 503, "UPSTREAM_UNAVAILABLE"),
    ],
)
def test_structured_failure_when_provider_rejects(
    content: str, status: int, reason: str
) -> None:
    with provider(content, status) as url, pytest.raises(ModelFailure) as error:
        VllmTurnExtractor(url.url, "test").extract(
            pb.ProcessTurnRequest(user_message="호텔")
        )
    assert error.value.reason == reason


def test_context_rejected_when_actual_tokenizer_exceeds_budget() -> None:
    with provider("{}", tokens=20000) as url, pytest.raises(ModelFailure) as error:
        VllmTurnExtractor(url.url, "test").extract(
            pb.ProcessTurnRequest(user_message="호텔")
        )
    assert error.value.reason == "CONTEXT_TOO_LARGE"


def test_live_request_routes_schema_and_non_thinking_parameters() -> None:
    given = pb.ProcessTurnRequest(user_message="호텔", session_id="payload-check")
    with provider('{"updates":{"lodging_type":1}}') as endpoint:
        VllmTurnExtractor(endpoint.url, "test").extract(given)
    assert [route for route, _ in endpoint.requests] == [
        "/tokenize",
        "/v1/chat/completions",
    ]
    token_body = json.loads(endpoint.requests[0][1])
    chat_body = json.loads(endpoint.requests[1][1])
    assert token_body["model"] == chat_body["model"] == "test"
    assert token_body["add_generation_prompt"] is True
    assert token_body["chat_template_kwargs"]["enable_thinking"] is False
    assert chat_body["chat_template_kwargs"]["enable_thinking"] is False
    assert token_body["messages"] == chat_body["messages"]
    snapshot = json.loads(chat_body["messages"][-1]["content"])
    assert snapshot["session_id"] == "payload-check"
    assert snapshot["user_message"] == given.user_message
    assert snapshot["expected_field"] == "lodging_type"
    response_format = chat_body["response_format"]
    assert response_format["type"] == "json_schema"
    schema = response_format["json_schema"]["schema"]
    assert "updates" in schema["properties"]
    assert schema["additionalProperties"] is False
    # Given the decoding schema, the model must also receive its field structure.
    system_content = chat_body["messages"][0]["content"]
    supplied_schema = json.loads(system_content.split("\nOUTPUT_SCHEMA_JSON\n", 1)[1])
    assert supplied_schema == schema
