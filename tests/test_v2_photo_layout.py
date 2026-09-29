from io import BytesIO

import pytest
from PIL import Image, ImageChops, ImageDraw
from test_v2_draft import request

from v2.composition import Composition, compose
from v2.draft import DraftEngine


@pytest.mark.parametrize(
    "size,expected",
    [
        ((1200, 800), [(1024, 683), (1024, 1024), (1024, 683)]),
        ((800, 1200), [(683, 1024), (1024, 1024), (683, 1024)]),
        ((1000, 900), [(1024, 922), (1024, 1024), (1024, 1024)]),
    ],
)
def test_three_formats_when_source_ratio_changes(
    size: tuple[int, int], expected: list[tuple[int, int]]
) -> None:
    # Given: one source and the existing three direction requests.
    given = request()
    stream = BytesIO()
    Image.new("RGB", size, "#789999").save(stream, "PNG")
    given.original_image_bytes = stream.getvalue()
    engine = DraftEngine(fake=True)
    dimensions: list[tuple[int, int]] = []
    # When: the three drafts are rendered.
    for direction in (1, 2, 3):
        given.direction = direction
        with Image.open(BytesIO(engine.generate(given).image_bytes)) as result:
            dimensions.append(result.size)
    # Then: the wide crop is avoided automatically, the near-square crop is used.
    assert dimensions == expected


def test_photo_reaches_edges_when_copy_is_overlaid() -> None:
    # Given: a photo with different landmarks at both edges.
    source = Image.new("RGB", (1024, 768), "#91a8b7")
    draw = ImageDraw.Draw(source)
    draw.rectangle((0, 0, 100, 767), fill="#c3a15d")
    draw.rectangle((923, 0, 1023, 767), fill="#568aad")
    # When: a full-photo advertisement is composed.
    result = compose(source, Composition("바다 호텔", "편안한 하루", 1, 1))
    # Then: the middle strip retains both edges, without an external panel.
    with Image.open(BytesIO(result)) as rendered:
        strip = (0, 350, 1024, 400)
        assert rendered.size == source.size
        assert (
            ImageChops.difference(rendered.crop(strip), source.crop(strip)).getbbox()
            is None
        )


def test_live_draft_needs_no_image_provider_when_photo_is_local() -> None:
    # Given: live mode with no API key.
    engine = DraftEngine()
    # When: the validated photo is rendered.
    result = engine.generate(request())
    # Then: local readiness and a real PNG do not depend on an image API.
    assert engine.healthy()
    assert result.image_bytes.startswith(b"\x89PNG")


def test_square_keeps_scale_when_cropping_a_wide_photo() -> None:
    # Given: the central 1024 pixels fit a square without any resampling.
    source = Image.new("RGB", (1536, 1024), "#39759a")
    draw = ImageDraw.Draw(source)
    draw.rectangle((0, 0, 255, 1023), fill="red")
    draw.rectangle((1280, 0, 1535, 1023), fill="blue")
    draw.ellipse((600, 440, 936, 580), fill="#c4a055")
    # When: the square candidate is composed.
    result = compose(source, Composition("호텔", "편안한 휴식", 2, 1))
    # Then: the clear middle strip is the central source crop, never stretched.
    with Image.open(BytesIO(result)) as rendered:
        expected = source.crop((256, 470, 1280, 540))
        actual = rendered.crop((0, 470, 1024, 540))
        assert ImageChops.difference(actual, expected).getbbox() is None


@pytest.mark.parametrize("size", [(800, 1200), (1600, 900), (1000, 1000)])
def test_copy_fits_all_candidates_when_at_contract_limits(
    size: tuple[int, int],
) -> None:
    # Given: maximum-length Korean copy and common photo orientations.
    given = request()
    given.brief.lodging_name = "가나다라마바사아자차" * 10
    given.brief.ad_copy = "가나다라마바사아자차" * 6
    stream = BytesIO()
    Image.new("RGB", size, "#789999").save(stream, "PNG")
    given.original_image_bytes = stream.getvalue()
    engine = DraftEngine()
    results: set[bytes] = set()
    # When: every candidate is generated in both rounds.
    for direction in (1, 2, 3):
        for round_number in (1, 2):
            given.direction = direction
            given.generation_round = round_number
            given.is_regeneration = round_number == 2
            results.add(engine.generate(given).image_bytes)
    # Then: all six layouts render complete text and remain distinct.
    assert len(results) == 6
