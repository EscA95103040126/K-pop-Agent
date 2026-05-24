from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import google.generativeai as genai
import requests

from src.config import Settings, settings
from src.router import ARTIST_PATTERNS, Intent, route_message
from src.tools.chart_db import ChartHistoryRepository
from src.tools.naver_news import NaverNewsClient
from src.tools.sentiment import analyze_sentiment_from_csv

_SENTIMENT_FALLBACK: dict = {
    "sentiment": {"positive": 0, "neutral": 0, "negative": 0},
    "top_keywords": [],
    "summary": "Tool D 尚未取得足夠評論樣本。",
}
VALID_INSIGHT_RISKS = {"高", "中", "低"}
GEMINI_REQUEST_TIMEOUT_SECONDS = 10
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEMO_ARTISTS = (
    "aespa",
    "IVE",
    "BABYMONSTER",
    "NMIXX",
    "ILLIT",
    "NCT",
    "ZEROBASEONE",
    "TXT",
    "ENHYPEN",
    "BOYNEXTDOOR",
)
SUPPORTED_ARTISTS = DEMO_ARTISTS
CACHE_DIR = settings.base_dir / "data" / "cache"
ARTIST_CACHE_DIR = CACHE_DIR / "artists"
CHART_CACHE_DIR = CACHE_DIR / "chart"
WEEKLY_CHART_CACHE_PATH = CHART_CACHE_DIR / "weekly.json"
CHART_CACHE_TTL = timedelta(hours=24)
LOCAL_SUMMARIES = {
    "aespa": "aespa 近期仍具高話題度，雖然榜單排名有短期波動，但作品聲量與粉絲討論維持穩定。",
    "IVE": "IVE 目前榜單表現進入調整期，但成員個人影響力與粉絲討論仍能支撐穩定曝光。",
    "BABYMONSTER": "BABYMONSTER 仍處於聲量累積期，榜單表現與粉絲反應適合持續追蹤。",
    "NMIXX": "NMIXX 近期音樂風格辨識度明確，市場熱度可透過榜單與粉絲討論同步觀察。",
    "ILLIT": "ILLIT 近期作品具備年輕族群討論度，後續可觀察榜單續航與粉絲口碑變化。",
    "NCT": "NCT 具備穩定核心粉絲與高討論度，短期聲量可由影片留言與新聞曝光觀察。",
    "ZEROBASEONE": "ZEROBASEONE 仍維持強粉絲動員力，適合觀察回歸期留言熱度與榜單變化。",
    "TXT": "TXT 具備海外與韓國雙市場聲量，短期趨勢可由新曲討論與週榜資料交叉判讀。",
    "ENHYPEN": "ENHYPEN 的全球粉絲動能明顯，影片留言反應可作為近期熱度的重要參考。",
    "BOYNEXTDOOR": "BOYNEXTDOOR 仍在擴張受眾階段，粉絲留言與榜單露出可觀察成長動能。",
}
# 韓式 ins 風格：奶油白 × 玫瑰棕
FLEX_HEADER_BG        = "#C4956A"   # 玫瑰棕
FLEX_HEADER_TEXT      = "#FFFFFF"   # 白色
FLEX_HEADER_SUBTITLE  = "#FDEBD8"   # 淺暖白
FLEX_PAGE_BACKGROUND  = "#FAF7F4"   # 奶油白
FLEX_BLOCK_BACKGROUND = "#FFFFFF"   # 純白
FLEX_BLOCK_ACCENT     = "#C4956A"   # 豎線裝飾色（同 header）
FLEX_BLOCK_TITLE      = "#8B5E52"   # 深玫瑰棕
FLEX_TEXT_COLOR       = "#5C4033"   # 深棕
FLEX_SEPARATOR_COLOR  = "#E8D5C4"   # 淺奶茶
FLEX_FOOTER_BG        = "#F2EAE3"   # 淺奶油
FLEX_FOOTER_TEXT      = "#8B5E52"   # 深玫瑰棕


