from concurrent import futures

import grpc
import hotel_ad_image_pb2
import hotel_ad_image_pb2_grpc

from grpc_server import AdvertisementImageServicer
from image_service import AdvertisementImageRequest, GeneratedImage


class FakeImageGenerator:
    def generate(self, request: AdvertisementImageRequest) -> GeneratedImage:
        return GeneratedImage(image_bytes=b"generated-png", image_mime_type="image/png")


def test_generate_advertisement_image_over_grpc() -> None:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
    hotel_ad_image_pb2_grpc.add_HotelAdvertisementImageServiceServicer_to_server(
        AdvertisementImageServicer(FakeImageGenerator()), server
    )
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
            response = hotel_ad_image_pb2_grpc.HotelAdvertisementImageServiceStub(
                channel
            ).GenerateAdvertisementImage(
                hotel_ad_image_pb2.GenerateAdvertisementImageRequest(
                    request_id="request-123",
                    hotel_image_bytes=b"hotel-photo",
                    image_mime_type="image/png",
                    hotel_description="Seoul boutique hotel",
                    ad_copy="Stay tonight",
                )
            )
    finally:
        server.stop(0).wait()

    assert response.image_bytes == b"generated-png"
    assert response.image_mime_type == "image/png"
