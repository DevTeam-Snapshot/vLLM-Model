"""Compose confirmed text over full-bleed photographs in three output formats."""

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Final

import grpc
from PIL import Image, ImageDraw, ImageFont, ImageOps

from v2.errors import ModelFailure
from v2.image_validation import MAX_BYTES

FONT_PATH: Final = Path(__file__).resolve().parents[1] / "assets/fonts/NotoSansKR.ttf"


@dataclass(frozen=True, slots=True)
class Composition:
    lodging_name: str
    ad_copy: str
    direction: int
    generation_round: int
    fake: bool = False


def wrap_text(text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    """Insert display line breaks without deleting or replacing input characters."""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        line = ""
        for character in paragraph:
            if line and font.getlength(line + character) > width:
                lines.append(line)
                line = ""
            line += character
        lines.append(line)
    return lines


def draw_fitted(
    draw: ImageDraw.ImageDraw, text: str, box: tuple[int, int, int, int]
) -> None:
    left, top, width, height = box
    for size in range(58, 7, -2):
        font = ImageFont.truetype(str(FONT_PATH), size)
        lines = wrap_text(text, font, width)
        line_height = sum(font.getmetrics()) + 4
        if len(lines) * line_height <= height and all(
            font.getlength(line) <= width for line in lines
        ):
            for index, line in enumerate(lines):
                draw.text(
                    (left, top + index * line_height),
                    line,
                    font=font,
                    fill="#ffffff",
                    anchor="lt",
                )
            return
    raise ModelFailure("COMPOSITION_FAILED", grpc.StatusCode.INTERNAL)


def uses_square(image: Image.Image, direction: int) -> bool:
    retained = min(image.size) / max(image.size)
    return direction == 2 or (direction == 3 and retained >= 0.85)


def compose(image: Image.Image, spec: Composition) -> bytes:
    try:
        if uses_square(image, spec.direction):
            canvas = ImageOps.fit(image, (1024, 1024), method=Image.Resampling.LANCZOS)
        else:
            scale = 1024 / max(image.size)
            size = (
                max(1, round(image.width * scale)),
                max(1, round(image.height * scale)),
            )
            canvas = image.resize(size, Image.Resampling.LANCZOS)
        width, height = canvas.size
        inset = max(
            8, round(min(width, height) * (0.06 + 0.015 * (spec.direction - 1)))
        )
        top = (spec.direction + spec.generation_round) % 2 == 0
        overlay_height = round(height * 0.44)
        overlay = Image.new("RGBA", canvas.size)
        shade = ImageDraw.Draw(overlay)
        for offset in range(overlay_height):
            alpha = round(190 * (1 - offset / overlay_height) ** 0.7)
            y = offset if top else height - 1 - offset
            shade.line((0, y, width, y), fill=(12, 20, 24, alpha))
        canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(canvas)
        text_y = inset if top else height - overlay_height + inset // 2
        content_height = overlay_height - inset * 2
        text_width = width - 2 * inset
        if spec.direction == 3:
            text_width = round(text_width * 0.82)
        draw.rectangle((inset, text_y, inset + 50, text_y + 3), fill="#e7ce96")
        name_height = round(content_height * 0.48)
        copy_y = text_y + 14 + name_height
        draw_fitted(
            draw, spec.lodging_name, (inset, text_y + 12, text_width, name_height)
        )
        draw_fitted(
            draw,
            spec.ad_copy,
            (inset, copy_y, text_width, content_height - name_height),
        )
        if spec.fake:
            font = ImageFont.truetype(str(FONT_PATH), max(8, min(18, width // 30)))
            draw.text(
                (width - 8, height // 2),
                "FAKE / LOCAL TEST",
                font=font,
                fill="white",
                stroke_width=1,
                stroke_fill="#142b35",
                anchor="rm",
            )
        output = BytesIO()
        canvas.save(output, format="PNG")
        data = output.getvalue()
        if len(data) > MAX_BYTES:
            raise ModelFailure("OUTPUT_TOO_LARGE", grpc.StatusCode.INTERNAL)
        return data
    except (OSError, ValueError) as error:
        raise ModelFailure("COMPOSITION_FAILED", grpc.StatusCode.INTERNAL) from error
