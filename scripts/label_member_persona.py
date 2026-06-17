"""Fill the `persona` column in bias_radar_members.csv using Gemini.

Persona is a subjective archetype that benefits from factual context, so we let
Gemini assign 1-3 labels per member based on the member's existing tags plus the
member profile text from the CSV source_url when available. The allowed label set
is imported from app.py so there is a single source of truth shared with the
recommender.

Usage:
    python scripts/label_member_persona.py            # label rows with empty persona
    python scripts/label_member_persona.py --force     # relabel every row
    python scripts/label_member_persona.py --limit 10  # only the first N rows
    python scripts/label_member_persona.py --dry-run   # print, do not write

Requires GEMINI_API_KEY in the environment / .env.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import sys
import time
from pathlib import Path

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app import AI_CURATOR_PROFILE_VOCAB
from src.agent import GEMINI_API_URL, GEMINI_REQUEST_TIMEOUT_SECONDS
from src.config import settings


MEMBERS_CSV = PROJECT_ROOT / "data" / "play_zone" / "bias_radar_members.csv"
PERSONA_LABELS = tuple(AI_CURATOR_PROFILE_VOCAB["persona"])
SOURCE_CACHE_DIR = Path("/private/tmp/kpop-agent-persona-source-cache")
MAX_PERSONA_PER_MEMBER = 3
REQUEST_PAUSE_SECONDS = 2.0
MAX_API_ATTEMPTS = 4
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
RETRY_BASE_SECONDS = 8.0
SOURCE_REQUEST_PAUSE_SECONDS = 1.0
SOURCE_CONTEXT_CHAR_LIMIT = 4500
source_text_cache: dict[str, str] = {}
PERSONA_ALIASES = {
    "弟系": "忙內",
    "忙内": "忙內",
    "邻家": "鄰家",
    "元气": "元氣",
    "痞帅": "痞帥",
    "知性": "知性",
    "治愈": "治癒",
    "疗愈": "治癒",
    "综艺担": "綜藝擔",
    "综艺担当": "綜藝擔",
    "性感": "性感",
    "忧郁感": "憂鬱感",
    "忧郁": "憂鬱感",
    "阳光": "陽光",
    "王子": "王子",
    "野性": "野性",
}

PERSONA_GUIDE = {
    "姐系": "成熟、御姐、氣場強、大人感、姐姐角色",
    "忙內": "忙內、奶狗、活潑可愛、弟弟角色",
    "鄰家": "親和、清純、好親近、鄰家感",
    "氛圍": "高級感、神秘、有距離感、氛圍擔",
    "元氣": "開朗、活力、能量充沛",
    "痞帥": "痞痞壞壞、玩世不恭、壞男孩魅力",
    "知性": "知性、有才氣、文藝書卷氣",
    "治癒": "溫柔、療癒、暖系、給人安全感",
    "綜藝擔": "搞笑、反應快、綜藝感強",
    "性感": "性感、魅惑、有成熟魅力",
    "憂鬱感": "憂鬱、厭世、陰鬱神秘",
    "陽光": "陽光、開朗大男孩或大女孩、活力外放",
    "王子": "王子感、貴氣、優雅、端正、浪漫紳士感",
    "野性": "野性、原始能量、未馴服感、強烈爆發力",
}


def main() -> None:
    args = _parse_args()
    if settings.use_gemini_mock:
        raise SystemExit("GEMINI_API_KEY is not set; cannot label personas.")

    fieldnames, rows = _read_members()
    if "persona" not in fieldnames:
        raise SystemExit("bias_radar_members.csv has no 'persona' column.")

    targets = [
        row for row in rows
        if args.force or not (row.get("persona") or "").strip()
    ]
    if args.limit is not None:
        targets = targets[: args.limit]

    print(f"Labeling {len(targets)} / {len(rows)} members...", flush=True)
    counts = {label: 0 for label in PERSONA_LABELS}
    for index, row in enumerate(targets, start=1):
        labels = _label_member(row)
        row["persona"] = "|".join(labels)
        for label in labels:
            counts[label] += 1
        print(
            f"{index}/{len(targets)} {row.get('artist', '')} {row.get('member', '')}: "
            f"{row['persona'] or '(無)'}",
            flush=True,
        )
        time.sleep(REQUEST_PAUSE_SECONDS)

    if args.dry_run:
        print("\n[dry-run] not writing file.")
    else:
        _write_members(fieldnames, rows)
        print(f"\nWrote {MEMBERS_CSV}")
    print("Persona distribution:")
    for label in PERSONA_LABELS:
        print(f"  {label}: {counts[label]}")


def _label_member(row: dict[str, str]) -> list[str]:
    prompt = _build_prompt(row)
    last_error: Exception | None = None
    for attempt in range(1, MAX_API_ATTEMPTS + 1):
        try:
            response = requests.post(
                GEMINI_API_URL.format(model=settings.gemini_model),
                params={"key": settings.gemini_api_key},
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.0,
                        "maxOutputTokens": 80,
                        "responseMimeType": "application/json",
                    },
                },
                timeout=GEMINI_REQUEST_TIMEOUT_SECONDS,
            )
            if (
                response.status_code in RETRYABLE_STATUS_CODES
                and attempt < MAX_API_ATTEMPTS
            ):
                wait_seconds = _retry_wait_seconds(response, attempt)
                print(
                    f"  ! {response.status_code}; retrying in {wait_seconds:.1f}s",
                    flush=True,
                )
                time.sleep(wait_seconds)
                continue
            response.raise_for_status()
            text = response.json()["candidates"][0]["content"]["parts"][0].get("text", "")
            return _parse_labels(text)
        except Exception as error:  # noqa: BLE001 - keep going on per-row failures
            last_error = error
            if attempt < MAX_API_ATTEMPTS:
                wait_seconds = RETRY_BASE_SECONDS * attempt
                print(f"  ! failed ({error}); retrying in {wait_seconds:.1f}s", flush=True)
                time.sleep(wait_seconds)
                continue
            break
    print(f"  ! failed ({last_error}); leaving empty", flush=True)
    return []


def _retry_wait_seconds(response: requests.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return max(float(retry_after), RETRY_BASE_SECONDS)
        except ValueError:
            pass
    return RETRY_BASE_SECONDS * attempt


def _build_prompt(row: dict[str, str]) -> str:
    guide = "\n".join(f"- {label}：{desc}" for label, desc in PERSONA_GUIDE.items())
    source_text = _source_evidence_for_row(row)
    source_block = source_text or "抓不到或無可用文字，請退回只依現有 tags 判斷。"
    return f"""你是 K-pop 成員人設標註員。請依下方成員資料，從固定標籤中選出最貼切的 1-3 個 persona。
