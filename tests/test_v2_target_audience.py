from concurrent.futures import ThreadPoolExecutor

import grpc
import hotel_ad_v2_pb2 as pb
import hotel_ad_v2_pb2_grpc as rpc
import pytest
from test_v2_planning import full_brief, request
from test_v2_planning_vllm import provider

from v2.draft import DraftEngine
from v2.planning import PlanningEngine
from v2.services import register_services
from v2.turn_types import Extraction, Updates
from v2.vllm import VllmTurnExtractor


class AudienceExtractor:
    def __init__(self, result: Extraction) -> None:
        self.result = result

    def healthy(self) -> bool:
        return True

    def extract(self, request: pb.ProcessTurnRequest) -> Extraction:
        return self.result


def audience_request(message: str) -> pb.ProcessTurnRequest:
    given = request(message)
    given.brief.CopyFrom(full_brief())
    given.brief.ClearField("target_audience")
    given.original_image_uploaded = True
    given.current_step = pb.PLANNING_STEP_TARGET_AUDIENCE
    return given


@pytest.mark.parametrize(
    "message,value",
    [
        ("알아서 정해주세요", "커플 여행객"),
        ("가족 여행객", "家庭旅行者"),
        ("잘 모르겠어요", "가족"),
    ],
)
def test_invented_or_translated_audience_is_not_saved(message: str, value: str) -> None:
    given = audience_request(message)
    result = PlanningEngine(
        AudienceExtractor(
            Extraction(
                updates=Updates(target_audience=value),
                confirmed=["target_audience"],
                explanation="家庭旅行者로 정했어요",
            )
        )
    ).process(given)
    assert not result.brief_updates.HasField("target_audience")
    assert result.next_step == pb.PLANNING_STEP_TARGET_AUDIENCE
    assert result.answer_status == pb.ANSWER_STATUS_AMBIGUOUS
    assert "家庭" not in result.assistant_message
    assert pb.BRIEF_FIELD_TARGET_AUDIENCE in result.missing_fields


def test_audience_cannot_be_inferred_before_target_question() -> None:
    given = audience_request("커플 느낌의 분홍색")
    given.current_step = pb.PLANNING_STEP_COLOR_PREFERENCE
    result = PlanningEngine(
        AudienceExtractor(Extraction(updates=Updates(target_audience="커플")))
    ).process(given)
    assert not result.brief_updates.HasField("target_audience")
    assert result.next_step == pb.PLANNING_STEP_TARGET_AUDIENCE


@pytest.mark.parametrize(
    "message",
    [
        "가족 여행객",
        "가족 여행객을 대상으로 하고 싶어요",
        '{"target_audience":"가족 여행객"}',
        '{"target_audience":"\\uac00\\uc871 \\uc5ec\\ud589\\uac1d"}',
    ],
)
def test_explicit_audience_answer_is_saved_without_translation(message: str) -> None:
    given = audience_request(message)
    result = PlanningEngine(
        AudienceExtractor(Extraction(updates=Updates(target_audience="가족 여행객")))
    ).process(given)
    assert result.brief_updates.target_audience.set_value == "가족 여행객"
    assert result.next_step == pb.PLANNING_STEP_AD_COPY


def test_question_mentioning_an_audience_does_not_confirm_it() -> None:
    given = audience_request("커플에게 광고하는 게 좋을까요?")
    result = PlanningEngine(
        AudienceExtractor(
            Extraction(intent="question", updates=Updates(target_audience="커플"))
        )
    ).process(given)
    assert not result.brief_updates.HasField("target_audience")
    assert result.next_step == pb.PLANNING_STEP_TARGET_AUDIENCE


def test_reconfirmation_is_not_cleared_by_invented_answer() -> None:
    given = audience_request("알아서 해주세요")
    given.brief.target_audience = "가족"
    given.fields_to_reconfirm.append(pb.BRIEF_FIELD_TARGET_AUDIENCE)
    given.resume_step = pb.PLANNING_STEP_AD_COPY
    result = PlanningEngine(
        AudienceExtractor(
            Extraction(
                updates=Updates(target_audience="커플"), confirmed=["target_audience"]
            )
        )
    ).process(given)
    assert not result.brief_updates.HasField("target_audience")
    assert pb.BRIEF_FIELD_TARGET_AUDIENCE in result.fields_to_reconfirm
    assert result.next_step == pb.PLANNING_STEP_TARGET_AUDIENCE


def test_color_then_explicit_audience_over_real_grpc_and_vllm_http() -> None:
    with (
        provider(
            '{"updates":{"color_preference":"파란색","target_audience":"가족 여행객"}}'
        ) as endpoint,
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
                given = audience_request("파란색")
                given.brief.ClearField("color_preference")
                given.current_step = pb.PLANNING_STEP_COLOR_PREFERENCE
                color = stub.ProcessTurn(given, timeout=10)
                assert color.brief_updates.color_preference.set_value == "파란색"
                assert not color.brief_updates.HasField("target_audience")
                assert color.next_step == pb.PLANNING_STEP_TARGET_AUDIENCE
                assert "어떤 고객에게 광고할까요?" in color.assistant_message
                given.brief.color_preference = (
                    color.brief_updates.color_preference.set_value
                )
                given.current_step = color.next_step
                given.state_revision += 1
                given.user_message = "가족 여행객"
                given.request_id = "audience-answer"
                audience = stub.ProcessTurn(given, timeout=10)
                assert audience.brief_updates.target_audience.set_value == "가족 여행객"
                assert audience.next_step == pb.PLANNING_STEP_AD_COPY
                assert audience.state_revision == given.state_revision
        finally:
            server.stop(0).wait()
