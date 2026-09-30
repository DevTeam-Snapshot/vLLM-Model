import base64
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from email import policy
from email.parser import BytesParser
from io import BytesIO
from threading import Barrier

import grpc
import pytest
from PIL import Image
from test_v2_draft import request
from test_v2_draft_provider import provider

from v2.draft import DraftEngine
from v2.errors import ModelFailure


def image_reply(size: tuple[int, int] = (1152, 1440)) -> bytes:
    with BytesIO() as stream:
        Image.new("RGB", size, "#bc965b").save(stream, "PNG")
        return json.dumps(
            {
                "created": 1,
                "size": f"{size[0]}x{size[1]}",
                "data": [{"b64_json": base64.b64encode(stream.getvalue()).decode()}],
            }
        ).encode()


@pytest.mark.parametrize("direction", [1, 2, 3])
@pytest.mark.parametrize("round_number", [1, 2])
def test_live_returns_edited_image_without_template_overlays(
    direction: int,
    round_number: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an edits provider returns a complete 4:5 advertisement.
    with provider(image_reply()) as (url, received):
        monkeypatch.setenv("OPENAI_API_KEY", "local-test-only")
        monkeypatch.setenv("OPENAI_BASE_URL", url)
        # When: a live draft is requested.
        given = request()
        given.direction = direction
        given.generation_round = round_number
        given.is_regeneration = round_number == 2
        result = DraftEngine().generate(given)
    # Then: only a proportional resize is applied; no text or panels are overlaid.
    assert len(received) == 1
    with Image.open(BytesIO(result.image_bytes)) as image:
        assert image.size == (1080, 1350)
        assert image.getextrema() == ((188, 188), (150, 150), (91, 91))
        assert image.info["generation_provider"] == "openai_image_edit"
    body = received[0]
    boundary = body.split(b"\r\n", 1)[0][2:]
    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: multipart/form-data; boundary=" + boundary + b"\r\n\r\n" + body
    )
    parts = {
        part.get_param("name", header="content-disposition"): part.get_payload(
            decode=True
        )
        for part in message.iter_parts()
    }
    assert parts["model"] == b"gpt-image-2"
    assert parts["size"] == b"1152x1440"
    assert parts["quality"] == b"high"
    assert parts["n"] == b"1"
    assert parts["image"] == request().original_image_bytes
    assert "input_fidelity" not in parts
    context = json.loads(parts["prompt"].decode().split("SOURCE DATA JSON:\n")[1])
    assert context["selling_points"] == list(request().brief.selling_points)
    assert context["lodging_service"] == list(request().brief.lodging_service)
    assert (
        context["primary_focus"]
        == {
            1: "selling_points",
            2: "mood",
            3: "lodging_service",
        }[direction]
    )
    assert context["ad_copy"] == request().brief.ad_copy
    assert context["candidate"] == direction
    assert context["generation_round"] == round_number


