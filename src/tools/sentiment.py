from __future__ import annotations

import csv
import time
from pathlib import Path

import requests

from src.config import settings


DEFAULT_COMMENTS_CSV = settings.base_dir / "data" / "sample_comments.csv"
REQUIRED_COLUMNS = ["artist", "song", "comment"]
ARTIST_ALIASES = {
    "new jeans": "newjeans",
}

VALID_SENTIMENT_LABELS = {"positive", "neutral", "negative"}
GEMINI_REQUEST_TIMEOUT_SECONDS = 10
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_SENTIMENT_PROMPT = """你是一個韓文情感分析專家。
請判斷以下韓文評論的情感傾向，只能回答其中一個：positive / neutral / negative
評論：{comment}
只回答一個英文單字，不要有其他內容。"""


def load_comments(csv_path: str | None = None) -> list[dict]:
    path = Path(csv_path) if csv_path else DEFAULT_COMMENTS_CSV
    if not path.is_absolute():
        path = settings.base_dir / path

    with path.open(encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        missing_columns = [
            column for column in REQUIRED_COLUMNS if column not in (reader.fieldnames or [])
        ]
        if missing_columns:
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
    """Zero-shot Korean comment sentiment classifier powered by Gemini.

    Returns 'positive', 'negative', or 'neutral'.
    """
    if not comment:
        return "neutral"

    if not settings.gemini_api_key:
        return "neutral"

    try:
        response = requests.post(
            GEMINI_API_URL.format(model=settings.gemini_model),
            params={"key": settings.gemini_api_key},
            json={
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {
                                "text": GEMINI_SENTIMENT_PROMPT.format(
                                    comment=comment.strip()
                                )
                            }
                        ],
                    }
                ],
                "generationConfig": {
                    "temperature": 0,
                    "maxOutputTokens": 5,
                },
            },
            timeout=GEMINI_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
        label = (
            data["candidates"][0]["content"]["parts"][0].get("text", "")
        ).strip().casefold()
    except Exception:
        return "neutral"

    return label if label in VALID_SENTIMENT_LABELS else "neutral"


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
    has_sentiment_column = all("sentiment" in row for row in comments)

    for row in comments:
        if has_sentiment_column:
            label = (row.get("sentiment") or "").strip().casefold()
        else:
            text = row["comment"]
            try:
                label = classify_comment(text)
            except Exception:
                label = "neutral"
            time.sleep(0.5)
        if label not in counts:
            label = "neutral"
        counts[label] += 1

    sentiment = {k: round(v / total, 4) for k, v in counts.items()}

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
        "top_keywords": [],
        "summary": summary,
    }


def _normalize_artist_name(artist_name: str) -> str:
    normalized = artist_name.strip().casefold()
    return ARTIST_ALIASES.get(normalized, normalized.replace(" ", ""))
