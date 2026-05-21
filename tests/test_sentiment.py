"""pytest coverage for Tool D sentiment module (Phase 3-2D)."""
from __future__ import annotations

from types import SimpleNamespace

from src.tools.sentiment import (
    analyze_sentiment_from_csv,
    classify_comment,
    get_comments_by_artist,
    load_comments,
)
import src.tools.sentiment as sentiment_module


# ── 1. load_comments ──────────────────────────────────────────────────────────

def test_load_comments_total_ge_60():
    comments = load_comments()
    assert len(comments) >= 200


# ── 2-4. get_comments_by_artist ───────────────────────────────────────────────

def test_get_comments_aespa_count():
    assert len(get_comments_by_artist("aespa")) == 20


def test_get_comments_ive_count():
    assert len(get_comments_by_artist("IVE")) == 20


def test_get_comments_babymonster_count():
    assert len(get_comments_by_artist("BABYMONSTER")) == 20


def test_get_comments_enhypen_count():
    assert len(get_comments_by_artist("ENHYPEN")) == 20


# ── 5-8. classify_comment ─────────────────────────────────────────────────────


def test_classify_comment_returns_valid_label(monkeypatch):
    class DummyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "candidates": [
                    {"content": {"parts": [{"text": "positive"}]}}
                ]
            }

    monkeypatch.setattr(
        sentiment_module,
        "settings",
        SimpleNamespace(gemini_api_key="test-key", gemini_model="gemini-3.5-flash"),
    )
    monkeypatch.setattr(sentiment_module.requests, "post", lambda *args, **kwargs: DummyResponse())

    result = classify_comment("이번 노래는 무대랑 잘 어울리고 계속 듣게 돼요")
    assert result in {"positive", "neutral", "negative"}


def test_classify_empty_returns_neutral():
    assert classify_comment("") == "neutral"


def test_classify_invalid_gemini_response_falls_back_to_neutral(monkeypatch):
    class DummyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "candidates": [
                    {"content": {"parts": [{"text": "happy"}]}}
                ]
            }

    monkeypatch.setattr(
        sentiment_module,
        "settings",
        SimpleNamespace(gemini_api_key="test-key", gemini_model="gemini-3.5-flash"),
    )
    monkeypatch.setattr(sentiment_module.requests, "post", lambda *args, **kwargs: DummyResponse())

    result = classify_comment("이번 활동 의상은 사이버 콘셉트에 맞춰진 느낌이에요")
    assert result == "neutral"


def test_classify_none_returns_neutral():
    assert classify_comment(None) == "neutral"


# ── 9. analyze_sentiment_from_csv ─────────────────────────────────────────────

def test_analyze_aespa_structure(monkeypatch):
    monkeypatch.setattr(sentiment_module, "classify_comment", lambda comment: "neutral")
    monkeypatch.setattr(sentiment_module.time, "sleep", lambda seconds: None)

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


def test_analyze_sentiment_ratios_sum_to_one(monkeypatch):
    monkeypatch.setattr(sentiment_module, "classify_comment", lambda comment: "neutral")
    monkeypatch.setattr(sentiment_module.time, "sleep", lambda seconds: None)

    for artist in ["aespa", "IVE", "BABYMONSTER"]:
        result = analyze_sentiment_from_csv(artist)
        s = result["sentiment"]
        total = s["positive"] + s["neutral"] + s["negative"]
        assert abs(total - 1.0) < 0.01, f"{artist} ratios sum to {total}"
