from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.fetch_youtube_comments import fetch_artist_comments
from src.agent import DEMO_ARTISTS
from src.config import settings
from src.tools.absa import (
    ABSA_CACHE_DIR,
    KcElectraSentimentAnalyzer,
    KeywordSentimentAnalyzer,
    build_absa_payload,
    load_cached_or_sample_comments,
    write_absa_payload,
    write_absa_summary_csv,
)
from src.tools.naver_news import NaverNewsClient


DEFAULT_COMMENTS_PER_ARTIST = 50
SUMMARY_CSV = ABSA_CACHE_DIR / "summary.csv"


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    args = _parse_args()
    artists = tuple(args.artists or DEMO_ARTISTS)
    cache_dir = Path(args.output_dir) if args.output_dir else ABSA_CACHE_DIR
    analyzer = _build_analyzer(use_model=not args.no_model, model_name=args.model_name)
    news_client = NaverNewsClient(settings)
    youtube_api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    payloads = []

    for index, artist in enumerate(artists):
        news = news_client.search(artist=artist, display=args.news_count)
        comments = _collect_youtube_comments(
            artist=artist,
            api_key=youtube_api_key,
            target_count=args.comments_per_artist,
            use_api=not args.use_sample_comments,
        )
        payload = build_absa_payload(
            artist=artist,
            news=news,
            comments=comments,
            analyzer=analyzer,
        )
        output_path = write_absa_payload(payload, cache_dir=cache_dir)
        payloads.append(payload)
        print(
            f"OK {artist}: {output_path} "
            f"(news={len(news)}, comments={len(comments)}, backend={payload['sources']['model']['backend']})"
        )
        if index < len(artists) - 1:
            time.sleep(args.delay_seconds)

    summary_path = cache_dir / SUMMARY_CSV.name
    write_absa_summary_csv(payloads, output_path=summary_path)
    print(f"Wrote ABSA summary CSV to {summary_path}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build offline ABSA cache for supported K-pop artists.",
    )
    parser.add_argument(
        "--artists",
        nargs="+",
        help="Artist names to process. Defaults to all supported demo artists.",
    )
    parser.add_argument(
        "--comments-per-artist",
        type=int,
        default=DEFAULT_COMMENTS_PER_ARTIST,
        help="Target Korean YouTube comments per artist when YOUTUBE_API_KEY is available.",
    )
    parser.add_argument(
        "--news-count",
        type=int,
        default=10,
        help="Naver News items per artist.",
    )
    parser.add_argument(
        "--model-name",
        default=os.getenv("ABSA_MODEL_NAME"),
        help="KcELECTRA sentiment/ABSA model name. Defaults to ABSA_MODEL_NAME or project default.",
    )
    parser.add_argument(
        "--no-model",
        action="store_true",
        help="Skip Transformers/KcELECTRA and use keyword fallback for cache generation.",
    )
    parser.add_argument(
        "--use-sample-comments",
        action="store_true",
        help="Use data/sample_comments.csv instead of YouTube API.",
    )
    parser.add_argument(
        "--output-dir",
        help="Directory for data/cache/absa JSON files.",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=1.0,
        help="Delay between artists to reduce API pressure.",
    )
    return parser.parse_args()


def _build_analyzer(use_model: bool, model_name: str | None):
    if not use_model:
        return KeywordSentimentAnalyzer()
    try:
        return KcElectraSentimentAnalyzer(model_name=model_name)
    except Exception as exc:
        print(f"WARNING KcELECTRA backend unavailable; using keyword fallback: {exc}")
        return KeywordSentimentAnalyzer()


def _collect_youtube_comments(
    artist: str,
    api_key: str,
    target_count: int,
    use_api: bool,
) -> list[dict[str, str]]:
    if use_api and api_key:
        rows = fetch_artist_comments(
            artist=artist,
            api_key=api_key,
            target_count=target_count,
        )
        if rows:
            return rows
        print(f"WARNING {artist}: YouTube API returned no Korean comments; using sample CSV.")
    return load_cached_or_sample_comments(artist)


if __name__ == "__main__":
    main()