規則：
- 只能使用這些標籤：{", ".join(PERSONA_LABELS)}。
- 通常選 1-2 個；第 3 個只有在真實資料或既有 tags 有明確佐證時才加，避免為了湊數而稀釋精準度。
- 最相關的放第一個；若真的難判斷就選 1 個。
- 先看真實資料佐證，再用現有 tags 補足語感；不要只因為既有 tags 有「霸氣」就自動標姐系。
- 若性別組是 male，成熟、強勢、距離感請優先歸到「氛圍」，不要用「姐系」。
- 若真實資料提到綜藝、主持、variety、funny、mood maker、reaction、comedian，優先考慮「綜藝擔」。
- 若真實資料呈現溫柔、照顧人、healing、comfort、warm，優先考慮「治癒」。
- 若真實資料呈現聰明、學業、創作、作詞作曲、藝術、樂器、reading/writing，優先考慮「知性」。
- 「性感」需有舞台魅惑、sensual/sexy、成熟吸引力等明確佐證；不要只因為氣場強就標。
- 「王子」需有優雅、貴氣、端正、紳士、浪漫感等明確佐證；「野性」需有未馴服、爆發力、原始舞台能量等明確佐證。
- 只輸出 JSON 陣列，例如 ["姐系"]，不要任何說明。

標籤說明：
{guide}

成員資料：
- 團體：{row.get('artist', '')}
- 成員：{row.get('member', '')}
- 性別組：{row.get('gender_group', '')}
- 外型：{row.get('appearance', '')}
- 定位：{row.get('position', '')}
- 氣質：{row.get('vibe', '')}
- 關係感：{row.get('relationship', '')}

