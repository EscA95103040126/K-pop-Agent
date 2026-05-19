from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import google.generativeai as genai

from src.config import Settings, settings
from src.router import Intent, route_message
from src.tools.chart_db import ChartHistoryRepository
from src.tools.naver_news import NaverNewsClient
from src.tools.sentiment import analyze_sentiment_from_csv

_SENTIMENT_FALLBACK: dict = {
    "sentiment": {"positive": 0, "neutral": 0, "negative": 0},
    "top_keywords": [],
    "summary": "Tool D 尚未取得足夠評論樣本。",
}
SUPPORTED_ARTISTS = ("aespa", "IVE", "NewJeans")
LOCAL_SUMMARIES = {
    "aespa": "aespa 近期仍具高話題度，雖然榜單排名有短期波動，但作品聲量與粉絲討論維持穩定。",
    "IVE": "IVE 目前榜單表現進入調整期，但成員個人影響力與粉絲討論仍能支撐穩定曝光。",
    "NewJeans": "NewJeans 近期榜單資料較少，但既有熱門作品仍維持長尾聆聽與品牌辨識度。",
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
            return self.generate_weekly_chart_report()
        if intent.artist not in SUPPORTED_ARTISTS:
            return _unsupported_artist_message(intent.artist)

        chart = self.chart_repo.get_artist_trend(intent.artist, weeks=intent.period_months * 4)
        sentiment = self._fetch_sentiment(intent.artist)
        return self._generate_local_report(intent=intent, chart=chart, sentiment=sentiment)

    def build_flex_message(self, report: str) -> dict[str, Any]:
        return build_report_flex(report)

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
        return f"""# {intent.artist} 近期市場與輿論分析

## 1. 榜單表現
- 最近 {intent.period_months * 4} 週最高排名：第 {chart.get("best_rank", "N/A")} 名
- 平均排名：{chart.get("avg_rank", "N/A")}
- 上榜週數：{chart.get("weeks_on_chart", "N/A")} 週
- 排名趨勢：{chart.get("trend", "資料不足")}

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

        return f"""# {intent.artist} 近期市場與輿論分析

## 1. 榜單表現
- 最近 {intent.period_months * 4} 週最高排名：{best_rank}
- 平均排名：{chart.get("avg_rank", "N/A")}
- 上榜週數：{chart.get("weeks_on_chart", "N/A")}
- 排名趨勢：{chart.get("trend", "資料不足")}

## 2. 新聞事件脈絡
- 近期主要事件：本地 demo 模式先以 Bugs 週榜與韓文評論樣本作為分析依據。
- 事件類型：榜單 / 粉絲反應 / 市場觀察

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


def build_report_flex(report: str) -> dict[str, Any]:
    sections = _extract_report_sections(report)
    artist_name = _extract_artist_name(report)
    summary = _section_body(sections.get("5", "")).strip() or "分析報告已產生。"

    block_configs = [
        ("榜單表現", sections.get("1", "")),
        ("粉絲與輿論反應", sections.get("3", "")),
        ("綜合判斷", sections.get("4", "")),
    ]
    body_contents: list[dict[str, Any]] = []
    for i, (title, section) in enumerate(block_configs):
        if i > 0:
            body_contents.append({
                "type": "separator",
                "color": FLEX_SEPARATOR_COLOR,
                "margin": "md",
            })
        body_contents.append(_flex_block(title, _section_body(section)))

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


def _unsupported_artist_message(artist: str) -> str:
    return (
        "目前 demo 版先支援 aespa、IVE、NewJeans 三組藝人。\n"
        "請輸入：分析 aespa、分析 IVE、分析 NewJeans。"
    )


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
