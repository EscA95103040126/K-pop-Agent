from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import settings
from src.tools.kpop_radar import KpopRadarRepository


PLAY_ZONE_DIR = settings.base_dir / "data" / "play_zone"
BIAS_RADAR_MEMBERS_PATH = PLAY_ZONE_DIR / "bias_radar_members.csv"
DAILY_MV_PATH = PLAY_ZONE_DIR / "daily_mv.csv"
DAILY_FANCAM_PATH = PLAY_ZONE_DIR / "daily_fancam.csv"
PHOTO_CARDS_PATH = PLAY_ZONE_DIR / "photo_cards.csv"

MANUAL_ARTIST_GENDERS = {
    "2pm": "boy_group",
    "alldayproject": "mixed",
    "astro": "boy_group",
    "boynextdoor": "boy_group",
    "bss": "boy_group",
    "cortis": "boy_group",
    "cravity": "boy_group",
    "day6": "boy_group",
    "gotthebeat": "girl_group",
    "got7": "boy_group",
    "ioi": "girl_group",
    "idle": "girl_group",
    "itzy": "girl_group",
    "izone": "girl_group",
    "monstax": "boy_group",
    "nct127": "boy_group",
    "nctdojaejung": "boy_group",
    "nctdream": "boy_group",
    "nctu": "boy_group",
    "nctwish": "boy_group",
    "nexz": "boy_group",
    "redvelvetxaespa": "girl_group",
    "riize": "boy_group",
    "superjunior": "boy_group",
    "treasure": "boy_group",
    "triples": "girl_group",
    "tws": "boy_group",
    "verivery": "boy_group",
    "zerobaseone": "boy_group",
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import Play Zone CSV content into Supabase kpop_items."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and print counts without writing to Supabase.",
    )
    args = parser.parse_args()

    items = build_kpop_items()
    counts = _count_items(items)
    if args.dry_run:
        print(json.dumps({"dry_run": True, "counts": counts}, ensure_ascii=False))
        return

    repo = KpopRadarRepository(settings)
    result = repo.sync_kpop_items(items)
    print(json.dumps({"counts": counts, "sync": result}, ensure_ascii=False))


def build_kpop_items() -> list[dict[str, Any]]:
    artist_gender, member_profiles = _load_bias_radar_lookup()
    return [
        *_build_daily_mv_items(artist_gender),
        *_build_daily_fancam_items(artist_gender),
        *_build_photo_card_items(member_profiles),
    ]


def _build_daily_mv_items(artist_gender: dict[str, str]) -> list[dict[str, Any]]:
    items = []
    for row in _read_csv_rows(DAILY_MV_PATH):
        artist = row.get("artist", "").strip()
        title = row.get("title", "").strip()
        url = row.get("url", "").strip()
        if not (artist and title and url):
            continue
        items.append(
            {
                "item_type": "mv",
                "gender_category": _artist_gender_category(artist, artist_gender),
                "artist": artist,
                "member": None,
                "title": title,
                "url": url,
                "thumbnail_url": None,
                "source": "data/play_zone/daily_mv.csv",
            }
        )
    return items


def _build_daily_fancam_items(artist_gender: dict[str, str]) -> list[dict[str, Any]]:
    items = []
    for row in _read_csv_rows(DAILY_FANCAM_PATH):
        artist = row.get("artist", "").strip()
        member = row.get("member", "").strip()
        title = row.get("title", "").strip()
        url = row.get("url", "").strip()
        if not (artist and title and url):
            continue
        items.append(
            {
                "item_type": "fancam",
                "gender_category": _artist_gender_category(artist, artist_gender),
                "artist": artist,
                "member": member or None,
                "title": title,
                "url": url,
                "thumbnail_url": None,
                "source": "data/play_zone/daily_fancam.csv",
            }
        )
    return items


def _build_photo_card_items(
    member_profiles: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    items = []
    for row in _read_csv_rows(PHOTO_CARDS_PATH):
        raw_name = row.get("artist", "").strip()
        card_type = row.get("type", "").strip()
        url = row.get("url", "").strip()
        if not (raw_name and card_type and url):
            continue
        profile = member_profiles.get(_lookup_key(raw_name), {})
        member = profile.get("member") or raw_name
        artist = profile.get("artist") or raw_name
        items.append(
            {
                "item_type": "photo",
                "gender_category": profile.get("gender_category") or "mixed",
                "artist": artist,
                "member": member,
                "title": f"{_display_name(member)} {card_type}",
                "url": url,
                "thumbnail_url": None,
                "source": "data/play_zone/photo_cards.csv",
            }
        )
    return items


def _load_bias_radar_lookup() -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    artist_gender: dict[str, str] = dict(MANUAL_ARTIST_GENDERS)
    member_profiles: dict[str, dict[str, str]] = {}
    for row in _read_csv_rows(BIAS_RADAR_MEMBERS_PATH):
        artist = row.get("artist", "").strip()
        member = row.get("member", "").strip()
        group_type = row.get("group_type", "").strip()
        if group_type not in {"girl_group", "boy_group"}:
            continue
        if artist:
            artist_gender.setdefault(_lookup_key(artist), group_type)
        if member:
            member_profiles[_lookup_key(member)] = {
                "artist": artist,
                "member": _display_name(member),
                "gender_category": group_type,
            }
    return artist_gender, member_profiles


def _artist_gender_category(artist: str, artist_gender: dict[str, str]) -> str:
    return artist_gender.get(_lookup_key(artist), "mixed")


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def _lookup_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).casefold()
    without_marks = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", "", without_marks)


def _display_name(value: str) -> str:
    cleaned = value.strip()
    special_names = {"RM", "V", "DK", "D.O.", "I.N", "THE8", "S.COUPS"}
    if cleaned.upper() in special_names:
        return cleaned.upper()
    if cleaned and cleaned == cleaned.upper():
        return cleaned.title()
    return cleaned


def _count_items(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"mv": 0, "fancam": 0, "photo": 0}
    for item in items:
        counts[str(item["item_type"])] += 1
    return counts


if __name__ == "__main__":
    main()
