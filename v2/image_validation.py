"""Decode bounded, normalized image payloads at the RPC boundary."""

from io import BytesIO
from typing import Final

import grpc
from PIL import Image, UnidentifiedImageError

from v2.errors import ModelFailure

MAX_BYTES: Final = 25 * 1024 * 1024
MAX_PIXELS: Final = 20_000_000
MIME_FORMAT: Final = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}


def decode_image(data: bytes, mime: str) -> Image.Image:
    if len(data) > MAX_BYTES:
        raise ModelFailure("INPUT_TOO_LARGE", grpc.StatusCode.RESOURCE_EXHAUSTED)
    if not data or mime not in MIME_FORMAT:
        raise ModelFailure("INVALID_IMAGE", grpc.StatusCode.INVALID_ARGUMENT)
    try:
        with Image.open(BytesIO(data)) as source:
            if source.width * source.height > MAX_PIXELS:
                raise ModelFailure(
                    "INPUT_TOO_LARGE", grpc.StatusCode.RESOURCE_EXHAUSTED
                )
            if (
                source.format != MIME_FORMAT[mime]
                or getattr(source, "n_frames", 1) != 1
                or source.getexif().get(274, 1) != 1
            ):
                raise ModelFailure("INVALID_IMAGE", grpc.StatusCode.INVALID_ARGUMENT)
            source.load()
            return source.convert("RGB")
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
        Image.DecompressionBombError,
    ) as error:
        raise ModelFailure("INVALID_IMAGE", grpc.StatusCode.INVALID_ARGUMENT) from error
