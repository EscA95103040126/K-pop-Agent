from __future__ import annotations

import re
from dataclasses import dataclass

from src.utils.text_cleaner import normalize_artist


ARTIST_PATTERNS = {
    "aespa": re.compile(r"\b(aespa|에스파)\b", re.IGNORECASE),
    "IVE": re.compile(r"\b(ive|아이브)\b", re.IGNORECASE),
    "NewJeans": re.compile(r"\b(newjeans|new jeans|뉴진스)\b", re.IGNORECASE),
}


@dataclass(frozen=True)
class Intent:
    name: str
    artist: str
    period_months: int = 3
    raw_text: str = ""


def route_message(message: str) -> Intent:
    artist = _extract_artist(message)
    period_months = _extract_period_months(message)

    intent_name = "artist_analysis"
    if any(keyword in message for keyword in ("反應", "輿論", "風向", "評價", "新聞")):
        intent_name = "artist_sentiment_context"
    if any(keyword in message for keyword in ("榜", "排名", "表現", "趨勢")):
        intent_name = "artist_market_analysis"

    return Intent(
        name=intent_name,
        artist=artist,
        period_months=period_months,
        raw_text=message,
    )


def _extract_artist(message: str) -> str:
    for artist, pattern in ARTIST_PATTERNS.items():
        if pattern.search(message):
            return artist

    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]{1,}", message)
    if tokens:
        return normalize_artist(tokens[0])
    return "aespa"


def _extract_period_months(message: str) -> int:
    if "三個月" in message or "3個月" in message or "3 個月" in message:
        return 3
    if "一個月" in message or "1個月" in message or "1 個月" in message:
        return 1
    if "半年" in message or "六個月" in message or "6個月" in message:
        return 6
    return 3
