from dataclasses import dataclass
from typing import Literal, assert_never

from PIL import Image, ImageDraw

from v2.ad_drawing import TextBox, lettering


@dataclass(frozen=True, slots=True)
class AdContent:
    name: str
    headline: str
    features: tuple[str, ...]
    top: bool
    right: bool
    palette: Literal["ocean", "forest", "terracotta"]


def colors(palette: Literal["ocean", "forest", "terracotta"]) -> tuple[str, str]:
    match palette:
        case "ocean":
            return "#123e4b", "#efd29b"
        case "forest":
            return "#243f35", "#e0e8b3"
        case "terracotta":
            return "#653d32", "#f4c6a1"
        case unreachable:
            assert_never(unreachable)


def heading(image: Image.Image, content: AdContent, size: int) -> None:
    draw = ImageDraw.Draw(image)
    _, accent = colors(content.palette)
    y = 70 if content.top else 915
    lettering(
        draw, content.name, TextBox((70, y, 940, 105), 32, 600, right=content.right)
    )
    x = 922 if content.right else 70
    draw.line((x, y + 114, x + 88, y + 114), fill=accent, width=5)
    lettering(
        draw,
        content.headline,
        TextBox((70, y + 139, 940, 280), size, 750, right=content.right),
    )


def cta(draw: ImageDraw.ImageDraw, y: int, palette: tuple[str, str]) -> None:
    ink, accent = palette
    draw.rounded_rectangle((690, y, 1010, y + 64), radius=32, fill=accent)
    lettering(draw, "숙소 자세히 보기", TextBox((719, y + 14, 240, 45), 25, 650, ink))
    draw.line((974, y + 32, 991, y + 32), fill=ink, width=2)
    draw.line((984, y + 25, 991, y + 32, 984, y + 39), fill=ink, width=2)


def emotional(image: Image.Image, content: AdContent) -> None:
    heading(image, content, 86)
    draw = ImageDraw.Draw(image)
    palette = colors(content.palette)
    y = 940 if content.top else 70
    lettering(
        draw, "STAY / YOUR OWN PACE", TextBox((70, y, 940, 45), 23, 500, palette[1])
    )
    count = len(content.features)
    for index, feature in enumerate(content.features):
        width = (940 - (count - 1) * 18) // count
        x = 70 + index * (width + 18)
        draw.rounded_rectangle(
            (x, y + 68, x + width, y + 252), radius=20, outline=palette[1], width=2
        )
        lettering(draw, feature, TextBox((x + 20, y + 94, width - 40, 140), 36, 650))
    cta(draw, y + 277, palette)


def spotlight(image: Image.Image, content: AdContent) -> None:
    heading(image, content, 72)
    draw = ImageDraw.Draw(image)
    palette = colors(content.palette)
    y = 865 if content.top else 46
    draw.rounded_rectangle((48, y, 1032, y + 439), radius=32, fill=palette[0])
    draw.rounded_rectangle((78, y + 28, 290, y + 76), radius=24, fill=palette[1])
    lettering(draw, "이곳의 매력", TextBox((102, y + 37, 174, 36), 24, 700, palette[0]))
    if content.features:
        lettering(draw, content.features[0], TextBox((78, y + 96, 916, 167), 84, 800))
    for index, feature in enumerate(content.features[1:]):
        x = 78 + index * 466
        draw.ellipse((x, y + 291, x + 8, y + 299), fill=palette[1])
        lettering(draw, feature, TextBox((x + 20, y + 274, 426, 75), 29, 500))
    cta(draw, y + 353, palette)


def editorial(image: Image.Image, content: AdContent) -> None:
    heading(image, content, 92)
    draw = ImageDraw.Draw(image)
    palette = colors(content.palette)
    y = 875 if content.top else 52
    lettering(
        draw, "A STAY TO REMEMBER", TextBox((70, y, 940, 40), 24, 500, palette[1])
    )
    for index, feature in enumerate(content.features):
        row = y + 62 + index * 94
        draw.line((70, row, 1010, row), fill=palette[1], width=1)
        lettering(
            draw, f"0{index + 1}", TextBox((70, row + 17, 76, 60), 37, 350, palette[1])
        )
        lettering(draw, feature, TextBox((165, row + 14, 845, 73), 40, 650))
    cta(draw, y + 348, palette)
