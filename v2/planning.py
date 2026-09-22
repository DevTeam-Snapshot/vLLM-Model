"""Stateless planning transition engine with authoritative snapshot validation."""

import json
import re

import grpc
import hotel_ad_v2_pb2 as pb

from v2.errors import ModelFailure
from v2.planning_fields import (
    FIELD_IDS,
    FIELDS,
    STEPS,
    expected_field_id,
    missing_fields,
    required_fields,
    validate_brief,
)
from v2.turn_types import Extraction, TurnExtractor, Updates

QUESTIONS = (
    "숙소 유형을 알려주세요.",
    "기타 숙소 유형을 구체적으로 알려주세요.",
    "숙소 이름을 알려주세요.",
    "숙소가 있는 지역을 알려주세요.",
    "숙소의 가장 큰 장점을 알려주세요.",
    "광고에 사용할 숙소 사진을 업로드해 주세요.",
    "어떤 고객에게 광고할까요?",
    "원하는 광고 분위기를 알려주세요.",
    "원하는 색상을 알려주세요. 선호가 없으면 위임할 수 있어요.",
    "광고 문구를 입력하거나 추천받으세요.",
)
COMPLETE_MESSAGE = "기획서가 완성되었습니다. 이제 광고 이미지를 생성할 수 있습니다."


def validate_request(request: pb.ProcessTurnRequest) -> None:
    invalid = (
        not request.request_id.strip()
        or not request.session_id.strip()
        or not request.HasField("state_revision")
        or not request.HasField("original_image_uploaded")
        or not request.HasField("brief")
        or request.current_step not in range(1, 8)
    )
    if invalid:
        raise ModelFailure("INVALID_ARGUMENT", grpc.StatusCode.INVALID_ARGUMENT)
    if request.current_step == pb.PLANNING_STEP_COMPLETE:
        raise ModelFailure("BRIEF_READ_ONLY", grpc.StatusCode.FAILED_PRECONDITION)
    valid_event = (request.event_type == 1 and bool(request.user_message.strip())) or (
        request.event_type == 2
        and not request.user_message
        and request.original_image_uploaded
    )
    if not valid_event:
        raise ModelFailure("INVALID_EVENT", grpc.StatusCode.INVALID_ARGUMENT)
    validate_brief(request.brief)
    reconfirm = list(request.fields_to_reconfirm)
    if (
        len(set(reconfirm)) != len(reconfirm)
        or any(
            field not in required_fields(request.brief) or field == 6
            for field in reconfirm
        )
        or bool(reconfirm) != request.HasField("resume_step")
        or (request.HasField("resume_step") and request.resume_step not in range(1, 7))
        or len(request.ad_copy_candidates) > 3
        or any(not s.strip() or len(s) > 60 for s in request.ad_copy_candidates)
        or any(
            m.role not in (1, 2) or not m.content.strip()
            for m in request.conversation_history
        )
    ):
        raise ModelFailure("INVALID_ARGUMENT", grpc.StatusCode.INVALID_ARGUMENT)
    if len(request.conversation_history) > 12:
        raise ModelFailure("CONTEXT_TOO_LARGE", grpc.StatusCode.INVALID_ARGUMENT)


