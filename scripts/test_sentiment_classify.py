from pathlib import Path
import sys

# 讓這個 script 可以從專案根目錄直接執行：
# python3 scripts/test_sentiment_classify.py
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.tools.sentiment import classify_comment


def main():
    examples = {
        "positive example": "노래가 너무 좋아요 무대도 완벽해요",
        "negative example": "이번 곡은 조금 아쉽고 임팩트가 약해요",
        "neutral example": "이번 곡은 새로운 스타일이에요",
        "mixed example": "노래는 좋아요 하지만 컨셉은 조금 아쉬워요",
        "empty example": "",
    }

    for label, comment in examples.items():
        result = classify_comment(comment)
        print(f"{label}: {result}")


if __name__ == "__main__":
    main()