@pytest.mark.parametrize(
    "status,reason",
    [
        (401, "GENERATION_REJECTED"),
        (403, "GENERATION_REJECTED"),
        (429, "UPSTREAM_RATE_LIMIT"),
        (500, "RESULT_UNKNOWN"),
    ],
)
def test_provider_failure_is_explicit(
    status: int, reason: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with provider(b'{"error":{"message":"private provider detail"}}', status) as (
        url,
        received,
    ):
        monkeypatch.setenv("OPENAI_API_KEY", "local-test-only")
        monkeypatch.setenv("OPENAI_BASE_URL", url)
        with pytest.raises(ModelFailure) as failure:
            DraftEngine().generate(request())
    assert failure.value.reason == reason
    assert len(received) == 1
    assert "private" not in str(failure.value)


def test_transient_rate_limit_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    limited = b'{"error":{"type":"requests","code":"rate_limit_exceeded"}}'
    with provider(limited, 429) as (url, received):
        monkeypatch.setenv("OPENAI_API_KEY", "local-test-only")
        monkeypatch.setenv("OPENAI_BASE_URL", url)
        with pytest.raises(ModelFailure) as failure:
            DraftEngine().generate(request())
    assert failure.value.reason == "UPSTREAM_RATE_LIMIT"
    assert len(received) == 1


def test_permanent_rate_limit_logs_provider_code_without_retry(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Given: the provider reports exhausted project credit.
    exhausted = b'{"error":{"type":"insufficient_quota","code":"credit_balance_exhausted","message":"private billing detail"}}'
    with provider(exhausted, 429) as (url, received):
        monkeypatch.setenv("OPENAI_API_KEY", "local-test-only")
        monkeypatch.setenv("OPENAI_BASE_URL", url)
        # When: a live draft is requested.
        with caplog.at_level(logging.WARNING), pytest.raises(ModelFailure):
            DraftEngine().generate(request())
    # Then: operators see the safe provider code and no futile retry occurs.
    assert len(received) == 1
    assert "error_code=credit_balance_exhausted" in caplog.text
    assert "private billing detail" not in caplog.text


def test_three_image_requests_overlap_over_grpc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hotel_ad_v2_pb2_grpc as rpc

    from v2.planning import PlanningEngine
    from v2.services import register_services

    activity = [0, 0]
    with provider(image_reply(), activity=activity, barrier=Barrier(3)) as (
        url,
        received,
    ):
        monkeypatch.setenv("OPENAI_API_KEY", "local-test-only")
        monkeypatch.setenv("OPENAI_BASE_URL", url)
        with (
            ThreadPoolExecutor(max_workers=4) as server_pool,
            ThreadPoolExecutor(max_workers=3) as callers,
        ):
            server = grpc.server(server_pool)
            register_services(server, PlanningEngine(), DraftEngine())
            port = server.add_insecure_port("127.0.0.1:0")
            server.start()
            try:
                with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
                    stub = rpc.DraftImageServiceStub(channel)
                    requests = []
                    for direction in (1, 2, 3):
                        given = request()
                        given.direction = direction
                        given.request_id = f"request-{direction}"
                        given.draft_id = f"draft-{direction}"
                        requests.append(given)
                    futures = [
                        callers.submit(stub.GenerateDraft, given, timeout=15)
                        for given in requests
                    ]
                    results = [future.result() for future in futures]
                assert [(r.direction, r.request_id, r.draft_id) for r in results] == [
                    (n, f"request-{n}", f"draft-{n}") for n in (1, 2, 3)
                ]
                assert all(
                    r.image_mime_type == "image/png" and r.image_bytes for r in results
                )
            finally:
                server.stop(0).wait()
    assert len(received) == 3
    assert activity[1] == 3


@pytest.mark.parametrize(
    "reply",
    [
        b"{}",
        b"not JSON",
        b'{"created":1,"data":[]}',
        b'{"created":1,"data":[{"b64_json":"!bad!"}]}',
        b'{"created":1,"data":[{"b64_json":"bm90IGEgcGhvdG8="}]}',
        b'{"created":1,"data":[{"url":"https://example.com/image.png"}]}',
        image_reply((1024, 1024)),
        image_reply((800, 1000)),
    ],
)
def test_invalid_output_is_rejected(
    reply: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    with provider(reply) as (url, received):
        monkeypatch.setenv("OPENAI_API_KEY", "local-test-only")
        monkeypatch.setenv("OPENAI_BASE_URL", url)
        with pytest.raises(ModelFailure) as failure:
            DraftEngine().generate(request())
    assert failure.value.reason == "MODEL_OUTPUT_INVALID"
    assert failure.value.code == grpc.StatusCode.INTERNAL
    assert len(received) == 1


def test_concurrency_one_restores_sequential_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    activity = [0, 0]
    with provider(image_reply(), activity=activity, delay_seconds=0.1) as (
        url,
        received,
    ):
        monkeypatch.setenv("OPENAI_API_KEY", "local-test-only")
        monkeypatch.setenv("OPENAI_BASE_URL", url)
        monkeypatch.setenv("IMAGE_MAX_CONCURRENCY", "1")
        engine = DraftEngine()
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(engine.generate, (request(), request(), request())))
    assert len(results) == len(received) == 3
    assert activity[1] == 1
