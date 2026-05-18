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
        "뉴진스": "NewJeans",
        "new jeans": "NewJeans",
    }
    compact = WHITESPACE_RE.sub(" ", value).strip()
    return aliases.get(compact.lower(), compact)
