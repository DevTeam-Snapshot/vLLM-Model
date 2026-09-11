from __future__ import annotations

import os
from concurrent import futures
from typing import Final

import grpc
import hotel_ad_image_pb2
import hotel_ad_image_pb2_grpc
from openai import OpenAIError

from image_service import (
    AdvertisementImageRequest,
    ImageGenerationError,
    ImageGenerator,
    ImageSizeLimitExceeded,
    InvalidAdvertisementImageRequest,
    OpenAIImageGenerator,
)

DEFAULT_PORT: Final = "50051"
MAX_GRPC_MESSAGE_BYTES: Final = 32 * 1024 * 1024


class AdvertisementImageServicer(
    hotel_ad_image_pb2_grpc.HotelAdvertisementImageServiceServicer
):
    def __init__(self, generator: ImageGenerator) -> None:
        self._generator = generator

    def GenerateAdvertisementImage(self, request, context):
        try:
            image = self._generator.generate(
                AdvertisementImageRequest(
                    request_id=request.request_id,
                    hotel_image_bytes=request.hotel_image_bytes,
                    image_mime_type=request.image_mime_type,
                    hotel_description=request.hotel_description,
                    ad_copy=request.ad_copy,
                    additional_instructions=request.additional_instructions,
                )
            )
        except InvalidAdvertisementImageRequest as error:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(error))
        except ImageSizeLimitExceeded:
            context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, "hotel image exceeds 25MiB")
        except (ImageGenerationError, OpenAIError):
            context.abort(grpc.StatusCode.UNAVAILABLE, "OpenAI image generation failed")
        return hotel_ad_image_pb2.GenerateAdvertisementImageResponse(
            image_bytes=image.image_bytes,
            image_mime_type=image.image_mime_type,
        )

    def HealthCheck(self, request, context):
        return hotel_ad_image_pb2.HealthCheckResponse(healthy=True)


def serve() -> None:
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=8),
        options=(
            ("grpc.max_send_message_length", MAX_GRPC_MESSAGE_BYTES),
            ("grpc.max_receive_message_length", MAX_GRPC_MESSAGE_BYTES),
        ),
    )
    hotel_ad_image_pb2_grpc.add_HotelAdvertisementImageServiceServicer_to_server(
        AdvertisementImageServicer(OpenAIImageGenerator()), server
    )
    server.add_insecure_port(f"[::]:{os.getenv('PORT', DEFAULT_PORT)}")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
