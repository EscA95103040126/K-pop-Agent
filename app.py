from __future__ import annotations

import json
import csv
import logging
import random
import re
import sqlite3
import unicodedata
from collections import OrderedDict
from datetime import date, timedelta
from pathlib import Path
from time import monotonic, time
from typing import Callable
from urllib.parse import parse_qsl, quote

import requests
from flask import Flask, abort, jsonify, request, send_file, send_from_directory

from src.agent import (
    GEMINI_API_URL,
    GEMINI_REQUEST_TIMEOUT_SECONDS,
    KpopAnalysisAgent,
    SUPPORTED_ARTISTS,
)
from src.config import settings
from src.router import ARTIST_PATTERNS, route_message
from src.tools.bugs_chart import fetch_bugs_weekly_chart
from src.tools.kpop_radar import KpopRadarRepository
from src.tools.naver_news import NaverNewsClient
from src.utils.response_formatter import fit_line_text

try:
    from linebot.v3 import WebhookHandler
    from linebot.v3.exceptions import InvalidSignatureError
    from linebot.v3.messaging import (
        ApiClient,
        Configuration,
        FlexContainer,
        FlexMessage,
        MessageAction,
        MessagingApi,
        PostbackAction,
        QuickReply,
        QuickReplyItem,
        ReplyMessageRequest,
        ButtonsTemplate,
        TemplateMessage,
        TextMessage,
    )
    from linebot.v3.webhooks import (
        FollowEvent,
        MessageEvent,
        PostbackEvent,
        TextMessageContent,
    )
except ImportError:  # pragma: no cover - lets local mock mode run without LINE SDK.
    WebhookHandler = None
    InvalidSignatureError = Exception
    ApiClient = None
    Configuration = None
    FlexContainer = None
    FlexMessage = None
    MessageAction = None
    MessagingApi = None
    PostbackAction = None
    QuickReply = None
    QuickReplyItem = None
    ReplyMessageRequest = None
    ButtonsTemplate = None
    TemplateMessage = None
    TextMessage = None
    FollowEvent = None
    MessageEvent = None
    PostbackEvent = None
    TextMessageContent = None


app = Flask(__name__)
agent = KpopAnalysisAgent()
radar_repo = KpopRadarRepository(settings)
logger = logging.getLogger(__name__)
daily_kpop_queues: dict[str, list[dict[str, str]]] = {}
daily_kpop_source_keys: dict[str, tuple[tuple[str, str, str, str], ...]] = {}
photo_card_queue: list[dict[str, str]] = []
photo_card_source_key: tuple[tuple[str, str, str], ...] = ()
member_quiz_queue: list[dict[str, str]] = []
member_quiz_source_key: tuple[tuple[str, str, str, str, str, str], ...] = ()
csv_row_cache: dict[Path, tuple[tuple[int, int], list[dict[str, str]]]] = {}
BIAS_RADAR_TRIGGERS = {"本命雷達測驗", "本命雷達", "測本命"}
BIAS_RADAR_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
bias_radar_sessions: dict[str, dict[str, object]] = {}
ai_curator_reason_contexts: dict[str, dict[str, object] | list[dict[str, str]]] = {}
BIAS_RADAR_SESSION_TTL_SECONDS = 60 * 30
BIAS_RADAR_SESSION_MAX_SIZE = 500
AI_CURATOR_REASON_CONTEXT_TTL_SECONDS = 60 * 30
AI_CURATOR_REASON_CONTEXT_MAX_SIZE = 500
HISTORICAL_WEEKLY_CHART_PREFIX = "歷史週榜:"
PHOTO_CARD_EMPTY_TEXT = "目前還沒有神圖資料，請先補 data/play_zone/photo_cards.csv"
MEMBER_QUIZ_EMPTY_TEXT = (
    "目前還沒有認人測驗題目，請先補 data/play_zone/member_quiz.csv，"
    "並把圖片放到 data/play_zone/member_quiz_images/"
)
PLAY_ZONE_ACCENT_COLOR = "#5D6F66"
PLAY_ZONE_BODY_COLOR = "#F7FAF8"
PLAY_ZONE_SUBTITLE_COLOR = "#EAF4EE"
PLAY_ZONE_TEXT_COLOR = "#3F554A"
PLAY_ZONE_MUTED_TEXT_COLOR = "#4F665B"
KPOP_RADAR_TRIGGERS = {
    "我的口袋",
    "我的 K-pop 口袋",
    "我的K-pop口袋",
    "K-pop 口袋",
    "K-pop口袋",
    "KPOP口袋",
    "口袋",
    "我的 K-pop 雷達",
    "我的K-pop雷達",
    "K-pop 雷達",
    "K-pop雷達",
    "KPOP雷達",
    "我的收藏",
    "收藏庫",
}
KPOP_RADAR_ACTIONS = {
    "open_radar",
    "view_saved",
    "open_pref",
    "set_pref",
    "save_item",
}
KPOP_RADAR_ACCENT_COLOR = "#B76E61"
KPOP_RADAR_BODY_COLOR = "#FFF6F0"
KPOP_RADAR_SUBTITLE_COLOR = "#FFE9DF"
KPOP_RADAR_TEXT_COLOR = "#5C3F37"
KPOP_RADAR_MUTED_TEXT_COLOR = "#7A6258"
KPOP_RADAR_ITEM_LABELS = {
    "mv": ("🎬", "MV", "個"),
    "fancam": ("🎥", "直拍", "個"),
    "photo": ("🖼️", "照片", "張"),
}
KPOP_RADAR_GENDER_LABELS = {
    "girl_group": "女團",
    "boy_group": "男團",
    "all": "都可以",
}
AI_CURATOR_ENTRY_TRIGGERS = {
    "我的雷達",
    "雷達",
    "ai入坑",
    "ai入坑指南",
    "入坑指南",
    "k-pop雷達",
    "kpop雷達",
    "ai策展人",
    "aik-pop策展人",
    "aikpop策展人",
    "ai k-pop策展人",
    "k-pop策展人",
    "kpop策展人",
    "策展人",
}
MEMBER_QUIZ_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
FAN_ATTRIBUTE_TYPES = {
    "group": {
        "name": "團飯",
        "tagline": "你喜歡的是整個團的化學反應。",
        "description": "你會看見每位成員在團體裡的角色，也享受舞台、團綜、互動與作品概念拼在一起的完整感。",
        "tip": "適合玩法：團體雷達、舞台名場面整理、全員魅力圖鑑。",
    },
    "solo": {
        "name": "唯飯",
        "tagline": "你有一位特別放在心尖上的本命。",
        "description": "你會優先追本命的直拍、造型、個人資源與成長瞬間，對細節記憶力很強，也很知道他的魅力在哪。",
        "tip": "適合玩法：本命雷達、直拍推薦、個人成長時間線。",
    },
    "trend": {
        "name": "跟風粉",
        "tagline": "你很會捕捉正在變紅的熱點。",
        "description": "你常被熱門舞台、短影音片段或社群討論吸引，喜歡先感受流行氛圍，再決定要不要深入入坑。",
        "tip": "適合玩法：熱門榜單、每日一首、神圖抽卡。",
    },
}
FAN_ATTRIBUTE_ORDER = ("group", "solo", "trend")
FAN_ATTRIBUTE_QUIZ = [
    {
        "question": "你通常是怎麼開始注意一個 K-pop 團？",
        "options": [
            {
                "label": "整團舞台很合",
                "description": "隊形、聲線和成員互動一起打到你。",
                "weights": {"group": 3, "solo": 1, "trend": 0},
            },
            {
                "label": "某位成員太亮眼",
                "description": "先被一個人吸住，才慢慢認識其他內容。",
                "weights": {"group": 0, "solo": 3, "trend": 1},
            },
            {
                "label": "大家都在討論",
                "description": "熱門片段、梗圖或榜單聲量讓你點進去看。",
                "weights": {"group": 1, "solo": 0, "trend": 3},
            },
        ],
    },
    {
        "question": "回歸期間，你最期待哪種內容？",
        "options": [
            {
                "label": "團體舞台",
                "description": "想看全員配置、走位和整體概念。",
                "weights": {"group": 3, "solo": 1, "trend": 0},
            },
            {
                "label": "本命直拍",
                "description": "先找自己最愛那位的鏡頭和造型。",
                "weights": {"group": 0, "solo": 3, "trend": 1},
            },
            {
                "label": "熱門精華",
                "description": "想先看社群上最紅、最多人轉的片段。",
                "weights": {"group": 1, "solo": 0, "trend": 3},
            },
        ],
    },
    {
        "question": "朋友問你推坑重點，你會先推薦？",
        "options": [
            {
                "label": "團綜或舞台",
                "description": "看完就懂這團的默契和定位。",
                "weights": {"group": 3, "solo": 0, "trend": 1},
            },
            {
                "label": "本命名場面",
                "description": "那個表情、那段高音或那支直拍不能錯過。",
                "weights": {"group": 1, "solo": 3, "trend": 0},
            },
            {
                "label": "爆紅短影片",
                "description": "先丟最容易懂、最有流量感的入門片段。",
                "weights": {"group": 0, "solo": 1, "trend": 3},
            },
        ],
    },
    {
        "question": "你整理收藏時，資料夾最可能怎麼分？",
        "options": [
            {
                "label": "團體時期",
                "description": "依回歸、舞台、團綜，把全員內容收好。",
                "weights": {"group": 3, "solo": 1, "trend": 0},
            },
            {
                "label": "本命專區",
                "description": "照片、直拍、訪談都先按同一位成員分類。",
                "weights": {"group": 0, "solo": 3, "trend": 1},
            },
            {
                "label": "最近熱門",
                "description": "先收現在最紅、最多人傳的內容。",
                "weights": {"group": 1, "solo": 0, "trend": 3},
            },
        ],
    },
    {
        "question": "你最容易被哪種瞬間再次圈住？",
        "options": [
            {
                "label": "全員默契爆發",
                "description": "舞台或互動讓你覺得少一個人都不行。",
                "weights": {"group": 3, "solo": 1, "trend": 0},
            },
            {
                "label": "本命神級鏡頭",
                "description": "一個眼神或一句話就足夠反覆重播。",
                "weights": {"group": 0, "solo": 3, "trend": 1},
            },
            {
                "label": "熱搜突然爆了",
                "description": "看到大家都在喊，會想立刻補課跟上。",
                "weights": {"group": 1, "solo": 0, "trend": 3},
            },
        ],
    },
]
line_processed_event_ids: OrderedDict[str, float] | None = None
line_processing_event_ids: set[str] = set()
line_recent_message_keys: OrderedDict[tuple[str, str], float] = OrderedDict()
LINE_EVENT_DEDUPE_TTL_SECONDS = 60 * 60 * 24
LINE_EVENT_DEDUPE_MAX_SIZE = 1000
LINE_MESSAGE_DEBOUNCE_SECONDS = 1.5
LINE_EVENT_DEDUPE_PATH = settings.base_dir / "data" / "cache" / "line_seen_events.json"

line_handler = (
    WebhookHandler(settings.line_channel_secret)
    if WebhookHandler and settings.line_channel_secret
    else None
)
line_configuration = (
    Configuration(access_token=settings.line_channel_access_token)
    if Configuration and settings.line_channel_access_token
    else None
)


@app.get("/")
def index() -> tuple[dict, int]:
    return {
        "status": "ok",
        "service": "kpop-agent",
        "health": "/health",
        "webhook": "/webhook",
    }, 200


@app.post("/")
def root_webhook() -> tuple[str, int]:
    return webhook()


@app.get("/health")
def health() -> tuple[dict, int]:
    sqlite_status = _sqlite_status()
    bugs_tool_available = callable(fetch_bugs_weekly_chart)
    supabase_status = radar_repo.status()
    status = "ok" if sqlite_status["ok"] and bugs_tool_available else "degraded"
    return {
        "status": status,
        "sqlite_ok": sqlite_status["ok"],
        "sqlite": sqlite_status,
        "bugs_tool_available": bugs_tool_available,
        "naver_mode": _naver_mode(),
        "gemini_mode": _mode(settings.use_gemini_mock),
        "line_mode": _mode(settings.use_line_mock),
        "supabase_mode": "real" if radar_repo.enabled else "disabled",
        "supabase": supabase_status,
    }, 200 if status == "ok" else 503


@app.get("/play-zone/images/<path:filename>")
def play_zone_member_quiz_image(filename: str):
    safe_filename = _safe_member_quiz_image_filename(filename)
    if safe_filename is None:
        abort(404)
    return send_from_directory(_member_quiz_image_dir(), safe_filename)


@app.get("/play-zone/images/flex/<path:filename>")
def play_zone_member_quiz_flex_image(filename: str):
    safe_filename = _safe_member_quiz_image_filename(filename)
    if safe_filename is None:
        abort(404)
    return _send_member_quiz_flex_image(safe_filename)


@app.get("/play-zone/radar-image/<path:filename>")
def play_zone_bias_radar_image(filename: str):
    safe_filename = _safe_bias_radar_image_filename(filename)
    if safe_filename is None:
        abort(404)
    return send_from_directory(_bias_radar_image_dir(), safe_filename)


@app.post("/analyze")
def analyze() -> tuple[dict, int]:
    payload = request.get_json(silent=True) or {}
    message = str(payload.get("message") or "").strip()
    artist = str(payload.get("artist") or "").strip()
    user_id = str(payload.get("user_id") or "analyze-user")
    if not message and artist:
        message = f"分析 {artist}"
    if not message:
        return {"error": "message or artist is required"}, 400
    intent = route_message(message)
    artist_from_payload = route_message(f"分析 {artist}").artist if artist else ""
    analysis_artist = intent.artist or artist_from_payload
    if _is_kpop_radar_request(message):
        response = _kpop_radar_response(message, user_id=user_id)
    elif _is_play_zone_request(message):
        response = {
            "report": "K-pop Play Zone",
            "flex": _build_play_zone_flex_contents(),
        }
    elif _is_ai_curator_entry_request(message):
        response = {
            "report": "AI 入坑",
            "flex": _build_ai_curator_entry_flex_contents(),
        }
    elif _is_ai_curator_preference_request(message):
        response = _ai_curator_response(message, user_id=user_id)
    elif _is_bias_radar_quiz_request(message, user_id):
        response = _bias_radar_quiz_response(user_id, message)
    elif _is_fan_attribute_quiz_request(message):
        response = {
            "report": _fan_attribute_quiz_text(message),
            "flex": _build_fan_attribute_quiz_flex_contents(message),
        }
    elif _is_member_quiz_answer(message):
        response = _member_quiz_answer_response(message)
    elif _is_member_quiz_request(message):
        response = _member_quiz_question_response()
    elif _is_daily_kpop_request(message):
        response = {
            "report": "每日一首 K-pop",
            "flex": _build_daily_kpop_flex_contents(),
        }
    elif _is_daily_kpop_category_request(message):
        response = _daily_kpop_response(message, user_id=user_id)
    elif _is_photo_card_request(message):
        response = _photo_card_response()
    elif _is_historical_weekly_chart_request(message):
        chart_date = _historical_weekly_chart_date(message)
        response = {
            "report": agent.generate_weekly_chart_report_for_date(chart_date),
            "cache": {
                "type": "weekly_chart_history",
                "chart_date": chart_date,
            },
            "flex": None,
        }
    elif intent.name == "weekly_chart":
        chart_cache = agent.get_weekly_chart_cache()
        response = {
            "report": chart_cache["report"],
            "cache": {
                "type": "weekly_chart",
                "cached_at": chart_cache["cached_at"],
            },
            "flex": None,
        }
    elif analysis_artist and (artist or _is_full_artist_report_request(message)):
        artist_cache = agent.get_artist_analysis_cache(
            analysis_artist,
            period_months=intent.period_months,
        )
        response = {
            "report": artist_cache["report"],
            "cache": {
                "type": artist_cache.get("cache_type", "artist"),
                "artist": artist_cache["artist"],
                "cached_at": artist_cache["cached_at"],
            },
            "flex": artist_cache["flex"],
        }
    elif _is_ai_curator_reason_followup(message):
        response = _ai_curator_reason_followup_response(message, user_id=user_id)
    else:
        report = _reply_text_for_message(message, user_id=user_id)
        response = {"report": report, "flex": None}
    return response, 200


@app.post("/webhook")
def webhook() -> tuple[str, int]:
    body = request.get_data(as_text=True)
    signature = request.headers.get("X-Line-Signature", "")

    if settings.use_line_mock or line_handler is None:
        payload = request.get_json(silent=True) or {}
        message = _extract_mock_message(payload)
        if message:
            user_id = str(payload.get("user_id") or "mock-user")
            reply = fit_line_text(_reply_text_for_message(message, user_id=user_id))
            return jsonify({"mock_reply": reply}).get_data(as_text=True), 200
        return "OK", 200

    try:
        line_handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK", 200


def _extract_mock_message(payload: dict) -> str:
    if "message" in payload:
        return str(payload["message"])
    events = payload.get("events") or []
    if not events:
        return ""
    message = events[0].get("message") or {}
    return str(message.get("text") or "")


