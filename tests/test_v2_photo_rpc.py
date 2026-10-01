from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import grpc
import hotel_ad_v2_pb2_grpc as rpc
import pytest
from google.protobuf import empty_pb2
from PIL import Image
from test_v2_draft import request
from test_v2_draft_provider import provider
from test_v2_image_editor import image_reply

from v2.draft import DraftEngine
from v2.planning import PlanningEngine
from v2.services import register_services


def test_live_photo_candidates_when_called_over_grpc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a real loopback gRPC listener with the production image-edit SDK path.
    with (
        provider(image_reply()) as (url, received),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        monkeypatch.setenv("OPENAI_API_KEY", "local-test-only")
        monkeypatch.setenv("OPENAI_BASE_URL", url)
        server = grpc.server(pool)
        register_services(server, PlanningEngine(), DraftEngine())
        port = server.add_insecure_port("127.0.0.1:0")
        server.start()
        try:
            with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
                stub = rpc.DraftImageServiceStub(channel)
                assert stub.HealthCheck(empty_pb2.Empty(), timeout=5).healthy
                given = request()
                outputs: list[bytes] = []
                # When: the backend sends all three candidates in both rounds.
                for round_number in (1, 2):
                    given.generation_round = round_number
                    given.is_regeneration = round_number == 2
                    for direction in (1, 2, 3):
                        given.direction = direction
                        result = stub.GenerateDraft(given, timeout=10)
                        # Then: each reply keeps its identity and the required ratio.
                        assert result.direction == direction
                        assert result.generation_round == round_number
                        assert result.draft_id == given.draft_id
                        with Image.open(BytesIO(result.image_bytes)) as photo:
                            assert photo.size == (1080, 1350)
                        outputs.append(result.image_bytes)
                assert len(outputs) == 6
                assert all(output == outputs[0] for output in outputs)
                assert len(received) == 6
        finally:
            server.stop(0).wait()
