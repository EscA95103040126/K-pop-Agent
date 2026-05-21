from __future__ import annotations

import csv
import signal
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.tools.sentiment import classify_comment


COMMENTS_CSV = PROJECT_ROOT / "data" / "sample_comments.csv"
FIELDNAMES = ["artist", "song", "comment", "sentiment"]
VALID_SENTIMENTS = {"positive", "neutral", "negative"}
CLASSIFY_TIMEOUT_SECONDS = 15


def main() -> None:
    rows = _read_comments()
    counts = {"positive": 0, "neutral": 0, "negative": 0}

    for index, row in enumerate(rows, start=1):
        try:
            sentiment = _classify_with_timeout(row.get("comment"))
        except Exception:
            sentiment = "neutral"
        if sentiment not in VALID_SENTIMENTS:
            sentiment = "neutral"

        row["sentiment"] = sentiment
        counts[sentiment] += 1
        print(f"{index}/{len(rows)} {row.get('artist', '')}: {sentiment}", flush=True)
        time.sleep(0.3)

    _write_comments(rows)
    print(f"Wrote labeled comments to {COMMENTS_CSV}")
    print("Sentiment distribution:")
    for label in ["positive", "neutral", "negative"]:
        print(f"{label}: {counts[label]}")


def _classify_with_timeout(comment: str | None) -> str:
    def _handle_timeout(signum, frame):
        raise TimeoutError("Gemini sentiment classification timed out")

    previous_handler = signal.signal(signal.SIGALRM, _handle_timeout)
    signal.setitimer(signal.ITIMER_REAL, CLASSIFY_TIMEOUT_SECONDS)
    try:
        return classify_comment(comment)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def _read_comments() -> list[dict[str, str]]:
    with COMMENTS_CSV.open(encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        missing = [name for name in FIELDNAMES[:3] if name not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"Missing required columns: {', '.join(missing)}")
        return [
            {
                "artist": row.get("artist", ""),
                "song": row.get("song", ""),
                "comment": row.get("comment", ""),
            }
            for row in reader
        ]


def _write_comments(rows: list[dict[str, str]]) -> None:
    with COMMENTS_CSV.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
