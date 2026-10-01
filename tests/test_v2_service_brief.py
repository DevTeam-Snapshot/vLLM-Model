import json

import hotel_ad_v2_pb2 as pb
import pytest
from test_v2_draft import request as draft_request
from test_v2_planning import full_brief, request
from test_v2_planning_vllm import provider
from v2_contract_codec import brief_from_domain, patch_from_domain, patch_to_domain

from v2.draft import DraftEngine
from v2.errors import ModelFailure
from v2.image_prompt import build_prompt
from v2.planning import PlanningEngine
from v2.planning_fields import expected_field_id, validate_brief
from v2.vllm import VllmTurnExtractor


def test_service_patch_roundtrip_preserves_conditions_and_empty_replacement() -> None:
    for services in (["유료 조식 — 사전 예약", "무료 주차 — 객실당 1대"], [], ["없음"]):
        domain = {"lodging_service": services}
        wire = pb.BriefPatch.FromString(patch_from_domain(domain).SerializeToString())
        assert wire.HasField("lodging_service")
        assert patch_to_domain(wire) == domain
        assert list(brief_from_domain(domain).lodging_service) == services
    with pytest.raises(ValueError):
        patch_from_domain({"lodging_service": None})


def test_planning_follows_service_mood_color_target_copy_order() -> None:
    given = request()
    given.brief.CopyFrom(full_brief())
    given.original_image_uploaded = True
    for field in ("lodging_service", "mood", "color_preference", "target_audience"):
        given.brief.ClearField(field)
    turns = (
        (
            "lodging_service",
            ["유료 조식"],
            pb.PLANNING_STEP_LODGING_SERVICE,
            pb.PLANNING_STEP_MOOD,
        ),
        ("mood", "차분한", pb.PLANNING_STEP_MOOD, pb.PLANNING_STEP_COLOR_PREFERENCE),
        (
            "color_preference",
            "auto",
            pb.PLANNING_STEP_COLOR_PREFERENCE,
            pb.PLANNING_STEP_TARGET_AUDIENCE,
        ),
        (
            "target_audience",
            "커플",
            pb.PLANNING_STEP_TARGET_AUDIENCE,
            pb.PLANNING_STEP_AD_COPY,
        ),
        ("ad_copy", "편안한 하루", pb.PLANNING_STEP_AD_COPY, pb.PLANNING_STEP_COMPLETE),
    )
    for field, value, step, next_step in turns:
        given.current_step = step
        given.user_message = json.dumps({field: value}, ensure_ascii=False)
        result = PlanningEngine().process(given)
        assert result.next_step == next_step
        assert patch_to_domain(result.brief_updates) == {field: value}
        assert result.is_complete == (next_step == pb.PLANNING_STEP_COMPLETE)
        if field == "lodging_service":
            given.brief.lodging_service.extend(value)
        else:
            setattr(given.brief, field, value)


def test_service_is_required_and_no_benefits_can_be_explicit() -> None:
    given = draft_request()
    given.brief.ClearField("lodging_service")
    with pytest.raises(ModelFailure) as failure:
        DraftEngine(fake=True).generate(given)
    assert failure.value.reason == "BRIEF_INCOMPLETE"
    turn = request("없음")
    turn.brief.CopyFrom(given.brief)
    turn.original_image_uploaded = True
    turn.current_step = pb.PLANNING_STEP_LODGING_SERVICE
    result = PlanningEngine().process(turn)
    assert list(result.brief_updates.lodging_service.values) == ["없음"]
    assert not result.is_complete
    assert list(result.fields_to_reconfirm) == [pb.BRIEF_FIELD_AD_COPY]
    given.brief.lodging_service.append("없음")
    assert DraftEngine(fake=True).generate(given).image_mime_type == "image/png"


