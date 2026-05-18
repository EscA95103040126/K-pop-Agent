from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import requests

from src.config import Settings, settings
from src.utils.text_cleaner import clean_html_text


NAVER_NEWS_URL = "https://openapi.naver.com/v1/search/news.json"
logger = logging.getLogger(__name__)


class NaverNewsClient:
    def __init__(self, config: Settings = settings) -> None:
        self.config = config

    def search(self, artist: str, display: int = 10) -> list[dict[str, Any]]:
        if self.config.use_naver_mock:
            return self._load_mock(artist)

        try:
            payload = self._request_real(artist=artist, display=display)
        except requests.RequestException as exc:
            logger.warning("Naver News API failed; falling back to mock data: %s", exc)
            return self._load_mock(artist)
        return [self._normalize_item(item) for item in payload.get("items", [])]

    def real_api_available(self) -> bool:
        if self.config.use_naver_mock:
            return False
        try:
            self._request_real(artist="aespa", display=1)
        except requests.RequestException:
            return False
        return True

    def _request_real(self, artist: str, display: int) -> dict[str, Any]:
        headers = {
            "X-Naver-Client-Id": self.config.naver_client_id or "",
            "X-Naver-Client-Secret": self.config.naver_client_secret or "",
        }
        params = {
            "query": self._build_query(artist),
            "display": display,
            "sort": "date",
        }
        response = requests.get(NAVER_NEWS_URL, headers=headers, params=params, timeout=8)
        response.raise_for_status()
        return response.json()

    def _load_mock(self, artist: str) -> list[dict[str, Any]]:
        file_name = f"naver_{artist.lower().replace(' ', '_')}.json"
        mock_path = self.config.mock_data_dir / file_name
        if not mock_path.exists():
            mock_path = self.config.mock_data_dir / "naver_aespa.json"
        return json.loads(mock_path.read_text(encoding="utf-8"))

    def _build_query(self, artist: str) -> str:
        artist_keywords = {
            "aespa": "에스파",
            "IVE": "아이브",
            "NewJeans": "뉴진스",
        }
        return artist_keywords.get(artist, artist)

    def _normalize_item(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "title": clean_html_text(item.get("title")),
            "date": self._parse_pub_date(item.get("pubDate")),
            "summary": clean_html_text(item.get("description")),
            "category": "news",
            "link": item.get("link"),
        }

    def _parse_pub_date(self, value: str | None) -> str:
        if not value:
            return ""
        try:
            parsed = datetime.strptime(value, "%a, %d %b %Y %H:%M:%S %z")
            return parsed.date().isoformat()
        except ValueError:
            return value


def search_recent_news(artist: str, display: int = 10) -> list[dict[str, Any]]:
    return NaverNewsClient().search(artist=artist, display=display)