def _build_line_reply_message(report: str):
    if FlexMessage is None or FlexContainer is None:
        return TextMessage(text=fit_line_text(report))

    if _is_weekly_chart_report(report):
        return TextMessage(text=fit_line_text(report))

    try:
        flex_contents = agent.build_flex_message(report)
        return FlexMessage(
            altText="K-pop 분석 보고서",
            contents=FlexContainer.from_dict(flex_contents),
        )
    except Exception:
        return TextMessage(text=fit_line_text(report))


def _build_line_flex_message(flex_contents: dict, alt_text: str = "K-pop 분석 보고서"):
    if FlexMessage is None or FlexContainer is None:
        return TextMessage(text=alt_text)
    try:
        return FlexMessage(
            altText=alt_text,
            contents=FlexContainer.from_dict(flex_contents),
        )
    except Exception:
        logger.exception("Cached Flex build failed; falling back to text.")
        return TextMessage(text=alt_text)


def _build_artist_picker_message():
    if TextMessage is None:
        return None
    if FlexMessage is not None and FlexContainer is not None:
        try:
            return FlexMessage(
                altText="選擇要分析的 K-pop 藝人",
                contents=FlexContainer.from_dict(_artist_picker_flex_contents()),
            )
        except Exception:
            logger.exception("Artist picker Flex build failed; falling back to text.")

    if QuickReply is None or QuickReplyItem is None or MessageAction is None:
        return TextMessage(text=f"請輸入：分析 {SUPPORTED_ARTISTS[0]}，或使用預載藝人名稱。")

    return TextMessage(
        text="想分析哪位藝人？",
        quickReply=QuickReply(
            items=[
                QuickReplyItem(action=MessageAction(label=artist, text=f"分析 {artist}"))
                for artist in SUPPORTED_ARTISTS
            ]
        ),
    )


def _artist_picker_flex_contents() -> dict:
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#C4956A",
            "paddingAll": "18px",
            "contents": [
                {
                    "type": "text",
                    "text": "K-pop Agent",
                    "size": "xs",
                    "color": "#FDEBD8",
                },
                {
                    "type": "text",
                    "text": "選擇藝人",
                    "size": "xxl",
                    "weight": "bold",
                    "color": "#FFFFFF",
                    "margin": "sm",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#FAF7F4",
            "paddingAll": "18px",
            "spacing": "md",
            "contents": [
                {
                    "type": "text",
                    "text": "請選擇要產生分析報告的藝人，或直接輸入「分析 藝人名」。",
                    "size": "sm",
                    "color": "#5C4033",
                    "wrap": True,
                },
                *[
                    _artist_picker_button(artist, f"分析 {artist}")
                    for artist in SUPPORTED_ARTISTS
                ],
            ],
        },
    }


def _artist_picker_button(label: str, text: str) -> dict:
    return {
        "type": "button",
        "style": "primary",
        "height": "sm",
        "color": "#8B5E52",
        "action": {
            "type": "message",
            "label": label,
            "text": text,
        },
    }


def _build_play_zone_flex_contents() -> dict:
    return _selection_page_flex_contents(
        title="K-pop Play Zone",
        subtitle="選一個互動玩法",
        description="把既有資料包成 LINE 互動體驗：測驗、雷達、認人與抽卡。",
        accent_color=PLAY_ZONE_ACCENT_COLOR,
        body_background=PLAY_ZONE_BODY_COLOR,
        subtitle_color=PLAY_ZONE_SUBTITLE_COLOR,
        description_color=PLAY_ZONE_TEXT_COLOR,
        item_description_color=PLAY_ZONE_MUTED_TEXT_COLOR,
        items=[
            {
                "icon": "🧭",
                "title": "本命雷達測驗",
                "description": "用幾題選擇題推測最適合你的團體與本命。",
                "text": "本命雷達測驗",
            },
            {
                "icon": "💬",
                "title": "粉絲屬性測驗",
                "description": "5 題判斷你是團飯、唯飯還是跟風粉。",
                "text": "粉絲屬性測驗",
            },
            {
                "icon": "👀",
                "title": "認人測驗",
                "description": "從成員特色與舞台線索練習辨認成員。",
                "text": "認人測驗",
            },
            {
                "icon": "✨",
                "title": "神圖抽卡",
                "description": "抽一張預先整理好的直拍或神圖連結。",
                "text": "神圖抽卡",
            },
        ],
    )


def _build_ai_curator_entry_flex_contents() -> dict:
    return _selection_page_flex_contents(
        title="AI 入坑",
        subtitle="偏好推薦",
        description="直接告訴我你的偏好，我會根據本命雷達、每日推薦與藝人資料幫你排入坑路線。",
        accent_color="#6F5BA7",
        items=[
            {
                "icon": "🌙",
                "title": "清冷女團入坑",
                "description": "適合喜歡清冷感、舞台視覺和概念感的人。",
                "text": "我想入坑清冷感、舞台強的女團",
            },
            {
                "icon": "🎤",
                "title": "Vocal 取向推薦",
                "description": "適合想先看唱功、現場和直拍的人。",
                "text": "幫我推薦 vocal 強、現場穩的 K-pop",
            },
            {
                "icon": "🔥",
                "title": "霸氣舞台路線",
                "description": "適合偏好 rap、dance 和舞台支配感的人。",
                "text": "我喜歡霸氣舞台、rap 和 dance，推薦我入坑路線",
            },
            {
                "icon": "💿",
                "title": "自由描述偏好",
                "description": "也可以直接輸入：我喜歡...，幫我推薦。",
                "text": "我喜歡甜系、白月光感和好聽 MV，幫我推薦",
            },
        ],
    )


def _build_ai_curator_followup_flex_contents(
    artist: str | None = None,
    recommended_members: list[dict[str, str]] | None = None,
) -> dict:
    reason_buttons = []
    seen_members = set()
    for recommendation in recommended_members or []:
        member = recommendation.get("member", "").strip()
        if not member:
            continue
        display_member = _display_member_name(member)
        lookup_key = display_member.casefold()
        if lookup_key in seen_members:
            continue
        seen_members.add(lookup_key)
        action_text = f"為什麼推薦 {display_member}？"
        reason_buttons.append(_ai_curator_button(action_text, action_text))
        if len(reason_buttons) >= 3:
            break

    buttons = [
        *reason_buttons,
        _ai_curator_button("本命雷達", "本命雷達測驗"),
        _ai_curator_button("抽 MV", "每日 MV"),
        _ai_curator_button("抽直拍", "每日直拍"),
    ]
    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#6F5BA7",
            "paddingAll": "14px",
            "contents": [
                {
                    "type": "text",
                    "text": "接下來想看？",
                    "size": "md",
                    "weight": "bold",
                    "color": "#FFFFFF",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#F7F3FF",
            "paddingAll": "14px",
            "spacing": "sm",
            "contents": buttons,
        },
    }


def _ai_curator_button(label: str, text: str) -> dict:
    return {
        "type": "button",
        "style": "secondary",
        "height": "sm",
        "action": {
            "type": "message",
            "label": label,
            "text": text,
        },
    }


def _build_bias_radar_question_flex_contents(question_index: int) -> dict:
    questions = _load_bias_radar_questions()
    question = questions[question_index]
    question_number = question_index + 1
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": PLAY_ZONE_ACCENT_COLOR,
            "paddingAll": "18px",
            "contents": [
                {
                    "type": "text",
                    "text": "本命雷達測驗",
                    "size": "xs",
                    "color": PLAY_ZONE_SUBTITLE_COLOR,
                },
                {
                    "type": "text",
                    "text": f"Q{question_number}/{len(questions)}",
                    "size": "xl",
                    "weight": "bold",
                    "color": "#FFFFFF",
                    "margin": "sm",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": PLAY_ZONE_BODY_COLOR,
            "paddingAll": "18px",
            "spacing": "md",
            "contents": [
                {
                    "type": "text",
                    "text": question["question"],
                    "size": "md",
                    "weight": "bold",
                    "color": PLAY_ZONE_TEXT_COLOR,
                    "wrap": True,
                },
                *[
                    _bias_radar_option_button(question_index, option)
                    for option in question["options"]
                ],
            ],
        },
    }


def _bias_radar_option_button(question_index: int, option: str) -> dict:
    return {
        "type": "box",
        "layout": "vertical",
        "paddingAll": "12px",
        "backgroundColor": "#FFFFFF",
        "cornerRadius": "8px",
        "action": {
            "type": "postback",
            "data": f"本命雷達:{question_index}:{option}",
        },
        "contents": [
            {
                "type": "text",
                "text": option,
                "size": "md",
                "weight": "bold",
                "color": PLAY_ZONE_ACCENT_COLOR,
            },
        ],
    }


