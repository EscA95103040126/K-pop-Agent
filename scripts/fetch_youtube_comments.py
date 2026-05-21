from __future__ import annotations

import csv
import html
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_CSV = PROJECT_ROOT / "data" / "sample_comments.csv"
ARTISTS = (
    "aespa",
    "IVE",
    "BABYMONSTER",
    "NMIXX",
    "ILLIT",
    "NCT",
    "ZEROBASEONE",
    "TXT",
    "ENHYPEN",
    "BOYNEXTDOOR",
)
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_COMMENTS_URL = "https://www.googleapis.com/youtube/v3/commentThreads"
HANGUL_RE = re.compile(r"[가-힣]")
SEARCH_RESULTS_PER_ARTIST = 5
COMMENTS_PER_ARTIST = 20


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("YOUTUBE_API_KEY is required in .env")

    all_rows: list[dict[str, str]] = []
    counts: dict[str, int] = {}

    for index, artist in enumerate(ARTISTS):
        try:
            rows = fetch_artist_comments(
                artist=artist,
                api_key=api_key,
                target_count=COMMENTS_PER_ARTIST,
            )
            counts[artist] = len(rows)
            all_rows.extend(rows)
            if len(rows) < COMMENTS_PER_ARTIST:
                print(f"WARNING {artist}: only fetched {len(rows)} Korean comments.")
            else:
                print(f"OK {artist}: fetched {len(rows)} Korean comments.")
        except Exception as exc:
            counts[artist] = 0
            print(f"FAILED {artist}: {exc}")

        if index < len(ARTISTS) - 1:
            time.sleep(1)

    write_comments_csv(all_rows)
    print(f"Wrote {len(all_rows)} comments to {OUTPUT_CSV}")
    for artist in ARTISTS:
        print(f"{artist}: {counts.get(artist, 0)}")


def fetch_artist_comments(artist: str, api_key: str, target_count: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen_comments: set[str] = set()

    for video in search_videos(artist=artist, api_key=api_key):
        comments = fetch_korean_comments(
            video_id=video["video_id"],
            api_key=api_key,
            target_count=target_count - len(rows),
        )
        for comment in comments:
            if comment in seen_comments:
                continue
            seen_comments.add(comment)
            rows.append(
                {
                    "artist": artist,
                    "song": video["title"],
                    "comment": comment,
                }
            )
            if len(rows) >= target_count:
                return rows
        time.sleep(0.2)

    return rows


def search_videos(artist: str, api_key: str) -> list[dict[str, str]]:
    params = {
        "part": "snippet",
        "q": f"{artist} official MV OR stage OR comeback",
        "type": "video",
        "maxResults": SEARCH_RESULTS_PER_ARTIST,
        "order": "relevance",
        "relevanceLanguage": "ko",
        "key": api_key,
    }
    payload = _youtube_get(YOUTUBE_SEARCH_URL, params=params)
    videos: list[dict[str, str]] = []
    seen_video_ids: set[str] = set()
    for item in payload.get("items", []):
        video_id = item.get("id", {}).get("videoId")
        if not video_id or video_id in seen_video_ids:
            continue
        seen_video_ids.add(video_id)
        videos.append(
            {
                "video_id": video_id,
                "title": _clean_text(item.get("snippet", {}).get("title", "")),
            }
        )
    return videos


def fetch_korean_comments(video_id: str, api_key: str, target_count: int) -> list[str]:
    comments: list[str] = []
    page_token = ""

    while len(comments) < target_count:
        params = {
            "part": "snippet",
            "videoId": video_id,
            "maxResults": 100,
            "textFormat": "plainText",
            "order": "relevance",
            "key": api_key,
        }
        if page_token:
            params["pageToken"] = page_token

        payload = _youtube_get(YOUTUBE_COMMENTS_URL, params=params)
        for item in payload.get("items", []):
            text = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {}).get("textDisplay", "")
            cleaned = _clean_text(text)
            if cleaned and HANGUL_RE.search(cleaned):
                comments.append(cleaned)
                if len(comments) >= target_count:
                    break

        page_token = payload.get("nextPageToken", "")
        if not page_token:
            break

    return comments


def write_comments_csv(rows: list[dict[str, str]]) -> None:
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["artist", "song", "comment"])
        writer.writeheader()
        writer.writerows(rows)


def _youtube_get(url: str, params: dict[str, Any]) -> dict[str, Any]:
    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()
    return response.json()


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


if __name__ == "__main__":
    main()