@pytest.mark.parametrize(
    "services", [[" "], ["x" * 101], ["혜택"] * 6, ["없음", "무료 주차"]]
)
def test_invalid_service_list_is_rejected(services: list[str]) -> None:
    brief = full_brief()
    del brief.lodging_service[:]
    brief.lodging_service.extend(services)
    with pytest.raises(ModelFailure) as failure:
        validate_brief(brief)
    assert failure.value.reason == "INVALID_ARGUMENT"


def test_changed_service_invalidates_copy_and_reconfirmation_uses_flow_order() -> None:
    given = request('{"lodging_service":["유료 주차"]}')
    given.brief.CopyFrom(full_brief())
    given.brief.ad_copy = "무료 주차와 함께 쉬어요"
    given.original_image_uploaded = True
    given.current_step = pb.PLANNING_STEP_LODGING_SERVICE
    given.fields_to_reconfirm.extend(
        [pb.BRIEF_FIELD_AD_COPY, pb.BRIEF_FIELD_LODGING_SERVICE]
    )
    given.resume_step = pb.PLANNING_STEP_COLOR_PREFERENCE
    given.ad_copy_candidates.append("무료 주차와 함께 쉬어요")
    result = PlanningEngine().process(given)
    assert list(result.brief_updates.lodging_service.values) == ["유료 주차"]
    assert pb.BRIEF_FIELD_LODGING_SERVICE in result.corrected_fields
    assert list(result.fields_to_reconfirm) == [pb.BRIEF_FIELD_AD_COPY]
    assert not result.ad_copy_candidates
    assert (
        expected_field_id(given.brief, True, [7, 8, 11])
        == pb.BRIEF_FIELD_LODGING_SERVICE
    )


def test_service_deletion_returns_to_service_step() -> None:
    given = request('{"lodging_service":[]}')
    given.brief.CopyFrom(full_brief())
    given.original_image_uploaded = True
    given.current_step = pb.PLANNING_STEP_LODGING_SERVICE
    given.fields_to_reconfirm.append(pb.BRIEF_FIELD_LODGING_SERVICE)
    given.resume_step = pb.PLANNING_STEP_MOOD
    result = PlanningEngine().process(given)
    assert result.brief_updates.HasField("lodging_service")
    assert not result.brief_updates.lodging_service.values
    assert result.next_step == pb.PLANNING_STEP_LODGING_SERVICE
    assert pb.BRIEF_FIELD_LODGING_SERVICE in result.missing_fields


def test_vllm_receives_service_snapshot_and_extracts_only_service() -> None:
    given = request("조식은 유료입니다")
    given.brief.CopyFrom(full_brief())
    given.brief.ClearField("lodging_service")
    given.original_image_uploaded = True
    given.current_step = pb.PLANNING_STEP_LODGING_SERVICE
    with provider(
        '{"updates":{"lodging_service":["유료 조식"],"mood":"임의 분위기"}}'
    ) as endpoint:
        result = PlanningEngine(VllmTurnExtractor(endpoint.url, "test")).process(given)
    assert list(result.brief_updates.lodging_service.values) == ["유료 조식"]
    assert not result.brief_updates.HasField("mood")
    payload = json.loads(endpoint.requests[-1][1])
    snapshot = json.loads(payload["messages"][-1]["content"])
    assert snapshot["expected_field"] == "lodging_service"


def test_candidate_sources_and_existing_wire_numbers() -> None:
    assert (
        pb.DRAFT_DIRECTION_SPACE,
        pb.DRAFT_DIRECTION_MOOD,
        pb.DRAFT_DIRECTION_SERVICE,
    ) == (1, 2, 3)
    assert (
        pb.AdvertisementBrief.DESCRIPTOR.fields_by_name["lodging_service"].number == 10
    )
    assert pb.PLANNING_STEP_COMPLETE == 7
    given = draft_request()
    for direction, focus in (
        (1, "selling_points"),
        (2, "mood"),
        (3, "lodging_service"),
    ):
        given.direction = direction
        context = json.loads(build_prompt(given).split("SOURCE DATA JSON:\n")[1])
        assert context["primary_focus"] == focus
        assert context["lodging_service"] == list(given.brief.lodging_service)
