from io import BytesIO

import pytest
from PIL import Image, ImageChops, ImageDraw

from v2.composition import Composition, compose
from v2.layout import LayoutAdvice


def advice() -> LayoutAdvice:
    return LayoutAdvice(
        output_format="square",
        focus_x=0.9,
        focus_y=0.5,
        text_position="bottom_right",
        overlay_opacity=0.75,
    )


def test_vision_focus_preserves_off_center_subject() -> None:
    source = Image.new("RGB", (2048, 1024), "#559977")
    ImageDraw.Draw(source).rectangle((1400, 450, 1800, 550), fill="gold")
    rendered = compose(source, Composition("호텔", "휴식", 2, 1, layout=advice()))
    with Image.open(BytesIO(rendered)) as result:
        expected = source.crop((1024, 470, 2048, 530))
        actual = result.crop((0, 470, 1024, 530))
        assert ImageChops.difference(expected, actual).getbbox() is None


@pytest.mark.parametrize("direction,expected", [(1, (1024, 512)), (2, (1024, 1024))])
def test_fixed_formats_override_model_recommendation(
    direction: int, expected: tuple[int, int]
) -> None:
    source = Image.new("RGB", (2048, 1024), "#559977")
    layout = advice().model_copy(
        update={"output_format": "original" if direction == 2 else "square"}
    )
    rendered = compose(source, Composition("호텔", "휴식", direction, 1, layout=layout))
    with Image.open(BytesIO(rendered)) as result:
        assert result.size == expected


def test_vision_position_and_opacity_control_overlay() -> None:
    source = Image.new("RGB", (1024, 1024), "#aabbcc")
    rendered = compose(source, Composition("호텔", "휴식", 2, 1, layout=advice()))
    with Image.open(BytesIO(rendered)) as result:
        assert (
            result.crop((0, 0, 1024, 400)).tobytes()
            == source.crop((0, 0, 1024, 400)).tobytes()
        )
        assert result.convert("L").getpixel((0, 1023)) < source.convert("L").getpixel(
            (0, 1023)
        )
