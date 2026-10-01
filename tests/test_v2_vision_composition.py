from io import BytesIO

import pytest
from PIL import Image, ImageChops, ImageDraw

from v2.composition import Composition, compose, portrait_crop
from v2.layout import LayoutAdvice


def advice() -> LayoutAdvice:
    return LayoutAdvice(
        focus_x=0.9,
        focus_y=0.5,
        text_position="bottom_right",
        overlay_opacity=0.75,
        palette="ocean",
        selling_point_indices=[0],
    )


def test_vision_focus_preserves_off_center_subject() -> None:
    source = Image.new("RGB", (2160, 1350), "#559977")
    ImageDraw.Draw(source).rectangle((1500, 500, 1800, 800), fill="gold")
    rendered = portrait_crop(source, (0.9, 0.5))
    expected = source.crop((1080, 0, 2160, 1350))
    assert ImageChops.difference(expected, rendered).getbbox() is None


@pytest.mark.parametrize("direction", [1, 2, 3])
def test_all_designs_keep_fixed_portrait_format(direction: int) -> None:
    source = Image.new("RGB", (2048, 1024), "#559977")
    rendered = compose(
        source,
        Composition(
            "호텔", "휴식", direction, 1, layout=advice(), selling_points=("바다 전망",)
        ),
    )
    with Image.open(BytesIO(rendered)) as result:
        assert result.size == (1080, 1350)


def test_vision_opacity_changes_shading_without_changing_photo_center() -> None:
    source = Image.new("RGB", (1080, 1350), "#aabbcc")
    rendered = compose(
        source,
        Composition(
            "호텔", "휴식", 1, 1, layout=advice(), selling_points=("바다 전망",)
        ),
    )
    with Image.open(BytesIO(rendered)) as result:
        strip = (0, 540, 1080, 780)
        assert result.crop(strip).tobytes() == source.crop(strip).tobytes()
        assert result.convert("L").getpixel((0, 1349)) < source.convert("L").getpixel(
            (0, 1349)
        )
