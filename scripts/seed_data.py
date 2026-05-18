from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.tools.chart_db import ChartHistoryRepository


CSV_PATH = PROJECT_ROOT / "data" / "seed_chart_data.csv"


def seed(csv_path: Path = CSV_PATH, db_path: Path | None = None) -> int:
    repo = ChartHistoryRepository(db_path=db_path) if db_path else ChartHistoryRepository()
    repo.init_db()

    inserted = 0
    with csv_path.open(encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        with sqlite3.connect(repo.db_path) as conn:
            for row in reader:
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
                        row["album"],
                        int(row["change_rank"]),
                    ),
                )
                inserted += cursor.rowcount
    return inserted


def main() -> None:
    inserted = seed()
    print(f"Seeded {inserted} chart rows into {ChartHistoryRepository().db_path}")


if __name__ == "__main__":
    main()
