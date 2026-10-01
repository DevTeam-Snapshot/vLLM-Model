from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class LayoutAdvice(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    focus_x: float = Field(ge=0, le=1, allow_inf_nan=False)
    focus_y: float = Field(ge=0, le=1, allow_inf_nan=False)
    text_position: Literal["top_left", "top_right", "bottom_left", "bottom_right"]
    overlay_opacity: float = Field(ge=0.5, le=0.85, allow_inf_nan=False)
    palette: Literal["ocean", "forest", "terracotta"]
    selling_point_indices: list[Annotated[int, Field(ge=0, le=4)]] = Field(
        min_length=1, max_length=3
    )
