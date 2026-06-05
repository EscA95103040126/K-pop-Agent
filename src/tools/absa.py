from __future__ import annotations

import csv
import json
import logging
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.config import settings
from src.tools.sentiment import _normalize_artist_name, get_comments_by_artist

logger = logging.getLogger(__name__)

ABSA_CACHE_DIR = settings.base_dir / "data" / "cache" / "absa"
DEFAULT_KCELECTRA_MODEL = "cocoaice/kcELECTRA-absa"
ABSA_ASPECTS: dict[str, dict[str, Any]] = {
    "song_music": {
        "label": "song / music",
        "keywords": (
            "노래",
            "곡",
            "음악",
            "앨범",
            "멜로디",
            "사운드",
            "컴백",
            "타이틀",
            "뮤직",
            "music",
            "song",
        ),
    },
    "performance": {
        "label": "performance",
        "keywords": (
            "무대",
            "퍼포먼스",
            "춤",
            "안무",
            "댄스",
            "직캠",
            "라이브",
            "stage",
            "dance",
            "performance",
        ),
    },
    "visual_styling": {
        "label": "visual / styling",
        "keywords": (
            "비주얼",
            "얼굴",
            "스타일",
            "스타일링",
            "의상",
            "메이크업",
            "컨셉",
            "뮤비",
            "mv",
            "visual",
            "styling",
        ),
    },
    "vocal_rap": {
        "label": "vocal / rap",
        "keywords": (
            "보컬",
            "랩",
            "실력",
            "가창",
            "고음",
            "음색",
            "라이브",
            "vocal",
            "rap",
        ),
    },
    "fandom_public_opinion": {
        "label": "fandom / public_opinion",
        "keywords": (
            "팬",
            "반응",
            "여론",
            "인기",
            "화제",
            "댓글",
            "조회수",
            "차트",
            "대상",
            "팬덤",
            "fandom",
        ),
    },
}
VALID_SENTIMENT_LABELS = ("positive", "neutral", "negative")
POSITIVE_HINTS = (
    "좋",
    "미쳤",
    "완벽",
    "대박",
    "최고",
    "예쁘",
    "멋",
    "독보",
    "잘",
    "찢",
    "갓",
    "사랑",
    "취향",
    "퀄리티",
    "세련",
)
NEGATIVE_HINTS = (
    "아쉽",
    "별로",
    "싫",
    "논란",
    "실망",
    "부족",
    "촌스럽",
    "불안",
    "위험",
    "비판",
    "악플",
)


class KcElectraSentimentAnalyzer:
    """Optional offline KcELECTRA sentiment backend.

    The LINE app never creates this class. It is intended for batch scripts only.
    If Transformers/PyTorch or model files are unavailable, callers can fall back
    to KeywordSentimentAnalyzer and still emit a stable cache schema.
    """

    backend_name = "kcelectra"

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or os.getenv("ABSA_MODEL_NAME") or DEFAULT_KCELECTRA_MODEL
        try:
            from transformers import pipeline
        except ImportError as exc:  # pragma: no cover - optional dependency.
            raise RuntimeError(
                "Transformers is required for KcELECTRA ABSA. "
                "Install transformers and torch for offline preprocessing."
            ) from exc
        self._pipeline = pipeline("text-classification", model=self.model_name)

    def classify(self, text: str) -> str:
        if not text.strip():
            return "neutral"
        try:
            result = self._pipeline(text[:512], truncation=True)
        except TypeError:
            result = self._pipeline(text[:512])
        if isinstance(result, list):
            result = result[0] if result else {}
        return _normalize_model_label(str(result.get("label", "")), result.get("score"))


class KeywordSentimentAnalyzer:
    backend_name = "keyword-fallback"
    model_name = "keyword-fallback"

    def classify(self, text: str) -> str:
        positive = sum(1 for hint in POSITIVE_HINTS if hint in text)
        negative = sum(1 for hint in NEGATIVE_HINTS if hint in text)
        if positive > negative:
            return "positive"
        if negative > positive:
            return "negative"
        return "neutral"


