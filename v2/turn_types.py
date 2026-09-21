"""Strict extraction boundary; the model never decides state transitions."""

from typing import Literal, Protocol

import hotel_ad_v2_pb2 as pb
from pydantic import BaseModel, ConfigDict, Field

FieldName = Literal[
    "lodging_type",
    "lodging_type_detail",
    "lodging_name",
    "location",
    "selling_points",
    "target_audience",
    "mood",
    "color_preference",
    "ad_copy",
]


class Updates(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    lodging_type: Literal[1, 2, 3, 4, 5] | None = None
    lodging_type_detail: str | None = Field(default=None, min_length=1)
    lodging_name: str | None = Field(default=None, min_length=1)
    location: str | None = Field(default=None, min_length=1)
    selling_points: list[str] = Field(default_factory=list)
    target_audience: str | None = Field(default=None, min_length=1)
    mood: str | None = Field(default=None, min_length=1)
    color_preference: str | None = Field(default=None, min_length=1)
    ad_copy: str | None = Field(default=None, min_length=1)


class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    updates: Updates = Field(default_factory=Updates)
    intent: Literal["answer", "correction", "question"] = "answer"
    status: Literal["valid", "ambiguous", "off_topic"] = "valid"
    reconfirm: list[FieldName] = Field(default_factory=list)
    confirmed: list[FieldName] = Field(default_factory=list)
    candidates: list[str] = Field(default_factory=list, max_length=3)
    explanation: str = ""


class TurnExtractor(Protocol):
    def extract(self, request: pb.ProcessTurnRequest) -> Extraction: ...
    def healthy(self) -> bool: ...
