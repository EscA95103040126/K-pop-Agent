from __future__ import annotations


LINE_TEXT_LIMIT = 4900


def fit_line_text(text: str, limit: int = LINE_TEXT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    suffix = "\n\n（內容已截斷，請縮小查詢範圍後再試一次。）"
    return text[: limit - len(suffix)].rstrip() + suffix
