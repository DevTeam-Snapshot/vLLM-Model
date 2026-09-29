import json
from io import BytesIO

import grpc
import pytest
from PIL import Image
from test_v2_draft import request
from test_v2_draft_provider import provider

from v2.draft import DraftEngine
from v2.errors import ModelFailure


def vision_reply() -> bytes:
    return json.dumps(
        {
            "id": "resp_local",
            "object": "response",
            "created_at": 1,
            "status": "completed",
            "model": "gpt-4.1-mini",
            "error": None,
            "output": [
                {
                    "type": "message",
                    "id": "msg_local",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "annotations": [],
                            "text": json.dumps(
                                {
                                    "palette": "ocean",
                                    "selling_point_indices": [0],
                                    "focus_x": 0.8,
                                    "focus_y": 0.5,
                                    "text_position": "bottom_right",
                                    "overlay_opacity": 0.75,
                                }
                            ),
                        }
                    ],
                }
            ],
        }
    ).encode()


def test_live_uses_vision_design_with_fixed_portrait_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a wide source photo and a confirmed hotel brief.
    given = request()
    given.direction = 3
    with provider(vision_reply()) as (url, received):
        monkeypatch.setenv("OPENAI_API_KEY", "local-test-only")
        monkeypatch.setenv("OPENAI_BASE_URL", url)
        # When: a live draft is requested.
        result = DraftEngine().generate(given)
    # Then: Vision supplies structured design choices and output remains portrait.
    assert len(received) == 1
    payload = json.loads(received[0])
    assert payload["store"] is False
    assert payload["text"]["format"]["strict"] is True
    assert "tools" not in payload
    assert payload["input"][0]["content"][1]["type"] == "input_image"
    context = json.loads(payload["input"][0]["content"][0]["text"])
    assert context["selling_points"] == list(given.brief.selling_points)
    with Image.open(BytesIO(result.image_bytes)) as image:
        assert image.size == (1080, 1350)


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


@pytest.mark.parametrize("indices", [[1], [0, 0]])
def test_unavailable_or_duplicate_facts_are_rejected(
    indices: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: a brief with one fact and a provider selecting invalid facts.
    reply = json.loads(vision_reply())
    advice = json.loads(reply["output"][0]["content"][0]["text"])
    advice["selling_point_indices"] = indices
    reply["output"][0]["content"][0]["text"] = json.dumps(advice)
    with provider(json.dumps(reply).encode()) as (url, received):
        monkeypatch.setenv("OPENAI_API_KEY", "local-test-only")
        monkeypatch.setenv("OPENAI_BASE_URL", url)
        # When: the live pipeline consumes the advice.
        with pytest.raises(ModelFailure) as failure:
            DraftEngine().generate(request())
    # Then: it fails explicitly without silently substituting or inventing facts.
    assert failure.value.reason == "MODEL_OUTPUT_INVALID"
    assert len(received) == 1


@pytest.mark.parametrize(
    "text",
    [
        "not JSON",
        "{}",
        '{"palette":"ocean","selling_point_indices":[0],"focus_x":1.5,"focus_y":0.5,"text_position":"top_left","overlay_opacity":0.7}',
        '{"palette":"ocean","selling_point_indices":[0],"focus_x":0.5,"focus_y":0.5,"text_position":"center","overlay_opacity":0.7}',
    ],
)
def test_invalid_advice_is_rejected(text: str, monkeypatch: pytest.MonkeyPatch) -> None:
    reply = json.loads(vision_reply())
    reply["output"][0]["content"][0]["text"] = text
    with provider(json.dumps(reply).encode()) as (url, received):
        monkeypatch.setenv("OPENAI_API_KEY", "local-test-only")
        monkeypatch.setenv("OPENAI_BASE_URL", url)
        with pytest.raises(ModelFailure) as failure:
            DraftEngine().generate(request())
    assert failure.value.code == grpc.StatusCode.INTERNAL
    assert failure.value.reason == "MODEL_OUTPUT_INVALID"
    assert len(received) == 1
