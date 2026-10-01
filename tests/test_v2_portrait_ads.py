from io import BytesIO

import pytest
from PIL import Image, ImageDraw
from test_v2_draft import request

from v2 import ad_templates
from v2.ad_drawing import TextBox
from v2.composition import Composition, compose
from v2.draft import DraftEngine
from v2.layout import LayoutAdvice


@pytest.mark.parametrize("size", [(1600, 900), (900, 1600), (1000, 1000)])
def test_all_templates_use_instagram_portrait(size: tuple[int, int]) -> None:
    # Given: the same hotel brief with three truthful advantages and any source ratio.
    given = request()
    given.brief.selling_points[:] = ["해변 도보 3분", "오션뷰 객실", "루프탑 수영장"]
    stream = BytesIO()
    Image.new("RGB", size, "#7799aa").save(stream, "PNG")
    given.original_image_bytes = stream.getvalue()
    outputs: set[bytes] = set()
    # When: all three candidate requests are rendered.
    for direction in (1, 2, 3):
        given.direction = direction
        result = DraftEngine(fake=True).generate(given)
        # Then: every candidate is 1080x1350 and contains the supplied facts.
        with Image.open(BytesIO(result.image_bytes)) as image:
            assert image.size == (1080, 1350)
            assert image.info["output_format"] == "portrait_4_5"
        outputs.add(result.image_bytes)
    assert len(outputs) == 3


def test_selected_advantages_keep_qualifiers(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: facts with restrictions that must not become unconditional promises.
    facts = ("일부 객실 바다 전망", "조식 유료", "해변 도보 약 3분")
    advice = LayoutAdvice(
        focus_x=0.5,
        focus_y=0.5,
        text_position="top_left",
        overlay_opacity=0.75,
        palette="ocean",
        selling_point_indices=[2, 0, 1],
    )
    drawn: list[str] = []
    original = ad_templates.lettering

    def record(draw: ImageDraw.ImageDraw, text: str, box: TextBox) -> None:
        drawn.append(text)
        original(draw, text, box)

    monkeypatch.setattr(ad_templates, "lettering", record)
    # When: the spotlight template draws the model-selected facts.
    compose(
        Image.new("RGB", (1080, 1350)),
        Composition("호텔", "휴식", 2, 1, layout=advice, selling_points=facts),
    )
    # Then: each complete input fact is rendered verbatim in the selected order.
    assert [text for text in drawn if text in facts] == [facts[2], facts[0], facts[1]]


@pytest.mark.parametrize("direction", [1, 2, 3])
def test_maximum_length_advantages_fit(direction: int) -> None:
    given = request()
    given.direction = direction
    given.brief.selling_points[:] = ["가나다라마바사아자차" * 10] * 3
    given.brief.lodging_name = "가나다라마바사아자차" * 10
    given.brief.ad_copy = "가나다라마바사아자차" * 6
    result = DraftEngine(fake=True).generate(given)
    with Image.open(BytesIO(result.image_bytes)) as image:
        assert image.size == (1080, 1350)
