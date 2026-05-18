from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.tools.bugs_chart import fetch_bugs_weekly_chart, save_bugs_weekly_chart


def main() -> None:
    rows = fetch_bugs_weekly_chart()
    inserted = save_bugs_weekly_chart(rows=rows)
    print(f"Fetched {len(rows)} Bugs weekly chart rows.")
    print(f"Inserted {inserted} new rows into chart_history.")
    if rows:
        first = rows[0]
        print(
            "Top row: "
            f"#{first['rank']} {first['title']} - {first['artist']} "
            f"({first['chart_date']})"
        )


if __name__ == "__main__":
    main()
