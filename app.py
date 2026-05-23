from __future__ import annotations

import json
import csv
import logging
import random
import re
import sqlite3
import unicodedata
from io import BytesIO
from collections import OrderedDict
from pathlib import Path
from time import monotonic, time
from urllib.parse import quote

from flask import Flask, abort, jsonify, request, send_file, send_from_directory

from src.agent import KpopAnalysisAgent, SUPPORTED_ARTISTS
from src.config import settings
from src.router import ARTIST_PATTERNS, route_message
from src.tools.bugs_chart import fetch_bugs_weekly_chart
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
        ImageMessage,
        MessageAction,
        MessagingApi,
        QuickReply,
        QuickReplyItem,
        ReplyMessageRequest,
        ButtonsTemplate,
        TemplateMessage,
        TextMessage,
    )
    from linebot.v3.webhooks import MessageEvent, PostbackEvent, TextMessageContent
except ImportError:  # pragma: no cover - lets local mock mode run without LINE SDK.
    WebhookHandler = None
    InvalidSignatureError = Exception
    ApiClient = None
    Configuration = None
    FlexContainer = None
    FlexMessage = None
    ImageMessage = None
    MessageAction = None
    MessagingApi = None
    QuickReply = None
    QuickReplyItem = None
    ReplyMessageRequest = None
    ButtonsTemplate = None
    TemplateMessage = None
    TextMessage = None
    MessageEvent = None
    PostbackEvent = None
    TextMessageContent = None


