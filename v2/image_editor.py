import base64
from io import BytesIO
from logging import getLogger
from threading import BoundedSemaphore

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
from pydantic import BaseModel, ConfigDict, Field

from v2.config import Settings
from v2.errors import ModelFailure
from v2.image_prompt import build_prompt
from v2.image_validation import MAX_BYTES, MAX_PIXELS

logger = getLogger(__name__)


class EditedImage(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    b64_json: str = Field(min_length=1, max_length=((MAX_BYTES + 2) // 3) * 4)


class EditResponse(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    data: list[EditedImage] = Field(min_length=1, max_length=1)


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
        self._request_slots = BoundedSemaphore(settings.image_max_concurrency)

    def healthy(self) -> bool:
        return bool(self.settings.openai_api_key.get_secret_value().strip())

    def generate(self, request: pb.GenerateDraftRequest) -> bytes:
        if not self.healthy():
            raise ModelFailure("UPSTREAM_UNAVAILABLE", grpc.StatusCode.UNAVAILABLE)
        extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[
            request.image_mime_type
        ]
        with self._request_slots:
            return self._generate_once(request, extension)

    def _generate_once(self, request: pb.GenerateDraftRequest, extension: str) -> bytes:
        try:
            with OpenAI(
                api_key=self.settings.openai_api_key.get_secret_value(),
                base_url=self.settings.openai_base_url,
                timeout=self.settings.image_timeout_seconds,
                max_retries=0,
            ) as client:
                response = client.images.with_raw_response.edit(
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
            parsed = EditResponse.model_validate_json(response.text)
            return normalize_ad(parsed.data[0].b64_json, self.settings.image_model)
        except RateLimitError as error:
            logger.warning(
                "openai_image_rate_limited request_id=%r status=%s error_type=%s error_code=%s retry_after=%s upstream_request_id=%r attempt=1",
                request.request_id,
                error.status_code,
                error.type,
                error.code,
                error.response.headers.get("retry-after"),
                error.request_id,
            )
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
