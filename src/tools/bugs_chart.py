from __future__ import annotations

import re
from datetime import date
from typing import Any

import requests
from bs4 import BeautifulSoup

from src.tools.chart_db import ChartHistoryRepository


BUGS_WEEKLY_CHART_URL = "https://music.bugs.co.kr/chart/track/week/total"
BUGS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}
DATE_RANGE_RE = re.compile(r"(\d{4})\.(\d{2})\.(\d{2})\s*~\s*\d{4}\.\d{2}\.\d{2}")


def fetch_bugs_weekly_chart(limit: int = 100) -> list[dict[str, Any]]:
    response = requests.get(BUGS_WEEKLY_CHART_URL, headers=BUGS_HEADERS, timeout=10)
    response.raise_for_status()
    return parse_bugs_weekly_chart(response.text, limit=limit)


def parse_bugs_weekly_chart(
    html: str,
    limit: int = 100,
    fetch_date: str | None = None,
) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    chart_date = _extract_chart_date(soup)
    fetched_at = fetch_date or date.today().isoformat()

    rows = []
    for row in soup.select("table.byChart tbody tr")[:limit]:
        parsed = _parse_chart_row(row, chart_date=chart_date, fetch_date=fetched_at)
        if parsed:
            rows.append(parsed)
    return rows


def save_bugs_weekly_chart(
    limit: int = 100,
    rows: list[dict[str, Any]] | None = None,
) -> int:
    rows = rows if rows is not None else fetch_bugs_weekly_chart(limit=limit)
    return ChartHistoryRepository().insert_chart_rows(rows)


def fetch_weekly_chart() -> list[dict[str, Any]]:
    return fetch_bugs_weekly_chart()


def _parse_chart_row(row: Any, chart_date: str, fetch_date: str) -> dict[str, Any] | None:
    rank_node = row.select_one("div.ranking strong")
    title_node = row.select_one("p.title a")
    artist_node = row.select_one("p.artist")
    album_node = row.select_one("a.album")

    if not (rank_node and title_node and artist_node):
        return None

    return {
        "fetch_date": fetch_date,
        "chart_date": chart_date,
        "source": "bugs",
        "chart_type": "weekly",
        "rank": int(rank_node.get_text(strip=True)),
        "title": _node_title_or_text(title_node),
        "artist": _artist_text(artist_node),
        "album": _node_title_or_text(album_node) if album_node else "",
        "change_rank": _parse_change_rank(row.select_one("p.change")),
    }


def _extract_chart_date(soup: BeautifulSoup) -> str:
    text = soup.get_text(" ", strip=True)
    match = DATE_RANGE_RE.search(text)
    if not match:
        return date.today().isoformat()
    year, month, day = match.groups()
    return f"{year}-{month}-{day}"


def _parse_change_rank(change_node: Any) -> int:
    if not change_node:
        return 0

    classes = set(change_node.get("class", []))
    number_match = re.search(r"\d+", change_node.get_text(" ", strip=True))
    amount = int(number_match.group(0)) if number_match else 0

    if "up" in classes:
        return amount
    if "down" in classes:
        return -amount
    return 0


def _node_title_or_text(node: Any) -> str:
    title = node.get("title") if node else None
    return (title or node.get_text(" ", strip=True)).strip()


def _artist_text(node: Any) -> str:
    artists = [
        _node_title_or_text(link)
        for link in node.select("a")
        if _node_title_or_text(link)
    ]
    if artists:
        return ", ".join(artists)
    return node.get_text(" ", strip=True)
