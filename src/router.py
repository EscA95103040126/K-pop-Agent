from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from src.utils.text_cleaner import normalize_artist


ARTIST_PATTERNS = {
    "aespa": re.compile(r"(aespa|에스파)", re.IGNORECASE),
    "IVE": re.compile(r"(ive|아이브)", re.IGNORECASE),
    "BABYMONSTER": re.compile(r"(babymonster|baby\s*monster|베이비몬스터)", re.IGNORECASE),
    "NMIXX": re.compile(r"(nmixx|엔믹스)", re.IGNORECASE),
    "ILLIT": re.compile(r"(illit|아일릿)", re.IGNORECASE),
    "NCT": re.compile(r"(nct|엔시티)", re.IGNORECASE),
    "ZEROBASEONE": re.compile(r"(zerobaseone|zero\s*base\s*one|zb1|제로베이스원)", re.IGNORECASE),
    "TXT": re.compile(r"(txt|투모로우바이투게더|tomorrow\s*x\s*together)", re.IGNORECASE),
    "ENHYPEN": re.compile(r"(enhypen|엔하이픈)", re.IGNORECASE),
    "BOYNEXTDOOR": re.compile(r"(boynextdoor|boy\s*next\s*door|보이넥스트도어)", re.IGNORECASE),
}
WEEKLY_CHART_KEYWORDS = ("本週榜單", "本週 K-pop 榜單", "本週Kpop榜單", "榜單", "chart")


@dataclass(frozen=True)
class Intent:
    name: str
    artist: str
    period_months: int = 3
    raw_text: str = ""


def route_message(message: str) -> Intent:
    normalized = _normalize_message(message)
    if _is_weekly_chart_request(normalized):
        return Intent(
            name="weekly_chart",
            artist="",
            period_months=3,
            raw_text=message,
        )

    artist = _extract_artist(normalized)
    period_months = _extract_period_months(normalized)

    intent_name = "artist_analysis"
    if any(keyword in normalized for keyword in ("反應", "輿論", "與論", "風向", "評價", "新聞")):
        intent_name = "artist_sentiment_context"
    if any(keyword in normalized for keyword in ("榜", "排名", "表現", "趨勢")):
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


def _is_weekly_chart_request(message: str) -> bool:
    normalized_message = _normalize_chart_query(message)
    return any(
        _normalize_chart_query(keyword) in normalized_message
        for keyword in WEEKLY_CHART_KEYWORDS
    )


def _normalize_chart_query(message: str) -> str:
    return re.sub(r"[\s\-_]+", "", message.casefold())


def _normalize_message(message: str) -> str:
    return unicodedata.normalize("NFKC", message)
