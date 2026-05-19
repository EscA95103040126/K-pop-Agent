from pathlib import Path

from scripts.seed_data import seed
from src.tools.chart_db import ChartHistoryRepository


def test_chart_db_returns_artist_trend(tmp_path: Path) -> None:
    db_path = tmp_path / "chart_history.db"
    repo = ChartHistoryRepository(db_path=db_path)
    repo.init_db()

    seed(db_path=db_path)
    result = repo.get_artist_trend("aespa", weeks=12)

    assert result["artist"] == "aespa"
    assert result["best_rank"] == 1
    assert result["weeks_on_chart"] == 12


def test_chart_db_insert_chart_rows_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "chart_history.db"
    repo = ChartHistoryRepository(db_path=db_path)
    rows = [
        {
            "fetch_date": "2026-05-18",
            "chart_date": "2026-05-11",
            "source": "bugs",
            "chart_type": "weekly",
            "rank": 1,
            "title": "REDRED",
            "artist": "CORTIS (코르티스)",
            "album": "GREENGREEN",
            "change_rank": 2,
        }
    ]

    assert repo.insert_chart_rows(rows) == 1
    assert repo.insert_chart_rows(rows) == 0


def test_chart_db_returns_latest_weekly_chart(tmp_path: Path) -> None:
    db_path = tmp_path / "chart_history.db"
    repo = ChartHistoryRepository(db_path=db_path)
    rows = [
        {
            "fetch_date": "2026-05-18",
            "chart_date": "2026-05-11",
            "source": "bugs",
            "chart_type": "weekly",
            "rank": 1,
            "title": "REDRED",
            "artist": "CORTIS (코르티스)",
            "album": "GREENGREEN",
            "change_rank": 2,
        }
    ]
    repo.insert_chart_rows(rows)

    result = repo.get_latest_weekly_chart()

    assert result["chart_date"] == "2026-05-11"
    assert result["items"][0]["title"] == "REDRED"