def absa_cache_path(artist: str, cache_dir: Path | None = None) -> Path:
    return (cache_dir or ABSA_CACHE_DIR) / f"{_cache_key(artist)}.json"


def load_absa_cache(artist: str, cache_dir: Path | None = None) -> dict[str, Any] | None:
    path = absa_cache_path(artist, cache_dir=cache_dir)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not read ABSA cache: %s", path, exc_info=True)
        return None
    return payload if validate_absa_payload(payload) else None


def validate_absa_payload(payload: dict[str, Any]) -> bool:
    required = {
        "artist",
        "generated_at",
        "sources",
        "aspect_sentiment",
        "overall_sentiment",
        "top_comments_or_evidence",
        "naver_news_summary",
        "report_text",
    }
    if not required.issubset(payload):
        return False
    if not isinstance(payload.get("aspect_sentiment"), dict):
        return False
    return all(aspect in payload["aspect_sentiment"] for aspect in ABSA_ASPECTS)


def build_absa_payload(
    artist: str,
    news: list[dict[str, Any]],
    comments: list[dict[str, str]],
    analyzer: Any | None = None,
) -> dict[str, Any]:
    sentiment_analyzer = analyzer or KeywordSentimentAnalyzer()
    records = _records_from_sources(news=news, comments=comments)
    overall_counts: Counter[str] = Counter()
    aspect_counts: dict[str, Counter[str]] = {
        aspect: Counter() for aspect in ABSA_ASPECTS
    }
    aspect_evidence: dict[str, list[dict[str, str]]] = {aspect: [] for aspect in ABSA_ASPECTS}

    for record in records:
        label = _valid_label(sentiment_analyzer.classify(record["text"]))
        overall_counts[label] += 1
        aspects = detect_aspects(record["text"])
        for aspect in aspects:
            aspect_counts[aspect][label] += 1
            if len(aspect_evidence[aspect]) < 2:
                aspect_evidence[aspect].append(
                    {
                        "source": record["source"],
                        "sentiment": label,
                        "text": _truncate(record["text"], 180),
                    }
                )

    aspect_sentiment = {
        aspect: _format_aspect_result(aspect, aspect_counts[aspect], aspect_evidence[aspect])
        for aspect in ABSA_ASPECTS
    }
    overall_sentiment = _ratio_summary(overall_counts)
    naver_summary = _summarize_news(news)
    top_evidence = _top_evidence(aspect_evidence)
    report_text = _build_report_text(
        artist=artist,
        aspect_sentiment=aspect_sentiment,
        overall_sentiment=overall_sentiment,
        naver_news_summary=naver_summary,
        top_evidence=top_evidence,
    )

    return {
        "artist": artist,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "naver_news": {
                "count": len(news),
                "items": news[:10],
            },
            "youtube_comments": {
                "count": len(comments),
            },
            "model": {
                "name": getattr(sentiment_analyzer, "model_name", "unknown"),
                "backend": getattr(sentiment_analyzer, "backend_name", "unknown"),
            },
        },
        "aspect_sentiment": aspect_sentiment,
        "overall_sentiment": overall_sentiment,
        "top_comments_or_evidence": top_evidence,
        "naver_news_summary": naver_summary,
        "report_text": report_text,
    }


