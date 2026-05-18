from __future__ import annotations

import csv
from pathlib import Path

from src.config import settings


DEFAULT_COMMENTS_CSV = settings.base_dir / "data" / "sample_comments.csv"
REQUIRED_COLUMNS = ["artist", "song", "comment"]
ARTIST_ALIASES = {
    "new jeans": "newjeans",
}


def load_comments(csv_path: str | None = None) -> list[dict]:
    path = Path(csv_path) if csv_path else DEFAULT_COMMENTS_CSV
    if not path.is_absolute():
        path = settings.base_dir / path

    with path.open(encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != REQUIRED_COLUMNS:
            raise ValueError(f"CSV columns must be: {','.join(REQUIRED_COLUMNS)}")
        return [dict(row) for row in reader]


def get_comments_by_artist(artist_name: str, csv_path: str | None = None) -> list[dict]:
    normalized_artist = _normalize_artist_name(artist_name)
    return [
        row
        for row in load_comments(csv_path)
        if _normalize_artist_name(row["artist"]) == normalized_artist
    ]


def _normalize_artist_name(artist_name: str) -> str:
    normalized = artist_name.strip().casefold()
    return ARTIST_ALIASES.get(normalized, normalized.replace(" ", ""))
