from __future__ import annotations

import logging
import sqlite3

from flask import Flask, abort, jsonify, request

from src.agent import KpopAnalysisAgent
from src.config import settings
from src.router import route_message
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
        MessageAction,
        MessagingApi,
        QuickReply,
        QuickReplyItem,
        ReplyMessageRequest,
        ButtonsTemplate,
        TemplateMessage,
        TextMessage,
    )
    from linebot.v3.webhooks import MessageEvent, TextMessageContent
except ImportError:  # pragma: no cover - lets local mock mode run without LINE SDK.
    WebhookHandler = None
    InvalidSignatureError = Exception
    ApiClient = None
    Configuration = None
    FlexContainer = None
    FlexMessage = None
    MessageAction = None
    MessagingApi = None
    QuickReply = None
    QuickReplyItem = None
    ReplyMessageRequest = None
    ButtonsTemplate = None
    TemplateMessage = None
    TextMessage = None
    MessageEvent = None
    TextMessageContent = None


app = Flask(__name__)
agent = KpopAnalysisAgent()
logger = logging.getLogger(__name__)

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


@app.post("/analyze")
def analyze() -> tuple[dict, int]:
    payload = request.get_json(silent=True) or {}
    message = payload.get("message", "")
    artist = payload.get("artist", "")
    if not message and artist:
        message = f"分析 {artist}"
    if not message:
        return {"error": "message or artist is required"}, 400
    report = agent.analyze_message(message)
    response = {"report": report}
    try:
        response["flex"] = agent.build_flex_message(report)
    except Exception:
        response["flex"] = None
    return response, 200


@app.post("/webhook")
def webhook() -> tuple[str, int]:
    body = request.get_data(as_text=True)
    signature = request.headers.get("X-Line-Signature", "")

    if settings.use_line_mock or line_handler is None:
        payload = request.get_json(silent=True) or {}
        message = _extract_mock_message(payload)
        if message:
            report = fit_line_text(agent.analyze_message_local(message))
            return jsonify({"mock_reply": report}).get_data(as_text=True), 200
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


def _build_artist_picker_message():
    if TextMessage is None:
        return None
    if TemplateMessage is not None and ButtonsTemplate is not None and MessageAction is not None:
        try:
            return TemplateMessage(
                altText="選擇要分析的 K-pop 藝人",
                template=ButtonsTemplate(
                    title="選擇藝人",
                    text="請選擇要產生分析報告的藝人。",
                    actions=[
                        MessageAction(label="aespa", text="分析 aespa"),
                        MessageAction(label="IVE", text="分析 IVE"),
                        MessageAction(label="NewJeans", text="分析 NewJeans"),
                    ],
                ),
            )
        except Exception:
            logger.exception("Artist picker template build failed; falling back to text.")

    if QuickReply is None or QuickReplyItem is None or MessageAction is None:
        return TextMessage(text="請輸入：分析 aespa、分析 IVE、分析 NewJeans")

    return TextMessage(
        text="想分析哪位藝人？",
        quickReply=QuickReply(
            items=[
                QuickReplyItem(action=MessageAction(label="aespa", text="分析 aespa")),
                QuickReplyItem(action=MessageAction(label="IVE", text="分析 IVE")),
                QuickReplyItem(action=MessageAction(label="NewJeans", text="分析 NewJeans")),
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
                    "text": "請選擇要產生分析報告的藝人。",
                    "size": "sm",
                    "color": "#5C4033",
                    "wrap": True,
                },
                _artist_picker_button("aespa", "分析 aespa"),
                _artist_picker_button("IVE", "分析 IVE"),
                _artist_picker_button("NewJeans", "分析 NewJeans"),
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


def _build_help_message():
    return TextMessage(
        text=(
            "你可以這樣問我：\n"
            "1. 分析 aespa\n"
            "2. 分析 IVE\n"
            "3. 分析 NewJeans\n"
            "4. 本週 K-pop 榜單"
        )
    )


def _is_artist_picker_request(message: str) -> bool:
    normalized = message.strip().casefold()
    return normalized in {"分析", "分析藝人", "選擇藝人", "artist", "藝人"}


def _is_help_request(message: str) -> bool:
    return message.strip() in {"使用說明", "help", "Help", "HELP"}


def _is_supported_artist_analysis(message: str) -> bool:
    intent = route_message(message)
    return intent.name != "weekly_chart" and intent.artist in {"aespa", "IVE", "NewJeans"}


def _is_weekly_chart_report(report: str) -> bool:
    return report.lstrip().startswith("# 本週 K-pop 榜單")


def _mode(is_mock: bool) -> str:
    return "mock" if is_mock else "real"


def _naver_mode() -> str:
    if settings.use_naver_mock:
        return "mock"
    return "real" if NaverNewsClient(settings).real_api_available() else "mock"


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

    @line_handler.add(MessageEvent, message=TextMessageContent)
    def handle_text_message(event: MessageEvent) -> None:
        user_text = event.message.text
        if not line_configuration:
            return
        with ApiClient(line_configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            if _is_artist_picker_request(user_text):
                reply_message = _build_artist_picker_message()
                fallback_text = "請輸入：分析 aespa、分析 IVE、分析 NewJeans"
            elif _is_help_request(user_text):
                reply_message = _build_help_message()
                fallback_text = reply_message.text
            else:
                if not _is_supported_artist_analysis(user_text) and route_message(user_text).name != "weekly_chart":
                    reply_message = _build_artist_picker_message()
                    fallback_text = "目前 demo 版先支援 aespa、IVE、NewJeans。請選擇要分析的藝人。"
                    report = ""
                else:
                    report = agent.analyze_message_local(user_text)
                    reply_message = _build_line_reply_message(report)
                    fallback_text = fit_line_text(report)

            if reply_message is None:
                return

            try:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[reply_message],
                    )
                )
            except Exception as exc:
                logger.warning("Flex reply failed; retrying with text fallback: %s", exc)
                try:
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=fallback_text)],
                        )
                    )
                except Exception as fallback_exc:
                    logger.exception("LINE reply failed: %s", fallback_exc)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=settings.port)
