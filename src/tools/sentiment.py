from __future__ import annotations

import csv
from pathlib import Path

from src.config import settings


DEFAULT_COMMENTS_CSV = settings.base_dir / "data" / "sample_comments.csv"
REQUIRED_COLUMNS = ["artist", "song", "comment"]
ARTIST_ALIASES = {
    "new jeans": "newjeans",
}

POSITIVE_KEYWORDS = [
    "중독성", "대박", "완벽", "멋있", "최고", "좋아", "예쁘", "사랑스럽",
    "흥미", "화려", "깔끔", "당당", "편안", "자연스럽", "강렬", "중독",
    "좋다", "잘했어", "사랑", "좋고",
]

NEGATIVE_KEYWORDS = [
    "아쉬워", "아쉽게", "아쉽긴", "실망", "낯설", "이상하고", "짧아요",
    "약하다", "약해요", "부족", "별로", "지루", "어색", "평범", "논란",
]


def load_comments(csv_path: str | None = None) -> list[dict]:
    path = Path(csv_path) if csv_path else DEFAULT_COMMENTS_CSV
    if not path.is_absolute():
        path = settings.base_dir / path

    with path.open(encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != REQUIRED_COLUMNS:
            raise ValueError(f"CSV columns must be: {','.join(REQUIRED_COLUMNS)}")
        return [dict(row) for row in reader]


def get_comments_by_artist(artist_name: str, csv_path: str | None = None) -> list[dict]:
    normalized_artist = _normalize_artist_name(artist_name)
    return [
        row
        for row in load_comments(csv_path)
        if _normalize_artist_name(row["artist"]) == normalized_artist
    ]


def classify_comment(comment: str | None) -> str:
    """Rule-based Korean comment sentiment classifier.

    Returns 'positive', 'negative', or 'neutral'.
    """
    if not comment:
        return "neutral"
    pos = sum(1 for kw in POSITIVE_KEYWORDS if kw in comment)
    neg = sum(1 for kw in NEGATIVE_KEYWORDS if kw in comment)
    if pos > neg:
        return "positive"
    elif neg > pos:
        return "negative"
    else:
        return "neutral"


def analyze_sentiment_from_csv(artist_name: str, song: str | None = None) -> dict:
    """Analyze comment sentiment for an artist (optionally filtered by song).

    Returns a dict with total_comments, sentiment ratios, top_keywords, and summary.
    """
    comments = get_comments_by_artist(artist_name)
    if song:
        comments = [c for c in comments if c["song"].casefold() == song.casefold()]

    total = len(comments)
    if total == 0:
        return {
            "artist": artist_name,
            "song": song,
            "total_comments": 0,
            "sentiment": {"positive": 0, "neutral": 0, "negative": 0},
            "top_keywords": [],
            "summary": "Tool D 尚未取得足夠評論樣本。",
        }

    counts: dict[str, int] = {"positive": 0, "neutral": 0, "negative": 0}
    keyword_freq: dict[str, int] = {}
    all_keywords = POSITIVE_KEYWORDS + NEGATIVE_KEYWORDS

    for row in comments:
        text = row["comment"]
        label = classify_comment(text)
        counts[label] += 1
        for kw in all_keywords:
            if kw in text:
                keyword_freq[kw] = keyword_freq.get(kw, 0) + 1

    sentiment = {k: round(v / total, 4) for k, v in counts.items()}
    top_keywords = sorted(keyword_freq, key=lambda k: keyword_freq[k], reverse=True)[:5]

    pos = sentiment["positive"]
    neg = sentiment["negative"]
    if pos >= 0.5:
        summary = "整體評論偏正面。"
    elif neg >= 0.5:
        summary = "整體評論偏負面。"
    elif pos > neg:
        summary = "評論以正面為主，但也有部分中性或負面意見。"
    elif neg > pos:
        summary = "評論以負面為主，但也有部分中性或正面意見。"
    else:
        summary = "正負評論比例相近，整體評論呈中性。"

    return {
        "artist": artist_name,
        "song": song,
        "total_comments": total,
        "sentiment": sentiment,
        "top_keywords": top_keywords,
        "summary": summary,
    }


def _normalize_artist_name(artist_name: str) -> str:
    normalized = artist_name.strip().casefold()
    return ARTIST_ALIASES.get(normalized, normalized.replace(" ", ""))