def _build_bias_radar_result_flex_contents(result: dict) -> dict:
    recommendation = result["recommendation"]
    bubble = {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": PLAY_ZONE_ACCENT_COLOR,
            "paddingAll": "18px",
            "contents": [
                {
                    "type": "text",
                    "text": "你的本命雷達結果",
                    "size": "xs",
                    "color": PLAY_ZONE_SUBTITLE_COLOR,
                },
                {
                    "type": "text",
                    "text": f"{recommendation['artist']} {recommendation['member']}",
                    "size": "xl",
                    "weight": "bold",
                    "color": "#FFFFFF",
                    "margin": "sm",
                    "wrap": True,
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": PLAY_ZONE_BODY_COLOR,
            "paddingAll": "18px",
            "spacing": "md",
            "contents": [
                {
                    "type": "text",
                    "text": f"類型：{_bias_radar_group_type_label(recommendation)}",
                    "size": "sm",
                    "color": PLAY_ZONE_TEXT_COLOR,
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": f"命中標籤：{result['matched_label_text']}",
                    "size": "sm",
                    "color": PLAY_ZONE_TEXT_COLOR,
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": result["reason"],
                    "size": "sm",
                    "color": PLAY_ZONE_MUTED_TEXT_COLOR,
                    "wrap": True,
                },
                {
                    "type": "button",
                    "style": "primary",
                    "height": "sm",
                    "color": PLAY_ZONE_ACCENT_COLOR,
                    "action": {
                        "type": "message",
                        "label": "再測一次",
                        "text": "本命雷達測驗",
                    },
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "height": "sm",
                    "action": {
                        "type": "message",
                        "label": "回 Play Zone",
                        "text": "互動專區",
                    },
                },
            ],
        },
    }
    image_url = _bias_radar_image_url(recommendation)
    if image_url:
        bubble["hero"] = {
            "type": "image",
            "url": image_url,
            "size": "full",
            "aspectRatio": "20:13",
            "aspectMode": "fit",
        }
    return bubble


def _build_fan_attribute_quiz_flex_contents(message: str) -> dict:
    quiz_state = _parse_fan_attribute_quiz_state(message)
    if quiz_state["is_result"]:
        return _build_fan_attribute_result_flex_contents(quiz_state["scores"])
    return _build_fan_attribute_question_flex_contents(
        quiz_state["question_index"],
        quiz_state["scores"],
    )


def _build_fan_attribute_question_flex_contents(
    question_index: int,
    scores: dict[str, int],
) -> dict:
    question = FAN_ATTRIBUTE_QUIZ[question_index]
    question_number = question_index + 1
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": PLAY_ZONE_ACCENT_COLOR,
            "paddingAll": "18px",
            "contents": [
                {
                    "type": "text",
                    "text": "粉絲屬性測驗",
                    "size": "xs",
                    "color": PLAY_ZONE_SUBTITLE_COLOR,
                },
                {
                    "type": "text",
                    "text": f"Q{question_number}/5",
                    "size": "xl",
                    "weight": "bold",
                    "color": "#FFFFFF",
                    "margin": "sm",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": PLAY_ZONE_BODY_COLOR,
            "paddingAll": "18px",
            "spacing": "md",
            "contents": [
                {
                    "type": "text",
                    "text": question["question"],
                    "size": "md",
                    "weight": "bold",
                    "color": PLAY_ZONE_TEXT_COLOR,
                    "wrap": True,
                },
                *[
                    _fan_attribute_option_button(question_index, scores, option)
                    for option in question["options"]
                ],
            ],
        },
    }


def _fan_attribute_option_button(
    question_index: int,
    scores: dict[str, int],
    option: dict,
) -> dict:
    next_scores = _add_fan_attribute_scores(scores, option["weights"])
    action_text = _fan_attribute_action_text(question_index + 1, next_scores)
    return {
        "type": "box",
        "layout": "vertical",
        "paddingAll": "12px",
        "backgroundColor": "#FFFFFF",
        "cornerRadius": "8px",
        "action": {"type": "postback", "data": action_text},
        "contents": [
            {
                "type": "text",
                "text": option["label"],
                "size": "md",
                "weight": "bold",
                "color": PLAY_ZONE_ACCENT_COLOR,
            },
            {
                "type": "text",
                "text": option["description"],
                "size": "xs",
                "color": PLAY_ZONE_MUTED_TEXT_COLOR,
                "wrap": True,
                "margin": "xs",
            },
        ],
    }


def _build_fan_attribute_result_flex_contents(scores: dict[str, int]) -> dict:
    fan_type_key = _fan_attribute_result_key(scores)
    fan_type = FAN_ATTRIBUTE_TYPES[fan_type_key]
    score_text = " / ".join(
        f"{FAN_ATTRIBUTE_TYPES[key]['name'].replace('粉絲', '')} {scores[key]}"
        for key in FAN_ATTRIBUTE_ORDER
    )
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": PLAY_ZONE_ACCENT_COLOR,
            "paddingAll": "18px",
            "contents": [
                {
                    "type": "text",
                    "text": "你的粉絲屬性是",
                    "size": "xs",
                    "color": PLAY_ZONE_SUBTITLE_COLOR,
                },
                {
                    "type": "text",
                    "text": fan_type["name"],
                    "size": "xl",
                    "weight": "bold",
                    "color": "#FFFFFF",
                    "margin": "sm",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": PLAY_ZONE_BODY_COLOR,
            "paddingAll": "18px",
            "spacing": "md",
            "contents": [
                {
                    "type": "text",
                    "text": fan_type["tagline"],
                    "size": "md",
                    "weight": "bold",
                    "color": PLAY_ZONE_TEXT_COLOR,
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": fan_type["description"],
                    "size": "sm",
                    "color": PLAY_ZONE_MUTED_TEXT_COLOR,
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": fan_type["tip"],
                    "size": "sm",
                    "color": PLAY_ZONE_ACCENT_COLOR,
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": f"分數：{score_text}",
                    "size": "xs",
                    "color": PLAY_ZONE_MUTED_TEXT_COLOR,
                    "wrap": True,
                },
                {
                    "type": "button",
                    "style": "primary",
                    "height": "sm",
                    "color": PLAY_ZONE_ACCENT_COLOR,
                    "action": {
                        "type": "message",
                        "label": "再測一次",
                        "text": "粉絲屬性測驗",
                    },
                },
            ],
        },
    }


def _build_daily_kpop_flex_contents() -> dict:
    return _selection_page_flex_contents(
        title="每日一首 K-pop",
        subtitle="今天想看哪一種？",
        description="每日推薦資料分成 MV、直拍、經典舞台三份 CSV，方便直接補歌名與連結。",
        accent_color="#4E779A",
        body_background="#F4F8FC",
        subtitle_color="#EAF3FF",
        description_color="#314B60",
        item_description_color="#48677E",
        items=[
            {
                "icon": "🎬",
                "title": "MV",
                "description": "官方 MV 或值得補的主打歌。",
                "text": "每日 MV",
            },
            {
                "icon": "🎥",
                "title": "直拍",
                "description": "舞台表現、成員魅力與飯拍導向。",
                "text": "每日直拍",
            },
            {
                "icon": "🏆",
                "title": "經典舞台",
                "description": "回顧代表性舞台與名場面。",
                "text": "每日經典舞台",
            },
        ],
    )


def _build_daily_kpop_redraw_flex_contents(save_item_id: str = "") -> dict:
    body_contents = [
        {
            "type": "text",
            "text": "想再抽哪一種 K-pop 推薦？",
            "size": "xs",
            "color": "#314B60",
            "wrap": True,
        },
        {
            "type": "box",
            "layout": "horizontal",
            "spacing": "sm",
            "contents": [
                _daily_redraw_button("MV", "每日 MV"),
                _daily_redraw_button("直拍", "每日直拍"),
                _daily_redraw_button("舞台", "每日經典舞台"),
            ],
        },
    ]
    if save_item_id:
        body_contents.append(_kpop_radar_save_button(save_item_id))

    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#4E779A",
            "paddingAll": "14px",
            "contents": [
                {
                    "type": "text",
                    "text": "再抽一首",
                    "size": "md",
                    "weight": "bold",
                    "color": "#FFFFFF",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#F4F8FC",
            "paddingAll": "14px",
            "spacing": "sm",
            "contents": body_contents,
        },
    }


def _build_photo_card_redraw_flex_contents() -> dict:
    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": PLAY_ZONE_ACCENT_COLOR,
            "paddingAll": "14px",
            "contents": [
                {
                    "type": "text",
                    "text": "再抽一次",
                    "size": "md",
                    "weight": "bold",
                    "color": "#FFFFFF",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": PLAY_ZONE_BODY_COLOR,
            "paddingAll": "14px",
            "spacing": "sm",
            "contents": [
                {
                    "type": "text",
                    "text": "想再抽一張神圖嗎？",
                    "size": "xs",
                    "color": PLAY_ZONE_TEXT_COLOR,
                    "wrap": True,
                },
                {
                    "type": "button",
                    "style": "primary",
                    "height": "sm",
                    "color": PLAY_ZONE_ACCENT_COLOR,
                    "action": {
                        "type": "message",
                        "label": "再抽一次",
                        "text": "神圖抽卡",
                    },
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "height": "sm",
                    "action": {
                        "type": "message",
                        "label": "回 Play Zone",
                        "text": "互動專區",
                    },
                },
            ],
        },
    }


def _build_member_quiz_question_flex_contents(quiz: dict[str, str]) -> dict:
    return {
        "type": "bubble",
        "size": "mega",
        "hero": {
            "type": "image",
            "url": _member_quiz_image_url(quiz),
            "size": "full",
            "aspectRatio": "1:1",
            "aspectMode": "fit",
            "backgroundColor": "#F7FAF8",
        },
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#5D6F66",
            "paddingAll": "18px",
            "contents": [
                {
                    "type": "text",
                    "text": "認人測驗",
                    "size": "xs",
                    "color": "#E7F1EC",
                },
                {
                    "type": "text",
                    "text": quiz["question"],
                    "size": "xl",
                    "weight": "bold",
                    "color": "#FFFFFF",
                    "margin": "sm",
                    "wrap": True,
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#F7FAF8",
            "paddingAll": "18px",
            "spacing": "md",
            "contents": [
                _member_quiz_option_button(quiz, "A", quiz["option_a"]),
                _member_quiz_option_button(quiz, "B", quiz["option_b"]),
            ],
        },
    }


def _member_quiz_option_button(quiz: dict[str, str], option: str, label: str) -> dict:
    return {
        "type": "button",
        "style": "primary",
        "height": "sm",
        "color": "#5D6F66",
        "action": {
            "type": "postback",
            "label": label,
            "data": f"認人答案:{quiz['id']}:{option}",
        },
    }


def _build_member_quiz_again_flex_contents() -> dict:
    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#5D6F66",
            "paddingAll": "14px",
            "contents": [
                {
                    "type": "text",
                    "text": "再來一題？",
                    "size": "md",
                    "weight": "bold",
                    "color": "#FFFFFF",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#F7FAF8",
            "paddingAll": "14px",
            "spacing": "sm",
            "contents": [
                {
                    "type": "text",
                    "text": "想繼續挑戰認人測驗嗎？",
                    "size": "xs",
                    "color": "#3F5149",
                    "wrap": True,
                },
                {
                    "type": "button",
                    "style": "primary",
                    "height": "sm",
                    "color": "#5D6F66",
                    "action": {
                        "type": "message",
                        "label": "再一題",
                        "text": "認人測驗",
                    },
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "height": "sm",
                    "action": {
                        "type": "message",
                        "label": "回 Play Zone",
                        "text": "互動專區",
                    },
                },
            ],
        },
    }


def _daily_redraw_button(label: str, text: str) -> dict:
    return {
        "type": "button",
        "style": "primary",
        "height": "sm",
        "color": "#4E779A",
        "action": {
            "type": "message",
            "label": label,
            "text": text,
        },
    }


def _selection_page_flex_contents(
    *,
    title: str,
    subtitle: str,
    description: str,
    accent_color: str,
    body_background: str = "#FAF7F4",
    subtitle_color: str = "#FDEBD8",
    description_color: str = "#5C4033",
    item_description_color: str = "#6B4A3E",
    items: list[dict[str, str]],
) -> dict:
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": accent_color,
            "paddingAll": "18px",
            "contents": [
                {
                    "type": "text",
                    "text": subtitle,
                    "size": "xs",
                    "color": subtitle_color,
                },
                {
                    "type": "text",
                    "text": title,
                    "size": "xl",
                    "weight": "bold",
                    "color": "#FFFFFF",
                    "margin": "sm",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": body_background,
            "paddingAll": "18px",
            "spacing": "md",
            "contents": [
                {
                    "type": "text",
                    "text": description,
                    "size": "sm",
                    "color": description_color,
                    "wrap": True,
                },
                *[
                    _selection_page_button(
                        item,
                        accent_color,
                        item_description_color,
                    )
                    for item in items
                ],
            ],
        },
    }


def _selection_page_button(
    item: dict[str, str],
    accent_color: str,
    description_color: str,
) -> dict:
    return {
        "type": "box",
        "layout": "horizontal",
        "spacing": "md",
        "paddingAll": "12px",
        "backgroundColor": "#FFFFFF",
        "cornerRadius": "8px",
        "action": {"type": "message", "text": item["text"]},
        "contents": [
            {
                "type": "text",
                "text": item["icon"],
                "size": "xl",
                "flex": 0,
                "gravity": "center",
            },
            {
                "type": "box",
                "layout": "vertical",
                "spacing": "xs",
                "contents": [
                    {
                        "type": "text",
                        "text": item["title"],
                        "size": "md",
                        "weight": "bold",
                        "color": accent_color,
                    },
                    {
                        "type": "text",
                        "text": item["description"],
                        "size": "xs",
                        "color": description_color,
                        "wrap": True,
                    },
                ],
            },
        ],
    }


def _build_weekly_chart_history_quick_reply(
    current_chart_date: str = "",
    limit: int = 12,
):
    if QuickReply is None or QuickReplyItem is None or MessageAction is None:
        return None
    chart_dates = [
        chart_date
        for chart_date in agent.list_weekly_chart_dates(limit=limit + 1, min_items=1)
        if chart_date and chart_date != current_chart_date
    ][:limit]
    if not chart_dates:
        return None
    return QuickReply(
        items=[
            QuickReplyItem(
                action=MessageAction(
                    label=f"📅 {_weekly_chart_date_label(chart_date)}",
                    text=f"{HISTORICAL_WEEKLY_CHART_PREFIX}{chart_date}",
                )
            )
            for chart_date in chart_dates
        ]
    )


def _kpop_radar_response(message: str, user_id: str = "analyze-user") -> dict:
    action = _kpop_radar_action(message)
    try:
        _ensure_kpop_radar_user(user_id)
        if action == "view_saved":
            item_type = _kpop_radar_param(message, "type", "mv")
            return _kpop_radar_saved_response(user_id, item_type)
        if action == "open_pref":
            return {
                "report": "請選擇你的每日 MV 推薦偏好。",
                "flex": _build_kpop_radar_preference_flex_contents(),
            }
        if action == "set_pref":
            preferred_gender = _kpop_radar_param(message, "gender", "all")
            return _kpop_radar_set_preference_response(user_id, preferred_gender)
        if action == "save_item":
            item_id = _kpop_radar_param(message, "item_id", "")
            return _kpop_radar_save_item_response(user_id, item_id)
        return _kpop_radar_home_response(user_id)
    except Exception:
        logger.exception("K-pop Radar response failed.")
        return {
            "report": "我的K-pop 口袋暫時連不上資料庫，晚點再試一次。",
            "flex": None,
        }


def _ensure_kpop_radar_user(user_id: str) -> None:
    if user_id:
        radar_repo.ensure_user(user_id)


def _kpop_radar_home_response(user_id: str) -> dict:
    preferred_gender = radar_repo.get_preference(user_id)
    counts = radar_repo.saved_counts(user_id)
    return {
        "report": "我的K-pop 口袋",
        "flex": _build_kpop_radar_flex_contents(preferred_gender, counts),
    }


def _kpop_radar_saved_response(user_id: str, item_type: str) -> dict:
    if item_type not in KPOP_RADAR_ITEM_LABELS:
        item_type = "mv"
    items = radar_repo.list_saved_items(user_id, item_type)
    return {
        "report": _format_kpop_radar_saved_items(item_type, items),
        "flex": None,
    }


def _kpop_radar_set_preference_response(user_id: str, preferred_gender: str) -> dict:
    if preferred_gender not in KPOP_RADAR_GENDER_LABELS:
        preferred_gender = "all"
    updated = radar_repo.upsert_preference(user_id, preferred_gender)
    counts = radar_repo.saved_counts(user_id)
    label = KPOP_RADAR_GENDER_LABELS.get(updated, "都可以")
    return {
        "report": f"已更新每日 MV 推薦偏好：{label}",
        "flex": _build_kpop_radar_flex_contents(updated, counts),
    }


def _kpop_radar_save_item_response(user_id: str, item_id: str) -> dict:
    if not item_id:
        return {"report": "找不到要收藏的內容。", "flex": None}
    result = radar_repo.save_item(user_id, item_id)
    if result.saved:
        preferred_gender = radar_repo.get_preference(user_id)
        counts = radar_repo.saved_counts(user_id)
        return {
            "report": "已加入你的 K-pop 口袋 ⭐",
            "flex": _build_kpop_radar_flex_contents(preferred_gender, counts),
        }
    if result.duplicate:
        preferred_gender = radar_repo.get_preference(user_id)
        counts = radar_repo.saved_counts(user_id)
        return {
            "report": "這個內容已經在你的口袋裡了 ⭐",
            "flex": _build_kpop_radar_flex_contents(preferred_gender, counts),
        }
    if result.status == "missing":
        return {"report": "找不到這個 K-pop 內容，可能已被移除。", "flex": None}
    return {"report": "K-pop 口袋尚未設定 Supabase，暫時無法收藏。", "flex": None}


def _build_kpop_radar_flex_contents(
    preferred_gender: str,
    counts: dict[str, int],
) -> dict:
    preference_label = KPOP_RADAR_GENDER_LABELS.get(preferred_gender, "都可以")
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": KPOP_RADAR_ACCENT_COLOR,
            "paddingAll": "18px",
            "contents": [
                {
                    "type": "text",
                    "text": "收藏庫",
                    "size": "xs",
                    "color": KPOP_RADAR_SUBTITLE_COLOR,
                },
                {
                    "type": "text",
                    "text": "我的K-pop 口袋",
                    "size": "xl",
                    "weight": "bold",
                    "color": "#FFFFFF",
                    "margin": "sm",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": KPOP_RADAR_BODY_COLOR,
            "paddingAll": "18px",
            "spacing": "md",
            "contents": [
                {
                    "type": "text",
                    "text": "收藏 MV、直拍與照片，建立你的專屬 K-pop 收藏庫。",
                    "size": "sm",
                    "color": KPOP_RADAR_TEXT_COLOR,
                    "wrap": True,
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "xs",
                    "paddingAll": "12px",
                    "backgroundColor": "#FFFFFF",
                    "cornerRadius": "8px",
                    "contents": [
                        _kpop_radar_info_text(f"目前推薦偏好：{preference_label}"),
                        _kpop_radar_info_text(
                            f"🎬 收藏過的 MV：{counts.get('mv', 0)} 個"
                        ),
                        _kpop_radar_info_text(
                            f"🎥 收藏過的直拍：{counts.get('fancam', 0)} 個"
                        ),
                        _kpop_radar_info_text(
                            f"🖼️ 收藏過的照片：{counts.get('photo', 0)} 張"
                        ),
                    ],
                },
                {
                    "type": "text",
                    "text": "收藏越多，每日推薦會越貼近你的喜好。",
                    "size": "xs",
                    "color": KPOP_RADAR_MUTED_TEXT_COLOR,
                    "wrap": True,
                },
                _kpop_radar_button("查看 MV 收藏", "action=view_saved&type=mv"),
                _kpop_radar_button("查看直拍收藏", "action=view_saved&type=fancam"),
                _kpop_radar_button("查看照片收藏", "action=view_saved&type=photo"),
                _kpop_radar_button("修改推薦偏好", "action=open_pref", primary=True),
            ],
        },
    }


def _kpop_radar_info_text(text: str) -> dict:
    return {
        "type": "text",
        "text": text,
        "size": "sm",
        "color": KPOP_RADAR_TEXT_COLOR,
        "wrap": True,
    }


def _kpop_radar_button(label: str, data: str, primary: bool = False) -> dict:
    button = {
        "type": "button",
        "style": "primary" if primary else "secondary",
        "height": "sm",
        "action": {
            "type": "postback",
            "label": label,
            "data": data,
        },
    }
    if primary:
        button["color"] = KPOP_RADAR_ACCENT_COLOR
    return button


def _build_kpop_radar_preference_flex_contents() -> dict:
    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": KPOP_RADAR_ACCENT_COLOR,
            "paddingAll": "14px",
            "contents": [
                {
                    "type": "text",
                    "text": "修改推薦偏好",
                    "size": "md",
                    "weight": "bold",
                    "color": "#FFFFFF",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": KPOP_RADAR_BODY_COLOR,
            "paddingAll": "14px",
            "spacing": "sm",
            "contents": [
                _kpop_radar_preference_button("女團", "girl_group"),
                _kpop_radar_preference_button("男團", "boy_group"),
                _kpop_radar_preference_button("都可以", "all"),
            ],
        },
    }


def _kpop_radar_preference_button(label: str, preferred_gender: str) -> dict:
    return {
        "type": "button",
        "style": "primary",
        "height": "sm",
        "color": KPOP_RADAR_ACCENT_COLOR,
        "action": {
            "type": "postback",
            "label": label,
            "data": f"action=set_pref&gender={preferred_gender}",
        },
    }


def _build_kpop_radar_preference_quick_reply():
    if QuickReply is None or QuickReplyItem is None or PostbackAction is None:
        return None
    return QuickReply(
        items=[
            QuickReplyItem(
                action=PostbackAction(
                    label=label,
                    data=f"action=set_pref&gender={gender}",
                )
            )
            for label, gender in (
                ("女團", "girl_group"),
                ("男團", "boy_group"),
                ("都可以", "all"),
            )
        ]
    )


def _format_kpop_radar_saved_items(
    item_type: str,
    items: list[dict[str, object]],
) -> str:
    icon, label, _unit = KPOP_RADAR_ITEM_LABELS.get(
        item_type,
        KPOP_RADAR_ITEM_LABELS["mv"],
    )
    if not items:
        return f"{icon} 你的 {label} 收藏\n\n目前還沒有收藏。"
    lines = [f"{icon} 你的 {label} 收藏", ""]
    for index, item in enumerate(items[:20], start=1):
        artist = str(item.get("artist") or "").strip()
        title = str(item.get("title") or "").strip()
        member = str(item.get("member") or "").strip()
        url = str(item.get("url") or "").strip()
        name = f"{artist} - {title}" if artist else title
        if member:
            name = f"{name} ({member})"
        lines.append(f"{index}. {name}")
        if url:
            lines.append(f"   🔗 {url}")
    return "\n".join(lines)


def _build_help_message():
    return TextMessage(
        text=(
            "📖 使用說明\n\n"
            "輸入：\n"
            "分析 aespa\n"
            "分析 IVE\n"
            "本週榜單\n"
            "互動專區\n"
            "每日一首\n\n"
            "目前支援：\n"
            "- 藝人分析報告\n"
            "- 本週 Bugs 榜單\n"
            "- 粉絲留言情緒分析\n"
            "- Play Zone 互動入口\n"
            "- 每日一首 K-pop 入口\n\n"
            "可分析藝人：\n"
            "aespa、IVE、BABYMONSTER、NMIXX、ILLIT、NCT、ZEROBASEONE、TXT、ENHYPEN、BOYNEXTDOOR"
        )
    )


def _build_welcome_message():
    return TextMessage(
        text=(
            "🇰🇷 歡迎來到 KPOP 補給站！🎶\n"
            "從入坑到深陷，我都陪你 ✨\n"
            "\n"
            "你可以這樣玩 ↓\n"
            "\n"
            "🔍 分析藝人\n"
            "└ 輸入「分析 aespa」看完整報告\n"
            "\n"
            "📊 本週榜單\n"
            "└ 看 Bugs 即時週榜 + 歷史週次\n"
            "\n"
            "🎮 互動專區\n"
            "└ 本命雷達、粉絲屬性、認人測驗、神圖抽卡\n"
            "\n"
            "🎧 每日一首\n"
            "└ 今日 MV、直拍、經典舞台一鍵推薦\n"
            "\n"
            "💡 AI 入坑\n"
            "└ 描述你的喜好，我幫你找到適合的團\n"
            "\n"
            "📮 我的口袋\n"
            "└ 把喜歡的 MV / 直拍 / 神圖通通收進來\n"
            "\n"
            "👇 直接點下方功能選單開始，\n"
            "或輸入「help」隨時查指令～\n"
            "祝你追星愉快！🎀"
        )
    )


def _is_artist_picker_request(message: str) -> bool:
    normalized = message.strip().casefold()
    return normalized in {"分析", "分析藝人", "選擇藝人", "artist", "藝人"}


def _is_help_request(message: str) -> bool:
    return message.strip() in {"help", "Help", "HELP"}


def _is_kpop_radar_request(message: str) -> bool:
    normalized = message.strip()
    compact = normalized.casefold().replace(" ", "")
    if normalized in KPOP_RADAR_TRIGGERS:
        return True
    if compact in {trigger.casefold().replace(" ", "") for trigger in KPOP_RADAR_TRIGGERS}:
        return True
    return _kpop_radar_action(message) in KPOP_RADAR_ACTIONS


def _kpop_radar_action(message: str) -> str:
    return _kpop_radar_params(message).get("action", "")


def _kpop_radar_param(message: str, key: str, default: str = "") -> str:
    return _kpop_radar_params(message).get(key, default)


def _kpop_radar_params(message: str) -> dict[str, str]:
    data = message.strip()
    if "=" not in data:
        return {}
    return {
        str(key): str(value)
        for key, value in parse_qsl(data, keep_blank_values=True)
    }


def _is_play_zone_request(message: str) -> bool:
    normalized = message.strip().casefold()
    return normalized in {
        "互動專區",
        "測驗",
        "k-pop play zone",
        "kpop play zone",
        "play zone",
        "playzone",
    }


def _is_ai_curator_entry_request(message: str) -> bool:
    normalized = message.strip().casefold().replace(" ", "")
    return normalized in AI_CURATOR_ENTRY_TRIGGERS


def _is_ai_curator_preference_request(message: str) -> bool:
    normalized = message.strip().casefold()
    compact = normalized.replace(" ", "")
    if not compact:
        return False
    if _is_ai_curator_reason_followup(message) or _is_fixed_command_request(message):
        return False
    if compact.startswith(("ai策展:", "策展:", "雷達:", "推薦:")):
        return True
    preference_actions = (
        "我想入坑",
        "幫我推薦",
        "有沒有推薦",
        "推薦我",
        "推薦",
        "推坑",
        "適合我",
        "適合",
        "入坑路線",
        "入坑",
        "想找",
        "找",
        "想追",
        "想看",
        "想認識",
        "哪個",
        "哪位",
        "誰",
        "求",
        "我喜歡",
        "喜歡",
    )
    preference_terms = (
        "女團",
        "男團",
        "小鹿",
        "鹿",
        "小兔",
        "兔",
        "貓",
        "狗",
        "狐",
        "vocal",
        "dance",
        "rap",
        "visual",
        "all-rounder",
        "清冷",
        "甜系",
        "霸氣",
        "反差",
        "冷感",
        "舞台",
        "直拍",
        "mv",
        "本命",
        "白月光感",
        "白月光",
        "守護感",
        "神性",
        "成員",
        "偶像",
        "愛豆",
        "idol",
        "主唱",
        "rapper",
        "舞擔",
        "門面",
        "全能",
        "現場",
        "聲線",
        "鏡頭",
    )
    member_target_terms = ("成員", "偶像", "愛豆", "idol", "本命")
    artist_mentioned = _ai_curator_query_mentions_known_artist(compact)
    has_action = any(action in compact for action in preference_actions)
    has_preference_term = any(term in compact for term in preference_terms)
    has_member_target = any(term in compact for term in member_target_terms)
    return (has_action and (has_preference_term or artist_mentioned)) or (
        has_member_target and (has_preference_term or artist_mentioned)
    )


def _is_fixed_command_request(message: str) -> bool:
    return (
        _is_artist_picker_request(message)
        or _is_kpop_radar_request(message)
        or _is_help_request(message)
        or _is_play_zone_request(message)
        or _is_ai_curator_entry_request(message)
        or _is_fan_attribute_quiz_request(message)
        or _is_member_quiz_answer(message)
        or _is_member_quiz_request(message)
        or _is_daily_kpop_request(message)
        or _is_daily_kpop_category_request(message)
        or _is_photo_card_request(message)
        or _is_historical_weekly_chart_request(message)
        or _is_play_zone_placeholder_request(message)
        or _is_bias_radar_quiz_request(message)
        or route_message(message).name == "weekly_chart"
        or _is_full_artist_report_request(message)
    )


def _is_fan_attribute_quiz_request(message: str) -> bool:
    normalized = message.strip()
    return normalized == "粉絲屬性測驗" or normalized.startswith("粉絲屬性測驗:")


def _is_bias_radar_quiz_request(message: str, user_id: str = "analyze-user") -> bool:
    normalized = message.strip()
    _prune_bias_radar_sessions()
    return (
        normalized in BIAS_RADAR_TRIGGERS
        or normalized.startswith("本命雷達:")
        or user_id in bias_radar_sessions
    )


def _is_daily_kpop_request(message: str) -> bool:
    normalized = message.strip().casefold()
    return normalized in {
        "每日一首",
        "每日一首 k-pop",
        "每日一首 kpop",
        "今日推歌",
        "每日 k-pop",
        "每日 kpop",
    }


def _is_member_quiz_request(message: str) -> bool:
    normalized = message.strip()
    return normalized in {"認人測驗", "再一題", "再來一題"}


def _is_member_quiz_answer(message: str) -> bool:
    return re.fullmatch(r"認人答案:[^:]+:[AB]", message.strip()) is not None


def _is_play_zone_placeholder_request(message: str) -> bool:
    normalized = message.strip()
    return normalized in {"粉絲屬性測驗", "神圖抽卡"}


def _is_daily_kpop_category_request(message: str) -> bool:
    normalized = message.strip()
    return normalized in {"每日 MV", "每日MV", "每日直拍", "每日 經典舞台", "每日經典舞台"}


def _is_photo_card_request(message: str) -> bool:
    normalized = message.strip()
    return normalized in {"神圖抽卡", "再抽一次神圖", "再抽一張", "抽卡"}


def _is_historical_weekly_chart_request(message: str) -> bool:
    return _historical_weekly_chart_date(message) != ""


def _historical_weekly_chart_date(message: str) -> str:
    normalized = message.strip()
    if not normalized.startswith(HISTORICAL_WEEKLY_CHART_PREFIX):
        return ""
    raw_date = normalized.removeprefix(HISTORICAL_WEEKLY_CHART_PREFIX).strip()
    return _normalize_weekly_chart_date(raw_date)


def _normalize_weekly_chart_date(raw_date: str) -> str:
    compact = re.sub(r"\D+", "", raw_date)
    if len(compact) != 8:
        return ""
    return f"{compact[:4]}-{compact[4:6]}-{compact[6:]}"


def _weekly_chart_date_label(chart_date: str) -> str:
    try:
        start_date = date.fromisoformat(chart_date)
    except ValueError:
        return chart_date
    end_date = start_date + timedelta(days=6)
    return f"{start_date.month}/{start_date.day}-{end_date.month}/{end_date.day}"


def _is_ai_curator_reason_followup(message: str) -> bool:
    compact = unicodedata.normalize("NFKC", message).strip().casefold().replace(" ", "")
    if not compact:
        return False
    return (
        "為什麼推薦" in compact
        or "推薦理由" in compact
        or "為何推薦" in compact
        or ("推薦" in compact and "理由" in compact)
    )


def _is_supported_artist_analysis(message: str) -> bool:
    intent = route_message(message)
    return intent.name != "weekly_chart" and intent.artist in SUPPORTED_ARTISTS


def _is_full_artist_report_request(message: str) -> bool:
    normalized = message.strip().casefold()
    if normalized in {artist.casefold() for artist in SUPPORTED_ARTISTS}:
        return True
    if not _mentions_supported_artist(message):
        return False
    return bool(
        re.search(r"(^|\s)(分析|analyze|report|보고서|분석)\s*", normalized)
        and route_message(message).artist in SUPPORTED_ARTISTS
    )


def _is_kpop_small_analysis_request(message: str) -> bool:
    if _mentions_supported_artist(message):
        return True
    normalized = message.casefold()
    return any(
        keyword in normalized
        for keyword in (
            "k-pop",
            "kpop",
            "藝人",
            "榜單",
            "聲量",
            "輿論",
            "風險",
            "粉絲",
            "留言",
            "比較",
        )
    )


def _mentions_supported_artist(message: str) -> bool:
    normalized = unicodedata.normalize("NFKC", message)
    return any(
        artist in SUPPORTED_ARTISTS and pattern.search(normalized)
        for artist, pattern in ARTIST_PATTERNS.items()
    )


def _reply_text_for_message(message: str, user_id: str = "analyze-user") -> str:
    if _is_kpop_radar_request(message):
        return _kpop_radar_response(message, user_id=user_id)["report"]
    if _is_help_request(message):
        return _build_help_message().text
    if _is_play_zone_request(message):
        return "請在 LINE 中點選 K-pop Play Zone 卡片開始互動。"
    if _is_ai_curator_entry_request(message):
        return "請在 LINE 中點選 AI 入坑，或直接輸入你的 K-pop 偏好。"
    if _is_ai_curator_preference_request(message):
        return _ai_curator_response(message, user_id=user_id)["report"]
    if _is_bias_radar_quiz_request(message, user_id):
        return _bias_radar_quiz_response(user_id, message)["report"]
    if _is_fan_attribute_quiz_request(message):
        return _fan_attribute_quiz_text(message)
    if _is_member_quiz_answer(message):
        return _member_quiz_answer_response(message)["report"]
    if _is_member_quiz_request(message):
        return _member_quiz_question_response()["report"]
    if _is_daily_kpop_request(message):
        return "請在 LINE 中點選每日一首 K-pop 卡片選擇 MV、直拍或經典舞台。"
    if _is_photo_card_request(message):
        return _photo_card_response()["report"]
    if _is_play_zone_placeholder_request(message):
        return _play_zone_placeholder_text(message)
    if _is_daily_kpop_category_request(message):
        return _daily_kpop_response(message, user_id=user_id)["report"]
    if _is_historical_weekly_chart_request(message):
        return agent.generate_weekly_chart_report_for_date(_historical_weekly_chart_date(message))
    if route_message(message).name == "weekly_chart":
        return agent.analyze_message_local(message)
    if _is_full_artist_report_request(message):
        return agent.analyze_message_local(message)
    if _is_ai_curator_reason_followup(message):
        return _ai_curator_reason_followup_response(message, user_id=user_id)["report"]
    return _fixed_command_help_text()


def _fixed_command_help_text() -> str:
    return (
        "目前支援固定指令：\n"
        "1. 分析 aespa\n"
        "2. 分析 IVE\n"
        "3. 本週榜單\n"
        "4. 互動專區\n"
        "5. 每日一首\n"
        "6. 我的K-pop 口袋\n\n"
        "請用「分析 藝人名」取得完整報告。"
    )


def _play_zone_placeholder_text(message: str) -> str:
    feature = message.strip()
    if feature == "我的雷達":
        feature = "我的K-pop 口袋"
    return (
        f"{feature}入口已建立。\n"
        "下一步會接題庫與本地 JSON 結果表，讓它變成真正可玩的互動流程。"
    )


def _ai_curator_response(message: str, user_id: str | None = None) -> dict:
    query = _clean_ai_curator_query(message)
    context = _build_ai_curator_context(query)
    _store_ai_curator_reason_context(user_id, context.get("recommended_members", []))
    fallback = _fallback_ai_curator_answer(query, context)
    report = _generate_ai_curator_answer(query, context, fallback)
    return {
        "report": report,
        "flex": _build_ai_curator_followup_flex_contents(
            context.get("primary_artist"),
            context.get("recommended_members", []),
        ),
    }


def _store_ai_curator_reason_context(
    user_id: str | None,
    recommended_members: list[dict[str, str]],
) -> None:
    if not user_id:
        return
    now = time()
    _prune_ai_curator_reason_contexts(now=now)
    compact_members = [
        {
            "artist": recommendation.get("artist", "").strip(),
            "member": recommendation.get("member", "").strip(),
        }
        for recommendation in recommended_members[:3]
        if recommendation.get("artist", "").strip()
        and recommendation.get("member", "").strip()
    ]
    if compact_members:
        ai_curator_reason_contexts[user_id] = {
            "members": compact_members,
            "stored_at": now,
        }
        _trim_ai_curator_reason_contexts()
    else:
        ai_curator_reason_contexts.pop(user_id, None)


def _ai_curator_reason_context_members(user_id: str) -> list[dict[str, str]]:
    entry = ai_curator_reason_contexts.get(user_id)
    if not entry:
        return []
    if isinstance(entry, list):
        return entry

    stored_at = _safe_float(entry.get("stored_at"))
    if stored_at and time() - stored_at > AI_CURATOR_REASON_CONTEXT_TTL_SECONDS:
        ai_curator_reason_contexts.pop(user_id, None)
        return []

    members = entry.get("members")
    if not isinstance(members, list):
        return []
    return [
        member
        for member in members
        if isinstance(member, dict)
    ]


def _prune_ai_curator_reason_contexts(now: float | None = None) -> None:
    current_time = now if now is not None else time()
    expired_user_ids = []
    for user_id, entry in ai_curator_reason_contexts.items():
        if isinstance(entry, list):
            continue
        stored_at = _safe_float(entry.get("stored_at"))
        if stored_at and current_time - stored_at > AI_CURATOR_REASON_CONTEXT_TTL_SECONDS:
            expired_user_ids.append(user_id)
    for user_id in expired_user_ids:
        ai_curator_reason_contexts.pop(user_id, None)


def _trim_ai_curator_reason_contexts() -> None:
    while len(ai_curator_reason_contexts) > AI_CURATOR_REASON_CONTEXT_MAX_SIZE:
        oldest_user_id = min(
            ai_curator_reason_contexts,
            key=lambda user_id: _context_stored_at(ai_curator_reason_contexts[user_id]),
        )
        ai_curator_reason_contexts.pop(oldest_user_id, None)


def _context_stored_at(entry: dict[str, object] | list[dict[str, str]]) -> float:
    if isinstance(entry, list):
        return 0
    return _safe_float(entry.get("stored_at"))


def _safe_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _clean_ai_curator_query(message: str) -> str:
    cleaned = message.strip()
    for prefix in ("AI入坑:", "ai入坑:", "入坑指南:", "AI策展:", "ai策展:", "策展:", "雷達:", "推薦:"):
        if cleaned.startswith(prefix):
            return cleaned.removeprefix(prefix).strip() or "幫我推薦 K-pop 入坑路線"
    return cleaned


def _build_ai_curator_context(query: str) -> dict:
    profile = _extract_ai_curator_preferences(query)
    mv_artists = {
        row.get("artist", "").strip()
        for row in _load_daily_kpop_rows("MV")
        if row.get("artist", "").strip()
    }
    member_candidates = _prioritize_members_with_mv(
        _rank_bias_radar_members_for_curator(profile),
        mv_artists,
    )[:5]
    recommended_members = _ai_curator_recommended_members(member_candidates)
    recommended_artists = _ai_curator_recommended_artists(member_candidates)[:3]
    daily_items = _rank_daily_mv_rows_for_artists(recommended_artists, profile)[:5]
    artist_candidates = _ai_curator_artist_candidates(member_candidates, daily_items)[:5]
    return {
        "query": query,
        "profile": profile,
        "member_candidates": member_candidates,
        "recommended_members": recommended_members,
        "daily_items": daily_items,
        "artist_summaries": _load_ai_curator_artist_summaries(artist_candidates[:3]),
        "primary_artist": artist_candidates[0] if artist_candidates else None,
        "recommended_artists": recommended_artists,
    }


def _extract_ai_curator_preferences(query: str) -> dict[str, set[str] | str | None]:
    compact = unicodedata.normalize("NFKC", query).casefold().replace(" ", "")
    gender: str | None = None
    if "男團" in compact or "男偶像" in compact or "男idol" in compact:
        gender = "male"
    elif "女團" in compact or "女偶像" in compact or "女idol" in compact:
        gender = "female"

    tags = {
        "artists": _extract_ai_curator_artist_preferences(compact),
        "appearance": _keyword_matches(
            compact,
            {
                "貓咪": ("貓", "貓咪", "cat"),
                "狗狗": ("狗", "狗狗", "dog"),
                "小兔": ("兔", "兔子", "小兔", "rabbit"),
                "狐狸": ("狐", "狐狸", "fox"),
                "小鹿": ("鹿", "小鹿", "deer"),
            },
        ),
        "position": _keyword_matches(
            compact,
            {
                "Vocal": ("vocal", "唱功", "主唱", "高音", "現場"),
                "Dance": ("dance", "舞蹈", "跳舞", "舞台", "直拍"),
                "Rap": ("rap", "rapper", "饒舌"),
                "Visual": ("visual", "門面", "顏值", "外貌", "神顏"),
                "All-rounder": ("all-rounder", "allrounder", "全能", "全方位"),
            },
        ),
        "vibe": _keyword_matches(
            compact,
            {
                "冷感": ("冷感", "高冷"),
                "甜系": ("甜", "甜系", "可愛"),
                "霸氣": ("霸氣", "強勢", "帥"),
                "反差": ("反差",),
                "清冷": ("清冷", "仙", "乾淨"),
            },
        ),
        "relationship": _keyword_matches(
            compact,
            {
                "戀愛感": ("戀愛感", "女友", "男友"),
                "神性": ("神性", "神", "仙"),
                "朋友感": ("朋友感", "親切"),
                "白月光感": ("白月光", "白月光感", "初戀", "初戀感", "守護", "守護感", "想保護"),
                "舞台支配感": ("舞台支配", "舞台支配感", "壓場", "舞台強"),
            },
        ),
    }
    return {"gender": gender, **tags}


def _extract_ai_curator_artist_preferences(compact_query: str) -> set[str]:
    return {
        artist
        for artist in _ai_curator_known_artists()
        if _compact_ai_curator_text(artist) in compact_query
    }


def _ai_curator_query_mentions_known_artist(compact_query: str) -> bool:
    return any(
        _compact_ai_curator_text(artist) in compact_query
        for artist in _ai_curator_known_artists()
    )


def _ai_curator_known_artists() -> list[str]:
    artists = []
    for member in _load_bias_radar_members():
        artists.append(member.get("artist", "").strip())
    for category in ("MV", "直拍", "經典舞台"):
        for row in _load_daily_kpop_rows(category):
            artists.append(row.get("artist", "").strip())
    return list(dict.fromkeys(artist for artist in artists if artist))


def _compact_ai_curator_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold().replace(" ", "")


def _keyword_matches(compact_query: str, mapping: dict[str, tuple[str, ...]]) -> set[str]:
    return {
        label
        for label, keywords in mapping.items()
        if any(keyword.casefold().replace(" ", "") in compact_query for keyword in keywords)
    }


def _rank_bias_radar_members_for_curator(profile: dict) -> list[dict[str, str]]:
    scored: list[tuple[int, dict[str, str]]] = []
    preferred_artists = {
        artist.casefold()
        for artist in (profile.get("artists") or set())
        if isinstance(artist, str)
    }
    for member in _load_bias_radar_members():
        score = 0
        artist = member.get("artist", "").strip()
        if preferred_artists and artist.casefold() in preferred_artists:
            score += 8
        gender = profile.get("gender")
        if gender and member.get("gender_group") == gender:
            score += 3
        elif not gender:
            score += 1
        for field in ("appearance", "position", "vibe", "relationship"):
            wanted = profile.get(field) or set()
            matched = wanted & _split_bias_radar_tags(member.get(field, ""))
            score += len(matched) * 2
        if score > 0:
            scored.append((score, member))
    random.shuffle(scored)
    scored.sort(key=lambda item: item[0], reverse=True)
    return [member for _, member in scored]


def _prioritize_members_with_mv(
    members: list[dict[str, str]],
    mv_artists: set[str],
) -> list[dict[str, str]]:
    with_mv = [member for member in members if member.get("artist", "").strip() in mv_artists]
    without_mv = [member for member in members if member.get("artist", "").strip() not in mv_artists]
    return with_mv + without_mv


def _ai_curator_recommended_members(member_candidates: list[dict[str, str]]) -> list[dict[str, str]]:
    recommendations = []
    seen_members = set()
    for member in member_candidates:
        artist_name = member.get("artist", "").strip()
        member_name = member.get("member", "").strip()
        if not artist_name or not member_name:
            continue
        lookup_key = (artist_name.casefold(), member_name.casefold())
        if lookup_key in seen_members:
            continue
        seen_members.add(lookup_key)
        recommendations.append({"artist": artist_name, "member": member_name})
        if len(recommendations) >= 3:
            break
    return recommendations


def _ai_curator_recommended_artists(member_candidates: list[dict[str, str]]) -> list[str]:
    artists: list[str] = []
    for member in member_candidates:
        artist = member.get("artist", "").strip()
        if artist and artist not in artists:
            artists.append(artist)
    return artists


def _rank_daily_mv_rows_for_artists(
    artists: list[str],
    profile: dict,
) -> list[dict[str, str]]:
    rows = _load_daily_kpop_rows("MV")
    if not rows:
        return []

    artist_set = set(artists)
    matched_rows = [row for row in rows if row.get("artist", "").strip() in artist_set]
    if not matched_rows:
        # Fallback only when the three recommended artists' groups have no MV rows yet.
        return _rank_daily_kpop_rows_for_curator("MV", profile)

    random.shuffle(matched_rows)
    return matched_rows


def _rank_daily_kpop_rows_for_curator(category: str, profile: dict) -> list[dict[str, str]]:
    rows = _load_daily_kpop_rows(category)
    if not rows and category != "MV":
        rows = _load_daily_kpop_rows("MV")
    random.shuffle(rows)
    gender = profile.get("gender")
    if gender == "female":
        rows.sort(key=lambda row: 0 if _daily_artist_looks_female(row.get("artist", "")) else 1)
    elif gender == "male":
        rows.sort(key=lambda row: 0 if not _daily_artist_looks_female(row.get("artist", "")) else 1)
    return rows


def _daily_artist_looks_female(artist: str) -> bool:
    upper_artist = artist.upper()
    female_markers = {
        "AESPA",
        "IVE",
        "NMIXX",
        "ILLIT",
        "BABYMONSTER",
        "BLACKPINK",
        "TWICE",
        "KISS OF LIFE",
        "LE SSERAFIM",
        "QWER",
        "NEWJEANS",
    }
    return any(marker in upper_artist for marker in female_markers)


def _ai_curator_artist_candidates(
    member_candidates: list[dict[str, str]],
    daily_items: list[dict[str, str]],
) -> list[str]:
    artists: list[str] = []
    for member in member_candidates:
        artists.append(member.get("artist", "").strip())
    for item in daily_items:
        artists.append(item.get("artist", "").strip())
    return list(dict.fromkeys(artist for artist in artists if artist))


def _load_ai_curator_artist_summaries(artists: list[str]) -> list[dict[str, str]]:
    summaries = []
    for artist in artists:
        cache_path = settings.base_dir / "data" / "cache" / "artists" / f"{artist.lower()}.json"
        if not cache_path.exists():
            continue
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        sentiment = payload.get("sources", {}).get("sentiment", {}).get("sentiment", {})
        chart = payload.get("sources", {}).get("chart", {})
        insight = payload.get("insight", {})
        summaries.append(
            {
                "artist": artist,
                "chart": (
                    f"best_rank={chart.get('best_rank', 'NA')}, "
                    f"trend={chart.get('trend', 'NA')}"
                ),
                "sentiment": (
                    f"positive={sentiment.get('positive', 0)}, "
                    f"neutral={sentiment.get('neutral', 0)}, "
                    f"negative={sentiment.get('negative', 0)}"
                ),
                "insight": insight.get("headline", ""),
            }
        )
    return summaries


def _generate_ai_curator_answer(query: str, context: dict, fallback: str) -> str:
    if getattr(settings, "use_gemini_mock", True):
        return fallback
    try:
        prompt = _build_ai_curator_prompt(query, context)
        response = requests.post(
            GEMINI_API_URL.format(model=settings.gemini_model),
            params={"key": settings.gemini_api_key},
            json={
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": prompt}],
                    }
                ],
                "generationConfig": {
                    "temperature": 0.45,
                    "maxOutputTokens": 360,
                },
            },
            timeout=GEMINI_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0].get("text", "")
        return _clean_ai_curator_answer(text) or fallback
    except Exception:
        logger.warning("AI curator Gemini response failed; using fallback.")
        return fallback


