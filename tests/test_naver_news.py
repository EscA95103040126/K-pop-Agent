from src.config import Settings
from src.tools.naver_news import NaverNewsClient


def test_naver_news_uses_mock_without_keys() -> None:
    config = Settings(naver_client_id=None, naver_client_secret=None)
    client = NaverNewsClient(config)

    news = client.search("aespa")

    assert news
    assert news[0]["title"]
    assert "summary" in news[0]


def test_naver_news_falls_back_to_mock_on_api_failure(monkeypatch) -> None:
    config = Settings(naver_client_id="fake-id", naver_client_secret="fake-secret")
    client = NaverNewsClient(config)

    def raise_timeout(*args, **kwargs):
        import requests

        raise requests.Timeout("boom")

    monkeypatch.setattr("src.tools.naver_news.requests.get", raise_timeout)

    news = client.search("aespa")

    assert news
    assert news[0]["title"] == "aespa 新專輯概念照公開，回歸期待升溫"


def test_naver_news_unknown_artist_mock_returns_empty_list() -> None:
    config = Settings(naver_client_id=None, naver_client_secret=None)
    client = NaverNewsClient(config)

    assert client.search("UNKNOWN_ARTIST") == []
