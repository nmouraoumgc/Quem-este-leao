"""Configuração via ambiente / .env (pydantic-settings)."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Self

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Difficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class RevealDelay(str, Enum):
    MIN_30 = "30min"
    HOUR_1 = "1h"
    HOUR_3 = "3h"


REVEAL_DELAY_SECONDS: dict[RevealDelay, int] = {
    RevealDelay.MIN_30: 30 * 60,
    RevealDelay.HOUR_1: 60 * 60,
    RevealDelay.HOUR_3: 3 * 60 * 60,
}

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="QEEL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    difficulty: Difficulty = Difficulty.MEDIUM
    reveal_delay: RevealDelay = RevealDelay.HOUR_1
    timezone: str = "Europe/Lisbon"
    dry_run: bool = True
    format_id: str = "quem_e_este_leao"

    database_path: Path = Path("var/quem-e-este-leao.sqlite3")
    players_yaml: Path = Path("data/players.yaml")
    output_dir: Path = Path("var/output")
    preview_dir: Path = Path("examples")
    assets_dir: Path = Path("assets")

    wikimedia_enabled: bool = True
    http_user_agent: str = "QuemEEsteLeao/1.0 (quiz visual Sporting CP; operador local)"

    x_api_key: str = ""
    x_api_secret: str = ""
    x_access_token: str = ""
    x_access_token_secret: str = ""
    x_bearer_token: str = ""

    ocr_enabled: bool = True
    abort_if_recognizable: bool = True
    log_level: str = "INFO"

    @field_validator("database_path", "players_yaml", "output_dir", "preview_dir", "assets_dir")
    @classmethod
    def _resolve_path(cls, value: Path) -> Path:
        if value.is_absolute():
            return value
        return (PROJECT_ROOT / value).resolve()

    @model_validator(mode="after")
    def _dry_run_without_x(self) -> Self:
        if not self.has_x_credentials:
            object.__setattr__(self, "dry_run", True)
        return self

    @property
    def has_x_credentials(self) -> bool:
        return bool(
            self.x_api_key
            and self.x_api_secret
            and self.x_access_token
            and self.x_access_token_secret
        )

    @property
    def reveal_delay_seconds(self) -> int:
        return REVEAL_DELAY_SECONDS[self.reveal_delay]


def load_settings(**overrides: object) -> Settings:
    settings = Settings(**overrides)  # type: ignore[arg-type]
    return settings
