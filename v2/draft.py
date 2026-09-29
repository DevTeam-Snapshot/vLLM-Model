"""Validate V2 drafts and render corrected source photos locally."""

import grpc
import hotel_ad_v2_pb2 as pb
from PIL import ImageFont

from v2.composition import FONT_PATH, Composition, compose
from v2.errors import ModelFailure
from v2.image_validation import decode_image
from v2.photo_correction import correct_photo
from v2.planning_fields import require_complete


class DraftEngine:
    def __init__(self, *, fake: bool = False) -> None:
        self.fake = fake

    def healthy(self) -> bool:
        try:
            ImageFont.truetype(str(FONT_PATH), 24)
        except OSError:
            return False
        return True

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
        result = compose(
            image,
            Composition(
                request.brief.lodging_name,
                request.brief.ad_copy,
                request.direction,
                request.generation_round,
                self.fake,
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
