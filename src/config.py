from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import certifi
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())


def _path_from_env(name: str, default: str) -> Path:
    value = os.getenv(name, default)
    path = Path(value)
    return path if path.is_absolute() else BASE_DIR / path


@dataclass(frozen=True)
class Settings:
    base_dir: Path = BASE_DIR
    database_path: Path = _path_from_env("DATABASE_PATH", "data/chart_history.db")
    mock_data_dir: Path = _path_from_env("MOCK_DATA_DIR", "data/mock")
    naver_client_id: str | None = os.getenv("NAVER_CLIENT_ID") or None
    naver_client_secret: str | None = os.getenv("NAVER_CLIENT_SECRET") or None
    gemini_api_key: str | None = os.getenv("GEMINI_API_KEY") or None
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    youtube_api_key: str | None = os.getenv("YOUTUBE_API_KEY") or None
    line_channel_access_token: str | None = os.getenv("LINE_CHANNEL_ACCESS_TOKEN") or None
    line_channel_secret: str | None = os.getenv("LINE_CHANNEL_SECRET") or None
    port: int = int(os.getenv("PORT", "5000"))

    @property
    def use_naver_mock(self) -> bool:
        return not (self.naver_client_id and self.naver_client_secret)

    @property
    def use_gemini_mock(self) -> bool:
        return not self.gemini_api_key

    @property
    def use_line_mock(self) -> bool:
        return not (self.line_channel_access_token and self.line_channel_secret)


settings = Settings()