class KpopAnalysisAgent:
    def __init__(
        self,
        config: Settings = settings,
        news_client: NaverNewsClient | None = None,
        chart_repo: ChartHistoryRepository | None = None,
    ) -> None:
        self.config = config
        self.news_client = news_client or NaverNewsClient(config)
        self.chart_repo = chart_repo or ChartHistoryRepository(
            db_path=config.database_path,
            mock_data_dir=config.mock_data_dir,
        )

    def analyze_message(self, message: str) -> str:
        intent = route_message(message)
        if intent.name == "weekly_chart":
            return self.generate_weekly_chart_report()
        news = self.news_client.search(intent.artist)
        chart = self.chart_repo.get_artist_trend(intent.artist, weeks=intent.period_months * 4)
        sentiment = self._fetch_sentiment(intent.artist)
        return self.generate_report(intent=intent, news=news, chart=chart, sentiment=sentiment)

    def analyze_message_local(self, message: str) -> str:
        intent = route_message(message)
        if intent.name == "weekly_chart":
            return self.get_weekly_chart_cache()["report"]
        if intent.artist not in SUPPORTED_ARTISTS:
            return _unsupported_artist_message(intent.artist)

        return self.get_artist_cache(intent.artist, period_months=intent.period_months)["report"]

    def answer_kpop_question(self, question: str) -> str:
        if route_message(question).name == "weekly_chart":
            return self.get_weekly_chart_cache()["report"]

        artists = _extract_supported_artists(question)
        if not artists:
            return _kpop_scope_message()

        artist_payloads = [self.get_artist_cache(artist) for artist in artists[:3]]
        fallback = _fallback_small_analysis(question=question, payloads=artist_payloads)
        if self.config.use_gemini_mock:
            return fallback

        try:
            prompt = _build_small_analysis_prompt(question, artist_payloads)
            response = requests.post(
                GEMINI_API_URL.format(model=self.config.gemini_model),
                params={"key": self.config.gemini_api_key},
                json={
                    "contents": [
                        {
                            "role": "user",
                            "parts": [{"text": prompt}],
                        }
                    ],
                    "generationConfig": {
                        "temperature": 0.3,
                        "maxOutputTokens": 260,
                    },
                },
                timeout=GEMINI_REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            data = response.json()
            answer = data["candidates"][0]["content"]["parts"][0].get("text", "")
            answer = _clean_small_analysis_answer(answer)
        except Exception:
            return fallback

        return answer or fallback

    def build_flex_message(
        self,
        report: str,
        insight: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return build_report_flex(report, insight=insight)

    def get_artist_cache(self, artist: str, period_months: int = 3) -> dict[str, Any]:
        cache_path = artist_cache_path(artist)
        if cache_path.exists():
            return json.loads(cache_path.read_text(encoding="utf-8"))
        return self.preload_artist_cache(artist=artist, period_months=period_months)

    def preload_artist_cache(self, artist: str, period_months: int = 3) -> dict[str, Any]:
        ARTIST_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        intent = Intent(
            name="artist_analysis",
            artist=artist,
            period_months=period_months,
            raw_text=f"分析 {artist}",
        )
        news = self.news_client.search(artist)
        chart = self.chart_repo.get_artist_trend(artist, weeks=period_months * 4)
        sentiment = self._fetch_sentiment(artist)
        insight = self._generate_insight(
            artist=artist,
            chart=chart,
            sentiment=sentiment,
            news=news,
        )
        report = self._generate_local_report(
            intent=intent,
            chart=chart,
            sentiment=sentiment,
            news=news,
        )
        payload = {
            "cached_at": _now_iso(),
            "artist": artist,
            "period_months": period_months,
            "report": report,
            "insight": insight,
            "flex": self.build_flex_message(report, insight=insight),
            "sources": {
                "chart": chart,
                "news": news[:5],
                "sentiment": sentiment,
            },
        }
        artist_cache_path(artist).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return payload

    def get_weekly_chart_cache(self, limit: int = 10) -> dict[str, Any]:
        if WEEKLY_CHART_CACHE_PATH.exists():
            payload = json.loads(WEEKLY_CHART_CACHE_PATH.read_text(encoding="utf-8"))
            if _is_fresh(payload.get("cached_at"), max_age=CHART_CACHE_TTL):
                return payload
        return self.preload_weekly_chart_cache(limit=limit)

    def preload_weekly_chart_cache(self, limit: int = 10) -> dict[str, Any]:
        CHART_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        chart = self.chart_repo.get_latest_weekly_chart(limit=limit)
        report = self.generate_weekly_chart_report(limit=limit)
        payload = {
            "cached_at": _now_iso(),
            "chart": chart,
            "report": report,
        }
        WEEKLY_CHART_CACHE_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return payload

    def generate_weekly_chart_report(self, limit: int = 10) -> str:
        chart = self.chart_repo.get_latest_weekly_chart(limit=limit)
        items = chart.get("items", [])
        if not items:
            return "# 本週 K-pop 榜單\n\n目前沒有可用的 Bugs 週榜資料。"

        lines = [
            "# 本週 K-pop 榜單",
            "",
            f"資料來源：Bugs 週榜",
            f"榜單日期：{chart.get('chart_date', '未知')}",
            "",
        ]
        for item in items:
            change = _format_rank_change(item.get("change_rank", 0))
            lines.append(
                f"{item['rank']}. {item['title']} - {item['artist']} ({change})"
            )
        return "\n".join(lines)

    def _fetch_sentiment(self, artist_name: str) -> dict:
        try:
            result = analyze_sentiment_from_csv(artist_name)
            if result.get("total_comments", 0) == 0:
                return _SENTIMENT_FALLBACK
            return result
        except Exception:
            return _SENTIMENT_FALLBACK

    def _generate_insight(
        self,
        artist: str,
        chart: dict[str, Any],
        sentiment: dict,
        news: list[dict[str, Any]],
    ) -> dict[str, str]:
        fallback = _fallback_insight(artist=artist, chart=chart, sentiment=sentiment)
        if self.config.use_gemini_mock:
            return fallback

        s = sentiment.get("sentiment", {})
        prompt = _build_insight_prompt(
            artist=artist,
            chart=chart,
            positive=s.get("positive", 0),
            neutral=s.get("neutral", 0),
            negative=s.get("negative", 0),
            news_summary=_format_news_titles(news),
        )
        try:
            response = requests.post(
                GEMINI_API_URL.format(model=self.config.gemini_model),
                params={"key": self.config.gemini_api_key},
                json={
                    "contents": [
                        {
                            "role": "user",
                            "parts": [{"text": prompt}],
                        }
                    ],
                    "generationConfig": {
                        "temperature": 0.2,
                        "maxOutputTokens": 120,
                    },
                },
                timeout=GEMINI_REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            data = response.json()
            text = data["candidates"][0]["content"]["parts"][0].get("text", "")
            insight = _parse_insight_response(text)
        except Exception:
            return fallback

        return insight or fallback

    def generate_report(
        self,
        intent: Intent,
        news: list[dict[str, Any]],
        chart: dict[str, Any],
        sentiment: dict | None = None,
    ) -> str:
        if sentiment is None:
            sentiment = _SENTIMENT_FALLBACK
        if self.config.use_gemini_mock:
            return self._generate_mock_report(intent=intent, news=news, chart=chart, sentiment=sentiment)

        genai.configure(api_key=self.config.gemini_api_key)
        model = genai.GenerativeModel(self.config.gemini_model)
        prompt = self._build_prompt(intent=intent, news=news, chart=chart, sentiment=sentiment)
        response = model.generate_content(prompt)
        return (response.text or "").strip()

    def _generate_mock_report(
        self,
        intent: Intent,
        news: list[dict[str, Any]],
        chart: dict[str, Any],
        sentiment: dict | None = None,
    ) -> str:
        if sentiment is None:
            sentiment = _SENTIMENT_FALLBACK
        mock_report = self.config.mock_data_dir / f"report_{intent.artist.lower()}.md"
        if mock_report.exists():
            return mock_report.read_text(encoding="utf-8")

        news_titles = "、".join(item["title"] for item in news[:3]) or "暫無新聞資料"
        categories = sorted({item.get("category", "news") for item in news if item.get("category")})
        event_types = " / ".join(categories) if categories else "news"
        chart_performance = _format_chart_performance_lines(
            chart=chart,
            weeks=intent.period_months * 4,
        )
        return f"""# {intent.artist} 近期市場與輿論分析

## 1. 榜單表現
{chart_performance}

## 2. 新聞事件脈絡
- 近期主要事件：{news_titles}
- 事件類型：{event_types}

## 3. 粉絲與輿論反應
- 正面比例：{sentiment['sentiment']['positive']}
- 中立比例：{sentiment['sentiment']['neutral']}
- 負面比例：{sentiment['sentiment']['negative']}
- 主要情緒關鍵字：{', '.join(sentiment['top_keywords']) if sentiment['top_keywords'] else '（無資料）'}
- 簡短解讀：{sentiment['summary']}

## 4. 綜合判斷
- 市場熱度：{"高" if chart.get("best_rank", 99) <= 3 else "中"}
- 輿論風險：中
- 短期趨勢：{chart.get("trend", "資料不足")}

## 5. 一句話總結
{intent.artist} 近期可由榜單穩定度與新聞聲量觀察市場表現，後續可加入情感分析補足粉絲反應細節。
"""

    def _generate_local_report(
        self,
        intent: Intent,
        chart: dict[str, Any],
        sentiment: dict,
        news: list[dict[str, Any]] | None = None,
    ) -> str:
        s = sentiment.get("sentiment", {})
        positive = s.get("positive", 0)
        neutral = s.get("neutral", 0)
        negative = s.get("negative", 0)
        keywords = "、".join(sentiment.get("top_keywords", [])[:5]) or "（無資料）"
        best_rank = chart.get("best_rank", "N/A")
        market_heat = _market_heat(best_rank)
        risk = _sentiment_risk(negative)
        summary = LOCAL_SUMMARIES.get(intent.artist, f"{intent.artist} 目前資料量有限，建議持續觀察榜單與粉絲反應。")
        news_titles = _format_news_titles(news or [])
        chart_performance = _format_chart_performance_lines(
            chart=chart,
            weeks=intent.period_months * 4,
        )

        return f"""# {intent.artist} 近期市場與輿論分析

## 1. 榜單表現
{chart_performance}

## 2. 新聞事件脈絡
- 近期主要事件：{news_titles}
- 事件類型：新聞 / 榜單 / 粉絲反應 / 市場觀察

## 3. 粉絲與輿論反應
- 正面比例：{positive}
- 中立比例：{neutral}
- 負面比例：{negative}
- 主要情緒關鍵字：{keywords}
- 簡短解讀：{sentiment.get("summary", "評論樣本不足，需補充更多資料。")}

## 4. 綜合判斷
- 市場熱度：{market_heat}
- 輿論風險：{risk}
- 短期趨勢：{_local_trend_sentence(intent.artist, chart)}

## 5. 一句話總結
{summary}
"""

    def _build_prompt(
        self,
        intent: Intent,
        news: list[dict[str, Any]],
        chart: dict[str, Any],
        sentiment: dict | None = None,
    ) -> str:
        if sentiment is None:
            sentiment = _SENTIMENT_FALLBACK
        s = sentiment["sentiment"]
        kw = ", ".join(sentiment["top_keywords"]) if sentiment["top_keywords"] else "（無資料）"
        return f"""
你是 K-pop 市場分析助理。請根據工具資料，用繁體中文產生結構化分析報告。

使用者問題：
{intent.raw_text}

路由結果：
{json.dumps(intent.__dict__, ensure_ascii=False, indent=2)}

Tool B Naver News 結果：
{json.dumps(news, ensure_ascii=False, indent=2)}

Tool C SQLite 榜單趨勢：
{json.dumps(chart, ensure_ascii=False, indent=2)}

Tool D 情感分析結果：
{json.dumps(sentiment, ensure_ascii=False, indent=2)}

請嚴格使用以下格式，不要加入無資料支撐的 API key、程式細節或內部推理：

# {{藝人名}} 近期市場與輿論分析

## 1. 榜單表現
- 最近 8～12 週最高排名：
- 平均排名：
- 上榜週數：
- 排名趨勢：上升 / 下降 / 持平

## 2. 新聞事件脈絡
- 近期主要事件：
- 事件類型：comeback / 銷量 / 爭議 / 代言 / 演唱會 / 榜單

## 3. 粉絲與輿論反應
- 正面比例：{s['positive']}
- 中立比例：{s['neutral']}
- 負面比例：{s['negative']}
- 主要情緒關鍵字：{kw}
- 簡短解讀：{sentiment['summary']}

## 4. 綜合判斷
- 市場熱度：高 / 中 / 低
- 輿論風險：高 / 中 / 低
- 短期趨勢：

## 5. 一句話總結
""".strip()


def build_report_flex(
    report: str,
    insight: dict[str, str] | None = None,
) -> dict[str, Any]:
    sections = _extract_report_sections(report)
    artist_name = _extract_artist_name(report)
    summary = _section_body(sections.get("5", "")).strip() or "分析報告已產生。"

    block_configs = [
        ("榜單表現", sections.get("1", "")),
        ("粉絲與輿論反應", sections.get("3", "")),
        ("綜合判斷", sections.get("4", "")),
    ]
    if _has_insight(insight):
        block_configs.append(("市場洞察", _format_insight_block(insight or {})))

    body_contents: list[dict[str, Any]] = []
    for i, (title, section) in enumerate(block_configs):
        if i > 0:
            body_contents.append({
                "type": "separator",
                "color": FLEX_SEPARATOR_COLOR,
                "margin": "md",
            })
        block_body = section if title == "市場洞察" else _section_body(section)
        body_contents.append(_flex_block(title, block_body))

    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": FLEX_HEADER_BG,
            "paddingAll": "18px",
            "contents": [
                {
                    "type": "text",
                    "text": "近期市場與輿論分析",
                    "size": "xs",
                    "color": FLEX_HEADER_SUBTITLE,
                    "margin": "none",
                },
                {
                    "type": "text",
                    "text": artist_name,
                    "weight": "bold",
                    "size": "xxl",
                    "color": FLEX_HEADER_TEXT,
                    "wrap": True,
                    "margin": "sm",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": FLEX_PAGE_BACKGROUND,
            "spacing": "md",
            "paddingAll": "16px",
            "contents": body_contents,
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": FLEX_FOOTER_BG,
            "paddingAll": "14px",
            "contents": [
                {
                    "type": "text",
                    "text": _truncate(summary, 260),
                    "color": FLEX_FOOTER_TEXT,
                    "size": "sm",
                    "style": "italic",
                    "wrap": True,
                }
            ],
        },
    }


def _flex_block(title: str, body: str) -> dict[str, Any]:
    return {
        "type": "box",
        "layout": "vertical",
        "backgroundColor": FLEX_BLOCK_BACKGROUND,
        "cornerRadius": "12px",
        "paddingAll": "12px",
        "spacing": "md",
        "contents": [
            # 區塊標題列：玫瑰棕豎線 + 粗體標題
            {
                "type": "box",
                "layout": "horizontal",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "box",
                        "layout": "vertical",
                        "width": "4px",
                        "backgroundColor": FLEX_BLOCK_ACCENT,
                        "cornerRadius": "4px",
                        "contents": [{"type": "filler"}],
                    },
                    {
                        "type": "text",
                        "text": title,
                        "weight": "bold",
                        "size": "md",
                        "color": FLEX_BLOCK_TITLE,
                        "flex": 1,
                        "gravity": "center",
                    },
                ],
            },
            # 內文
            {
                "type": "text",
                "text": _truncate(body or "（無資料）", 520),
                "size": "sm",
                "color": FLEX_TEXT_COLOR,
                "wrap": True,
            },
        ],
    }


def _extract_artist_name(report: str) -> str:
    for line in report.splitlines():
        if line.startswith("# "):
            return line.removeprefix("# ").replace("近期市場與輿論分析", "").strip() or "K-pop Agent"
    return "K-pop Agent"


def _extract_report_sections(report: str) -> dict[str, str]:
    matches = list(re.finditer(r"^##\s+(\d+)\.\s+(.+)$", report, flags=re.MULTILINE))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(report)
        sections[match.group(1)] = report[start:end].strip()
    return sections


def _section_body(section: str) -> str:
    lines = []
    for line in section.splitlines()[1:]:
        clean_line = line.strip()
        if not clean_line:
            continue
        lines.append(clean_line.removeprefix("- ").strip())
    return "\n".join(lines)


def _truncate(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "…"


def _build_insight_prompt(
    artist: str,
    chart: dict[str, Any],
    positive: Any,
    neutral: Any,
    negative: Any,
    news_summary: str,
) -> str:
    return f"""
你是 K-pop 市場分析師，請根據以下資料產生簡短市場洞察。
只回傳 JSON，不要其他內容。

藝人：{artist}
榜單資料：{json.dumps(chart, ensure_ascii=False)}
情感分析：正面 {positive}、中立 {neutral}、負面 {negative}
近期新聞：{news_summary}

格式：
{{
  "headline": "一句話市場觀察，20字以內",
  "risk": "高/中/低",
  "opportunity": "一句話機會點，20字以內"
}}
""".strip()


def _parse_insight_response(text: str) -> dict[str, str] | None:
    payload = _extract_json_object(text)
    if not isinstance(payload, dict):
        return None

    headline = _clean_insight_text(payload.get("headline"), max_length=28)
    risk = str(payload.get("risk", "")).strip()
    opportunity = _clean_insight_text(payload.get("opportunity"), max_length=28)
    if not headline or risk not in VALID_INSIGHT_RISKS or not opportunity:
        return None
    return {
        "headline": headline,
        "risk": risk,
        "opportunity": opportunity,
    }


def _extract_json_object(text: str) -> Any:
    clean = text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean)
        clean = re.sub(r"\s*```$", "", clean).strip()

    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", clean, flags=re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None


def _fallback_insight(
    artist: str,
    chart: dict[str, Any],
    sentiment: dict,
) -> dict[str, str]:
    s = sentiment.get("sentiment", {})
    positive = _safe_float(s.get("positive", 0))
    negative = _safe_float(s.get("negative", 0))
    best_rank = chart.get("best_rank", "N/A")
    headline = _fallback_insight_headline(artist, best_rank, positive)
    return {
        "headline": _clean_insight_text(headline, max_length=28) or f"{artist}聲量穩定",
        "risk": _sentiment_risk(negative),
        "opportunity": _fallback_opportunity(best_rank=best_rank, positive=positive),
    }


def _fallback_insight_headline(artist: str, best_rank: Any, positive: float) -> str:
    try:
        rank = int(best_rank)
    except (TypeError, ValueError):
        rank = 999
    if rank <= 20 and positive >= 0.5:
        return f"{artist}本週聲量偏強"
    if positive >= 0.5:
        return f"{artist}留言口碑偏正向"
    if rank <= 20:
        return f"{artist}榜單表現亮眼"
    return f"{artist}仍需觀察後勢"


def _fallback_opportunity(best_rank: Any, positive: float) -> str:
    try:
        rank = int(best_rank)
    except (TypeError, ValueError):
        rank = 999
    if rank <= 20:
        return "放大本週上榜聲量"
    if positive >= 0.5:
        return "延續粉絲正面討論"
    return "累積更多榜單資料"


def _clean_insight_text(value: Any, max_length: int) -> str:
    text = str(value or "").strip().replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return _truncate(text, max_length)


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _has_insight(insight: dict[str, str] | None) -> bool:
    if not insight:
        return False
    return bool(
        insight.get("headline")
        and insight.get("risk") in VALID_INSIGHT_RISKS
        and insight.get("opportunity")
    )


def _format_insight_block(insight: dict[str, str]) -> str:
    return "\n".join(
        [
            str(insight.get("headline", "")).strip(),
            f"風險：{insight.get('risk', '低')}",
            f"機會：{insight.get('opportunity', '')}",
        ]
    )


def _extract_supported_artists(message: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", message)
    artists: list[str] = []
    for artist, pattern in ARTIST_PATTERNS.items():
        if artist in SUPPORTED_ARTISTS and pattern.search(normalized):
            artists.append(artist)
    return artists


def _build_small_analysis_prompt(question: str, payloads: list[dict[str, Any]]) -> str:
    compact_payloads = []
    for payload in payloads:
        sources = payload.get("sources", {})
        compact_payloads.append(
            {
                "artist": payload.get("artist"),
                "insight": payload.get("insight"),
                "chart": sources.get("chart"),
                "sentiment": sources.get("sentiment"),
                "news": sources.get("news", [])[:3],
                "report_excerpt": _truncate(payload.get("report", ""), 900),
            }
        )

    return f"""
你是 K-pop 市場分析助理。請只根據下列快取資料回答使用者的 K-pop 市場分析問題。
請用繁體中文，最多 4 句，避免提及 API、程式、快取或內部流程。
如果資料不足，請明確說資料不足並給保守觀察。

使用者問題：
{question}

快取資料：
{json.dumps(compact_payloads, ensure_ascii=False, indent=2)}
""".strip()


def _clean_small_analysis_answer(answer: str) -> str:
    text = answer.strip()
    text = re.sub(r"^```(?:\w+)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    return _truncate(text, 900)


def _fallback_small_analysis(question: str, payloads: list[dict[str, Any]]) -> str:
    if len(payloads) > 1:
        lines = ["目前可做保守比較："]
        for payload in payloads:
            artist = payload.get("artist", "該藝人")
            insight = payload.get("insight") or {}
            risk = insight.get("risk", "資料不足")
            headline = insight.get("headline") or f"{artist} 目前資料量有限"
            lines.append(f"{artist}：{headline}，風險 {risk}。")
        return "\n".join(lines)

    payload = payloads[0] if payloads else {}
    artist = payload.get("artist", "該藝人")
    insight = payload.get("insight") or {}
    headline = insight.get("headline") or f"{artist} 目前資料量有限，建議持續觀察。"
    risk = insight.get("risk", "資料不足")
    opportunity = insight.get("opportunity", "等待更多榜單與留言資料")
    return f"{headline}\n風險：{risk}\n機會：{opportunity}"


def _kpop_scope_message() -> str:
    supported = "、".join(SUPPORTED_ARTISTS)
    return (
        "我目前主要支援 K-pop 藝人、榜單、新聞與粉絲留言分析。\n"
        f"可分析藝人：{supported}\n"
        "你可以問：aespa 最近聲量如何？NCT 輿論風險高嗎？比較 IVE 和 BABYMONSTER。"
    )


def _unsupported_artist_message(artist: str) -> str:
    supported = "、".join(SUPPORTED_ARTISTS)
    return (
        f"目前 demo 版先支援：{supported}。\n"
        "請輸入：分析 aespa、分析 IVE、分析 BABYMONSTER。"
    )


def artist_cache_path(artist: str) -> Path:
    return ARTIST_CACHE_DIR / f"{_cache_key(artist)}.json"


def _cache_key(value: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
    return key or "unknown"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_fresh(cached_at: str | None, max_age: timedelta) -> bool:
    if not cached_at:
        return False
    try:
        cached_time = datetime.fromisoformat(cached_at)
    except ValueError:
        return False
    if cached_time.tzinfo is None:
        cached_time = cached_time.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - cached_time <= max_age


def _format_news_titles(news: list[dict[str, Any]]) -> str:
    titles = [item.get("title", "").strip() for item in news[:3] if item.get("title")]
    return "、".join(titles) if titles else "目前無可用新聞快取，先以榜單與留言資料判讀。"


def _market_heat(best_rank: Any) -> str:
    try:
        rank = int(best_rank)
    except (TypeError, ValueError):
        return "資料不足"
    if rank <= 20:
        return "高"
    if rank <= 60:
        return "中"
    return "低"


def _sentiment_risk(negative_ratio: Any) -> str:
    try:
        negative = float(negative_ratio)
    except (TypeError, ValueError):
        return "資料不足"
    if negative >= 0.4:
        return "高"
    if negative >= 0.25:
        return "中"
    return "低"


def _format_chart_performance_lines(chart: dict[str, Any], weeks: int) -> str:
    if chart.get("trend") == "資料不足":
        return "\n".join(
            [
                f"- 本週最高排名：{chart.get('best_rank', 'N/A')}",
                f"- 本週上榜歌曲數：{chart.get('weeks_on_chart', 'N/A')}",
                f"- 平均排名：{chart.get('avg_rank', 'N/A')}",
            ]
        )
    return "\n".join(
        [
            f"- 最近 {weeks} 週最高排名：{chart.get('best_rank', 'N/A')}",
            f"- 平均排名：{chart.get('avg_rank', 'N/A')}",
            f"- 上榜週數：{chart.get('weeks_on_chart', 'N/A')}",
            f"- 排名趨勢：{chart.get('trend', '資料不足')}",
        ]
    )


def _local_trend_sentence(artist: str, chart: dict[str, Any]) -> str:
    trend = chart.get("trend", "資料不足")
    weeks = chart.get("weeks_on_chart", 0)
    if trend == "上升":
        return f"{artist} 近期排名有上升跡象，可觀察後續作品與活動是否延續聲量。"
    if trend == "下降":
        return f"{artist} 近期榜單排名偏向下修，但仍有 {weeks} 筆週榜資料可作為追蹤基礎。"
    if trend == "持平":
        return f"{artist} 近期榜單變化相對穩定，短期熱度以維持既有聲量為主。"
    return f"{artist} 目前榜單樣本較少，短期趨勢需等待更多週榜資料確認。"


def _format_rank_change(change_rank: int) -> str:
    if change_rank > 0:
        return f"▲{change_rank}"
    if change_rank < 0:
        return f"▼{abs(change_rank)}"
    return "-"
