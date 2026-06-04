import json
from datetime import datetime, timedelta, timezone

import src.agent as agent_module
from src.agent import KpopAnalysisAgent


class DummyAgent:
    def __init__(self) -> None:
        self.preload_calls = 0

    def preload_artist_cache(self, artist: str, period_months: int = 3) -> dict:
        self.preload_calls += 1
        return {
            "artist": artist,
            "period_months": period_months,
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "report": "regenerated",
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
