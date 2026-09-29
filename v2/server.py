"""Run V1 and V2 on one listener with explicit live/offline selection."""

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from logging import basicConfig, getLogger
from typing import Final

import grpc
import hotel_ad_image_pb2_grpc as v1_rpc
from PIL import Image

from grpc_server import AdvertisementImageServicer
from image_service import (
    AdvertisementImageRequest,
    GeneratedImage,
    OpenAIImageGenerator,
    validate_request,
)
from v2.config import Settings
from v2.draft import DraftEngine
from v2.planning import PlanningEngine
from v2.services import register_services
from v2.vllm import VllmTurnExtractor

MAX_MESSAGE_BYTES: Final = 32 * 1024 * 1024
CHANNEL_OPTIONS: Final = (
    ("grpc.max_send_message_length", MAX_MESSAGE_BYTES),
    ("grpc.max_receive_message_length", MAX_MESSAGE_BYTES),
)


class OfflineV1Generator:
    """A paid-call-free V1 transport check, not an advertisement generator."""

    def generate(self, request: AdvertisementImageRequest) -> GeneratedImage:
        validate_request(request)
        with BytesIO() as output, Image.new("RGB", (1024, 1024), "#dce5e3") as image:
            image.save(output, "PNG")
            return GeneratedImage(output.getvalue(), "image/png")


def run() -> None:
    settings = Settings()
    basicConfig(level="INFO", format="%(levelname)s %(name)s %(message)s")
    logger = getLogger(__name__)
    fake = settings.model_mode == "fake"
    planning = (
        PlanningEngine()
        if fake
        else PlanningEngine(
            VllmTurnExtractor(
                base_url=settings.vllm_base_url,
                model=settings.vllm_model,
                api_key=settings.vllm_api_key.get_secret_value(),
                timeout_seconds=settings.vllm_timeout_seconds,
                max_context_tokens=settings.vllm_context_tokens,
            )
        )
    )
    draft = DraftEngine(fake=fake, settings=settings)
    with ThreadPoolExecutor(max_workers=12) as pool:
        server = grpc.server(pool, options=CHANNEL_OPTIONS)
        register_services(server, planning, draft)
        v1_rpc.add_HotelAdvertisementImageServiceServicer_to_server(
            AdvertisementImageServicer(
                OfflineV1Generator() if fake else OpenAIImageGenerator()
            ),
            server,
        )
        address = f"{settings.grpc_host}:{settings.port}"
        if server.add_insecure_port(address) == 0:
            raise RuntimeError("gRPC listener could not bind")
        server.start()
        logger.info("server_started address=%s mode=%s", address, settings.model_mode)
        try:
            server.wait_for_termination()
        except KeyboardInterrupt:
            logger.info("server_stopping")
        finally:
            server.stop(5).wait()


if __name__ == "__main__":
    run()
