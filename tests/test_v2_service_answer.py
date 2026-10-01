import hotel_ad_v2_pb2 as pb
import pytest
from test_v2_planning import full_brief, request
from test_v2_target_audience import AudienceExtractor

from v2.planning import PlanningEngine
from v2.turn_types import Extraction, Updates


@pytest.mark.parametrize(
    "step,message,accepted",
    [
        (pb.PLANNING_STEP_SELLING_POINTS, "이미지 업로드 완료", False),
        (pb.PLANNING_STEP_SELLING_POINTS, "없음", False),
        (pb.PLANNING_STEP_LODGING_SERVICE, "이미지 업로드 완료", False),
        (pb.PLANNING_STEP_LODGING_SERVICE, "잘 모르겠어요", False),
        (pb.PLANNING_STEP_LODGING_SERVICE, "조식은 없지만 무료 주차가 있어요", False),
        (pb.PLANNING_STEP_LODGING_SERVICE, "없음", True),
        (pb.PLANNING_STEP_LODGING_SERVICE, "없어요", True),
        (pb.PLANNING_STEP_LODGING_SERVICE, "제공하는 혜택은 없습니다", True),
    ],
)
def test_no_service_requires_explicit_answer(
    step: int, message: str, accepted: bool
) -> None:
    given = request(message)
    given.brief.CopyFrom(full_brief())
    for field in ("lodging_service", "mood", "ad_copy"):
        given.brief.ClearField(field)
    given.original_image_uploaded = True
    given.current_step = step
    extractor = AudienceExtractor(
        Extraction(
            updates=Updates(lodging_service=["없음"]), confirmed=["lodging_service"]
        )
    )
    result = PlanningEngine(extractor).process(given)
    assert result.brief_updates.HasField("lodging_service") == accepted
    assert result.next_step == (
        pb.PLANNING_STEP_MOOD if accepted else pb.PLANNING_STEP_LODGING_SERVICE
    )
    if not accepted:
        assert pb.BRIEF_FIELD_LODGING_SERVICE in result.missing_fields


def test_upload_then_service_answer_over_grpc() -> None:
    from concurrent.futures import ThreadPoolExecutor

    import grpc
    import hotel_ad_v2_pb2_grpc as rpc
    from test_v2_planning_vllm import provider

    from v2.draft import DraftEngine
    from v2.services import register_services
    from v2.vllm import VllmTurnExtractor

    given = request("이미지 업로드 완료")
    given.brief.CopyFrom(full_brief())
    for field in ("lodging_service", "mood", "ad_copy"):
        given.brief.ClearField(field)
    given.original_image_uploaded = True
    given.current_step = pb.PLANNING_STEP_SELLING_POINTS
    with (
        provider('{"updates":{"lodging_service":["없음"]}}') as endpoint,
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        server = grpc.server(pool)
        register_services(
            server,
            PlanningEngine(VllmTurnExtractor(endpoint.url, "test")),
            DraftEngine(fake=True),
        )
        port = server.add_insecure_port("127.0.0.1:0")
        server.start()
        try:
            with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
                stub = rpc.PlanningAgentServiceStub(channel)
                result = stub.ProcessTurn(given, timeout=10)
                assert not result.brief_updates.HasField("lodging_service")
                assert result.next_step == pb.PLANNING_STEP_LODGING_SERVICE
                assert result.assistant_message
                given.current_step = result.next_step
                given.user_message = "없어요"
                given.state_revision += 1
                result = stub.ProcessTurn(given, timeout=10)
                assert list(result.brief_updates.lodging_service.values) == ["없음"]
                assert result.next_step == pb.PLANNING_STEP_MOOD
        finally:
            server.stop(0).wait()


def test_upload_system_event_does_not_save_services() -> None:
    given = request("")
    given.brief.CopyFrom(full_brief())
    given.brief.ClearField("lodging_service")
    given.original_image_uploaded = True
    given.current_step = pb.PLANNING_STEP_SELLING_POINTS
    given.event_type = 2
    result = PlanningEngine().process(given)
    assert not result.brief_updates.HasField("lodging_service")
    assert result.next_step == pb.PLANNING_STEP_LODGING_SERVICE
