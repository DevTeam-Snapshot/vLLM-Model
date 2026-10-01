"""Planning behavior tests with actual protobuf snapshots."""

import grpc
import hotel_ad_v2_pb2 as pb
import pytest

from v2.errors import ModelFailure
from v2.planning import PlanningEngine
from v2.turn_types import Extraction, Updates


def request(message: str = '{"lodging_type":1}') -> pb.ProcessTurnRequest:
    return pb.ProcessTurnRequest(
        request_id="attempt",
        session_id="session",
        state_revision=0,
        event_type=1,
        user_message=message,
        current_step=1,
        brief=pb.AdvertisementBrief(),
        original_image_uploaded=False,
    )


def full_brief() -> pb.AdvertisementBrief:
    return pb.AdvertisementBrief(
        lodging_type=1,
        lodging_name="호텔",
        location="강릉",
        selling_points=["객실"],
        lodging_service=["무료 주차"],
        target_audience="가족",
        mood="따뜻한",
        color_preference="auto",
    )


def test_first_answer_when_initial_snapshot() -> None:
    given = request()
    actual = PlanningEngine().process(given)
    assert actual.next_step == 2 and actual.state_revision == 0
    assert actual.brief_updates.lodging_type.set_value == 1
    assert not given.brief.HasField("lodging_type")


def test_complete_when_final_copy_selected() -> None:
    given = request("2번")
    given.brief.CopyFrom(full_brief())
    given.original_image_uploaded = True
    given.current_step = 6
    given.ad_copy_candidates.extend(["첫째", "둘째"])
    actual = PlanningEngine().process(given)
    assert actual.is_complete and actual.next_step == 7
    assert actual.brief_updates.ad_copy.set_value == "둘째"
    assert not actual.ad_copy_candidates


def test_read_only_when_complete() -> None:
    given = request()
    given.current_step = 7
    with pytest.raises(ModelFailure) as error:
        PlanningEngine().process(given)
    assert error.value.reason == "BRIEF_READ_ONLY"


def test_image_event_when_only_photo_missing() -> None:
    given = request("")
    given.brief.CopyFrom(full_brief())
    given.brief.ad_copy = "쉬어가세요"
    given.event_type = 2
    given.original_image_uploaded = True
    given.current_step = 3
    actual = PlanningEngine().process(given)
    assert (
        actual.is_complete and actual.message_intent == 4 and actual.answer_status == 4
    )


def test_deletion_when_required_value_cleared() -> None:
    given = request('{"location":null}')
    given.brief.CopyFrom(full_brief())
    given.original_image_uploaded = True
    given.current_step = 6
    given.fields_to_reconfirm.append(pb.BRIEF_FIELD_LOCATION)
    given.resume_step = pb.PLANNING_STEP_AD_COPY
    actual = PlanningEngine().process(given)
    assert actual.next_step == 2 and 4 in actual.corrected_fields
    assert actual.brief_updates.location.WhichOneof("operation") == "clear"


def test_candidates_invalidated_when_fact_changes() -> None:
    given = request('{"location":"서울"}')
    given.brief.CopyFrom(full_brief())
    given.ad_copy_candidates.append("강릉에서 쉬어요")
    given.fields_to_reconfirm.append(pb.BRIEF_FIELD_LOCATION)
    given.resume_step = pb.PLANNING_STEP_SELLING_POINTS
    actual = PlanningEngine().process(given)
    assert not actual.ad_copy_candidates


def test_copy_reconfirmation_when_fact_changes() -> None:
    given = request('{"location":"서울"}')
    given.brief.CopyFrom(full_brief())
    given.brief.ad_copy = "강릉에서 쉬어요"
    given.original_image_uploaded = True
    given.fields_to_reconfirm.append(pb.BRIEF_FIELD_LOCATION)
    given.resume_step = pb.PLANNING_STEP_AD_COPY
    actual = PlanningEngine().process(given)
    assert list(actual.fields_to_reconfirm) == [10] and not actual.is_complete
    assert actual.resume_step == 6


def test_required_presence_when_revision_absent() -> None:
    given = request()
    given.ClearField("state_revision")
    with pytest.raises(ModelFailure) as error:
        PlanningEngine().process(given)
    assert error.value.code == grpc.StatusCode.INVALID_ARGUMENT


