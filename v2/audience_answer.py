import hotel_ad_v2_pb2 as pb
from pydantic import ValidationError

from v2.turn_types import Extraction, Updates


def ground_audience_answer(
    request: pb.ProcessTurnRequest, extraction: Extraction
) -> Extraction:
    value = extraction.updates.target_audience
    present = "target_audience" in extraction.updates.model_fields_set
    if not present and "target_audience" in extraction.confirmed:
        value = request.brief.target_audience or None
        present = value is not None
    message = request.user_message.strip()
    grounded = bool(value and value in message)
    if message.startswith("{"):
        try:
            supplied = Updates.model_validate_json(message)
            grounded = (
                "target_audience" in supplied.model_fields_set
                and supplied.target_audience == value
            )
        except ValidationError:
            grounded = False
    if (
        request.event_type == pb.TURN_EVENT_TYPE_USER_MESSAGE
        and request.current_step == pb.PLANNING_STEP_TARGET_AUDIENCE
        and extraction.status == "valid"
        and extraction.intent in ("answer", "correction")
        and present
        and grounded
    ):
        return extraction.model_copy(
            update={"updates": Updates(target_audience=value), "explanation": ""}
        )
    return Extraction(
        intent=extraction.intent,
        status="ambiguous",
        explanation="광고 대상은 직접 입력한 답변으로만 저장합니다.",
    )
