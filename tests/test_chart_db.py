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
    assert result["best_rank"] == min(item["rank"] for item in result["history"])
    assert result["weeks_on_chart"] == len({item["chart_date"] for item in result["history"]})
    assert result["history"]


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


def test_chart_db_single_week_multiple_songs_is_not_trend(tmp_path: Path) -> None:
    db_path = tmp_path / "chart_history.db"
    repo = ChartHistoryRepository(db_path=db_path)
    rows = [
        {
            "fetch_date": "2026-05-18",
            "chart_date": "2026-05-11",
            "source": "bugs",
            "chart_type": "weekly",
            "rank": rank,
            "title": title,
            "artist": "aespa",
            "album": title,
            "change_rank": 0,
        }
        for rank, title in [(7, "WDA"), (30, "Whiplash"), (60, "Supernova")]
    ]
    repo.insert_chart_rows(rows)

    result = repo.get_artist_trend("aespa", weeks=12)

    assert result["period"] == "本週"
    assert result["best_rank"] == 7
    assert result["avg_rank"] == 32.33
    assert result["weeks_on_chart"] == 1
    assert result["trend"] == "資料不足"
    assert [item["rank"] for item in result["history"]] == [7, 30, 60]


def test_chart_db_multi_week_uses_best_rank_per_week(tmp_path: Path) -> None:
    db_path = tmp_path / "chart_history.db"
    repo = ChartHistoryRepository(db_path=db_path)
    rows = []
    for chart_date, ranked_titles in {
        "2026-05-04": [(10, "Old Best"), (20, "Old Second")],
        "2026-05-11": [(5, "New Best"), (15, "New Second")],
    }.items():
        for rank, title in ranked_titles:
            rows.append(
                {
                    "fetch_date": "2026-05-18",
                    "chart_date": chart_date,
                    "source": "bugs",
                    "chart_type": "weekly",
                    "rank": rank,
                    "title": title,
                    "artist": "aespa",
                    "album": title,
                    "change_rank": 0,
                }
            )
    repo.insert_chart_rows(rows)

    result = repo.get_artist_trend("aespa", weeks=12)

    assert result["period"] == "2026-05-04 ～ 2026-05-11"
    assert result["best_rank"] == 5
    assert result["avg_rank"] == 7.5
    assert result["weeks_on_chart"] == 2
    assert result["trend"] == "上升"
    assert [item["rank"] for item in result["history"]] == [5, 10]


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


def test_chart_db_skips_incomplete_latest_weekly_chart(tmp_path: Path) -> None:
    db_path = tmp_path / "chart_history.db"
    repo = ChartHistoryRepository(db_path=db_path)
    complete_rows = [
        {
            "fetch_date": "2026-05-18",
            "chart_date": "2026-05-11",
            "source": "bugs",
            "chart_type": "weekly",
            "rank": rank,
            "title": f"Song {rank}",
            "artist": f"Artist {rank}",
            "album": "Album",
            "change_rank": 0,
        }
        for rank in range(1, 11)
    ]
    incomplete_rows = [
        {
            "fetch_date": "2026-05-25",
            "chart_date": "2026-05-18",
            "source": "bugs",
            "chart_type": "weekly",
            "rank": 1,
            "title": "Only One",
            "artist": "aespa",
            "album": "Album",
            "change_rank": 1,
        }
    ]
    repo.insert_chart_rows(complete_rows + incomplete_rows)

    result = repo.get_latest_weekly_chart(limit=10)

    assert result["chart_date"] == "2026-05-11"
    assert len(result["items"]) == 10


def test_chart_db_returns_weekly_chart_by_date_and_lists_dates(tmp_path: Path) -> None:
    db_path = tmp_path / "chart_history.db"
    repo = ChartHistoryRepository(db_path=db_path)
    rows = []
    for chart_date in ("2026-05-11", "2026-05-18"):
        for rank in range(1, 4):
            rows.append(
                {
                    "fetch_date": "2026-05-25",
                    "chart_date": chart_date,
                    "source": "bugs",
                    "chart_type": "weekly",
                    "rank": rank,
                    "title": f"Song {chart_date} {rank}",
                    "artist": f"Artist {rank}",
                    "album": "Album",
                    "change_rank": 0,
                }
            )
    repo.insert_chart_rows(rows)

    chart = repo.get_weekly_chart_by_date("2026-05-11", limit=2)
    dates = repo.list_weekly_chart_dates(limit=5)

    assert chart["chart_date"] == "2026-05-11"
    assert [item["rank"] for item in chart["items"]] == [1, 2]
    assert dates == ["2026-05-18", "2026-05-11"]
