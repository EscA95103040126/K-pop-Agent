from src.tools.bugs_chart import fetch_bugs_weekly_chart, parse_bugs_weekly_chart


BUGS_SAMPLE_HTML = """
<html>
  <body>
    <div>2026.05.11 ~ 2026.05.17</div>
    <table class="byChart">
      <tbody>
        <tr>
          <td><div class="ranking"><strong>1</strong><p class="change up"><em>2</em><span>계단 상승</span></p></div></td>
          <th scope="row"><p class="title"><a title="REDRED">REDRED</a></p></th>
          <td class="left"><p class="artist"><a title="CORTIS (코르티스)">CORTIS (코르티스)</a></p></td>
          <td class="left"><a class="album" title="GREENGREEN">GREENGREEN</a></td>
        </tr>
        <tr>
          <td><div class="ranking"><strong>3</strong><p class="change hot"><em>HOT</em></p></div></td>
          <th scope="row"><p class="title"><a title="It′s Me">It′s Me</a></p></th>
          <td class="left"><p class="artist"><a title="아일릿(ILLIT)">아일릿(ILLIT)</a></p></td>
          <td class="left"><a class="album" title="MAMIHLAPINATAPAI">MAMIHLAPINATAPAI</a></td>
        </tr>
        <tr>
          <td><div class="ranking"><strong>2</strong><p class="change down"><em>3</em><span>계단 하락</span></p></div></td>
          <th scope="row"><p class="title"><a title="BANG BANG">BANG BANG</a></p></th>
          <td class="left"><p class="artist"><a title="IVE (아이브)">IVE (아이브)</a></p></td>
          <td class="left"><a class="album" title="REVIVE+">REVIVE+</a></td>
        </tr>
      </tbody>
    </table>
  </body>
</html>
"""


def test_parse_bugs_weekly_chart() -> None:
    rows = parse_bugs_weekly_chart(BUGS_SAMPLE_HTML, fetch_date="2026-05-18")

    assert rows == [
        {
            "fetch_date": "2026-05-18",
            "chart_date": "2026-05-11",
            "source": "bugs",
            "chart_type": "weekly",
            "rank": 1,
            "title": "REDRED",
            "artist": "CORTIS (코르티스)",
            "album": "GREENGREEN",
            "change_rank": 2,
        },
        {
            "fetch_date": "2026-05-18",
            "chart_date": "2026-05-11",
            "source": "bugs",
            "chart_type": "weekly",
            "rank": 3,
            "title": "It′s Me",
            "artist": "아일릿(ILLIT)",
            "album": "MAMIHLAPINATAPAI",
            "change_rank": 0,
        },
        {
            "fetch_date": "2026-05-18",
            "chart_date": "2026-05-11",
            "source": "bugs",
            "chart_type": "weekly",
            "rank": 2,
            "title": "BANG BANG",
            "artist": "IVE (아이브)",
            "album": "REVIVE+",
            "change_rank": -3,
        },
    ]


def test_fetch_bugs_weekly_chart_passes_chartdate_param(monkeypatch) -> None:
    captured = {}

    class DummyResponse:
        text = BUGS_SAMPLE_HTML

        def raise_for_status(self):
            return None

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return DummyResponse()

    monkeypatch.setattr("src.tools.bugs_chart.requests.get", fake_get)

    rows = fetch_bugs_weekly_chart(chart_date="2026-05-18")

    assert rows
    assert captured["kwargs"]["params"] == {"chartdate": "20260518"}
