from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.tools.bugs_chart import fetch_bugs_weekly_chart, save_bugs_weekly_chart


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch and save Bugs weekly chart rows.")
    parser.add_argument(
        "--chart-date",
        help="Week start date to fetch, e.g. 2026-05-18 or 20260518.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Number of chart rows to fetch.",
    )
    args = parser.parse_args()

    rows = fetch_bugs_weekly_chart(limit=args.limit, chart_date=args.chart_date)
    inserted = save_bugs_weekly_chart(rows=rows)
    print(f"Fetched {len(rows)} Bugs weekly chart rows.")
    print(f"Inserted {inserted} new rows into chart_history.")
    if rows:
        first = rows[0]
        print(f"Chart date: {first['chart_date']}")
        print(
            "Top row: "
            f"#{first['rank']} {first['title']} - {first['artist']} "
            f"({first['chart_date']})"
        )


if __name__ == "__main__":
    main()
