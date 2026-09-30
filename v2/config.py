"""Validated environment settings; no implicit live/fake fallback."""

from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(frozen=True, extra="ignore")

    model_mode: Literal["fake", "live"] = "fake"
    grpc_host: str = "0.0.0.0"
    port: int = Field(default=50051, ge=1, le=65535)
    vllm_base_url: str = "http://127.0.0.1:8000/v1"
    vllm_model: str = "hotel-agent"
    vllm_api_key: SecretStr = SecretStr("EMPTY")
    vllm_context_tokens: int = Field(default=12288, ge=2048, le=131072)
    vllm_timeout_seconds: float = Field(default=25, gt=0, le=25)
    openai_api_key: SecretStr = SecretStr("")
    openai_base_url: str = "https://api.openai.com/v1"
    image_model: Literal["gpt-image-2"] = "gpt-image-2"
    image_quality: Literal["low", "medium", "high", "auto"] = "high"
    image_timeout_seconds: float = Field(default=150, gt=0, le=300)

    image_max_concurrency: int = Field(default=3, ge=1, le=3)
