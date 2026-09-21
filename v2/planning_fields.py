"""Brief boundaries shared by planning and image generation."""

from typing import Final

import grpc
import hotel_ad_v2_pb2 as pb

from v2.errors import ModelFailure

FIELDS: Final = (
    "lodging_type",
    "lodging_type_detail",
    "lodging_name",
    "location",
    "selling_points",
    "original_image",
    "target_audience",
    "mood",
    "color_preference",
    "ad_copy",
)
STEPS: Final = (
    pb.PLANNING_STEP_LODGING_TYPE,
    pb.PLANNING_STEP_LODGING_TYPE,
    pb.PLANNING_STEP_LODGING_INFORMATION,
    pb.PLANNING_STEP_LODGING_INFORMATION,
    pb.PLANNING_STEP_SELLING_POINTS,
    pb.PLANNING_STEP_SELLING_POINTS,
    pb.PLANNING_STEP_TARGET_AUDIENCE,
    pb.PLANNING_STEP_MOOD,
    pb.PLANNING_STEP_MOOD,
    pb.PLANNING_STEP_AD_COPY,
)
FIELD_IDS: Final = (
    pb.BRIEF_FIELD_LODGING_TYPE,
    pb.BRIEF_FIELD_LODGING_TYPE_DETAIL,
    pb.BRIEF_FIELD_LODGING_NAME,
    pb.BRIEF_FIELD_LOCATION,
    pb.BRIEF_FIELD_SELLING_POINTS,
    pb.BRIEF_FIELD_ORIGINAL_IMAGE,
    pb.BRIEF_FIELD_TARGET_AUDIENCE,
    pb.BRIEF_FIELD_MOOD,
    pb.BRIEF_FIELD_COLOR_PREFERENCE,
    pb.BRIEF_FIELD_AD_COPY,
)

LIMITS: Final = {
    "lodging_type_detail": 50,
    "lodging_name": 100,
    "location": 200,
    "target_audience": 100,
    "mood": 100,
    "color_preference": 100,
    "ad_copy": 60,
}


def validate_brief(brief: pb.AdvertisementBrief) -> None:
    if brief.HasField("lodging_type") and brief.lodging_type not in range(1, 6):
        raise ModelFailure("INVALID_ARGUMENT", grpc.StatusCode.INVALID_ARGUMENT)
    for name in FIELDS:
        if name in ("lodging_type", "selling_points", "original_image"):
            continue
        if brief.HasField(name) and (
            not getattr(brief, name).strip() or len(getattr(brief, name)) > LIMITS[name]
        ):
            raise ModelFailure("INVALID_ARGUMENT", grpc.StatusCode.INVALID_ARGUMENT)
    if len(brief.selling_points) > 5 or any(
        not value.strip() or len(value) > 100 for value in brief.selling_points
    ):
        raise ModelFailure("INVALID_ARGUMENT", grpc.StatusCode.INVALID_ARGUMENT)
    if (
        brief.HasField("lodging_type_detail")
        and brief.lodging_type != pb.LODGING_TYPE_OTHER
    ):
        raise ModelFailure("INVALID_ARGUMENT", grpc.StatusCode.INVALID_ARGUMENT)


def required_fields(brief: pb.AdvertisementBrief) -> list[pb.BriefField]:
    return [
        index
        for index in FIELD_IDS
        if index != 2 or brief.lodging_type == pb.LODGING_TYPE_OTHER
    ]


def missing_fields(
    brief: pb.AdvertisementBrief, image_uploaded: bool
) -> list[pb.BriefField]:
    missing: list[pb.BriefField] = []
    for index in required_fields(brief):
        name = FIELDS[index - 1]
        present = image_uploaded if index == 6 else bool(getattr(brief, name))
        if not present:
            missing.append(index)
    return missing


def require_complete(brief: pb.AdvertisementBrief) -> None:
    validate_brief(brief)
    if missing_fields(brief, True):
        raise ModelFailure("BRIEF_INCOMPLETE", grpc.StatusCode.FAILED_PRECONDITION)
