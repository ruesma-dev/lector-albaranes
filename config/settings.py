# config/settings.py
from __future__ import annotations
# config/settings.py

from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict  # <-- ya instalado


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str = ""
    gemini_model_name: str = "gemini-2.5-pro"
    gemini_rpm: int = 5
    gemini_on_429: str = "wait"
    gemini_min_confidence: float = 0.35

    output_dir: str = "output"
    log_level: str = "INFO"

    @field_validator("gemini_on_429")
    @classmethod
    def _norm_on429(cls, v: str) -> str:
        v = (v or "").strip().lower()
        return v if v in {"wait", "fallback"} else "wait"


settings = Settings(_env_file=".env", _secrets_dir=None)
