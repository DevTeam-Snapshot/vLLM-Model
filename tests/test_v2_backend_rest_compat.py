import hotel_ad_v2_pb2 as pb
import pytest
from google.protobuf.json_format import MessageToDict
from v2_contract_codec import (
    brief_from_domain,
    enum_number,
    enum_text,
    patch_from_domain,
)

from v2.planning_fields import missing_fields


@pytest.mark.parametrize("field", ["selling_points", "lodging_service"])
def test_rest_null_list_is_unanswered_without_weakening_patch_semantics(
    field: str,
) -> None:
    brief = brief_from_domain({field: None})
    assert not getattr(brief, field)
    field_id = pb.BriefField.Value("BRIEF_FIELD_" + field.upper())
    assert field_id in missing_fields(brief, True)
    assert brief == brief_from_domain({field: []})
    with pytest.raises(ValueError):
        patch_from_domain({field: None})


@pytest.mark.parametrize(
    "number,name,alias",
    [(1, "room", "space"), (2, "emotion", "mood"), (3, "benefit", "service")],
)
def test_direction_roundtrip_keeps_backend_rest_names(
    number: int, name: str, alias: str
) -> None:
    assert enum_number("direction", name) == enum_number("direction", alias) == number
    assert enum_text("direction", number) == name
    response = pb.GenerateDraftResponse(direction=number)
    assert MessageToDict(response)["direction"] == "DRAFT_DIRECTION_" + name.upper()
