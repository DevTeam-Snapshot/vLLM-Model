"""Offline integration mode: explicit JSON/label input, never language-model quality."""

import re

import hotel_ad_v2_pb2 as pb
from pydantic import ValidationError

from v2.turn_types import Extraction, Updates


class FakeTurnExtractor:
    def healthy(self) -> bool:
        return True

    def extract(self, request: pb.ProcessTurnRequest) -> Extraction:
        message = request.user_message.strip()
        if request.current_step == pb.PLANNING_STEP_LODGING_SERVICE and message in (
            "없음",
            "없어요",
            "혜택 없음",
            "서비스 없음",
        ):
            return Extraction(updates=Updates(lodging_service=["없음"]))
        if message.startswith("{"):
            try:
                return Extraction(updates=Updates.model_validate_json(message))
            except ValidationError:
                return Extraction(status="ambiguous")
        if request.current_step == 1:
            lodging_types = {"호텔": 1, "모텔": 2, "리조트": 3, "펜션": 4, "기타": 5}
            found = [
                value
                for label, value in lodging_types.items()
                if message == label or message == label + "입니다"
            ]
            if len(found) == 1:
                return Extraction(
                    updates=Updates.model_validate({"lodging_type": found[0]})
                )
        if request.current_step == 6:
            selection = re.fullmatch(
                r"([1-9])(?:번)?(?:으로)?(?: (?:해주세요|할게요|할께요))?[.!]?", message
            )
            if selection:
                index = int(selection.group(1)) - 1
                if index < len(request.ad_copy_candidates):
                    return Extraction(
                        updates=Updates(ad_copy=request.ad_copy_candidates[index])
                    )
                return Extraction(status="ambiguous")
            if message in ("추천", "추천해줘", "문구 추천"):
                name = request.brief.lodging_name
                return Extraction(
                    candidates=[
                        f"{name}에서 쉬어가세요",
                        f"당신의 휴식, {name}",
                        f"{name}에서 만나는 여행",
                    ]
                )
            if message.startswith("문구:") and message[3:].strip():
                return Extraction(updates=Updates(ad_copy=message[3:].strip()))
        return Extraction(
            status="ambiguous",
            explanation="가짜 모드는 필드 이름을 사용한 JSON 입력을 지원합니다.",
        )
