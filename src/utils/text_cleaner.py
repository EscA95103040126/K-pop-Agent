from __future__ import annotations

import html
import re


HTML_TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")


def clean_html_text(value: str | None) -> str:
    if not value:
        return ""
    text = html.unescape(value)
    text = HTML_TAG_RE.sub("", text)
    return WHITESPACE_RE.sub(" ", text).strip()


def normalize_artist(value: str) -> str:
    aliases = {
        "에스파": "aespa",
        "아이브": "IVE",
        "베이비몬스터": "BABYMONSTER",
        "baby monster": "BABYMONSTER",
        "엔믹스": "NMIXX",
        "아일릿": "ILLIT",
        "엔시티": "NCT",
        "제로베이스원": "ZEROBASEONE",
        "zero base one": "ZEROBASEONE",
        "zb1": "ZEROBASEONE",
        "투모로우바이투게더": "TXT",
        "tomorrow x together": "TXT",
        "엔하이픈": "ENHYPEN",
        "보이넥스트도어": "BOYNEXTDOOR",
        "boy next door": "BOYNEXTDOOR",
    }
    compact = WHITESPACE_RE.sub(" ", value).strip()
    return aliases.get(compact.lower(), compact)