app = Flask(__name__)
agent = KpopAnalysisAgent()
logger = logging.getLogger(__name__)
daily_kpop_queues: dict[str, list[dict[str, str]]] = {}
daily_kpop_source_keys: dict[str, tuple[tuple[str, str, str, str], ...]] = {}
photo_card_queue: list[dict[str, str]] = []
photo_card_source_key: tuple[tuple[str, str, str], ...] = ()
member_quiz_queue: list[dict[str, str]] = []
member_quiz_source_key: tuple[tuple[str, str, str, str, str, str], ...] = ()
BIAS_RADAR_TRIGGERS = {"本命雷達測驗", "本命雷達", "測本命"}
bias_radar_sessions: dict[str, dict[str, object]] = {}
PHOTO_CARD_EMPTY_TEXT = "目前還沒有神圖資料，請先補 data/play_zone/photo_cards.csv"
MEMBER_QUIZ_EMPTY_TEXT = (
    "目前還沒有認人測驗題目，請先補 data/play_zone/member_quiz.csv，"
    "並把圖片放到 data/play_zone/member_quiz_images/"
)
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
    status = "ok" if sqlite_status["ok"] and bugs_tool_available else "degraded"
    return {
        "status": status,
        "sqlite_ok": sqlite_status["ok"],
        "sqlite": sqlite_status,
        "bugs_tool_available": bugs_tool_available,
        "naver_mode": _naver_mode(),
        "gemini_mode": _mode(settings.use_gemini_mock),
        "line_mode": _mode(settings.use_line_mock),
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


@app.post("/analyze")
def analyze() -> tuple[dict, int]:
    payload = request.get_json(silent=True) or {}
    message = payload.get("message", "")
    artist = payload.get("artist", "")
    user_id = str(payload.get("user_id") or "analyze-user")
    if not message and artist:
        message = f"分析 {artist}"
    if not message:
        return {"error": "message or artist is required"}, 400
    intent = route_message(message)
    if _is_play_zone_request(message):
        response = {
            "report": "K-pop Play Zone",
            "flex": _build_play_zone_flex_contents(),
        }
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
        report = _daily_kpop_placeholder_text(message)
        response = {
            "report": report,
            "flex": _build_daily_kpop_redraw_flex_contents(),
        }
    elif _is_photo_card_request(message):
        report = _photo_card_placeholder_text()
        response = {
            "report": report,
            "flex": (
                None
                if report == PHOTO_CARD_EMPTY_TEXT
                else _build_photo_card_redraw_flex_contents()
            ),
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
    elif artist or _is_full_artist_report_request(message):
        artist_cache = agent.get_artist_cache(
            intent.artist,
            period_months=intent.period_months,
        )
        response = {
            "report": artist_cache["report"],
            "cache": {
                "type": "artist",
                "artist": artist_cache["artist"],
                "cached_at": artist_cache["cached_at"],
            },
            "flex": artist_cache["flex"],
        }
    else:
        report = _reply_text_for_message(message)
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
            reply = fit_line_text(_reply_text_for_message(message))
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


def _build_line_image_message(image_url: str, alt_text: str = "認人測驗圖片"):
    if ImageMessage is None:
        return TextMessage(text=alt_text)
    return ImageMessage(originalContentUrl=image_url, previewImageUrl=image_url)


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
        accent_color="#8B5E52",
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
            "backgroundColor": "#B5536C",
            "paddingAll": "18px",
            "contents": [
                {
                    "type": "text",
                    "text": "本命雷達測驗",
                    "size": "xs",
                    "color": "#FFE6ED",
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
            "backgroundColor": "#FFF7F9",
            "paddingAll": "18px",
            "spacing": "md",
            "contents": [
                {
                    "type": "text",
                    "text": question["question"],
                    "size": "md",
                    "weight": "bold",
                    "color": "#5C2F3A",
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
                "color": "#B5536C",
            },
        ],
    }


def _build_bias_radar_result_flex_contents(result: dict) -> dict:
    recommendation = result["recommendation"]
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#B5536C",
            "paddingAll": "18px",
            "contents": [
                {
                    "type": "text",
                    "text": "你的本命雷達結果",
                    "size": "xs",
                    "color": "#FFE6ED",
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
            "backgroundColor": "#FFF7F9",
            "paddingAll": "18px",
            "spacing": "md",
            "contents": [
                {
                    "type": "text",
                    "text": f"類型：{_bias_radar_group_type_label(recommendation)}",
                    "size": "sm",
                    "color": "#5C2F3A",
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": f"命中標籤：{result['matched_label_text']}",
                    "size": "sm",
                    "color": "#5C2F3A",
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": result["reason"],
                    "size": "sm",
                    "color": "#7A3A4A",
                    "wrap": True,
                },
                {
                    "type": "button",
                    "style": "primary",
                    "height": "sm",
                    "color": "#8B5E52",
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
            "backgroundColor": "#8B5E52",
            "paddingAll": "18px",
            "contents": [
                {
                    "type": "text",
                    "text": "粉絲屬性測驗",
                    "size": "xs",
                    "color": "#FDEBD8",
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
            "backgroundColor": "#FAF7F4",
            "paddingAll": "18px",
            "spacing": "md",
            "contents": [
                {
                    "type": "text",
                    "text": question["question"],
                    "size": "md",
                    "weight": "bold",
                    "color": "#5C4033",
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
                "color": "#8B5E52",
            },
            {
                "type": "text",
                "text": option["description"],
                "size": "xs",
                "color": "#6B4A3E",
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
            "backgroundColor": "#8B5E52",
            "paddingAll": "18px",
            "contents": [
                {
                    "type": "text",
                    "text": "你的粉絲屬性是",
                    "size": "xs",
                    "color": "#FDEBD8",
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
            "backgroundColor": "#FAF7F4",
            "paddingAll": "18px",
            "spacing": "md",
            "contents": [
                {
                    "type": "text",
                    "text": fan_type["tagline"],
                    "size": "md",
                    "weight": "bold",
                    "color": "#5C4033",
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": fan_type["description"],
                    "size": "sm",
                    "color": "#6B4A3E",
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": fan_type["tip"],
                    "size": "sm",
                    "color": "#8B5E52",
                    "wrap": True,
                },
                {
                    "type": "text",
                    "text": f"分數：{score_text}",
                    "size": "xs",
                    "color": "#8C756C",
                    "wrap": True,
                },
                {
                    "type": "button",
                    "style": "primary",
                    "height": "sm",
                    "color": "#8B5E52",
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
        accent_color="#C4956A",
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


def _build_daily_kpop_redraw_flex_contents() -> dict:
    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#C4956A",
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
            "backgroundColor": "#FAF7F4",
            "paddingAll": "14px",
            "spacing": "sm",
            "contents": [
                {
                    "type": "text",
                    "text": "想再抽哪一種 K-pop 推薦？",
                    "size": "xs",
                    "color": "#5C4033",
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
            ],
        },
    }


def _build_photo_card_redraw_flex_contents() -> dict:
    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#8B5E52",
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
            "backgroundColor": "#FAF7F4",
            "paddingAll": "14px",
            "spacing": "sm",
            "contents": [
                {
                    "type": "text",
                    "text": "想再抽一張神圖嗎？",
                    "size": "xs",
                    "color": "#5C4033",
                    "wrap": True,
                },
                {
                    "type": "button",
                    "style": "primary",
                    "height": "sm",
                    "color": "#8B5E52",
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
        "color": "#8B5E52",
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
                    "color": "#FDEBD8",
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
            "backgroundColor": "#FAF7F4",
            "paddingAll": "18px",
            "spacing": "md",
            "contents": [
                {
                    "type": "text",
                    "text": description,
                    "size": "sm",
                    "color": "#5C4033",
                    "wrap": True,
                },
                *[_selection_page_button(item, accent_color) for item in items],
            ],
        },
    }


def _selection_page_button(item: dict[str, str], accent_color: str) -> dict:
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
                        "color": "#6B4A3E",
                        "wrap": True,
                    },
                ],
            },
        ],
    }


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


def _is_artist_picker_request(message: str) -> bool:
    normalized = message.strip().casefold()
    return normalized in {"分析", "分析藝人", "選擇藝人", "artist", "藝人"}


def _is_help_request(message: str) -> bool:
    return message.strip() in {"使用說明", "help", "Help", "HELP"}


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


def _is_fan_attribute_quiz_request(message: str) -> bool:
    normalized = message.strip()
    return normalized == "粉絲屬性測驗" or normalized.startswith("粉絲屬性測驗:")


def _is_bias_radar_quiz_request(message: str, user_id: str = "analyze-user") -> bool:
    normalized = message.strip()
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
    return normalized in {"粉絲屬性測驗", "神圖抽卡", "我的雷達"}


def _is_daily_kpop_category_request(message: str) -> bool:
    normalized = message.strip()
    return normalized in {"每日 MV", "每日MV", "每日直拍", "每日 經典舞台", "每日經典舞台"}


def _is_photo_card_request(message: str) -> bool:
    normalized = message.strip()
    return normalized in {"神圖抽卡", "再抽一次神圖", "再抽一張", "抽卡"}


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


def _reply_text_for_message(message: str) -> str:
    if _is_help_request(message):
        return _build_help_message().text
    if _is_play_zone_request(message):
        return "請在 LINE 中點選 K-pop Play Zone 卡片開始互動。"
    if _is_bias_radar_quiz_request(message):
        return _bias_radar_quiz_response("text-user", message)["report"]
    if _is_fan_attribute_quiz_request(message):
        return _fan_attribute_quiz_text(message)
    if _is_member_quiz_answer(message):
        return _member_quiz_answer_response(message)["report"]
    if _is_member_quiz_request(message):
        return _member_quiz_question_response()["report"]
    if _is_daily_kpop_request(message):
        return "請在 LINE 中點選每日一首 K-pop 卡片選擇 MV、直拍或經典舞台。"
    if _is_photo_card_request(message):
        return _photo_card_placeholder_text()
    if _is_play_zone_placeholder_request(message):
        return _play_zone_placeholder_text(message)
    if _is_daily_kpop_category_request(message):
        return _daily_kpop_placeholder_text(message)
    if route_message(message).name == "weekly_chart":
        return agent.analyze_message_local(message)
    if _is_full_artist_report_request(message):
        return agent.analyze_message_local(message)
    return _fixed_command_help_text()


def _fixed_command_help_text() -> str:
    return (
        "目前支援固定指令：\n"
        "1. 分析 aespa\n"
        "2. 分析 IVE\n"
        "3. 本週榜單\n"
        "4. 互動專區\n"
        "5. 每日一首\n\n"
        "請用「分析 藝人名」取得完整報告。"
    )


def _play_zone_placeholder_text(message: str) -> str:
    feature = message.strip()
    if feature == "我的雷達":
        feature = "我的 K-pop 雷達"
    return (
        f"{feature}入口已建立。\n"
        "下一步會接題庫與本地 JSON 結果表，讓它變成真正可玩的互動流程。"
    )


def _photo_card_placeholder_text() -> str:
    card = _load_photo_card_recommendation()
    if card:
        return _format_photo_card_recommendation(card)
    return PHOTO_CARD_EMPTY_TEXT


def _bias_radar_quiz_response(user_id: str, message: str) -> dict:
    normalized = message.strip()
    questions = _load_bias_radar_questions()
    if normalized in BIAS_RADAR_TRIGGERS:
        bias_radar_sessions[user_id] = {"question_index": 0, "answers": []}
        return {
            "report": _bias_radar_question_text(0),
            "flex": _build_bias_radar_question_flex_contents(0),
        }

    session = bias_radar_sessions.get(user_id)
    if not session:
        bias_radar_sessions[user_id] = {"question_index": 0, "answers": []}
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
        bias_radar_sessions[user_id] = {
            "question_index": question_index,
            "answers": answers,
        }
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
    if not csv_path.exists():
        return []
    with csv_path.open(newline="", encoding="utf-8") as file:
        return [
            row
            for row in csv.DictReader(file)
            if _bias_radar_row_is_usable(row)
        ]


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
        "image_url": _member_quiz_image_url(quiz),
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
    if not csv_path.exists():
        return []
    with csv_path.open(newline="", encoding="utf-8") as file:
        return [
            _normalize_member_quiz_row(row)
            for row in csv.DictReader(file)
            if _member_quiz_row_is_usable(row)
        ]


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
    return f"{scheme}://{host}/play-zone/images/{quote(filename)}"


def _send_member_quiz_flex_image(filename: str):
    try:
        from PIL import Image, ImageOps

        with Image.open(_member_quiz_image_dir() / filename) as image:
            source = ImageOps.exif_transpose(image).convert("RGB")
            side = max(source.size)
            canvas = Image.new("RGB", (side, side), color=(247, 250, 248))
            offset = ((side - source.width) // 2, (side - source.height) // 2)
            canvas.paste(source, offset)
            output = BytesIO()
            canvas.save(output, format="JPEG", quality=92, optimize=True)
    except Exception:
        logger.exception("Could not build member quiz Flex image: %s", filename)
        abort(404)

    output.seek(0)
    return send_file(
        output,
        mimetype="image/jpeg",
        download_name=f"{Path(filename).stem}_flex.jpg",
        max_age=60 * 60,
    )


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
    if not csv_path.exists():
        return []
    with csv_path.open(newline="", encoding="utf-8") as file:
        return [
            row
            for row in csv.DictReader(file)
            if row.get("title", "").strip()
            and row.get("url", "").strip()
        ]


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
    if not csv_path.exists():
        return []
    with csv_path.open(newline="", encoding="utf-8") as file:
        return [
            row
            for row in csv.DictReader(file)
            if row.get("artist", "").strip()
            and row.get("type", "").strip()
            and row.get("url", "").strip()
        ]


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
        with ApiClient(line_configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            reply_messages = None
            if _is_artist_picker_request(user_text):
                reply_message = _build_artist_picker_message()
                fallback_text = "請輸入：分析 aespa、分析 IVE、分析 NCT"
            elif _is_help_request(user_text):
                reply_message = _build_help_message()
                fallback_text = reply_message.text
            elif _is_play_zone_request(user_text):
                reply_message = _build_line_flex_message(
                    _build_play_zone_flex_contents(),
                    alt_text="K-pop Play Zone",
                )
                fallback_text = "請選擇：本命雷達測驗、粉絲屬性測驗、認人測驗、神圖抽卡"
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
                    reply_messages = [
                        _build_line_image_message(
                            response["image_url"],
                            alt_text="認人測驗圖片",
                        ),
                        reply_message,
                    ]
            elif _is_daily_kpop_request(user_text):
                reply_message = _build_line_flex_message(
                    _build_daily_kpop_flex_contents(),
                    alt_text="每日一首 K-pop",
                )
                fallback_text = "請選擇：每日 MV、每日直拍、每日經典舞台"
            elif _is_daily_kpop_category_request(user_text):
                fallback_text = fit_line_text(_daily_kpop_placeholder_text(user_text))
                reply_message = TextMessage(text=fallback_text)
                reply_messages = [
                    reply_message,
                    _build_line_flex_message(
                        _build_daily_kpop_redraw_flex_contents(),
                        alt_text="再抽一首 K-pop",
                    ),
                ]
            elif _is_photo_card_request(user_text):
                report_text = _photo_card_placeholder_text()
                fallback_text = fit_line_text(report_text)
                reply_message = TextMessage(text=fallback_text)
                if report_text != PHOTO_CARD_EMPTY_TEXT:
                    reply_messages = [
                        reply_message,
                        _build_line_flex_message(
                            _build_photo_card_redraw_flex_contents(),
                            alt_text="再抽一次",
                        ),
                    ]
            else:
                if route_message(user_text).name == "weekly_chart":
                    chart_cache = agent.get_weekly_chart_cache()
                    report = chart_cache["report"]
                    reply_message = _build_line_reply_message(report)
                    fallback_text = fit_line_text(report)
                elif _is_full_artist_report_request(user_text):
                    intent = route_message(user_text)
                    artist_cache = agent.get_artist_cache(
                        intent.artist,
                        period_months=intent.period_months,
                    )
                    report = artist_cache["report"]
                    reply_message = _build_line_flex_message(
                        artist_cache["flex"],
                        alt_text=f"{artist_cache['artist']} K-pop 分析報告",
                    )
                    fallback_text = fit_line_text(report)
                else:
                    fallback_text = fit_line_text(_reply_text_for_message(user_text))
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=settings.port)
