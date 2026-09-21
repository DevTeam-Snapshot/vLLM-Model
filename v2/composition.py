"""Compose exact confirmed text in six deterministic square layouts."""

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
    for size in range(58, 15, -2):
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


def compose(image: Image.Image, spec: Composition) -> bytes:
    try:
        canvas = Image.new("RGB", (1024, 1024), "#142b35")
        # The photo is contained, never cropped: the supplied room remains visible.
        panel_top = (spec.direction + spec.generation_round) % 2 == 0
        photo_height = 640 if spec.direction != 3 else 570
        photo = ImageOps.contain(image, (1024, photo_height), Image.Resampling.LANCZOS)
        photo_y = 1024 - photo_height if panel_top else 0
        canvas.paste(
            photo,
            ((1024 - photo.width) // 2, photo_y + (photo_height - photo.height) // 2),
        )
        draw = ImageDraw.Draw(canvas)
        panel_y = 0 if panel_top else photo_height
        panel_height = 1024 - photo_height
        inset = 52 + (spec.direction - 1) * 12
        draw.rectangle((inset, panel_y + 30, inset + 72, panel_y + 36), fill="#d5b783")
        draw_fitted(
            draw, spec.lodging_name, (inset, panel_y + 52, 1024 - 2 * inset, 142)
        )
        draw_fitted(
            draw,
            spec.ad_copy,
            (inset, panel_y + 210, 1024 - 2 * inset, panel_height - 232),
        )
        if spec.fake:
            draw.rectangle((0, photo_y, 224, photo_y + 35), fill="#142b35")
            draw.text(
                (12, photo_y + 7),
                "FAKE / LOCAL TEST",
                font=ImageFont.truetype(str(FONT_PATH), 18),
                fill="white",
            )
        output = BytesIO()
        canvas.save(output, format="PNG")
        data = output.getvalue()
        if len(data) > MAX_BYTES:
            raise ModelFailure("OUTPUT_TOO_LARGE", grpc.StatusCode.INTERNAL)
        return data
    except (OSError, ValueError) as error:
        raise ModelFailure("COMPOSITION_FAILED", grpc.StatusCode.INTERNAL) from error