def write_absa_payload(payload: dict[str, Any], cache_dir: Path | None = None) -> Path:
    path = absa_cache_path(str(payload["artist"]), cache_dir=cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_absa_summary_csv(payloads: Iterable[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "artist",
                "generated_at",
                "overall_positive",
                "overall_neutral",
                "overall_negative",
                "comment_count",
                "news_count",
                "model_backend",
            ],
        )
        writer.writeheader()
        for payload in payloads:
            overall = payload.get("overall_sentiment", {}).get("ratio", {})
            sources = payload.get("sources", {})
            writer.writerow(
                {
                    "artist": payload.get("artist", ""),
                    "generated_at": payload.get("generated_at", ""),
                    "overall_positive": overall.get("positive", 0),
                    "overall_neutral": overall.get("neutral", 0),
                    "overall_negative": overall.get("negative", 0),
                    "comment_count": sources.get("youtube_comments", {}).get("count", 0),
                    "news_count": sources.get("naver_news", {}).get("count", 0),
                    "model_backend": sources.get("model", {}).get("backend", ""),
                }
            )


def load_cached_or_sample_comments(artist: str) -> list[dict[str, str]]:
    return [
        {
            "artist": row.get("artist", artist),
            "song": row.get("song", ""),
            "comment": row.get("comment", ""),
            "sentiment": row.get("sentiment", ""),
        }
        for row in get_comments_by_artist(artist)
    ]


def detect_aspects(text: str) -> list[str]:
    normalized = text.casefold()
    aspects = [
        aspect
        for aspect, config in ABSA_ASPECTS.items()
        if any(keyword.casefold() in normalized for keyword in config["keywords"])
    ]
    return aspects or ["fandom_public_opinion"]


def _records_from_sources(
    news: list[dict[str, Any]],
    comments: list[dict[str, str]],
) -> list[dict[str, str]]:
    records = []
    for item in news:
        title = str(item.get("title") or "")
        summary = str(item.get("summary") or item.get("description") or "")
        text = f"{title} {summary}".strip()
        if text:
            records.append({"source": "naver_news", "text": text})
    for row in comments:
        text = str(row.get("comment") or "").strip()
        if text:
            records.append({"source": "youtube_comment", "text": text})
    return records


def _format_aspect_result(
    aspect: str,
    counts: Counter[str],
    evidence: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "label": ABSA_ASPECTS[aspect]["label"],
        "count": sum(counts.values()),
        "ratio": _ratio_summary(counts)["ratio"],
        "dominant": _dominant_label(counts),
        "evidence": evidence,
    }


def _ratio_summary(counts: Counter[str]) -> dict[str, Any]:
    total = sum(counts.values())
    if total <= 0:
        ratio = {label: 0 for label in VALID_SENTIMENT_LABELS}
    else:
        ratio = {
            label: round(counts.get(label, 0) / total, 4)
            for label in VALID_SENTIMENT_LABELS
        }
    return {
        "count": total,
        "ratio": ratio,
        "dominant": _dominant_label(counts),
    }


def _dominant_label(counts: Counter[str]) -> str:
    if not counts:
        return "neutral"
    ordered = sorted(
        VALID_SENTIMENT_LABELS,
        key=lambda label: (counts.get(label, 0), label == "neutral"),
        reverse=True,
    )
    return ordered[0]


def _top_evidence(aspect_evidence: dict[str, list[dict[str, str]]]) -> list[dict[str, str]]:
    rows = []
    for aspect, evidence_rows in aspect_evidence.items():
        for row in evidence_rows[:1]:
            rows.append({"aspect": aspect, **row})
    return rows[:5]


def _summarize_news(news: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "title": _truncate(str(item.get("title") or ""), 100),
            "date": str(item.get("date") or ""),
            "summary": _truncate(str(item.get("summary") or ""), 180),
            "link": str(item.get("link") or ""),
        }
        for item in news[:5]
    ]


