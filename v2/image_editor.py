import base64
from io import BytesIO

import grpc
import hotel_ad_v2_pb2 as pb
from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)
from PIL import Image, PngImagePlugin, UnidentifiedImageError

from v2.config import Settings
from v2.errors import ModelFailure
from v2.image_prompt import build_prompt
from v2.image_validation import MAX_BYTES, MAX_PIXELS


def normalize_ad(encoded: str, model: str) -> bytes:
    try:
        if len(encoded) > ((MAX_BYTES + 2) // 3) * 4:
            raise ValueError("Oversized image")
        data = base64.b64decode(encoded, validate=True)
        if len(data) > MAX_BYTES:
            raise ValueError("Oversized image")
        with Image.open(BytesIO(data)) as source:
            if (
                source.format != "PNG"
                or getattr(source, "n_frames", 1) != 1
                or source.width * source.height > MAX_PIXELS
                or source.width * 5 != source.height * 4
                or source.width < 1080
                or source.getexif().get(274, 1) != 1
            ):
                raise ValueError("Invalid advertisement dimensions or format")
            image = source.convert("RGB").resize((1080, 1350), Image.Resampling.LANCZOS)
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("generation_provider", "openai_image_edit")
        metadata.add_text("output_format", "portrait_4_5")
        metadata.add_text("image_model", model)
        with BytesIO() as stream:
            image.save(stream, "PNG", pnginfo=metadata)
            return stream.getvalue()
    except (
        ValueError,
        OSError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
    ) as error:
        raise ModelFailure("MODEL_OUTPUT_INVALID", grpc.StatusCode.INTERNAL) from error


class OpenAIAdvertisementEditor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def healthy(self) -> bool:
        return bool(self.settings.openai_api_key.get_secret_value().strip())

    def generate(self, request: pb.GenerateDraftRequest) -> bytes:
        if not self.healthy():
            raise ModelFailure("UPSTREAM_UNAVAILABLE", grpc.StatusCode.UNAVAILABLE)
        extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[
            request.image_mime_type
        ]
        try:
            with OpenAI(
                api_key=self.settings.openai_api_key.get_secret_value(),
                base_url=self.settings.openai_base_url,
                timeout=self.settings.image_timeout_seconds,
                max_retries=0,
                _strict_response_validation=True,
            ) as client:
                response = client.images.edit(
                    model=self.settings.image_model,
                    image=(
                        f"hotel-source.{extension}",
                        request.original_image_bytes,
                        request.image_mime_type,
                    ),
                    prompt=build_prompt(request),
                    n=1,
                    size="1152x1440",
                    quality=self.settings.image_quality,
                    output_format="png",
                )
            if (
                not response.data
                or len(response.data) != 1
                or not response.data[0].b64_json
            ):
                raise ModelFailure("MODEL_OUTPUT_INVALID", grpc.StatusCode.INTERNAL)
            return normalize_ad(response.data[0].b64_json, self.settings.image_model)
        except RateLimitError as error:
            raise ModelFailure(
                "UPSTREAM_RATE_LIMIT", grpc.StatusCode.RESOURCE_EXHAUSTED, True
            ) from error
        except (APITimeoutError, APIConnectionError) as error:
            raise ModelFailure(
                "RESULT_UNKNOWN", grpc.StatusCode.DEADLINE_EXCEEDED
            ) from error
        except APIStatusError as error:
            if error.status_code in (400, 401, 403, 404, 422):
                raise ModelFailure(
                    "GENERATION_REJECTED", grpc.StatusCode.FAILED_PRECONDITION
                ) from error
            raise ModelFailure(
                "RESULT_UNKNOWN", grpc.StatusCode.DEADLINE_EXCEEDED
            ) from error
        except (APIResponseValidationError, ValueError) as error:
            raise ModelFailure(
                "MODEL_OUTPUT_INVALID", grpc.StatusCode.INTERNAL
            ) from error