def _build_ai_curator_prompt(query: str, context: dict) -> str:
    member_lines = [
        (
            f"- {member.get('artist')} {member.get('member')}: "
            f"position={member.get('position')}; vibe={member.get('vibe')}; "
            f"relationship={member.get('relationship')}"
        )
        for member in context["member_candidates"][:5]
    ]
    daily_lines = [
        f"- {item.get('artist')} - {item.get('title')} (MV): {item.get('url')}"
        for item in context["daily_items"][:5]
    ]
    artist_lines = [
        f"- {item['artist']}: {item['chart']}; {item['sentiment']}; insight={item['insight']}"
        for item in context["artist_summaries"]
    ]
    return f"""你是 K-pop 入坑指南，請用繁體中文根據使用者偏好做自然語言推薦。
只能根據下方候選資料回答，不要捏造不存在的資料。
回答 5 行以內，口吻像 LINE Bot，清楚給 2-3 個推薦與下一步。
不要使用英文。不要評論候選資料是否完全符合；請從候選中選最接近者給出推薦。
今日入口必須從「推薦 MV 候選」選一首，且藝人必須屬於本命候選前 3 位的所屬團體。

使用者偏好：
{query}

本命候選：
{chr(10).join(member_lines) or "- 無"}

推薦 MV 候選：
{chr(10).join(daily_lines) or "- 無"}

藝人分析摘要：
{chr(10).join(artist_lines) or "- 無"}
"""


