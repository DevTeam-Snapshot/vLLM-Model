import re

import hotel_ad_v2_pb2 as pb
from pydantic import ValidationError

from v2.turn_types import Extraction, Updates

NO_SERVICES = re.compile(
    r"(?:(?:제공하는|제공되는|별도의|별도|특별한)\s*)?"
    r"(?:(?:서비스나 혜택|서비스|혜택)(?:은|는|이|가)?\s*)?"
    r"(?:없음|없어요|없습니다|없다|없어|없는데요|없네요)[.!。]*"
)


def ground_service_answer(
    request: pb.ProcessTurnRequest, extraction: Extraction
) -> Extraction:
    message = request.user_message.strip()
    explicit_none = NO_SERVICES.fullmatch(message) is not None
    if message.startswith("{"):
        try:
            supplied = Updates.model_validate_json(message)
            explicit_none = supplied.lodging_service == ["없음"]
        except ValidationError:
            explicit_none = False
    values = extraction.updates.lodging_service
    if "lodging_service" in extraction.confirmed and not values:
        values = list(request.brief.lodging_service)
    if (
        request.event_type == pb.TURN_EVENT_TYPE_USER_MESSAGE
        and request.current_step == pb.PLANNING_STEP_LODGING_SERVICE
        and extraction.status == "valid"
        and extraction.intent in ("answer", "correction")
        and ("없음" not in values or explicit_none)
    ):
        return extraction
    return Extraction(
        intent=extraction.intent,
        status="ambiguous",
        explanation="서비스·혜택에 대한 답변을 확인해 주세요.",
    )