class ConfirmExtractor:
    def healthy(self) -> bool:
        return True

    def extract(self, request: pb.ProcessTurnRequest) -> Extraction:
        return Extraction(updates=Updates(location="강릉"), confirmed=["location"])


def test_return_to_missing_step_when_reconfirmation_resolves() -> None:
    given = request("강릉 맞아요")
    given.brief.CopyFrom(full_brief())
    given.original_image_uploaded = True
    given.current_step = 2
    given.fields_to_reconfirm.append(4)
    given.resume_step = 6
    actual = PlanningEngine(ConfirmExtractor()).process(given)
    assert actual.next_step == 6 and not actual.HasField("resume_step")


def test_list_replacement_when_points_deleted() -> None:
    given = request('{"selling_points":[]}')
    given.brief.CopyFrom(full_brief())
    given.fields_to_reconfirm.append(pb.BRIEF_FIELD_SELLING_POINTS)
    given.resume_step = pb.PLANNING_STEP_SELLING_POINTS
    actual = PlanningEngine().process(given)
    assert actual.brief_updates.HasField("selling_points")
    assert 5 in actual.corrected_fields and 5 in actual.missing_fields


def test_points_corrected_when_list_replaced() -> None:
    given = request('{"selling_points":["무료 주차"]}')
    given.brief.CopyFrom(full_brief())
    given.brief.ad_copy = "객실에서 쉬세요"
    given.ad_copy_candidates.append("객실에서 쉬세요")
    given.fields_to_reconfirm.append(pb.BRIEF_FIELD_SELLING_POINTS)
    given.resume_step = pb.PLANNING_STEP_SELLING_POINTS
    actual = PlanningEngine().process(given)
    assert 5 in actual.corrected_fields and 10 in actual.fields_to_reconfirm
    assert not actual.ad_copy_candidates


def test_choice_when_conversational_number_selection() -> None:
    given = request("2번으로 할게요")
    given.brief.CopyFrom(full_brief())
    given.original_image_uploaded = True
    given.current_step = 6
    given.ad_copy_candidates.extend(["첫째", "둘째"])
    actual = PlanningEngine().process(given)
    assert actual.brief_updates.ad_copy.set_value == "둘째"


class InventCopyExtractor:
    def healthy(self) -> bool:
        return True

    def extract(self, request: pb.ProcessTurnRequest) -> Extraction:
        return Extraction(updates=Updates(ad_copy="지어낸 문구"))


def test_output_rejected_when_model_invents_final_copy() -> None:
    given = request("추천해줘")
    given.brief.CopyFrom(full_brief())
    given.original_image_uploaded = True
    given.current_step = pb.PLANNING_STEP_AD_COPY
    with pytest.raises(ModelFailure) as error:
        PlanningEngine(InventCopyExtractor()).process(given)
    assert error.value.reason == "MODEL_OUTPUT_INVALID"


class MultiFieldExtractor:
    def healthy(self) -> bool:
        return True

    def extract(self, request: pb.ProcessTurnRequest) -> Extraction:
        return Extraction(
            updates=Updates(
                lodging_type=1,
                lodging_name="바다호텔",
                location="강릉",
            )
        )


def test_only_current_question_field_applied_when_model_returns_multiple() -> None:
    given = request("강릉 바다호텔이고 호텔이에요")

    actual = PlanningEngine(MultiFieldExtractor()).process(given)

    assert actual.brief_updates.lodging_type.set_value == 1
    assert not actual.brief_updates.HasField("lodging_name")
    assert not actual.brief_updates.HasField("location")
    assert actual.next_step == pb.PLANNING_STEP_LODGING_INFORMATION


def test_same_step_continues_with_next_single_field() -> None:
    given = request("바다호텔이고 강릉에 있어요")
    given.brief.lodging_type = pb.LODGING_TYPE_HOTEL
    given.current_step = pb.PLANNING_STEP_LODGING_INFORMATION

    actual = PlanningEngine(MultiFieldExtractor()).process(given)

    assert actual.brief_updates.lodging_name.set_value == "바다호텔"
    assert not actual.brief_updates.HasField("location")
    assert actual.next_step == pb.PLANNING_STEP_LODGING_INFORMATION