def _clean_ai_curator_answer(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:text)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    if len(cleaned) < 30:
        return ""
    suspicious_markers = ("not explicitly", "let'", "let's", "candidate", "closest")
    if any(marker in cleaned.casefold() for marker in suspicious_markers):
        return ""
    if _ascii_letter_ratio(cleaned) > 0.35:
        return ""
    return fit_line_text(cleaned, limit=900)


def _ascii_letter_ratio(text: str) -> float:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return 0
    ascii_letters = [char for char in letters if char.isascii()]
    return len(ascii_letters) / len(letters)


def _fallback_ai_curator_answer(query: str, context: dict) -> str:
    member_candidates = context.get("member_candidates", [])
    daily_items = context.get("daily_items", [])
    lines = [
        "🧭 AI 入坑",
        f"根據你說的「{query}」，我會這樣排：",
    ]
    if member_candidates:
        for index, member in enumerate(member_candidates[:3], start=1):
            lines.append(
                f"{index}. {member['artist']} {member['member']}："
                f"{member.get('vibe', '風格鮮明')}，適合先看本命雷達。"
            )
    elif daily_items:
        for index, item in enumerate(daily_items[:3], start=1):
            lines.append(f"{index}. {item['artist']}《{item['title']}》：適合先聽 MV 入坑。")
    else:
        lines.append("目前資料還不夠，建議先從本命雷達測驗或每日一首開始。")

    if daily_items:
        item = daily_items[0]
        lines.append(f"今日入口：先看 {item['artist']}《{item['title']}》")
        if item.get("url"):
            lines.append(item["url"])
    return fit_line_text("\n".join(lines), limit=900)


def _ai_curator_reason_followup_response(
    message: str,
    user_id: str | None = None,
) -> dict:
    explicit_member_row = _find_ai_curator_reason_member(message)
    if explicit_member_row and _contains_lookup_name(
        message,
        explicit_member_row.get("artist", ""),
    ):
        member_row = explicit_member_row
    else:
        member_row = _find_ai_curator_reason_member_from_context(message, user_id)
    if member_row is None:
        member_row = explicit_member_row
    if member_row:
        fallback = _fallback_ai_curator_reason_answer(member_row)
        reason = _generate_ai_curator_reason_answer(message, member_row, fallback)
        link_text = _find_recommendation_link_for_member(member_row)
        return {"report": fit_line_text(_join_nonempty_blocks(reason, link_text))}

    artist = _find_ai_curator_reason_artist(message)
    if artist:
        summary_text = _ai_curator_artist_summary_text(_load_ai_curator_artist_summary(artist))
        link_text = _find_recommendation_link_for_artist(artist)
        lines = [
            f"目前追問主要支援成員；你問到的是 {artist}，我先用本地資料補一個團體入口。",
            summary_text,
            link_text,
        ]
        return {"report": fit_line_text(_join_nonempty_blocks(*lines))}

    fallback_link = _find_random_daily_mv_link_text()
    return {
        "report": fit_line_text(
            _join_nonempty_blocks(
                "目前本地資料還找不到這位成員，但可以先從本命雷達或每日一首繼續探索。",
                fallback_link,
            )
        )
    }


def _find_ai_curator_reason_member_from_context(
    message: str,
    user_id: str | None,
) -> dict[str, str] | None:
    if not user_id:
        return None
    recommendations = _ai_curator_reason_context_members(user_id)
    if not recommendations:
        return None
    members = _load_ai_curator_reason_members()
    for recommendation in recommendations:
        rec_member = recommendation.get("member", "")
        rec_artist = recommendation.get("artist", "")
        if not _contains_lookup_name(message, rec_member):
            continue
        for member in members:
            if _same_lookup_name(member.get("artist", ""), rec_artist) and _same_lookup_name(
                member.get("member", ""),
                rec_member,
            ):
                return member
    return None


def _find_ai_curator_reason_member(message: str) -> dict[str, str] | None:
    for member in _load_ai_curator_reason_members():
        if _contains_lookup_name(message, member.get("artist", "")) and _contains_lookup_name(
            message,
            member.get("member", ""),
        ):
            return member
    for member in _load_ai_curator_reason_members():
        if _contains_lookup_name(message, member.get("member", "")):
            return member
    return None


def _find_ai_curator_reason_artist(message: str) -> str | None:
    artists = []
    for member in _load_ai_curator_reason_members():
        artists.append(member.get("artist", "").strip())
    for mv_row in _load_daily_kpop_rows("MV"):
        artists.append(mv_row.get("artist", "").strip())

    for artist in dict.fromkeys(artist for artist in artists if artist):
        if _contains_lookup_name(message, artist):
            return artist
    return None


def _load_ai_curator_reason_members() -> list[dict[str, str]]:
    csv_path = settings.base_dir / "data" / "play_zone" / "bias_radar_members.csv"
    return _load_cached_csv_rows(csv_path, _ai_curator_reason_member_is_usable)


def _ai_curator_reason_member_is_usable(row: dict[str, str]) -> bool:
    return (
        bool(row.get("artist", "").strip())
        and bool(row.get("member", "").strip())
        and any(
            row.get(field, "").strip()
            for field in ("appearance", "position", "vibe", "relationship")
        )
    )


def _fallback_ai_curator_reason_answer(member_row: dict[str, str]) -> str:
    artist = member_row.get("artist", "").strip()
    member = _display_member_name(member_row.get("member", ""))
    reason_sentences = _ai_curator_reason_sentences(member_row, member)

    lines = [f"✨ 我會先推 {artist} {member}。"]
    if reason_sentences:
        lines.extend(reason_sentences)
    else:
        lines.append("🔎 這位的線索比較少，我會先讓你從團體影片開始抓感覺。")

    summary_text = _ai_curator_artist_summary_text(_load_ai_curator_artist_summary(artist))
    if summary_text:
        lines.append(summary_text)
    return "\n".join(lines)


def _ai_curator_reason_sentences(member_row: dict[str, str], member: str) -> list[str]:
    appearance = _natural_bias_tag_text(member_row.get("appearance", ""))
    position = _natural_position_tag_text(member_row.get("position", ""))
    vibe = _natural_bias_tag_text(member_row.get("vibe", ""))
    relationship = _natural_bias_tag_text(member_row.get("relationship", ""))

    sentences = []
    if appearance and vibe:
        sentences.append(
            f"🔎 如果你吃{appearance}那種第一眼的清透感，"
            f"{member} 會很容易先對上；再加上{vibe}的反差，會讓人想多看幾支舞台。"
        )
    elif appearance:
        sentences.append(
            f"🔎 如果你吃{appearance}那種第一眼的清透感，{member} 會很容易先對上。"
        )
    elif vibe:
        sentences.append(f"🔎 {vibe}這種氣場很適合當入坑入口，第一支舞台就能先抓感覺。")

    if relationship and position:
        sentences.append(
            f"💫 {relationship}的距離感很適合慢慢被圈進去，"
            f"入門可以先看能感受到{position}魅力的直拍。"
        )
    elif relationship:
        sentences.append(f"💫 {relationship}的距離感很適合慢慢被圈進去。")
    elif position:
        sentences.append(f"💫 入門可以先看能感受到{position}魅力的直拍。")
    return sentences


def _natural_bias_tag_text(raw_value: str) -> str:
    return "、".join(tag.strip() for tag in raw_value.split("|") if tag.strip())


def _natural_position_tag_text(raw_value: str) -> str:
    labels = []
    mapping = {
        "vocal": "聲線",
        "dance": "舞台動作",
        "rap": "rap 節奏感",
        "visual": "鏡頭感",
        "all-rounder": "全方位感",
        "allrounder": "全方位感",
    }
    for tag in (part.strip() for part in raw_value.split("|") if part.strip()):
        label = mapping.get(tag.casefold(), tag)
        if label not in labels:
            labels.append(label)
    return _join_chinese_list(labels)


def _join_chinese_list(values: list[str]) -> str:
    if len(values) <= 1:
        return values[0] if values else ""
    if len(values) == 2:
        return "和".join(values)
    return "、".join(values[:-1]) + "和" + values[-1]


def _generate_ai_curator_reason_answer(
    message: str,
    member_row: dict[str, str],
    fallback: str,
) -> str:
    if getattr(settings, "use_gemini_mock", True):
        return fallback
    try:
        prompt = _build_ai_curator_reason_prompt(message, member_row)
        response = requests.post(
            GEMINI_API_URL.format(model=settings.gemini_model),
            params={"key": settings.gemini_api_key},
            json={
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": prompt}],
                    }
                ],
                "generationConfig": {
                    "temperature": 0.35,
                    "maxOutputTokens": 260,
                },
            },
            timeout=GEMINI_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0].get("text", "")
        return _clean_ai_curator_reason_answer(text) or fallback
    except Exception:
        logger.warning("AI curator reason Gemini response failed; using fallback.")
        return fallback