def _build_report_text(
    artist: str,
    aspect_sentiment: dict[str, Any],
    overall_sentiment: dict[str, Any],
    naver_news_summary: list[dict[str, str]],
    top_evidence: list[dict[str, str]],
) -> str:
    overall = overall_sentiment["ratio"]
    aspect_lines = []
    for aspect in ABSA_ASPECTS:
        result = aspect_sentiment[aspect]
        ratio = result["ratio"]
        aspect_lines.append(
            "- "
            f"{_localized_aspect_label(aspect)}：{_localized_sentiment(result['dominant'])} "
            f"(正 {ratio['positive']} / 中 {ratio['neutral']} / 負 {ratio['negative']})"
        )
    news_titles = _format_news_titles(naver_news_summary)
    fan_summary = _fan_summary(overall_sentiment["dominant"], overall)
    trend_summary = _trend_summary(
        artist=artist,
        overall=overall,
        dominant=overall_sentiment["dominant"],
        news_titles=news_titles,
    )
    market_insight = _market_insight_text(
        artist=artist,
        overall=overall,
        news_titles=news_titles,
    )
    footer_summary = _footer_summary(
        artist=artist,
        overall=overall,
        news_titles=news_titles,
    )

    return f"""# {artist} 近期市場與輿論分析

## 1. 榜單表現
- 榜單表現沿用既有 Bugs 榜單快取觀察，搭配本次新聞與留言聲量判讀。
- 目前更適合看作回歸期與內容曝光的輔助訊號，後續可再與週榜排名交叉追蹤。

## 2. 粉絲與輿論反應
- 正面比例：{overall['positive']}
- 中立比例：{overall['neutral']}
- 負面比例：{overall['negative']}
- 簡短解讀：{fan_summary}
{chr(10).join(aspect_lines)}

## 3. 綜合判斷
- 市場熱度：{_market_heat_from_overall(overall)}
- 輿論風險：{_risk_from_overall(overall)}
- Naver 新聞觀察：{news_titles}
- 短期趨勢：{trend_summary}

## 4. 市場洞察
{market_insight}

## 5. 一句話總結
{footer_summary}
"""


def _market_heat_from_overall(overall: dict[str, float]) -> str:
    if overall.get("positive", 0) >= 0.55:
        return "高"
    if overall.get("negative", 0) >= 0.45:
        return "中"
    return "中"


def _localized_aspect_label(aspect: str) -> str:
    return {
        "song_music": "歌曲／音樂性",
        "performance": "舞台／表演",
        "visual_styling": "造型／視覺",
        "vocal_rap": "演唱／Rap",
        "fandom_public_opinion": "粉絲與大眾反應",
    }.get(aspect, aspect)


def _format_news_titles(naver_news_summary: list[dict[str, str]]) -> str:
    text = " ".join(
        f"{item.get('title', '')} {item.get('summary', '')}"
        for item in naver_news_summary
    )
    if not text.strip():
        return "目前沒有明確新聞焦點"

    category_keywords = (
        ("公開演出與舞台曝光", ("열린음악회", "라인업", "출연", "공연", "콘서트", "무대")),
        ("海外媒體與產業評選", ("포브스", "forbes", "30세", "아시아", "영향력")),
        ("新作與音樂性討論", ("신보", "앨범", "컴백", "곡", "음악성", "serenade", "heavy serenade")),
        ("榜單與音源平台露出", ("차트", "멜론", "chart", "순위")),
        ("品牌與商業活動", ("브랜드", "캠페인", "광고", "화보", "앰버서더")),
        ("巡演與現場活動", ("투어", "월드투어", "팬미팅", "현장")),
    )
    lowered = text.casefold()
    categories = [
        label
        for label, keywords in category_keywords
        if any(keyword.casefold() in lowered for keyword in keywords)
    ]
    if categories:
        return "、".join(categories[:3])
    return "近期新聞曝光與內容話題"


def _fan_summary(dominant: str, overall: dict[str, float]) -> str:
    localized = _localized_sentiment(dominant)
    positive = overall.get("positive", 0)
    neutral = overall.get("neutral", 0)
    negative = overall.get("negative", 0)
    if negative >= 0.25:
        return f"討論以{localized}為主，但負面比例已需要留意。"
    if positive >= 0.5 and neutral >= 0.35:
        return "正面與中性討論並行，口碑穩定但仍有觀望聲音。"
    if positive >= 0.45:
        return "粉絲留言偏正向，音樂與內容曝光仍能帶動討論。"
    if neutral >= 0.6:
        return "討論多落在中性觀察，尚未形成明顯輿論壓力。"
    return f"討論目前偏{localized}，適合持續追蹤留言樣本變化。"


