from io import BytesIO

import grpc
import hotel_ad_v2_pb2 as pb
import pytest
from PIL import Image

from v2.draft import DraftEngine
from v2.errors import ModelFailure


def request() -> pb.GenerateDraftRequest:
    buffer = BytesIO()
    Image.new("RGB", (800, 600), "#678899").save(buffer, "PNG")
    return pb.GenerateDraftRequest(
        request_id="request",
        session_id="session",
        draft_id="draft",
        generation_round=1,
        is_regeneration=False,
        direction=1,
        brief=pb.AdvertisementBrief(
            lodging_type=1,
            lodging_name="바다 호텔",
            location="부산",
            selling_points=["바다 전망"],
            target_audience="가족",
            mood="편안한",
            color_preference="auto",
            ad_copy="바다와 함께 쉬어가세요",
        ),
        original_image_bytes=buffer.getvalue(),
        image_mime_type="image/png",
    )


def test_fake_returns_png_when_complete() -> None:
    given = request()
    result = DraftEngine(fake=True).generate(given)
    with Image.open(BytesIO(result.image_bytes)) as image:
        assert image.size == (1024, 768)
        assert image.format == "PNG"
    assert result.draft_id == given.draft_id


@pytest.mark.parametrize(
    "field,value",
    [
        ("direction", 99),
        ("image_mime_type", "image/jpeg"),
        ("original_image_bytes", b"broken"),
    ],
)
def test_rejects_invalid_input_when_malformed(
    field: str, value: str | int | bytes
) -> None:
    given = request()
    setattr(given, field, value)
    with pytest.raises(ModelFailure) as failure:
        DraftEngine(fake=True).generate(given)
    assert failure.value.code == grpc.StatusCode.INVALID_ARGUMENT


def test_rejects_round_when_flag_absent() -> None:
    given = request()
    given.ClearField("is_regeneration")
    with pytest.raises(ModelFailure) as failure:
        DraftEngine(fake=True).generate(given)
    assert failure.value.reason == "INVALID_GENERATION_ROUND"


def test_distinct_layout_when_direction_or_round_changes() -> None:
    given = request()
    engine = DraftEngine(fake=True)
    images = []
    for direction in (1, 2, 3):
        for round_number in (1, 2):
            given.direction = direction
            given.generation_round = round_number
            given.is_regeneration = round_number == 2
            images.append(engine.generate(given).image_bytes)
    assert len(set(images)) == 6


def test_rejects_orientation_when_not_normalized() -> None:
    given = request()
    source = Image.new("RGB", (40, 60))
    exif = Image.Exif()
    exif[274] = 6
    buffer = BytesIO()
    source.save(buffer, "JPEG", exif=exif)
    given.original_image_bytes = buffer.getvalue()
    given.image_mime_type = "image/jpeg"
    with pytest.raises(ModelFailure) as failure:
        DraftEngine(fake=True).generate(given)
    assert failure.value.reason == "INVALID_IMAGE"


def test_rejects_animation_when_png_has_multiple_frames() -> None:
    given = request()
    buffer = BytesIO()
    Image.new("RGB", (8, 8), "red").save(
        buffer,
        "PNG",
        save_all=True,
        append_images=[Image.new("RGB", (8, 8), "blue")],
        duration=100,
        loop=0,
    )
    given.original_image_bytes = buffer.getvalue()
    with pytest.raises(ModelFailure) as failure:
        DraftEngine(fake=True).generate(given)
    assert failure.value.reason == "INVALID_IMAGE"


def test_rejects_image_when_byte_limit_exceeded() -> None:
    given = request()
    given.original_image_bytes = bytes(25 * 1024 * 1024 + 1)
    with pytest.raises(ModelFailure) as failure:
        DraftEngine(fake=True).generate(given)
    assert failure.value.reason == "INPUT_TOO_LARGE"


def test_renders_when_text_at_contract_maximum() -> None:
    given = request()
    given.brief.lodging_name = "가나다라마바사아자차" * 10
    given.brief.ad_copy = "가나다라마바사아자차" * 6
    result = DraftEngine(fake=True).generate(given)
    assert result.image_bytes.startswith(b"\x89PNG")


def test_rejects_generation_when_brief_incomplete() -> None:
    given = request()
    given.brief.ClearField("ad_copy")
    with pytest.raises(ModelFailure) as failure:
        DraftEngine(fake=True).generate(given)
    assert failure.value.reason == "BRIEF_INCOMPLETE"