def _build_ai_curator_reason_prompt(message: str, member_row: dict[str, str]) -> str:
    artist = member_row.get("artist", "").strip()
    member = _display_member_name(member_row.get("member", ""))
    summary_text = _ai_curator_artist_summary_text(_load_ai_curator_artist_summary(artist))
    return f"""你是 K-pop AI 入坑推薦理由助理，請用繁體中文回答使用者追問。
只能根據下方本地 CSV 欄位與快取摘要回答，不要捏造沒有列出的資料。
回答 6 行以內，不要附網址，最後的推薦影片會由系統另外補上。
語氣要像自然推坑，不要逐欄列出資料表，不要寫「本地資料裡有幾個明確標籤」。
不要直接說「外貌、定位、氣質、關係感、資料、標籤、欄位」，要把可用線索揉進自然句子。
可以自然使用 2-4 個 emoji，但不要每句都塞滿。

使用者追問：
{message}

本地成員資料：
- artist: {artist}
- member: {member}
- appearance: {_bias_radar_tag_text(member_row.get("appearance", "")) or "無"}
- position: {_bias_radar_tag_text(member_row.get("position", "")) or "無"}
- vibe: {_bias_radar_tag_text(member_row.get("vibe", "")) or "無"}
- relationship: {_bias_radar_tag_text(member_row.get("relationship", "")) or "無"}

快取摘要：
{summary_text or "無"}
"""


def _clean_ai_curator_reason_answer(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:text)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    if len(cleaned) < 20 or "http" in cleaned.casefold():
        return ""
    suspicious_markers = ("not explicitly", "let'", "let's", "candidate", "closest")
    if any(marker in cleaned.casefold() for marker in suspicious_markers):
        return ""
    if _ascii_letter_ratio(cleaned) > 0.45:
        return ""
    return fit_line_text(cleaned, limit=900)


def _find_recommendation_link_for_member(member_row: dict[str, str]) -> str:
    member = member_row.get("member", "").strip()
    artist = member_row.get("artist", "").strip()
    fancams = _load_daily_kpop_rows("直拍")

    member_fancams = [
        row
        for row in fancams
        if _same_lookup_name(row.get("artist", ""), artist)
        and _same_lookup_name(row.get("member", ""), member)
    ]
    if member_fancams:
        return _format_fancam_link(random.choice(member_fancams), "🎬 先用這支直拍確認感覺：")

    member_fancams = [
        row
        for row in fancams
        if _same_lookup_name(row.get("member", ""), member)
    ]
    if member_fancams:
        return _format_fancam_link(
            random.choice(member_fancams),
            f"🎬 目前沒有找到 {_display_member_name(member)} 的同團直拍，先補一支同名成員直拍：",
        )

    artist_fancams = [
        row
        for row in fancams
        if _same_lookup_name(row.get("artist", ""), artist)
    ]
    if artist_fancams:
        return _format_fancam_link(
            random.choice(artist_fancams),
            f"🎬 目前沒有找到 {_display_member_name(member)} 的直拍，先補一支同團直拍：",
        )

    artist_mvs = [
        row
        for row in _load_daily_kpop_rows("MV")
        if _same_lookup_name(row.get("artist", ""), artist)
    ]
    if artist_mvs:
        return _format_mv_link(
            random.choice(artist_mvs),
            f"🎬 目前沒有找到 {_display_member_name(member)} 的直拍，先補一支所屬團體 MV：",
        )

    return _find_random_daily_mv_link_text(
        f"🎬 目前沒有找到 {_display_member_name(member)} 的直拍，先補一支每日 MV："
    )


def _find_recommendation_link_for_artist(artist: str) -> str:
    artist_mvs = [
        row
        for row in _load_daily_kpop_rows("MV")
        if _same_lookup_name(row.get("artist", ""), artist)
    ]
    if artist_mvs:
        return _format_mv_link(random.choice(artist_mvs), "先補一支團體 MV：")
    return _find_random_daily_mv_link_text()


def _find_random_daily_mv_link_text(prefix: str = "先補一支每日 MV：") -> str:
    mv_rows = _load_daily_kpop_rows("MV")
    if not mv_rows:
        return ""
    return _format_mv_link(random.choice(mv_rows), prefix)


def _format_fancam_link(row: dict[str, str], prefix: str) -> str:
    artist = row.get("artist", "").strip()
    member = _display_member_name(row.get("member", ""))
    title = row.get("title", "").strip()
    url = row.get("url", "").strip()
    return f"{prefix}{artist} {member} - {title}\n{url}"


def _format_mv_link(row: dict[str, str], prefix: str) -> str:
    artist = row.get("artist", "").strip()
    title = row.get("title", "").strip()
    url = row.get("url", "").strip()
    return f"{prefix}{artist} - {title}\n{url}"


def _ai_curator_artist_summary_text(summary: dict[str, str] | None) -> str:
    if not summary:
        return ""
    artist = summary.get("artist", "").strip()
    if summary.get("insight"):
        return f"📰 補充團體近況：{artist} 近期重點是「{summary['insight']}」。"

    chart = _parse_ai_curator_summary_pairs(summary.get("chart", ""))
    best_rank = chart.get("best_rank")
    trend = chart.get("trend")
    if best_rank and best_rank != "NA":
        if trend and trend != "NA":
            return f"📰 補充團體近況：{artist} 近期榜單最好名次是第 {best_rank} 名，趨勢是{trend}。"
        return f"📰 補充團體近況：{artist} 近期榜單最好名次是第 {best_rank} 名。"
    return ""


def _parse_ai_curator_summary_pairs(raw_value: str) -> dict[str, str]:
    pairs = {}
    for part in raw_value.split(","):
        key, separator, value = part.partition("=")
        if separator:
            pairs[key.strip()] = value.strip()
    return pairs


def _load_ai_curator_artist_summary(artist: str) -> dict[str, str] | None:
    summaries = _load_ai_curator_artist_summaries([artist])
    return summaries[0] if summaries else None


def _bias_radar_tag_text(raw_value: str) -> str:
    return " / ".join(tag.strip() for tag in raw_value.split("|") if tag.strip())


def _display_member_name(member: str) -> str:
    cleaned = member.strip()
    special_names = {"RM", "V", "DK", "D.O.", "I.N", "THE8"}
    if cleaned.upper() in special_names:
        return cleaned.upper()
    if cleaned and cleaned == cleaned.upper():
        return cleaned.title()
    return cleaned


def _contains_lookup_name(message: str, value: str) -> bool:
    normalized_message = _lookup_text(message)
    normalized_value = _lookup_text(value)
    if not normalized_message or not normalized_value:
        return False
    pattern = re.escape(normalized_value).replace(r"\ ", r"\s+")
    return re.search(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", normalized_message) is not None


def _same_lookup_name(left: str, right: str) -> bool:
    return _lookup_text(left) == _lookup_text(right)


def _lookup_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).casefold()
    without_marks = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    return re.sub(r"\s+", " ", without_marks.strip())


def _join_nonempty_blocks(*blocks: str) -> str:
    return "\n\n".join(block.strip() for block in blocks if block and block.strip())


def _photo_card_placeholder_text() -> str:
    card = _load_photo_card_recommendation()
    if card:
        return _format_photo_card_recommendation(card)
    return PHOTO_CARD_EMPTY_TEXT


def _photo_card_response() -> dict:
    card = _load_photo_card_recommendation()
    if not card:
        return {"report": PHOTO_CARD_EMPTY_TEXT, "flex": None}
    return {
        "report": _format_photo_card_recommendation(card),
        "flex": _build_recommendation_action_flex_contents(
            item_type="photo",
            url=card.get("url", ""),
            redraw_label="再抽神圖",
            redraw_text="神圖抽卡",
            fallback_flex=_build_photo_card_redraw_flex_contents(),
        ),
    }