class PlanningEngine:
    def __init__(self, extractor: TurnExtractor | None = None) -> None:
        from v2.turn_fake import FakeTurnExtractor

        self.extractor = extractor if extractor is not None else FakeTurnExtractor()

    def healthy(self) -> bool:
        return self.extractor.healthy()

    def process(self, request: pb.ProcessTurnRequest) -> pb.ProcessTurnResponse:
        validate_request(request)
        extraction = (
            Extraction() if request.event_type == 2 else self.extractor.extract(request)
        )
        expected = expected_field_id(
            request.brief,
            request.original_image_uploaded,
            list(request.fields_to_reconfirm),
        )
        allowed = FIELDS[expected - 1] if expected and expected != 6 else None
        supplied = extraction.updates.model_dump(exclude_unset=True)
        selected = {allowed: supplied[allowed]} if allowed in supplied else {}
        extraction = extraction.model_copy(
            update={
                "updates": Updates.model_validate(selected),
                "confirmed": [name for name in extraction.confirmed if name == allowed],
                "reconfirm": [name for name in extraction.reconfirm if name == allowed],
                "candidates": extraction.candidates if expected == 10 else [],
            }
        )
        copy = extraction.updates.ad_copy
        if copy:
            selected = re.fullmatch(
                r"([1-3])(?:번)?(?:으로)?(?: (?:해주세요|할게요|할께요))?[.!]?",
                request.user_message.strip(),
            )
            valid_choice = bool(
                selected
                and int(selected.group(1)) <= len(request.ad_copy_candidates)
                and request.ad_copy_candidates[int(selected.group(1)) - 1] == copy
            )
            if (
                copy not in request.user_message
                and json.dumps(copy, ensure_ascii=True)[1:-1]
                not in request.user_message
                and not valid_choice
            ):
                raise ModelFailure("MODEL_OUTPUT_INVALID", grpc.StatusCode.INTERNAL)
        brief = pb.AdvertisementBrief()
        brief.CopyFrom(request.brief)
        patch = pb.BriefPatch()
        corrected: list[pb.BriefField] = []
        changed: set[int] = set()
        reconfirm = set(request.fields_to_reconfirm)
        for name in extraction.updates.model_fields_set:
            index = FIELD_IDS[FIELDS.index(name)]
            value = getattr(extraction.updates, name)
            previous = getattr(request.brief, name)
            if name == "selling_points":
                patch.selling_points.values.extend(value)
                patch.selling_points.SetInParent()
                del brief.selling_points[:]
                brief.selling_points.extend(value)
                different = list(previous) != value
            else:
                different = (brief.HasField(name) and previous != value) or (
                    not brief.HasField(name) and value is not None
                )
                if value is None:
                    getattr(patch, name).clear.SetInParent()
                    brief.ClearField(name)
                else:
                    getattr(patch, name).set_value = value
                    setattr(brief, name, value)
            if different:
                changed.add(index)
                if bool(getattr(request.brief, name)):
                    corrected.append(index)
            if value:
                reconfirm.discard(index)
        if brief.lodging_type != pb.LODGING_TYPE_OTHER and brief.HasField(
            "lodging_type_detail"
        ):
            brief.ClearField("lodging_type_detail")
            patch.lodging_type_detail.clear.SetInParent()
            corrected.append(pb.BRIEF_FIELD_LODGING_TYPE_DETAIL)
        reconfirm.difference_update(
            FIELD_IDS[FIELDS.index(name)] for name in extraction.confirmed
        )
        reconfirm.update(FIELD_IDS[FIELDS.index(name)] for name in extraction.reconfirm)
        reconfirm.intersection_update(required_fields(brief))
        try:
            validate_brief(brief)
        except ModelFailure as error:
            raise ModelFailure(
                "MODEL_OUTPUT_INVALID", grpc.StatusCode.INTERNAL
            ) from error
        candidates = list(request.ad_copy_candidates)
        if changed.intersection({1, 2, 3, 4, 5, 7}):
            candidates = []
            if brief.HasField("ad_copy") and 10 not in changed:
                reconfirm.add(pb.BRIEF_FIELD_AD_COPY)
        if extraction.candidates:
            if any(
                not candidate.strip() or len(candidate) > 60
                for candidate in extraction.candidates
            ):
                raise ModelFailure("MODEL_OUTPUT_INVALID", grpc.StatusCode.INTERNAL)
            candidates = extraction.candidates
        if "ad_copy" in extraction.updates.model_fields_set and brief.HasField(
            "ad_copy"
        ):
            candidates = []
        natural_missing = missing_fields(brief, request.original_image_uploaded)
        missing = sorted(set(natural_missing) | reconfirm)
        natural_step = (
            STEPS[natural_missing[0] - 1]
            if natural_missing
            else pb.PLANNING_STEP_COMPLETE
        )
        next_step = STEPS[min(reconfirm) - 1] if reconfirm else natural_step
        next_field = min(reconfirm) if reconfirm else (
            natural_missing[0] if natural_missing else None
        )
        response = pb.ProcessTurnResponse(
            request_id=request.request_id,
            session_id=request.session_id,
            state_revision=request.state_revision,
            message_intent={
                "answer": pb.MESSAGE_INTENT_ANSWER,
                "correction": pb.MESSAGE_INTENT_CORRECTION,
                "question": pb.MESSAGE_INTENT_QUESTION,
            }[extraction.intent],
            answer_status={
                "valid": pb.ANSWER_STATUS_VALID,
                "ambiguous": pb.ANSWER_STATUS_AMBIGUOUS,
                "off_topic": pb.ANSWER_STATUS_OFF_TOPIC,
            }[extraction.status],
            assistant_message=(
                extraction.explanation + " " if extraction.explanation else ""
            )
            + (QUESTIONS[next_field - 1] if next_field else COMPLETE_MESSAGE),
            brief_updates=patch,
            corrected_fields=sorted(set(corrected)),
            fields_to_reconfirm=sorted(reconfirm),
            completed_fields=[
                field for field in required_fields(brief) if field not in missing
            ],
            missing_fields=missing,
            current_step=request.current_step,
            next_step=next_step,
            ad_copy_candidates=candidates,
            is_complete=not missing,
        )
        if reconfirm:
            response.resume_step = (
                request.resume_step
                if request.HasField("resume_step")
                else (natural_step if natural_step != 7 else next_step)
            )
        if corrected:
            response.message_intent = pb.MESSAGE_INTENT_CORRECTION
        if request.event_type == 2:
            response.message_intent = pb.MESSAGE_INTENT_SYSTEM_EVENT
            response.answer_status = pb.ANSWER_STATUS_NOT_APPLICABLE
        return response
