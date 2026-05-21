from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent import KpopAnalysisAgent, WEEKLY_CHART_CACHE_PATH
from src.tools.bugs_chart import fetch_bugs_weekly_chart, save_bugs_weekly_chart


def main() -> None:
    try:
        rows = fetch_bugs_weekly_chart()
        inserted = save_bugs_weekly_chart(rows=rows)
        print(f"Fetched {len(rows)} Bugs weekly chart rows.")
        print(f"Inserted {inserted} new rows into chart_history.")
    except Exception as exc:
        print(f"Bugs weekly chart fetch failed; using existing SQLite data: {exc}")

    payload = KpopAnalysisAgent().preload_weekly_chart_cache()
    items = payload.get("chart", {}).get("items", [])
    print(f"Weekly chart cache written: {WEEKLY_CHART_CACHE_PATH}")
    print(f"cached_at={payload['cached_at']}")
    print(f"items={len(items)}")
    if items:
        first = items[0]
        print(f"Top row: #{first['rank']} {first['title']} - {first['artist']}")


if __name__ == "__main__":
    main()
