"""pytest coverage for Tool D sentiment module (Phase 3-2D)."""
from __future__ import annotations

import pytest

from src.tools.sentiment import (
    analyze_sentiment_from_csv,
    classify_comment,
    get_comments_by_artist,
    load_comments,
)


# ── 1. load_comments ──────────────────────────────────────────────────────────

def test_load_comments_total_ge_60():
    comments = load_comments()
    assert len(comments) >= 60


# ── 2-4. get_comments_by_artist ───────────────────────────────────────────────

def test_get_comments_aespa_count():
    assert len(get_comments_by_artist("aespa")) == 20


def test_get_comments_ive_count():
    assert len(get_comments_by_artist("IVE")) == 20


def test_get_comments_newjeans_count():
    assert len(get_comments_by_artist("NewJeans")) == 20


def test_get_comments_newjeans_alias():
    # "new jeans" should alias to "newjeans"
    assert len(get_comments_by_artist("new jeans")) == 20


# ── 5-8. classify_comment ─────────────────────────────────────────────────────

def test_classify_positive():
    result = classify_comment("이번 노래 중독성 진짜 대박이고 무대도 완벽해요")
    assert result == "positive"


def test_classify_negative():
    result = classify_comment("기대가 커서 그런지 이번 곡은 약간 실망했어요")
    assert result == "negative"


def test_classify_neutral():
    result = classify_comment("이번 활동 의상은 사이버 콘셉트에 맞춰진 느낌이에요")
    assert result == "neutral"


def test_classify_none_returns_neutral():
    assert classify_comment(None) == "neutral"


# ── 9. analyze_sentiment_from_csv ─────────────────────────────────────────────

def test_analyze_aespa_structure():
    result = analyze_sentiment_from_csv("aespa")
    assert result["artist"] == "aespa"
    assert result["song"] is None
    assert result["total_comments"] == 20
    assert set(result["sentiment"].keys()) == {"positive", "neutral", "negative"}
    assert isinstance(result["top_keywords"], list)
    assert len(result["top_keywords"]) <= 5
    assert isinstance(result["summary"], str)


def test_analyze_unknown_artist_no_crash():
    result = analyze_sentiment_from_csv("UnknownArtistXYZ")
    assert result["total_comments"] == 0
    assert result["top_keywords"] == []
    assert result["summary"] == "Tool D 尚未取得足夠評論樣本。"


def test_analyze_sentiment_ratios_sum_to_one():
    for artist in ["aespa", "IVE", "NewJeans"]:
        result = analyze_sentiment_from_csv(artist)
        s = result["sentiment"]
        total = s["positive"] + s["neutral"] + s["negative"]
        assert abs(total - 1.0) < 0.01, f"{artist} ratios sum to {total}"
