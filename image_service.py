from __future__ import annotations

from base64 import b64decode
from dataclasses import dataclass
from io import BytesIO
from typing import Final, Protocol

from openai import OpenAI

DEFAULT_IMAGE_MODEL: Final = "gpt-image-2"
MAX_IMAGE_BYTES: Final = 25 * 1024 * 1024
SUPPORTED_MIME_TYPES: Final = frozenset({"image/jpeg", "image/png", "image/webp"})


@dataclass(frozen=True, slots=True)
class AdvertisementImageRequest:
    request_id: str
    hotel_image_bytes: bytes
    image_mime_type: str
    hotel_description: str
    ad_copy: str
    additional_instructions: str


@dataclass(frozen=True, slots=True)
class GeneratedImage:
    image_bytes: bytes
    image_mime_type: str


class ImageGenerator(Protocol):
    def generate(self, request: AdvertisementImageRequest) -> GeneratedImage: ...


class InvalidAdvertisementImageRequest(Exception):
    pass


class ImageSizeLimitExceeded(Exception):
    pass


class ImageGenerationError(Exception):
    pass


class OpenAIImageGenerator:
    def generate(self, request: AdvertisementImageRequest) -> GeneratedImage:
        validate_request(request)
        with BytesIO(request.hotel_image_bytes) as image, OpenAI() as client:
            response = client.images.edit(
                model=DEFAULT_IMAGE_MODEL,
                image=("hotel-image", image, request.image_mime_type),
                prompt=create_ad_prompt(request),
                output_format="png",
                quality="medium",
            )
        encoded = response.data[0].b64_json
        if encoded is None:
            raise ImageGenerationError()
        return GeneratedImage(image_bytes=b64decode(encoded), image_mime_type="image/png")


def validate_request(request: AdvertisementImageRequest) -> None:
    if not request.request_id:
        raise InvalidAdvertisementImageRequest("request_id must not be empty")
    if not request.hotel_image_bytes:
        raise InvalidAdvertisementImageRequest("hotel_image_bytes must not be empty")
    if len(request.hotel_image_bytes) > MAX_IMAGE_BYTES:
        raise ImageSizeLimitExceeded()
    if request.image_mime_type not in SUPPORTED_MIME_TYPES:
        raise InvalidAdvertisementImageRequest("image_mime_type must be JPEG, PNG, or WebP")
    if not request.hotel_description:
        raise InvalidAdvertisementImageRequest("hotel_description must not be empty")
    if not request.ad_copy:
        raise InvalidAdvertisementImageRequest("ad_copy must not be empty")


def create_ad_prompt(request: AdvertisementImageRequest) -> str:
    instructions = request.additional_instructions or "No additional visual instructions."
    return (
        "Create one polished hotel advertisement image using the supplied hotel photo as "
        "the visual reference. Preserve the hotel’s identifiable architecture, rooms, and amenities.\n\n"
        f"Hotel description:\n{request.hotel_description}\n\n"
        f"Required advertising copy:\n{request.ad_copy}\n\n"
        f"Additional creative direction:\n{instructions}"
    )