def _trend_summary(
    artist: str,
    overall: dict[str, float],
    dominant: str,
    news_titles: str,
) -> str:
    risk = _risk_from_overall(overall)
    localized = _localized_sentiment(dominant)
    if news_titles == "目前沒有明確新聞焦點":
        return f"{artist} 目前留言情緒偏{localized}，短期仍需等待更多新聞與榜單訊號。"
    if risk == "低":
        return f"Naver 新聞仍有可見曝光，留言端偏{localized}，短期輿論風險不高。"
    return f"Naver 新聞帶出近期話題，留言端偏{localized}，需要觀察負面討論是否擴大。"


def _market_insight_text(
    artist: str,
    overall: dict[str, float],
    news_titles: str,
) -> str:
    risk = _risk_from_overall(overall)
    positive = overall.get("positive", 0)
    if positive >= 0.45 and risk == "低":
        opportunity = "可延續音樂與內容品質帶來的正向討論，並把新聞曝光轉成舞台與作品話題。"
    elif risk == "低":
        opportunity = "目前輿論壓力低，適合透過舞台、MV 與成員內容累積更鮮明的正面聲量。"
    else:
        opportunity = "需先降低爭議或負面觀感，再放大作品與舞台表現的正向證據。"
    return "\n".join(
        [
            f"- 新聞焦點：{news_titles}",
            f"- 機會點：{opportunity}",
            f"- 觀察重點：持續比對 {artist} 的榜單續航、留言情緒與新聞曝光是否往同一方向收斂。",
        ]
    )


def _footer_summary(
    artist: str,
    overall: dict[str, float],
    news_titles: str,
) -> str:
    heat = _market_heat_from_overall(overall)
    risk = _risk_from_overall(overall)
    sentiment = _fan_summary(_dominant_from_ratio(overall), overall).rstrip("。")
    news_part = "新聞焦點尚不明顯" if news_titles == "目前沒有明確新聞焦點" else "Naver 新聞仍有近期曝光"
    return (
        f"{artist} 目前榜單可搭配後續週榜觀察，{sentiment}；"
        f"{news_part}，整體市場熱度為{heat}、輿論風險為{risk}。"
    )


def _dominant_from_ratio(overall: dict[str, float]) -> str:
    return max(VALID_SENTIMENT_LABELS, key=lambda label: overall.get(label, 0))


def _risk_from_overall(overall: dict[str, float]) -> str:
    if overall.get("negative", 0) >= 0.45:
        return "高"
    if overall.get("negative", 0) >= 0.25:
        return "中"
    return "低"


def _localized_sentiment(label: str) -> str:
    return {
        "positive": "正面",
        "neutral": "中性",
        "negative": "負面",
    }.get(label, "中性")


def _normalize_model_label(label: str, score: Any = None) -> str:
    normalized = label.strip().casefold()
    if "positive" in normalized or normalized in {"pos", "1", "label_1"}:
        return "positive"
    if "negative" in normalized or normalized in {"neg", "0", "label_0"}:
        return "negative"
    if "neutral" in normalized or normalized in {"neu", "2", "label_2"}:
        return "neutral"
    try:
        numeric_score = float(score)
    except (TypeError, ValueError):
        numeric_score = 0
    if normalized.startswith("label_") and numeric_score < 0.6:
        return "neutral"
    return "neutral"


def _valid_label(label: str) -> str:
    normalized = label.strip().casefold()
    return normalized if normalized in VALID_SENTIMENT_LABELS else "neutral"


def _cache_key(value: str) -> str:
    normalized = _normalize_artist_name(value)
    key = re.sub(r"[^a-z0-9]+", "_", normalized.casefold()).strip("_")
    return key or "unknown"


def _truncate(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "…"
