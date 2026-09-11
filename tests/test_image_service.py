import pytest

from image_service import (
    MAX_IMAGE_BYTES,
    AdvertisementImageRequest,
    ImageSizeLimitExceeded,
    InvalidAdvertisementImageRequest,
    validate_request,
)


def test_validate_request_when_image_exceeds_25_mib() -> None:
    request = AdvertisementImageRequest(
        request_id="request-123",
        hotel_image_bytes=b"x" * (MAX_IMAGE_BYTES + 1),
        image_mime_type="image/png",
        hotel_description="Seoul boutique hotel",
        ad_copy="Stay tonight",
        additional_instructions="",
    )

    with pytest.raises(ImageSizeLimitExceeded):
        validate_request(request)


def test_validate_request_when_image_format_is_not_supported() -> None:
    request = AdvertisementImageRequest(
        request_id="request-123",
        hotel_image_bytes=b"hotel-photo",
        image_mime_type="image/gif",
        hotel_description="Seoul boutique hotel",
        ad_copy="Stay tonight",
        additional_instructions="",
    )

    with pytest.raises(InvalidAdvertisementImageRequest):
        validate_request(request)
