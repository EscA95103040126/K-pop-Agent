"""Demo script: simulates live presentation queries via KpopAnalysisAgent."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent import KpopAnalysisAgent

QUERIES = [
    "分析 aespa 最近表現",
    "IVE 的輿論風向是什麼？",
    "NewJeans 近期市場表現如何？",
]


def main() -> None:
    agent = KpopAnalysisAgent()
    for i, query in enumerate(QUERIES, start=1):
        print(f"\n{'='*60}")
        print(f"[Demo {i}/{len(QUERIES)}] 輸入：{query}")
        print("=" * 60)
        try:
            report = agent.analyze_message(query)
            print(report)
        except Exception as exc:
            print(f"[ERROR] 分析失敗：{exc}")
    print(f"\n{'='*60}")
    print("Demo 完成。")


if __name__ == "__main__":
    main()
