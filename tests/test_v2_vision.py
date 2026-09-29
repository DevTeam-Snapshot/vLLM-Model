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
                                    "output_format": "square",
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


def test_live_uses_vision_instead_of_crop_loss_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a wide photo that the old rule would keep at its original ratio.
    given = request()
    given.direction = 3
    with provider(vision_reply()) as (url, received):
        monkeypatch.setenv("OPENAI_API_KEY", "local-test-only")
        monkeypatch.setenv("OPENAI_BASE_URL", url)
        # When: a live draft is requested.
        result = DraftEngine().generate(given)
    # Then: the vision decision controls the third candidate and never edits pixels remotely.
    assert len(received) == 1
    payload = json.loads(received[0])
    assert payload["store"] is False
    assert payload["text"]["format"]["strict"] is True
    assert "tools" not in payload
    assert payload["input"][0]["content"][1]["type"] == "input_image"
    with Image.open(BytesIO(result.image_bytes)) as image:
        assert image.size == (1024, 1024)


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


@pytest.mark.parametrize(
    "text",
    [
        "not JSON",
        "{}",
        '{"output_format":"square","focus_x":1.5,"focus_y":0.5,"text_position":"top_left","overlay_opacity":0.7}',
        '{"output_format":"square","focus_x":0.5,"focus_y":0.5,"text_position":"center","overlay_opacity":0.7}',
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
