from __future__ import annotations

import csv
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


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("YOUTUBE_API_KEY is required in .env")

    all_rows: list[dict[str, str]] = []
    counts: dict[str, int] = {}

    for index, artist in enumerate(ARTISTS):
        try:
            rows = fetch_artist_comments(artist=artist, api_key=api_key, target_count=20)
            counts[artist] = len(rows)
            all_rows.extend(rows)
            if len(rows) < 20:
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
    video = search_first_video(artist=artist, api_key=api_key)
    if not video:
        return []
    comments = fetch_korean_comments(
        video_id=video["video_id"],
        api_key=api_key,
        target_count=target_count,
    )
    return [
        {
            "artist": artist,
            "song": video["title"],
            "comment": comment,
        }
        for comment in comments[:target_count]
    ]


def search_first_video(artist: str, api_key: str) -> dict[str, str] | None:
    params = {
        "part": "snippet",
        "q": f"{artist} 뮤직비디오 OR MV OR 신곡",
        "type": "video",
        "maxResults": 1,
        "order": "relevance",
        "key": api_key,
    }
    payload = _youtube_get(YOUTUBE_SEARCH_URL, params=params)
    items = payload.get("items", [])
    if not items:
        return None
    item = items[0]
    video_id = item.get("id", {}).get("videoId")
    if not video_id:
        return None
    return {
        "video_id": video_id,
        "title": _clean_text(item.get("snippet", {}).get("title", "")),
    }


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
    return re.sub(r"\s+", " ", value).strip()


if __name__ == "__main__":
    main()
