"""No-cost public-surface check against an explicitly started offline server."""

import json
import os
from io import BytesIO
from pathlib import Path

import grpc
import hotel_ad_image_pb2 as v1
import hotel_ad_image_pb2_grpc as v1_rpc
import hotel_ad_v2_pb2 as pb
import hotel_ad_v2_pb2_grpc as rpc
from google.protobuf import empty_pb2
from grpc_status import rpc_status
from PIL import Image, ImageDraw

from v2.server import CHANNEL_OPTIONS


def main() -> None:
    if os.environ.get("MODEL_MODE", "fake") != "fake":
        raise SystemExit(
            "This smoke command requires MODEL_MODE=fake; no paid calls were made."
        )
    output = Path("artifacts/local-smoke")
    output.mkdir(parents=True, exist_ok=True)
    target = os.environ.get("SMOKE_TARGET", f"127.0.0.1:{os.getenv('PORT', '50051')}")
    with grpc.insecure_channel(target, options=CHANNEL_OPTIONS) as channel:
        grpc.channel_ready_future(channel).result(timeout=20)
        planning = rpc.PlanningAgentServiceStub(channel)
        drafts = rpc.DraftImageServiceStub(channel)
        assert planning.HealthCheck(empty_pb2.Empty(), timeout=5).healthy
        assert drafts.HealthCheck(empty_pb2.Empty(), timeout=5).healthy
        assert (
            v1_rpc.HotelAdvertisementImageServiceStub(channel)
            .HealthCheck(v1.HealthCheckRequest(), timeout=5)
            .healthy
        )
        brief = pb.AdvertisementBrief()
        turns = (
            ("lodging_type", 1, pb.PLANNING_STEP_LODGING_TYPE),
            ("lodging_name", "바다호텔", pb.PLANNING_STEP_LODGING_INFORMATION),
            ("location", "강릉", pb.PLANNING_STEP_LODGING_INFORMATION),
            ("selling_points", ["오션뷰 객실"], pb.PLANNING_STEP_SELLING_POINTS),
            ("lodging_service", ["무료 주차"], pb.PLANNING_STEP_LODGING_SERVICE),
            ("mood", "차분함", pb.PLANNING_STEP_MOOD),
            ("color_preference", "auto", pb.PLANNING_STEP_COLOR_PREFERENCE),
            ("target_audience", "커플", pb.PLANNING_STEP_TARGET_AUDIENCE),
        )
        response = pb.ProcessTurnResponse()
        for revision, (field, value, step) in enumerate(turns):
            response = planning.ProcessTurn(
                pb.ProcessTurnRequest(
                    request_id=f"smoke-chat-{revision + 1}",
                    session_id="smoke",
                    state_revision=revision,
                    event_type=pb.TURN_EVENT_TYPE_USER_MESSAGE,
                    user_message=json.dumps({field: value}, ensure_ascii=False),
                    current_step=step,
                    brief=brief,
                    original_image_uploaded=True,
                ),
                timeout=30,
            )
            assert response.state_revision == revision and not response.is_complete
            if field in ("selling_points", "lodging_service"):
                assert isinstance(value, list)
                getattr(brief, field).extend(value)
            else:
                setattr(brief, field, value)
        assert response.next_step == pb.PLANNING_STEP_AD_COPY
        accepted = planning.ProcessTurn(
            pb.ProcessTurnRequest(
                request_id="smoke-chat-final",
                session_id="smoke",
                state_revision=len(turns),
                event_type=pb.TURN_EVENT_TYPE_USER_MESSAGE,
                user_message="문구: 바다와 함께하는 둘만의 하루",
                current_step=pb.PLANNING_STEP_AD_COPY,
                brief=brief,
                original_image_uploaded=True,
            ),
            timeout=30,
        )
        assert accepted.is_complete and accepted.next_step == pb.PLANNING_STEP_COMPLETE
        brief.ad_copy = accepted.brief_updates.ad_copy.set_value
        with Image.new("RGB", (1200, 800), "#c6dce2") as source, BytesIO() as stream:
            draw = ImageDraw.Draw(source)
            draw.rectangle((100, 240, 1100, 730), fill="#ece5d4")
            draw.rectangle((230, 310, 700, 590), fill="#729cab")
            draw.rectangle((760, 390, 1030, 670), fill="#536963")
            source.save(stream, "PNG")
            image = stream.getvalue()
        legacy = v1_rpc.HotelAdvertisementImageServiceStub(
            channel
        ).GenerateAdvertisementImage(
            v1.GenerateAdvertisementImageRequest(
                request_id="smoke-v1",
                hotel_image_bytes=image,
                image_mime_type="image/png",
                hotel_description="test room",
                ad_copy="test",
            ),
            timeout=5,
        )
        assert legacy.image_mime_type == "image/png"
        assert legacy.image_bytes.startswith(bytes([137, 80, 78, 71, 13, 10, 26, 10]))
        hashes: set[bytes] = set()
        for generation_round in (1, 2):
            for direction in (
                pb.DRAFT_DIRECTION_SPACE,
                pb.DRAFT_DIRECTION_MOOD,
                pb.DRAFT_DIRECTION_SERVICE,
            ):
                draft_id = f"r{generation_round}-{direction}"
                request = pb.GenerateDraftRequest(
                    request_id=draft_id,
                    session_id="smoke",
                    draft_id=draft_id,
                    generation_round=generation_round,
                    is_regeneration=generation_round == 2,
                    direction=direction,
                    brief=brief,
                    original_image_bytes=image,
                    image_mime_type="image/png",
                )
                result = drafts.GenerateDraft(request, timeout=180)
                assert result.draft_id == draft_id and result.request_id == draft_id
                assert (
                    result.generation_round == generation_round
                    and result.direction == direction
                )
                assert result.image_mime_type == "image/png"
                with Image.open(BytesIO(result.image_bytes)) as decoded:
                    expected_size = (1080, 1350)
                    assert decoded.size == expected_size and decoded.format == "PNG"
                    decoded.verify()
                (output / f"{draft_id}.png").write_bytes(result.image_bytes)
                hashes.add(result.image_bytes)
        assert len(hashes) == 6
        try:
            planning.ProcessTurn(
                pb.ProcessTurnRequest(
                    request_id="smoke-readonly",
                    session_id="smoke",
                    state_revision=2,
                    event_type=pb.TURN_EVENT_TYPE_USER_MESSAGE,
                    user_message="수정",
                    current_step=pb.PLANNING_STEP_COMPLETE,
                    brief=brief,
                    original_image_uploaded=True,
                ),
                timeout=5,
            )
        except grpc.RpcError as error:
            assert error.code() == grpc.StatusCode.FAILED_PRECONDITION
            assert isinstance(error, grpc.Call)
            status = rpc_status.from_call(error)
            assert status is not None
            detail = pb.ModelErrorDetail()
            assert status.details[0].Unpack(detail)
            assert (
                detail.reason == "BRIEF_READ_ONLY"
                and detail.request_id == "smoke-readonly"
            )
        else:
            raise AssertionError("Read-only state accepted mutation")
    with grpc.insecure_channel(
        target, options=(("grpc.max_send_message_length", 40 * 1024 * 1024),)
    ) as large_channel:
        try:
            rpc.DraftImageServiceStub(large_channel).GenerateDraft(
                pb.GenerateDraftRequest(
                    original_image_bytes=b"x" * (32 * 1024 * 1024 + 1)
                ),
                timeout=5,
            )
        except grpc.RpcError as error:
            assert error.code() == grpc.StatusCode.RESOURCE_EXHAUSTED
        else:
            raise AssertionError("Server accepted a message over 32MiB")
    print(
        "PASS: V1/V2 health, sequential planning turns, six 1080x1350 advertisement drafts, "
        "structured error. FAKE mode; no paid calls."
    )
    print(f"Images: {output.resolve()}")


if __name__ == "__main__":
    main()
