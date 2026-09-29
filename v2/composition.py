from dataclasses import dataclass
from io import BytesIO
from typing import Literal, assert_never

import grpc
from PIL import Image, ImageDraw, ImageFont
from PIL.PngImagePlugin import PngInfo

from v2.ad_drawing import FONT_PATH, OUTPUT_SIZE, shade_edges
from v2.ad_templates import AdContent, editorial, emotional, spotlight
from v2.errors import ModelFailure
from v2.image_validation import MAX_BYTES
from v2.layout import LayoutAdvice


@dataclass(frozen=True, slots=True)
class Composition:
    lodging_name: str
    ad_copy: str
    direction: int
    generation_round: int
    fake: bool = False
    layout: LayoutAdvice | None = None
    selling_points: tuple[str, ...] = ()


def portrait_crop(image: Image.Image, focus: tuple[float, float]) -> Image.Image:
    crop_width = min(image.width, image.height * 4 / 5)
    crop_height = crop_width * 5 / 4
    left = max(
        0.0, min(image.width - crop_width, image.width * focus[0] - crop_width / 2)
    )
    upper = max(
        0.0, min(image.height - crop_height, image.height * focus[1] - crop_height / 2)
    )
    return image.resize(
        OUTPUT_SIZE,
        Image.Resampling.LANCZOS,
        box=(left, upper, left + crop_width, upper + crop_height),
    )


def compose(image: Image.Image, spec: Composition) -> bytes:
    try:
        focus = (
            (spec.layout.focus_x, spec.layout.focus_y) if spec.layout else (0.5, 0.5)
        )
        top = (
            spec.layout.text_position.startswith("top")
            if spec.layout
            else spec.generation_round == 1
        )
        right = (
            spec.layout.text_position.endswith("right")
            if spec.layout
            else spec.generation_round == 2
        )
        opacity = spec.layout.overlay_opacity if spec.layout else 0.76
        palette: Literal["ocean", "forest", "terracotta"] = "ocean"
        if spec.layout:
            palette = spec.layout.palette
            indices = spec.layout.selling_point_indices
            if len(indices) != len(set(indices)) or any(
                index >= len(spec.selling_points) for index in indices
            ):
                raise ModelFailure("MODEL_OUTPUT_INVALID", grpc.StatusCode.INTERNAL)
            features = tuple(spec.selling_points[index] for index in indices)
        else:
            features = spec.selling_points[:3]
            if spec.generation_round == 2:
                palette = "terracotta"
        canvas = shade_edges(portrait_crop(image, focus), top, opacity)
        content = AdContent(
            spec.lodging_name, spec.ad_copy, features, top, right, palette
        )
        template: Literal["emotional", "spotlight", "editorial"]
        match spec.direction:
            case 1:
                template = "emotional"
            case 2:
                template = "spotlight"
            case 3:
                template = "editorial"
            case _:
                raise ModelFailure("INVALID_ARGUMENT", grpc.StatusCode.INVALID_ARGUMENT)
        match template:
            case "emotional":
                emotional(canvas, content)
            case "spotlight":
                spotlight(canvas, content)
            case "editorial":
                editorial(canvas, content)
            case unreachable:
                assert_never(unreachable)
        if spec.fake:
            draw = ImageDraw.Draw(canvas)
            font = ImageFont.truetype(str(FONT_PATH), 18)
            draw.text(
                (1060, 675),
                "FAKE / LOCAL TEST",
                font=font,
                fill="white",
                stroke_width=1,
                stroke_fill="#142b35",
                anchor="rm",
            )
        metadata = PngInfo()
        metadata.add_text("layout_provider", "openai" if spec.layout else "local")
        metadata.add_text("output_format", "portrait_4_5")
        metadata.add_text("ad_template", template)
        with BytesIO() as output:
            canvas.save(output, format="PNG", pnginfo=metadata)
            data = output.getvalue()
        if len(data) > MAX_BYTES:
            raise ModelFailure("OUTPUT_TOO_LARGE", grpc.StatusCode.INTERNAL)
        return data
    except (OSError, ValueError) as error:
        raise ModelFailure("COMPOSITION_FAILED", grpc.StatusCode.INTERNAL) from error
