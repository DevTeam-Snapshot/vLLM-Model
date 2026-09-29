from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LayoutAdvice(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    output_format: Literal["original", "square"]
    focus_x: float = Field(ge=0, le=1, allow_inf_nan=False)
    focus_y: float = Field(ge=0, le=1, allow_inf_nan=False)
    text_position: Literal["top_left", "top_right", "bottom_left", "bottom_right"]
    overlay_opacity: float = Field(ge=0.5, le=0.85, allow_inf_nan=False)
