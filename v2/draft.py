"""Validate V2 drafts and render corrected source photos locally."""

from logging import getLogger

import grpc
import hotel_ad_v2_pb2 as pb
from PIL import ImageFont

from v2.composition import FONT_PATH, Composition, compose
from v2.config import Settings
from v2.errors import ModelFailure
from v2.image_validation import decode_image
from v2.photo_correction import correct_photo
from v2.planning_fields import require_complete
from v2.vision import OpenAILayoutPlanner

logger = getLogger(__name__)


class DraftEngine:
    def __init__(self, *, fake: bool = False, settings: Settings | None = None) -> None:
        self.fake = fake
        self.planner = OpenAILayoutPlanner(
            settings if settings is not None else Settings()
        )

    def healthy(self) -> bool:
        try:
            ImageFont.truetype(str(FONT_PATH), 24)
        except OSError:
            return False
        return self.fake or self.planner.healthy()

    def generate(self, request: pb.GenerateDraftRequest) -> pb.GenerateDraftResponse:
        if not all(
            value.strip()
            for value in (request.request_id, request.session_id, request.draft_id)
        ):
            raise ModelFailure("INVALID_ARGUMENT", grpc.StatusCode.INVALID_ARGUMENT)
        if (
            request.generation_round not in (1, 2)
            or not request.HasField("is_regeneration")
            or request.is_regeneration != (request.generation_round == 2)
        ):
            raise ModelFailure(
                "INVALID_GENERATION_ROUND", grpc.StatusCode.INVALID_ARGUMENT
            )
        if request.direction not in (1, 2, 3):
            raise ModelFailure("INVALID_ARGUMENT", grpc.StatusCode.INVALID_ARGUMENT)
        require_complete(request.brief)
        image = decode_image(request.original_image_bytes, request.image_mime_type)
        image = correct_photo(image)
        layout = None if self.fake else self.planner.plan(image, request)
        if layout is not None:
            logger.info(
                "openai_layout_applied candidate=%s round=%s model=%s recommended_format=%s position=%s",
                request.direction,
                request.generation_round,
                self.planner.settings.openai_vision_model,
                layout.output_format,
                layout.text_position,
            )
        result = compose(
            image,
            Composition(
                request.brief.lodging_name,
                request.brief.ad_copy,
                request.direction,
                request.generation_round,
                self.fake,
                layout,
            ),
        )
        return pb.GenerateDraftResponse(
            request_id=request.request_id,
            session_id=request.session_id,
            draft_id=request.draft_id,
            generation_round=request.generation_round,
            direction=request.direction,
            image_bytes=result,
            image_mime_type="image/png",
        )
