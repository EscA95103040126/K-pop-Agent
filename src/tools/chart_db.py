from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from src.config import Settings, settings


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS chart_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fetch_date TEXT,
    chart_date TEXT,
    source TEXT,
    chart_type TEXT,
    rank INTEGER,
    title TEXT,
    artist TEXT,
    album TEXT,
    change_rank INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(chart_date, source, chart_type, rank, title, artist)
);

CREATE INDEX IF NOT EXISTS idx_chart_history_artist_date
ON chart_history(artist, chart_date);
"""


@dataclass
class ChartHistoryRepository:
    db_path: Path = settings.database_path
    mock_data_dir: Path = settings.mock_data_dir

    def init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)

    def insert_chart_rows(self, rows: list[dict[str, Any]]) -> int:
        self.init_db()
        inserted = 0
        with self._connect() as conn:
            for row in rows:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO chart_history (
                        fetch_date, chart_date, source, chart_type, rank,
                        title, artist, album, change_rank
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["fetch_date"],
                        row["chart_date"],
                        row["source"],
                        row["chart_type"],
                        int(row["rank"]),
                        row["title"],
                        row["artist"],
                        row.get("album", ""),
                        int(row.get("change_rank", 0)),
                    ),
                )
                inserted += cursor.rowcount
        return inserted

    def get_artist_trend(self, artist: str, weeks: int = 12) -> dict[str, Any]:
        if not self.db_path.exists():
            return self._load_mock(artist)

        try:
            with self._connect() as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """
                    SELECT chart_date, rank, title, artist, album, change_rank
                    FROM chart_history
                    WHERE lower(artist) LIKE ?
                    ORDER BY chart_date DESC, rank ASC
                    """,
                    (f"%{artist.lower()}%",),
                ).fetchall()
        except sqlite3.Error:
            return self._load_mock(artist)

        if not rows:
            return self._load_mock(artist)

        rows_by_date: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            item = dict(row)
            rows_by_date.setdefault(item["chart_date"], []).append(item)

        chart_dates_desc = sorted(rows_by_date, reverse=True)
        if len(chart_dates_desc) == 1:
            history = sorted(rows_by_date[chart_dates_desc[0]], key=lambda row: row["rank"])
            ranks = [row["rank"] for row in history]
            return {
                "artist": artist,
                "period": "本週",
                "best_rank": min(ranks),
                "avg_rank": round(mean(ranks), 2),
                "weeks_on_chart": 1,
                "trend": "資料不足",
                "history": history,
            }

        selected_dates_desc = chart_dates_desc[:weeks]
        weekly_history_desc = [
            min(rows_by_date[chart_date], key=lambda row: row["rank"])
            for chart_date in selected_dates_desc
        ]
        history_asc = list(reversed(weekly_history_desc))
        ranks = [row["rank"] for row in weekly_history_desc]
        return {
            "artist": artist,
            "period": f"{history_asc[0]['chart_date']} ～ {history_asc[-1]['chart_date']}",
            "best_rank": min(ranks),
            "avg_rank": round(mean(ranks), 2),
            "weeks_on_chart": len(weekly_history_desc),
            "trend": self._calculate_trend(history_asc),
            "history": weekly_history_desc,
        }

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _calculate_trend(self, history_asc: list[dict[str, Any]]) -> str:
        if len(history_asc) < 2:
            return "資料不足"
        first_avg = mean(row["rank"] for row in history_asc[: max(1, len(history_asc) // 3)])
        last_avg = mean(row["rank"] for row in history_asc[-max(1, len(history_asc) // 3) :])
        if last_avg <= first_avg - 1:
            return "上升"
        if last_avg >= first_avg + 1:
            return "下降"
        return "持平"

    def _load_mock(self, artist: str) -> dict[str, Any]:
        file_name = f"chart_{artist.lower().replace(' ', '_')}.json"
        mock_path = self.mock_data_dir / file_name
        if not mock_path.exists():
            return {
                "artist": artist,
                "period": "資料不足",
                "best_rank": "N/A",
                "avg_rank": "N/A",
                "weeks_on_chart": 0,
                "trend": "資料不足",
                "history": [],
            }
        return json.loads(mock_path.read_text(encoding="utf-8"))

    def get_latest_weekly_chart(self, limit: int = 10) -> dict[str, Any]:
        if not self.db_path.exists():
            return {"chart_date": "", "source": "bugs", "items": []}

        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            chart_date_row = conn.execute(
                """
                SELECT chart_date
                FROM chart_history
                WHERE source = 'bugs' AND chart_type = 'weekly'
                GROUP BY chart_date
                HAVING COUNT(*) >= ?
                ORDER BY chart_date DESC
                LIMIT 1
                """,
                (limit,),
            ).fetchone()

            if not chart_date_row:
                chart_date_row = conn.execute(
                    """
                    SELECT chart_date
                    FROM chart_history
                    WHERE source = 'bugs' AND chart_type = 'weekly'
                    GROUP BY chart_date
                    ORDER BY COUNT(*) DESC, chart_date DESC
                    LIMIT 1
                    """
                ).fetchone()

            if not chart_date_row:
                return {"chart_date": "", "source": "bugs", "items": []}

            rows = conn.execute(
                """
                SELECT rank, title, artist, album, change_rank
                FROM chart_history
                WHERE source = 'bugs' AND chart_type = 'weekly' AND chart_date = ?
                ORDER BY rank ASC
                LIMIT ?
                """,
                (chart_date_row["chart_date"], limit),
            ).fetchall()

        return {
            "chart_date": chart_date_row["chart_date"],
            "source": "bugs",
            "items": [dict(row) for row in rows],
        }

    def get_weekly_chart_by_date(self, chart_date: str, limit: int = 10) -> dict[str, Any]:
        if not self.db_path.exists():
            return {"chart_date": chart_date, "source": "bugs", "items": []}

        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT rank, title, artist, album, change_rank
                FROM chart_history
                WHERE source = 'bugs' AND chart_type = 'weekly' AND chart_date = ?
                ORDER BY rank ASC
                LIMIT ?
                """,
                (chart_date, limit),
            ).fetchall()

        return {
            "chart_date": chart_date,
            "source": "bugs",
            "items": [dict(row) for row in rows],
        }

    def list_weekly_chart_dates(self, limit: int = 8, min_items: int = 1) -> list[str]:
        if not self.db_path.exists():
            return []

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT chart_date
                FROM chart_history
                WHERE source = 'bugs' AND chart_type = 'weekly'
                GROUP BY chart_date
                HAVING COUNT(*) >= ?
                ORDER BY chart_date DESC
                LIMIT ?
                """,
                (min_items, limit),
            ).fetchall()

        return [str(row[0]) for row in rows]


def get_artist_chart_trend(artist: str, weeks: int = 12) -> dict[str, Any]:
    return ChartHistoryRepository().get_artist_trend(artist=artist, weeks=weeks)