def _load_cached_csv_rows(
    csv_path: Path,
    row_filter: Callable[[dict[str, str]], bool],
    row_mapper: Callable[[dict[str, str]], dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    if not csv_path.exists():
        csv_row_cache.pop(csv_path, None)
        return []

    stat = csv_path.stat()
    cache_key = (stat.st_mtime_ns, stat.st_size)
    cached = csv_row_cache.get(csv_path)
    if cached and cached[0] == cache_key:
        return [dict(row) for row in cached[1]]

    with csv_path.open(newline="", encoding="utf-8") as file:
        rows = [
            row_mapper(row) if row_mapper else dict(row)
            for row in csv.DictReader(file)
            if row_filter(row)
        ]
    csv_row_cache[csv_path] = (cache_key, rows)
    return [dict(row) for row in rows]


def _bias_radar_quiz_response(user_id: str, message: str) -> dict:
    normalized = message.strip()
    questions = _load_bias_radar_questions()
    _prune_bias_radar_sessions()
    if normalized in BIAS_RADAR_TRIGGERS:
        _store_bias_radar_session(user_id, question_index=0, answers=[])
        return {
            "report": _bias_radar_question_text(0),
            "flex": _build_bias_radar_question_flex_contents(0),
        }

    session = bias_radar_sessions.get(user_id)
    if not session:
        _store_bias_radar_session(user_id, question_index=0, answers=[])
        return {
            "report": _bias_radar_question_text(0),
            "flex": _build_bias_radar_question_flex_contents(0),
        }

    question_index = int(session.get("question_index", 0))
    option = _bias_radar_answer_from_message(normalized, question_index)
    if option is None:
        return {
            "report": _bias_radar_question_text(question_index),
            "flex": _build_bias_radar_question_flex_contents(question_index),
        }

    answers = [str(answer) for answer in session.get("answers", [])]
    answers.append(option)
    question_index += 1
    if question_index < len(questions):
        _store_bias_radar_session(user_id, question_index=question_index, answers=answers)
        return {
            "report": _bias_radar_question_text(question_index),
            "flex": _build_bias_radar_question_flex_contents(question_index),
        }

    bias_radar_sessions.pop(user_id, None)
    result = _score_bias_radar_result(answers)
    return {
        "report": _format_bias_radar_result_text(result),
        "flex": _build_bias_radar_result_flex_contents(result),
    }


def _store_bias_radar_session(user_id: str, question_index: int, answers: list[str]) -> None:
    bias_radar_sessions[user_id] = {
        "question_index": question_index,
        "answers": answers,
        "updated_at": time(),
    }
    _trim_bias_radar_sessions()


def _prune_bias_radar_sessions(now: float | None = None) -> None:
    current_time = now if now is not None else time()
    expired_user_ids = [
        user_id
        for user_id, session in bias_radar_sessions.items()
        if current_time - _session_updated_at(session) > BIAS_RADAR_SESSION_TTL_SECONDS
    ]
    for user_id in expired_user_ids:
        bias_radar_sessions.pop(user_id, None)


def _trim_bias_radar_sessions() -> None:
    while len(bias_radar_sessions) > BIAS_RADAR_SESSION_MAX_SIZE:
        oldest_user_id = min(
            bias_radar_sessions,
            key=lambda user_id: _session_updated_at(bias_radar_sessions[user_id]),
        )
        bias_radar_sessions.pop(oldest_user_id, None)


def _session_updated_at(session: dict[str, object]) -> float:
    updated_at = _safe_float(session.get("updated_at"))
    return updated_at or time()


def _bias_radar_answer_from_message(message: str, question_index: int) -> str | None:
    questions = _load_bias_radar_questions()
    if question_index >= len(questions):
        return None
    options = questions[question_index]["options"]

    if message.startswith("本命雷達:"):
        parts = message.split(":", 2)
        if len(parts) != 3:
            return None
        try:
            action_question_index = int(parts[1])
        except ValueError:
            return None
        if action_question_index != question_index:
            return None
        option = parts[2].strip()
    else:
        option = message.strip()

    if option in options:
        return option
    return None


def _bias_radar_question_text(question_index: int) -> str:
    questions = _load_bias_radar_questions()
    question_number = question_index + 1
    return f"本命雷達測驗 Q{question_number}/{len(questions)}：請在 LINE 卡片中選擇最符合你的答案。"


def _load_bias_radar_questions() -> list[dict]:
    json_path = settings.base_dir / "data" / "play_zone" / "bias_radar_questions.json"
    with json_path.open(encoding="utf-8") as file:
        questions = json.load(file)
    return questions if isinstance(questions, list) else []


def _load_bias_radar_members() -> list[dict[str, str]]:
    csv_path = settings.base_dir / "data" / "play_zone" / "bias_radar_members.csv"
    return _load_cached_csv_rows(csv_path, _bias_radar_row_is_usable)


def _bias_radar_row_is_usable(row: dict[str, str]) -> bool:
    required_fields = ("id", "artist", "member", "gender_group", "group_type", "url")
    if any(not row.get(field, "").strip() for field in required_fields):
        return False
    filled_tag_fields = sum(
        1
        for field in ("appearance", "position", "vibe", "relationship")
        if row.get(field, "").strip()
    )
    return filled_tag_fields >= 3


def _score_bias_radar_result(answers: list[str]) -> dict:
    members = _load_bias_radar_members()
    if not members:
        raise ValueError("bias_radar_members.csv has no usable rows")

    scored_rows = [
        _score_bias_radar_member(member, answers)
        for member in members
    ]
    max_score = max(score for score, _, _ in scored_rows)
    top_matches = [
        (member, matched)
        for score, member, matched in scored_rows
        if score == max_score
    ]
    recommendation, matched = random.choice(top_matches)
    matched_label_text = "、".join(matched) if matched else "整體氣質接近"
    return {
        "recommendation": recommendation,
        "matched": matched,
        "matched_label_text": matched_label_text,
        "score": max_score,
        "reason": _bias_radar_reason(recommendation, answers, matched),
    }


def _score_bias_radar_member(
    member: dict[str, str],
    answers: list[str],
) -> tuple[int, dict[str, str], list[str]]:
    score = 0
    matched: list[str] = []
    gender_answer, appearance_answer, position_answer, vibe_answer, relationship_answer = answers

    if _bias_radar_gender_matches(member, gender_answer):
        score += 3

    for field, answer in (
        ("appearance", appearance_answer),
        ("position", position_answer),
        ("vibe", vibe_answer),
        ("relationship", relationship_answer),
    ):
        if answer in _split_bias_radar_tags(member.get(field, "")):
            score += 2
            matched.append(answer)

    return score, member, matched


def _bias_radar_gender_matches(member: dict[str, str], answer: str) -> bool:
    group_type = member.get("group_type", "").strip()
    gender_group = member.get("gender_group", "").strip()
    if answer == "都可以":
        return True
    if answer == "男團":
        return group_type == "boy_group" or gender_group == "male"
    if answer == "女團":
        return group_type == "girl_group" or gender_group == "female"
    return False


def _split_bias_radar_tags(raw_value: str) -> set[str]:
    return {
        tag.strip()
        for tag in raw_value.split("|")
        if tag.strip()
    }


def _bias_radar_image_dir() -> Path:
    return settings.base_dir / "data" / "play_zone" / "radar_image"


def _bias_radar_image_path(member: dict[str, str]) -> Path | None:
    member_id = member.get("id", "").strip()
    if not member_id:
        return None
    image_dir = _bias_radar_image_dir()
    for extension in BIAS_RADAR_IMAGE_EXTENSIONS:
        image_path = image_dir / f"{member_id}{extension}"
        if image_path.exists():
            return image_path
    return None


def _bias_radar_image_url(member: dict[str, str]) -> str:
    image_path = _bias_radar_image_path(member)
    if image_path is None:
        return ""
    filename = image_path.name
    forwarded_host = request.headers.get("X-Forwarded-Host", "").split(",", 1)[0].strip()
    forwarded_proto = request.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip()
    host = forwarded_host or request.host
    scheme = forwarded_proto or request.scheme
    if host.endswith(".hf.space"):
        return (
            "https://huggingface.co/spaces/EscA95103040126/kpop-agent/resolve/main/"
            f"data/play_zone/radar_image/{quote(filename)}"
        )
    return f"{scheme}://{host}/play-zone/radar-image/{quote(filename)}"


def _safe_bias_radar_image_filename(filename: str) -> str | None:
    normalized = filename.strip().replace("\\", "/")
    path = Path(normalized)
    if not normalized or "/" in normalized or path.name != normalized:
        return None
    if path.suffix.casefold() not in BIAS_RADAR_IMAGE_EXTENSIONS:
        return None
    return normalized


def _bias_radar_group_type_label(member: dict[str, str]) -> str:
    labels = {
        "boy_group": "男團",
        "girl_group": "女團",
        "solo": "solo",
        "mixed_group": "混合團",
    }
    return labels.get(member.get("group_type", "").strip(), "未分類")


def _bias_radar_reason(
    recommendation: dict[str, str],
    answers: list[str],
    matched: list[str],
) -> str:
    _, appearance_answer, position_answer, vibe_answer, relationship_answer = answers
    focus_tags = matched or [appearance_answer, position_answer, vibe_answer, relationship_answer]
    focus_text = "、".join(focus_tags[:3])
    return (
        f"你偏好{focus_text}的本命型，所以推薦你關注 "
        f"{recommendation['artist']} {recommendation['member']}。"
    )


def _format_bias_radar_result_text(result: dict) -> str:
    recommendation = result["recommendation"]
    return "\n".join(
        [
            "你的本命雷達結果",
            f"推薦：{recommendation['artist']} {recommendation['member']}",
            f"類型：{_bias_radar_group_type_label(recommendation)}",
            f"命中標籤：{result['matched_label_text']}",
            result["reason"],
            recommendation["url"],
        ]
    )


def _parse_fan_attribute_quiz_state(message: str) -> dict:
    normalized = message.strip()
    empty_scores = {key: 0 for key in FAN_ATTRIBUTE_ORDER}
    if normalized == "粉絲屬性測驗":
        return {
            "question_index": 0,
            "scores": empty_scores,
            "is_result": False,
        }

    parts = normalized.split(":")
    if len(parts) != 3 or parts[0] != "粉絲屬性測驗":
        return {
            "question_index": 0,
            "scores": empty_scores,
            "is_result": False,
        }

    scores = _decode_fan_attribute_scores(parts[2])
    if parts[1] == "result":
        return {
            "question_index": len(FAN_ATTRIBUTE_QUIZ),
            "scores": scores,
            "is_result": True,
        }

    try:
        question_index = int(parts[1])
    except ValueError:
        question_index = 0

    if question_index >= len(FAN_ATTRIBUTE_QUIZ):
        return {
            "question_index": len(FAN_ATTRIBUTE_QUIZ),
            "scores": scores,
            "is_result": True,
        }
    if question_index < 0:
        question_index = 0

    return {
        "question_index": question_index,
        "scores": scores,
        "is_result": False,
    }


def _decode_fan_attribute_scores(encoded_scores: str) -> dict[str, int]:
    values = encoded_scores.split(",")
    scores = {}
    for index, key in enumerate(FAN_ATTRIBUTE_ORDER):
        try:
            scores[key] = int(values[index])
        except (IndexError, ValueError):
            scores[key] = 0
    return scores


def _add_fan_attribute_scores(
    scores: dict[str, int],
    weights: dict[str, int],
) -> dict[str, int]:
    return {
        key: scores.get(key, 0) + weights.get(key, 0)
        for key in FAN_ATTRIBUTE_ORDER
    }


def _fan_attribute_action_text(question_index: int, scores: dict[str, int]) -> str:
    encoded_scores = ",".join(str(scores[key]) for key in FAN_ATTRIBUTE_ORDER)
    if question_index >= len(FAN_ATTRIBUTE_QUIZ):
        return f"粉絲屬性測驗:result:{encoded_scores}"
    return f"粉絲屬性測驗:{question_index}:{encoded_scores}"


def _fan_attribute_result_key(scores: dict[str, int]) -> str:
    return max(
        FAN_ATTRIBUTE_ORDER,
        key=lambda key: (scores.get(key, 0), -FAN_ATTRIBUTE_ORDER.index(key)),
    )


def _fan_attribute_quiz_text(message: str) -> str:
    quiz_state = _parse_fan_attribute_quiz_state(message)
    if not quiz_state["is_result"]:
        question_number = quiz_state["question_index"] + 1
        return f"粉絲屬性測驗 Q{question_number}/5：請在 LINE 卡片中選擇最符合你的答案。"

    scores = quiz_state["scores"]
    fan_type = FAN_ATTRIBUTE_TYPES[_fan_attribute_result_key(scores)]
    score_text = " / ".join(
        f"{FAN_ATTRIBUTE_TYPES[key]['name']} {scores[key]}"
        for key in FAN_ATTRIBUTE_ORDER
    )
    return (
        f"你的粉絲屬性是：{fan_type['name']}\n"
        f"{fan_type['tagline']}\n"
        f"{fan_type['description']}\n"
        f"{fan_type['tip']}\n"
        f"分數：{score_text}"
    )


def _member_quiz_question_response() -> dict:
    quiz = _load_member_quiz_recommendation()
    if not quiz:
        return {"report": MEMBER_QUIZ_EMPTY_TEXT, "flex": None}
    return {
        "report": f"認人測驗：{quiz['question']}",
        "flex": _build_member_quiz_question_flex_contents(quiz),
    }


def _member_quiz_answer_response(message: str) -> dict:
    quiz_id, selected_answer = _parse_member_quiz_answer(message)
    if not quiz_id or not selected_answer:
        return {"report": "這題資料已不存在，請重新抽一題。", "flex": None}

    quiz = _find_member_quiz_row(quiz_id)
    if not quiz:
        return {
            "report": "這題資料已不存在，請重新抽一題。",
            "flex": None,
        }

    if selected_answer == quiz["answer"]:
        report = "答對了！"
    else:
        report = f"答錯了。正解是 {_member_quiz_answer_label(quiz)}。"
    return {"report": report, "flex": _build_member_quiz_again_flex_contents()}


def _member_quiz_answer_label(quiz: dict[str, str]) -> str:
    if quiz.get("answer") == "A":
        return quiz.get("option_a", "").strip()
    return quiz.get("option_b", "").strip()


def _parse_member_quiz_answer(message: str) -> tuple[str, str]:
    parts = message.strip().split(":")
    if len(parts) != 3 or parts[0] != "認人答案" or parts[2] not in {"A", "B"}:
        return "", ""
    return parts[1].strip(), parts[2]


def _find_member_quiz_row(quiz_id: str) -> dict[str, str] | None:
    for row in _load_member_quiz_rows():
        if row["id"] == quiz_id:
            return row
    return None


def _load_member_quiz_recommendation() -> dict[str, str] | None:
    global member_quiz_queue, member_quiz_source_key

    rows = _load_member_quiz_rows()
    if not rows:
        member_quiz_queue = []
        member_quiz_source_key = ()
        return None

    source_key = _member_quiz_source_key(rows)
    if not member_quiz_queue or member_quiz_source_key != source_key:
        member_quiz_queue = rows[:]
        random.shuffle(member_quiz_queue)
        member_quiz_source_key = source_key
    return member_quiz_queue.pop()


def _load_member_quiz_rows() -> list[dict[str, str]]:
    csv_path = settings.base_dir / "data" / "play_zone" / "member_quiz.csv"
    return _load_cached_csv_rows(
        csv_path,
        _member_quiz_row_is_usable,
        _normalize_member_quiz_row,
    )


def _normalize_member_quiz_row(row: dict[str, str]) -> dict[str, str]:
    return {
        "id": row.get("id", "").strip(),
        "question": row.get("question", "").strip(),
        "image_path": row.get("image_path", "").strip(),
        "option_a": row.get("option_a", "").strip(),
        "option_b": row.get("option_b", "").strip(),
        "answer": row.get("answer", "").strip().upper(),
    }


def _member_quiz_row_is_usable(row: dict[str, str]) -> bool:
    normalized = _normalize_member_quiz_row(row)
    required_fields = ("id", "question", "image_path", "option_a", "option_b")
    return (
        all(normalized[field] for field in required_fields)
        and normalized["answer"] in {"A", "B"}
        and _member_quiz_filename_from_image_path(normalized["image_path"]) is not None
    )


def _member_quiz_source_key(
    rows: list[dict[str, str]],
) -> tuple[tuple[str, str, str, str, str, str], ...]:
    return tuple(
        (
            row.get("id", "").strip(),
            row.get("question", "").strip(),
            row.get("image_path", "").strip(),
            row.get("option_a", "").strip(),
            row.get("option_b", "").strip(),
            row.get("answer", "").strip(),
        )
        for row in rows
    )


def _member_quiz_image_dir() -> Path:
    return settings.base_dir / "data" / "play_zone" / "member_quiz_images"


def _member_quiz_image_url(quiz: dict[str, str]) -> str:
    filename = _member_quiz_filename_from_image_path(quiz.get("image_path", ""))
    if filename is None:
        filename = ""
    forwarded_host = request.headers.get("X-Forwarded-Host", "").split(",", 1)[0].strip()
    forwarded_proto = request.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip()
    host = forwarded_host or request.host
    scheme = forwarded_proto or request.scheme
    if host.endswith(".hf.space"):
        return (
            "https://huggingface.co/spaces/EscA95103040126/kpop-agent/resolve/main/"
            f"data/play_zone/member_quiz_images/{quote(filename)}"
        )
    return f"{scheme}://{host}/play-zone/images/{quote(filename)}"


def _send_member_quiz_flex_image(filename: str):
    try:
        from PIL import Image, ImageOps

        source_path, cache_path = _member_quiz_flex_image_cache_paths(filename)
        if not cache_path.exists():
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(source_path) as image:
                source = ImageOps.exif_transpose(image).convert("RGB")
                side = max(source.size)
                canvas = Image.new("RGB", (side, side), color=(247, 250, 248))
                offset = ((side - source.width) // 2, (side - source.height) // 2)
                canvas.paste(source, offset)
                canvas.save(cache_path, format="JPEG", quality=92, optimize=True)
    except Exception:
        logger.exception("Could not build member quiz Flex image: %s", filename)
        abort(404)

    return send_file(
        cache_path,
        mimetype="image/jpeg",
        download_name=f"{Path(filename).stem}_flex.jpg",
        max_age=60 * 60,
    )


def _member_quiz_flex_image_cache_paths(filename: str) -> tuple[Path, Path]:
    source_path = _member_quiz_image_dir() / filename
    stat = source_path.stat()
    cache_dir = settings.base_dir / "data" / "cache" / "play_zone" / "flex"
    cache_name = f"{Path(filename).stem}-{stat.st_mtime_ns}-{stat.st_size}.jpg"
    return source_path, cache_dir / cache_name


def _member_quiz_filename_from_image_path(image_path: str) -> str | None:
    normalized = image_path.strip().replace("\\", "/")
    filename = normalized.rsplit("/", 1)[-1]
    return _safe_member_quiz_image_filename(filename)


def _safe_member_quiz_image_filename(filename: str) -> str | None:
    normalized = filename.strip().replace("\\", "/")
    path = Path(normalized)
    if not normalized or "/" in normalized or path.name != normalized:
        return None
    if path.suffix.casefold() not in MEMBER_QUIZ_IMAGE_EXTENSIONS:
        return None
    return normalized


def _daily_kpop_response(message: str, user_id: str = "analyze-user") -> dict:
    category = _daily_kpop_category(message)
    if category == "MV" and radar_repo.enabled:
        try:
            recommendation = radar_repo.recommend_daily_mv(user_id)
        except Exception:
            logger.exception("Supabase daily MV recommendation failed; using CSV fallback.")
        else:
            if recommendation:
                return {
                    "report": _format_kpop_item_recommendation(category, recommendation),
                    "flex": _build_daily_kpop_redraw_flex_contents(
                        save_item_id=str(recommendation.get("id") or "")
                    ),
                }
            return {
                "report": "目前 Supabase 還沒有可推薦的 MV，請先匯入 kpop_items。",
                "flex": _build_daily_kpop_redraw_flex_contents(),
            }

    recommendation = _load_daily_kpop_recommendation(category)
    if recommendation:
        return {
            "report": _format_daily_kpop_recommendation(category, recommendation),
            "flex": _build_recommendation_action_flex_contents(
                item_type=_daily_kpop_item_type(category),
                url=recommendation.get("url", ""),
                redraw_label=f"再抽{category}",
                redraw_text=_daily_kpop_redraw_text(category),
                daily_redraw=True,
                fallback_flex=_build_daily_kpop_redraw_flex_contents(),
            ),
        }
    return {
        "report": (
            f"每日一首 K-pop：{category}\n"
            f"入口已建立。請先在 {_daily_kpop_csv_label(category)} 補上歌曲標題與連結。"
        ),
        "flex": _build_daily_kpop_redraw_flex_contents(),
    }


def _daily_kpop_placeholder_text(message: str) -> str:
    category = _daily_kpop_category(message)
    recommendation = _load_daily_kpop_recommendation(category)
    if recommendation:
        return _format_daily_kpop_recommendation(category, recommendation)
    return (
        f"每日一首 K-pop：{category}\n"
        f"入口已建立。請先在 {_daily_kpop_csv_label(category)} 補上歌曲標題與連結。"
    )


def _daily_kpop_category(message: str) -> str:
    normalized = message.strip().replace(" ", "")
    if "直拍" in normalized:
        return "直拍"
    if "經典舞台" in normalized:
        return "經典舞台"
    return "MV"


def _daily_kpop_item_type(category: str) -> str:
    if category == "直拍":
        return "fancam"
    if category == "MV":
        return "mv"
    return ""


def _daily_kpop_redraw_text(category: str) -> str:
    if category == "直拍":
        return "每日直拍"
    if category == "經典舞台":
        return "每日 經典舞台"
    return "每日 MV"


def _load_daily_kpop_recommendation(category: str) -> dict[str, str] | None:
    rows = _load_daily_kpop_rows(category)
    if not rows:
        return None

    source_key = _daily_kpop_source_key(rows)
    queue = daily_kpop_queues.get(category, [])
    if not queue or daily_kpop_source_keys.get(category) != source_key:
        queue = rows[:]
        random.shuffle(queue)
        daily_kpop_queues[category] = queue
        daily_kpop_source_keys[category] = source_key
    return daily_kpop_queues[category].pop()


def _load_daily_kpop_rows(category: str) -> list[dict[str, str]]:
    csv_path = settings.base_dir / "data" / "play_zone" / _daily_kpop_csv_filename(category)
    return _load_cached_csv_rows(csv_path, _daily_kpop_row_is_usable)


def _daily_kpop_row_is_usable(row: dict[str, str]) -> bool:
    return bool(row.get("title", "").strip() and row.get("url", "").strip())


def _load_photo_card_recommendation() -> dict[str, str] | None:
    global photo_card_queue, photo_card_source_key

    rows = _load_photo_card_rows()
    if not rows:
        photo_card_queue = []
        photo_card_source_key = ()
        return None

    source_key = _photo_card_source_key(rows)
    if not photo_card_queue or photo_card_source_key != source_key:
        photo_card_queue = rows[:]
        random.shuffle(photo_card_queue)
        photo_card_source_key = source_key
    return photo_card_queue.pop()


def _load_photo_card_rows() -> list[dict[str, str]]:
    csv_path = settings.base_dir / "data" / "play_zone" / "photo_cards.csv"
    return _load_cached_csv_rows(csv_path, _photo_card_row_is_usable)


def _photo_card_row_is_usable(row: dict[str, str]) -> bool:
    return bool(
        row.get("artist", "").strip()
        and row.get("type", "").strip()
        and row.get("url", "").strip()
    )


def _photo_card_source_key(rows: list[dict[str, str]]) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (
            row.get("artist", "").strip(),
            row.get("type", "").strip(),
            row.get("url", "").strip(),
        )
        for row in rows
    )


def _format_photo_card_recommendation(card: dict[str, str]) -> str:
    artist = card.get("artist", "").strip()
    card_type = card.get("type", "").strip()
    url = card.get("url", "").strip()
    return "\n".join(
        [
            "✨ 神圖抽卡結果 ✨",
            "",
            "🎉 恭喜你今天抽到",
            f"💖 {artist}",
            f"📸 類型：{card_type}",
            "",
            "🔗 點開看神圖",
            url,
        ]
    )


def _daily_kpop_source_key(rows: list[dict[str, str]]) -> tuple[tuple[str, str, str, str], ...]:
    return tuple(
        (
            row.get("artist", "").strip(),
            row.get("title", "").strip(),
            row.get("member", "").strip(),
            row.get("url", "").strip(),
        )
        for row in rows
    )


def _format_daily_kpop_recommendation(category: str, recommendation: dict[str, str]) -> str:
    artist = recommendation.get("artist", "").strip()
    title = recommendation.get("title", "").strip()
    url = recommendation.get("url", "").strip()
    member = recommendation.get("member", "").strip()

    lines = [f"🎵 今日推薦 {category}", f"今天推薦的是 {artist} 的《{title}》。"]
    if category == "直拍" and member:
        lines.append(f"直拍成員：{member}")
    lines.append(url)
    return "\n".join(lines)


def _format_kpop_item_recommendation(category: str, recommendation: dict[str, object]) -> str:
    artist = str(recommendation.get("artist") or "").strip()
    title = str(recommendation.get("title") or "").strip()
    url = str(recommendation.get("url") or "").strip()
    member = str(recommendation.get("member") or "").strip()

    lines = [f"🎵 今日推薦 {category}", f"今天推薦的是 {artist} 的《{title}》。"]
    if member:
        lines.append(f"成員：{member}")
    if url:
        lines.append(url)
    return "\n".join(lines)


def _build_recommendation_action_flex_contents(
    *,
    item_type: str,
    url: str,
    redraw_label: str,
    redraw_text: str,
    daily_redraw: bool = False,
    fallback_flex: dict | None = None,
) -> dict:
    item = None
    if item_type and radar_repo.enabled:
        try:
            item = radar_repo.find_item_by_url(item_type, url)
        except Exception:
            logger.exception("Could not look up K-pop Radar item for save button.")
    if item:
        if daily_redraw:
            return _build_daily_kpop_redraw_flex_contents(
                save_item_id=str(item.get("id") or "")
            )
        return _build_kpop_radar_save_prompt_flex_contents(
            item,
            _kpop_radar_item_type_label(item_type),
            redraw_label=redraw_label,
            redraw_text=redraw_text,
        )
    return fallback_flex or _build_single_redraw_flex_contents(redraw_label, redraw_text)


def _build_kpop_radar_save_prompt_flex_contents(
    recommendation: dict[str, object],
    category: str,
    *,
    redraw_label: str,
    redraw_text: str,
) -> dict:
    item_id = str(recommendation.get("id") or "")
    item_type = str(recommendation.get("item_type") or "mv")
    label = "收藏至口袋"
    contents = [
        {
            "type": "text",
            "text": "喜歡這個推薦嗎？",
            "size": "xs",
            "color": KPOP_RADAR_TEXT_COLOR,
            "wrap": True,
        },
    ]
    if item_id:
        contents.append(_kpop_radar_save_button(item_id, label=label))
    contents.append(_single_redraw_button(redraw_label, redraw_text))
    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": KPOP_RADAR_BODY_COLOR,
            "paddingAll": "14px",
            "spacing": "sm",
            "contents": contents,
        },
    }