真實資料摘錄（來自 source_url，已清洗截斷）：
{source_block}"""


def _source_evidence_for_row(row: dict[str, str]) -> str:
    source_url = row.get("source_url", "").strip()
    if not source_url:
        return ""
    source_text = _fetch_source_text(source_url)
    if not source_text:
        return ""
    return _member_source_excerpt(source_text, row)


def _fetch_source_text(source_url: str) -> str:
    if source_url in source_text_cache:
        return source_text_cache[source_url]
    cache_path = _source_cache_path(source_url)
    if cache_path.exists():
        try:
            cached = cache_path.read_text(encoding="utf-8")
        except OSError:
            cached = ""
        source_text_cache[source_url] = cached
        return cached
    try:
        response = requests.get(
            source_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
                )
            },
            timeout=GEMINI_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        cleaned = _clean_source_html(response.text)
    except Exception as error:  # noqa: BLE001 - source evidence is optional
        print(f"  ! source fetch failed ({source_url}: {error}); using tags only", flush=True)
        cleaned = ""
    try:
        SOURCE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(cleaned, encoding="utf-8")
    except OSError:
        pass
    source_text_cache[source_url] = cleaned
    time.sleep(SOURCE_REQUEST_PAUSE_SECONDS)
    return cleaned


def _source_cache_path(source_url: str) -> Path:
    digest = hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:24]
    return SOURCE_CACHE_DIR / f"{digest}.txt"


def _clean_source_html(raw_html: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript|svg|iframe).*?</\1>", " ", raw_html)
    text = re.sub(r"(?is)<!--.*?-->", " ", text)
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</(p|div|li|h[1-6]|tr|section|article)>", "\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _member_source_excerpt(source_text: str, row: dict[str, str]) -> str:
    names = _member_lookup_names(row)
    lowered = source_text.casefold()
    positions = [
        lowered.find(name.casefold())
        for name in names
        if name and lowered.find(name.casefold()) != -1
    ]
    if not positions:
        return source_text[:SOURCE_CONTEXT_CHAR_LIMIT]
    excerpts = []
    for position in sorted(set(positions))[:3]:
        start = max(0, position - 700)
        end = min(len(source_text), position + 2300)
        excerpts.append(source_text[start:end].strip())
    return "\n---\n".join(excerpts)[:SOURCE_CONTEXT_CHAR_LIMIT]


def _member_lookup_names(row: dict[str, str]) -> list[str]:
    member = row.get("member", "").strip()
    names = [member, member.title(), member.replace("-", " "), member.replace(".", "")]
    if "HUH YUN JIN" in member:
        names.extend(["Yunjin", "Huh Yunjin", "HUH YUNJIN"])
    if member == "J-HOPE":
        names.extend(["J-Hope", "Jhope", "Hobi"])
    if member == "I.N":
        names.append("I.N")
    if member == "THE8":
        names.extend(["THE 8", "The8", "Minghao"])
    return list(dict.fromkeys(name for name in names if name))


def _parse_labels(text: str) -> list[str]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        raw = json.loads(cleaned[start : end + 1])
    except (ValueError, TypeError):
        return []
    allowed = set(PERSONA_LABELS)
    seen: list[str] = []
    for value in raw if isinstance(raw, list) else []:
        label = _normalize_persona_label(value)
        if label in allowed and label not in seen:
            seen.append(label)
        if len(seen) >= MAX_PERSONA_PER_MEMBER:
            break
    return seen


def _normalize_persona_label(value: object) -> str:
    if not isinstance(value, str):
        return ""
    label = value.strip()
    return PERSONA_ALIASES.get(label, label)


def _read_members() -> tuple[list[str], list[dict[str, str]]]:
    with MEMBERS_CSV.open(encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        return list(reader.fieldnames or []), list(reader)


def _write_members(fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with MEMBERS_CSV.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="relabel rows that already have a persona")
    parser.add_argument("--limit", type=int, default=None, help="only process the first N target rows")
    parser.add_argument("--dry-run", action="store_true", help="print results without writing the file")
    return parser.parse_args()


if __name__ == "__main__":
    main()
