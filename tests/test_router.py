from src.router import route_message


def test_route_message_extracts_artist_and_period() -> None:
    intent = route_message("分析 aespa 最近三個月表現")

    assert intent.artist == "aespa"
    assert intent.period_months == 3
    assert intent.name == "artist_market_analysis"


def test_route_message_extracts_newjeans_alias() -> None:
    intent = route_message("NewJeans 最近的輿論風向是什麼？")

    assert intent.artist == "NewJeans"
    assert intent.name == "artist_sentiment_context"


def test_route_message_detects_weekly_chart_requests() -> None:
    for message in ("本週榜單", "本週 K-pop 榜單", "榜單", "chart"):
        intent = route_message(message)

        assert intent.name == "weekly_chart"
        assert intent.artist == ""