def _kpop_radar_save_button(item_id: str, label: str = "收藏至口袋") -> dict:
    return {
        "type": "button",
        "style": "primary",
        "height": "sm",
        "color": KPOP_RADAR_ACCENT_COLOR,
        "action": {
            "type": "postback",
            "label": label,
            "data": f"action=save_item&item_id={item_id}",
        },
    }


def _build_single_redraw_flex_contents(label: str, text: str) -> dict:
    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#F4F8FC",
            "paddingAll": "14px",
            "spacing": "sm",
            "contents": [
                {
                    "type": "text",
                    "text": "想再抽一次嗎？",
                    "size": "xs",
                    "color": "#314B60",
                    "wrap": True,
                },
                _single_redraw_button(label, text),
            ],
        },
    }


def _single_redraw_button(label: str, text: str) -> dict:
    if text == "神圖抽卡":
        return {
            "type": "button",
            "style": "primary",
            "height": "sm",
            "color": PLAY_ZONE_ACCENT_COLOR,
            "action": {
                "type": "message",
                "label": label,
                "text": text,
            },
        }
    return _daily_redraw_button(label, text)


def _kpop_radar_item_type_label(item_type: str) -> str:
    return {
        "mv": "MV",
        "fancam": "直拍",
        "photo": "照片",
    }.get(item_type, "內容")


def _daily_kpop_csv_filename(category: str) -> str:
    if category == "直拍":
        return "daily_fancam.csv"
    if category == "經典舞台":
        return "daily_stage.csv"
    return "daily_mv.csv"


def _daily_kpop_csv_label(category: str) -> str:
    return f"data/play_zone/{_daily_kpop_csv_filename(category)}"


def _is_weekly_chart_report(report: str) -> bool:
    return report.lstrip().startswith("# 本週 K-pop 榜單")


def _mode(is_mock: bool) -> str:
    return "mock" if is_mock else "real"


def _naver_mode() -> str:
    if settings.use_naver_mock:
        return "mock"
    return "real" if NaverNewsClient(settings).real_api_available() else "mock"


def _should_skip_line_event(event: MessageEvent, user_text: str) -> bool:
    event_id = _line_event_id(event)
    if event_id and _is_line_event_processed_or_processing(event_id):
        logger.info("Skipping duplicate LINE webhook event: %s", event_id)
        return True

    if _is_line_message_debounced(event, user_text):
        logger.info("Skipping debounced LINE message: %s", user_text)
        if event_id:
            line_processing_event_ids.discard(event_id)
        return True

    return False


def _line_event_id(event: object) -> str:
    for attr_name in ("webhook_event_id", "webhookEventId"):
        value = getattr(event, attr_name, "")
        if value:
            return str(value)
    return ""


def _is_line_event_processed_or_processing(event_id: str) -> bool:
    if event_id in line_processing_event_ids:
        return True

    processed_event_ids = _line_processed_event_ids()
    now = time()
    _prune_ordered_timestamps(
        processed_event_ids,
        now=now,
        ttl_seconds=LINE_EVENT_DEDUPE_TTL_SECONDS,
        max_size=LINE_EVENT_DEDUPE_MAX_SIZE,
    )
    if event_id in processed_event_ids:
        processed_event_ids.move_to_end(event_id)
        return True

    line_processing_event_ids.add(event_id)
    return False


def _mark_line_event_processed(event: MessageEvent) -> None:
    event_id = _line_event_id(event)
    if not event_id:
        return

    processed_event_ids = _line_processed_event_ids()
    processed_event_ids[event_id] = time()
    _prune_ordered_timestamps(
        processed_event_ids,
        now=processed_event_ids[event_id],
        ttl_seconds=LINE_EVENT_DEDUPE_TTL_SECONDS,
        max_size=LINE_EVENT_DEDUPE_MAX_SIZE,
    )
    line_processing_event_ids.discard(event_id)
    _save_line_processed_event_ids(processed_event_ids)


def _clear_line_event_processing(event: MessageEvent) -> None:
    event_id = _line_event_id(event)
    if event_id:
        line_processing_event_ids.discard(event_id)


def _line_processed_event_ids() -> OrderedDict[str, float]:
    global line_processed_event_ids
    if line_processed_event_ids is not None:
        return line_processed_event_ids

    line_processed_event_ids = OrderedDict()
    if not LINE_EVENT_DEDUPE_PATH.exists():
        return line_processed_event_ids

    try:
        raw_event_ids = json.loads(LINE_EVENT_DEDUPE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not read LINE event dedupe cache; starting fresh.")
        return line_processed_event_ids

    if not isinstance(raw_event_ids, dict):
        return line_processed_event_ids

    for event_id, timestamp in raw_event_ids.items():
        try:
            line_processed_event_ids[str(event_id)] = float(timestamp)
        except (TypeError, ValueError):
            continue
    return line_processed_event_ids


def _save_line_processed_event_ids(event_ids: OrderedDict[str, float]) -> None:
    try:
        LINE_EVENT_DEDUPE_PATH.parent.mkdir(parents=True, exist_ok=True)
        LINE_EVENT_DEDUPE_PATH.write_text(
            json.dumps(event_ids, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        logger.warning("Could not write LINE event dedupe cache.", exc_info=True)


def _is_line_message_debounced(event: MessageEvent, user_text: str) -> bool:
    key = _line_message_key(event, user_text)
    if key is None:
        return False

    now = monotonic()
    _prune_ordered_timestamps(
        line_recent_message_keys,
        now=now,
        ttl_seconds=LINE_MESSAGE_DEBOUNCE_SECONDS,
        max_size=200,
    )
    if key in line_recent_message_keys:
        line_recent_message_keys[key] = now
        line_recent_message_keys.move_to_end(key)
        return True

    line_recent_message_keys[key] = now
    return False


def _line_message_key(event: MessageEvent, user_text: str) -> tuple[str, str] | None:
    source_id = _line_user_id(event)
    if not source_id:
        return None
    return source_id, user_text.strip()


def _line_user_id(event: object) -> str:
    source = getattr(event, "source", None)
    return str(
        getattr(source, "user_id", "")
        or getattr(source, "group_id", "")
        or getattr(source, "room_id", "")
    )


def _prune_ordered_timestamps(
    timestamps: OrderedDict,
    *,
    now: float,
    ttl_seconds: float,
    max_size: int,
) -> None:
    expired_keys = [
        key
        for key, timestamp in timestamps.items()
        if now - float(timestamp) > ttl_seconds
    ]
    for key in expired_keys:
        timestamps.pop(key, None)

    while len(timestamps) > max_size:
        timestamps.popitem(last=False)


def _sqlite_status() -> dict:
    if not settings.database_path.exists():
        return {
            "ok": False,
            "path": str(settings.database_path),
            "error": "database file not found",
        }

    try:
        with sqlite3.connect(settings.database_path) as conn:
            table_exists = conn.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table' AND name = 'chart_history'
                """
            ).fetchone()
            if not table_exists:
                return {
                    "ok": False,
                    "path": str(settings.database_path),
                    "error": "chart_history table not found",
                }

            total_rows, min_date, max_date = conn.execute(
                "SELECT COUNT(*), MIN(chart_date), MAX(chart_date) FROM chart_history"
            ).fetchone()
            return {
                "ok": True,
                "path": str(settings.database_path),
                "chart_history_rows": total_rows,
                "chart_date_min": min_date,
                "chart_date_max": max_date,
            }
    except sqlite3.Error as exc:
        return {
            "ok": False,
            "path": str(settings.database_path),
            "error": str(exc),
        }


if line_handler is not None and MessageEvent is not None and TextMessageContent is not None:

    def _reply_line_event(event: MessageEvent | PostbackEvent, user_text: str) -> None:
        if _should_skip_line_event(event, user_text):
            return
        if not line_configuration:
            _clear_line_event_processing(event)
            return
        line_user_id = _line_user_id(event) or "line-user"
        try:
            _ensure_kpop_radar_user(line_user_id)
        except Exception:
            logger.exception("Could not initialize K-pop Radar user.")
        with ApiClient(line_configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            reply_messages = None
            if _is_artist_picker_request(user_text):
                reply_message = _build_artist_picker_message()
                fallback_text = "請輸入：分析 aespa、分析 IVE、分析 NCT"
            elif _is_kpop_radar_request(user_text):
                response = _kpop_radar_response(user_text, user_id=line_user_id)
                fallback_text = fit_line_text(response["report"])
                if _kpop_radar_action(user_text) == "open_pref":
                    reply_message = TextMessage(
                        text=fallback_text,
                        quickReply=_build_kpop_radar_preference_quick_reply(),
                    )
                    reply_messages = [
                        reply_message,
                        _build_line_flex_message(
                            response["flex"],
                            alt_text="修改推薦偏好",
                        ),
                    ]
                elif response["flex"] is not None:
                    reply_message = _build_line_flex_message(
                        response["flex"],
                        alt_text="我的K-pop 口袋",
                    )
                else:
                    reply_message = TextMessage(text=fallback_text)
            elif _is_help_request(user_text):
                reply_message = _build_help_message()
                fallback_text = reply_message.text
            elif _is_play_zone_request(user_text):
                reply_message = _build_line_flex_message(
                    _build_play_zone_flex_contents(),
                    alt_text="K-pop Play Zone",
                )
                fallback_text = "請選擇：本命雷達測驗、粉絲屬性測驗、認人測驗、神圖抽卡"
            elif _is_ai_curator_entry_request(user_text):
                reply_message = _build_line_flex_message(
                    _build_ai_curator_entry_flex_contents(),
                    alt_text="AI 入坑",
                )
                fallback_text = "請直接輸入你的 K-pop 偏好，例如：我想入坑清冷感、舞台強的女團。"
            elif _is_ai_curator_preference_request(user_text):
                response = _ai_curator_response(user_text, user_id=line_user_id)
                fallback_text = fit_line_text(response["report"])
                reply_message = TextMessage(text=fallback_text)
                reply_messages = [
                    reply_message,
                    _build_line_flex_message(
                        response["flex"],
                        alt_text="AI 入坑",
                    ),
                ]
            elif _is_bias_radar_quiz_request(user_text, line_user_id):
                response = _bias_radar_quiz_response(line_user_id, user_text)
                reply_message = _build_line_flex_message(
                    response["flex"],
                    alt_text="本命雷達測驗",
                )
                fallback_text = fit_line_text(response["report"])
            elif _is_fan_attribute_quiz_request(user_text):
                reply_message = _build_line_flex_message(
                    _build_fan_attribute_quiz_flex_contents(user_text),
                    alt_text="粉絲屬性測驗",
                )
                fallback_text = fit_line_text(_fan_attribute_quiz_text(user_text))
            elif _is_member_quiz_answer(user_text):
                response = _member_quiz_answer_response(user_text)
                fallback_text = fit_line_text(response["report"])
                reply_message = TextMessage(text=fallback_text)
                if response["flex"] is not None:
                    reply_messages = [
                        reply_message,
                        _build_line_flex_message(
                            response["flex"],
                            alt_text="再來一題？",
                        ),
                    ]
            elif _is_member_quiz_request(user_text):
                response = _member_quiz_question_response()
                fallback_text = fit_line_text(response["report"])
                if response["flex"] is None:
                    reply_message = TextMessage(text=fallback_text)
                else:
                    reply_message = _build_line_flex_message(
                        response["flex"],
                        alt_text="認人測驗",
                    )
            elif _is_daily_kpop_request(user_text):
                reply_message = _build_line_flex_message(
                    _build_daily_kpop_flex_contents(),
                    alt_text="每日一首 K-pop",
                )
                fallback_text = "請選擇：每日 MV、每日直拍、每日經典舞台"
            elif _is_daily_kpop_category_request(user_text):
                response = _daily_kpop_response(user_text, user_id=line_user_id)
                fallback_text = fit_line_text(response["report"])
                reply_message = TextMessage(text=fallback_text)
                if response["flex"] is not None:
                    reply_messages = [
                        reply_message,
                        _build_line_flex_message(
                            response["flex"],
                            alt_text="再抽一首 K-pop",
                        ),
                    ]
            elif _is_photo_card_request(user_text):
                response = _photo_card_response()
                report_text = response["report"]
                fallback_text = fit_line_text(report_text)
                reply_message = TextMessage(text=fallback_text)
                if response["flex"] is not None:
                    reply_messages = [
                        reply_message,
                        _build_line_flex_message(
                            response["flex"],
                            alt_text="再抽一次",
                        ),
                    ]
            else:
                if _is_historical_weekly_chart_request(user_text):
                    report = agent.generate_weekly_chart_report_for_date(
                        _historical_weekly_chart_date(user_text)
                    )
                    reply_message = TextMessage(text=fit_line_text(report))
                    fallback_text = fit_line_text(report)
                elif route_message(user_text).name == "weekly_chart":
                    chart_cache = agent.get_weekly_chart_cache()
                    report = chart_cache["report"]
                    fallback_text = fit_line_text(report)
                    history_qr = _build_weekly_chart_history_quick_reply(
                        current_chart_date=chart_cache.get("chart", {}).get("chart_date", ""),
                    )
                    reply_message = TextMessage(
                        text=fallback_text,
                        quickReply=history_qr,
                    )
                elif _is_full_artist_report_request(user_text):
                    intent = route_message(user_text)
                    artist_cache = agent.get_artist_analysis_cache(
                        intent.artist,
                        period_months=intent.period_months,
                    )
                    report = artist_cache["report"]
                    reply_message = _build_line_flex_message(
                        artist_cache["flex"],
                        alt_text=f"{artist_cache['artist']} K-pop 分析報告",
                    )
                    fallback_text = fit_line_text(report)
                elif _is_ai_curator_reason_followup(user_text):
                    response = _ai_curator_reason_followup_response(
                        user_text,
                        user_id=line_user_id,
                    )
                    fallback_text = fit_line_text(response["report"])
                    reply_message = TextMessage(text=fallback_text)
                else:
                    fallback_text = fit_line_text(
                        _reply_text_for_message(user_text, user_id=line_user_id)
                    )
                    reply_message = TextMessage(text=fallback_text)
                    report = ""

            if reply_message is None:
                _clear_line_event_processing(event)
                return

            try:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=reply_messages or [reply_message],
                    )
                )
                _mark_line_event_processed(event)
            except Exception as exc:
                logger.warning("Flex reply failed; retrying with text fallback: %s", exc)
                try:
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=fallback_text)],
                        )
                    )
                    _mark_line_event_processed(event)
                except Exception as fallback_exc:
                    _clear_line_event_processing(event)
                    logger.exception("LINE reply failed: %s", fallback_exc)

    @line_handler.add(MessageEvent, message=TextMessageContent)
    def handle_text_message(event: MessageEvent) -> None:
        _reply_line_event(event, event.message.text)

    if PostbackEvent is not None:

        @line_handler.add(PostbackEvent)
        def handle_postback(event: PostbackEvent) -> None:
            postback_data = getattr(event.postback, "data", "")
            _reply_line_event(event, str(postback_data))

    if FollowEvent is not None:

        @line_handler.add(FollowEvent)
        def handle_follow(event: FollowEvent) -> None:
            if not line_configuration:
                return
            try:
                line_user_id = _line_user_id(event) or "line-user"
                try:
                    _ensure_kpop_radar_user(line_user_id)
                except Exception:
                    logger.exception("Could not initialize K-pop Radar user on follow.")
                with ApiClient(line_configuration) as api_client:
                    line_bot_api = MessagingApi(api_client)
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[_build_welcome_message()],
                        )
                    )
            except Exception:
                logger.exception("Welcome reply failed.")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=settings.port)
