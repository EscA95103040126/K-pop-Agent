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
                    ORDER BY chart_date DESC
                    LIMIT ?
                    """,
                    (f"%{artist.lower()}%", weeks),
                ).fetchall()
        except sqlite3.Error:
            return self._load_mock(artist)

        if not rows:
            return self._load_mock(artist)

        history_desc = [dict(row) for row in rows]
        history_asc = list(reversed(history_desc))
        ranks = [row["rank"] for row in history_desc]
        return {
            "artist": artist,
            "period": f"{history_asc[0]['chart_date']} ～ {history_asc[-1]['chart_date']}",
            "best_rank": min(ranks),
            "avg_rank": round(mean(ranks), 2),
            "weeks_on_chart": len(history_desc),
            "trend": self._calculate_trend(history_asc),
            "history": history_desc,
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
            mock_path = self.mock_data_dir / "chart_aespa.json"
        return json.loads(mock_path.read_text(encoding="utf-8"))


def get_artist_chart_trend(artist: str, weeks: int = 12) -> dict[str, Any]:
    return ChartHistoryRepository().get_artist_trend(artist=artist, weeks=weeks)
