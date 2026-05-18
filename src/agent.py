from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import google.generativeai as genai

from src.config import Settings, settings
from src.router import Intent, route_message
from src.tools.chart_db import ChartHistoryRepository
from src.tools.naver_news import NaverNewsClient


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
        news = self.news_client.search(intent.artist)
        chart = self.chart_repo.get_artist_trend(intent.artist, weeks=intent.period_months * 4)
        return self.generate_report(intent=intent, news=news, chart=chart)

    def generate_report(
        self,
        intent: Intent,
        news: list[dict[str, Any]],
        chart: dict[str, Any],
    ) -> str:
        if self.config.use_gemini_mock:
            return self._generate_mock_report(intent=intent, news=news, chart=chart)

        genai.configure(api_key=self.config.gemini_api_key)
        model = genai.GenerativeModel(self.config.gemini_model)
        prompt = self._build_prompt(intent=intent, news=news, chart=chart)
        response = model.generate_content(prompt)
        return (response.text or "").strip()

    def _generate_mock_report(
        self,
        intent: Intent,
        news: list[dict[str, Any]],
        chart: dict[str, Any],
    ) -> str:
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
- Phase 1 MVP 尚未接入韓文情感模型
- 目前以新聞聲量和榜單趨勢作為輿論背景參考

## 4. 綜合判斷
- 市場熱度：{"高" if chart.get("best_rank", 99) <= 3 else "中"}
- 輿論風險：中
- 短期趨勢：{chart.get("trend", "資料不足")}

## 5. 一句話總結
{intent.artist} 近期可由榜單穩定度與新聞聲量觀察市場表現，後續可加入情感分析補足粉絲反應細節。
"""

    def _build_prompt(
        self,
        intent: Intent,
        news: list[dict[str, Any]],
        chart: dict[str, Any],
    ) -> str:
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
- Phase 1 尚未接入韓文情感分析模型，請只根據新聞摘要推估討論方向
- 不要編造正面/中立/負面比例

## 4. 綜合判斷
- 市場熱度：高 / 中 / 低
- 輿論風險：高 / 中 / 低
- 短期趨勢：

## 5. 一句話總結
""".strip()
