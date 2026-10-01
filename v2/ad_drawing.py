from dataclasses import dataclass
from pathlib import Path
from typing import Final

import grpc
from PIL import Image, ImageDraw, ImageFont

from v2.errors import ModelFailure

FONT_PATH: Final = Path(__file__).resolve().parents[1] / "assets/fonts/NotoSansKR.ttf"
OUTPUT_SIZE: Final = (1080, 1350)


@dataclass(frozen=True, slots=True)
class TextBox:
    bounds: tuple[int, int, int, int]
    size: int = 48
    weight: int = 500
    color: str = "#fff8eb"
    right: bool = False


def wrap_text(text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        line = ""
        for character in paragraph:
            if line and font.getlength(line + character) > width:
                split = line.rfind(" ")
                if split > 0:
                    lines.append(line[: split + 1])
                    line = line[split + 1 :]
                else:
                    lines.append(line)
                    line = ""
            line += character
        lines.append(line)
    return lines


def lettering(draw: ImageDraw.ImageDraw, text: str, box: TextBox) -> None:
    left, top, width, height = box.bounds
    for size in range(box.size, 11, -2):
        font = ImageFont.truetype(str(FONT_PATH), size)
        font.set_variation_by_axes([box.weight])
        lines = wrap_text(text, font, width)
        line_height = sum(font.getmetrics()) + 2
        if len(lines) * line_height <= height and all(
            font.getlength(line) <= width for line in lines
        ):
            for index, line in enumerate(lines):
                x = left + width - font.getlength(line) if box.right else left
                draw.text(
                    (x, top + index * line_height),
                    line,
                    font=font,
                    fill=box.color,
                    anchor="lt",
                )
            return
    raise ModelFailure("COMPOSITION_FAILED", grpc.StatusCode.INTERNAL)


def shade_edges(image: Image.Image, top: bool, opacity: float) -> Image.Image:
    overlay = Image.new("RGBA", OUTPUT_SIZE)
    draw = ImageDraw.Draw(overlay)
    for offset in range(520):
        alpha = round(255 * opacity * (1 - offset / 520) ** 0.65)
        main_y = offset if top else 1349 - offset
        other_y = 1349 - offset if top else offset
        draw.line((0, main_y, 1079, main_y), fill=(8, 20, 24, alpha))
        draw.line((0, other_y, 1079, other_y), fill=(8, 20, 24, round(alpha * 0.8)))
    return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
