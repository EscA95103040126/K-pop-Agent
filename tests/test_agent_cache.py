import json
from datetime import datetime, timedelta, timezone

import src.agent as agent_module
from src.agent import KpopAnalysisAgent


class DummyAgent:
    def __init__(self) -> None:
        self.preload_calls = 0
        self.weekly_preload_calls = 0

    def preload_artist_cache(self, artist: str, period_months: int = 3) -> dict:
        self.preload_calls += 1
        return {
            "artist": artist,
            "period_months": period_months,
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "report": "regenerated",
        }

    def preload_weekly_chart_cache(self, limit: int = 10) -> dict:
        self.weekly_preload_calls += 1
        return {
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "chart": {"items": []},
            "report": "weekly regenerated",
        }


def test_get_artist_cache_returns_fresh_matching_period(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(agent_module, "ARTIST_CACHE_DIR", tmp_path)
    cache_path = agent_module.artist_cache_path("aespa")
    cache_path.write_text(
        json.dumps(
            {
                "artist": "aespa",
                "period_months": 3,
                "cached_at": datetime.now(timezone.utc).isoformat(),
                "report": "cached",
            }
        ),
        encoding="utf-8",
    )
    dummy = DummyAgent()

    payload = KpopAnalysisAgent.get_artist_cache(dummy, "aespa", period_months=3)

    assert payload["report"] == "cached"
    assert dummy.preload_calls == 0


def test_get_artist_cache_regenerates_stale_cache(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(agent_module, "ARTIST_CACHE_DIR", tmp_path)
    cache_path = agent_module.artist_cache_path("aespa")
    cache_path.write_text(
        json.dumps(
            {
                "artist": "aespa",
                "period_months": 3,
                "cached_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
                "report": "stale",
            }
        ),
        encoding="utf-8",
    )
    dummy = DummyAgent()

    payload = KpopAnalysisAgent.get_artist_cache(dummy, "aespa", period_months=3)

    assert payload["report"] == "regenerated"
    assert dummy.preload_calls == 1


def test_get_weekly_chart_cache_regenerates_invalid_json(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "weekly.json"
    cache_path.write_text("{not-json", encoding="utf-8")
    monkeypatch.setattr(agent_module, "WEEKLY_CHART_CACHE_PATH", cache_path)
    dummy = DummyAgent()

    payload = KpopAnalysisAgent.get_weekly_chart_cache(dummy)

    assert payload["report"] == "weekly regenerated"
    assert dummy.weekly_preload_calls == 1
