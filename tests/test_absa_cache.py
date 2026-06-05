from __future__ import annotations

import json
from datetime import datetime, timezone

import app as app_module
import src.agent as agent_module
import src.tools.absa as absa_module
from src.agent import DEMO_ARTISTS, KpopAnalysisAgent
from src.tools.absa import (
    ABSA_ASPECTS,
    absa_cache_path,
    load_absa_cache,
    validate_absa_payload,
)


def _sample_absa_payload(artist: str = "aespa") -> dict:
    aspect_sentiment = {
        aspect: {
            "label": config["label"],
            "count": 1,
            "ratio": {"positive": 1.0, "neutral": 0.0, "negative": 0.0},
            "dominant": "positive",
            "evidence": [],
        }
        for aspect, config in ABSA_ASPECTS.items()
    }
    return {
        "artist": artist,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "naver_news": {"count": 1, "items": []},
            "youtube_comments": {"count": 1},
            "model": {"name": "test-kcelectra", "backend": "kcelectra"},
        },
        "aspect_sentiment": aspect_sentiment,
        "overall_sentiment": {
            "count": 1,
            "ratio": {"positive": 1.0, "neutral": 0.0, "negative": 0.0},
            "dominant": "positive",
        },
        "top_comments_or_evidence": [],
        "naver_news_summary": [],
        "report_text": "# aespa 近期市場與輿論分析\n\n## 1. 榜單表現\n- offline absa\n\n## 3. 粉絲與輿論反應\n- 正面比例：1.0\n\n## 4. 綜合判斷\n- 輿論風險：低\n\n## 5. 一句話總結\nABSA cache hit",
    }


def test_absa_cache_loader_reads_valid_payload(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(absa_module, "ABSA_CACHE_DIR", tmp_path)
    payload = _sample_absa_payload("aespa")
    absa_cache_path("aespa").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    loaded = load_absa_cache("aespa")

    assert loaded is not None
    assert loaded["artist"] == "aespa"
    assert loaded["sources"]["model"]["backend"] == "kcelectra"


def test_get_artist_analysis_cache_falls_back_when_absa_missing(monkeypatch) -> None:
    class DummyAgent:
        def __init__(self) -> None:
            self.fallback_calls = 0

        def get_artist_cache(self, artist: str, period_months: int = 3) -> dict:
            self.fallback_calls += 1
            return {
                "artist": artist,
                "period_months": period_months,
                "cached_at": "fallback-time",
                "report": "fallback report",
            }

    dummy = DummyAgent()
    monkeypatch.setattr(agent_module, "load_absa_cache", lambda artist: None)

    payload = KpopAnalysisAgent.get_artist_analysis_cache(dummy, "aespa")

    assert payload["report"] == "fallback report"
    assert dummy.fallback_calls == 1


def test_supported_artist_absa_cache_paths_and_schema() -> None:
    for artist in DEMO_ARTISTS:
        cache_path = absa_cache_path(artist)
        assert cache_path.exists(), f"missing ABSA cache for {artist}"
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        assert validate_absa_payload(payload), f"invalid ABSA schema for {artist}"
        assert set(payload["aspect_sentiment"]) == set(ABSA_ASPECTS)


def test_analyze_message_local_prefers_absa_cache(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(absa_module, "ABSA_CACHE_DIR", tmp_path)
    payload = _sample_absa_payload("aespa")
    absa_cache_path("aespa").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    agent = KpopAnalysisAgent()

    report = agent.analyze_message_local("分析 aespa")

    assert "ABSA cache hit" in report


def test_analyze_endpoint_uses_local_absa_cache(monkeypatch) -> None:
    class DummyAgent:
        def __init__(self) -> None:
            self.calls = 0

        def get_artist_analysis_cache(self, artist: str, period_months: int = 3) -> dict:
            self.calls += 1
            return {
                "artist": artist,
                "period_months": period_months,
                "cached_at": "absa-time",
                "report": "ABSA endpoint report",
                "flex": {"type": "bubble", "body": {"type": "box", "layout": "vertical", "contents": []}},
                "cache_type": "absa",
            }

    dummy = DummyAgent()
    monkeypatch.setattr(app_module, "agent", dummy)

    response = app_module.app.test_client().post(
        "/analyze",
        json={"message": "分析 aespa"},
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["report"] == "ABSA endpoint report"
    assert payload["cache"]["type"] == "absa"
    assert dummy.calls == 1
