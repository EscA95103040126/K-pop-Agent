import csv
import json
from pathlib import Path
from types import SimpleNamespace

import app as app_module
from app import app


def test_fan_attribute_quiz_starts_with_first_question() -> None:
    client = app.test_client()

    response = client.post("/analyze", json={"message": "粉絲屬性測驗"})
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["report"] == "粉絲屬性測驗 Q1/5：請在 LINE 卡片中選擇最符合你的答案。"
    assert payload["flex"]["header"]["contents"][1]["text"] == "Q1/5"


def test_bias_radar_questions_json_is_readable() -> None:
    json_path = Path(app_module.__file__).resolve().parent / "data" / "play_zone" / "bias_radar_questions.json"

    questions = json.loads(json_path.read_text(encoding="utf-8"))

    assert len(questions) == 5
    assert questions[0]["question"] == "想看："
    assert questions[0]["options"] == ["男團", "女團", "都可以"]


def test_bias_radar_members_csv_is_readable_and_large_enough() -> None:
    csv_path = Path(app_module.__file__).resolve().parent / "data" / "play_zone" / "bias_radar_members.csv"

    with csv_path.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))

    assert len(rows) >= 100
    assert set(rows[0]) == {
        "id",
        "artist",
        "member",
        "gender_group",
        "group_type",
        "appearance",
        "position",
        "vibe",
        "relationship",
        "url",
        "source_url",
    }


def test_bias_radar_starts_with_first_question() -> None:
    client = app.test_client()
    app_module.bias_radar_sessions.clear()

    response = client.post(
        "/analyze",
        json={"message": "本命雷達測驗", "user_id": "bias-start"},
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["report"] == "本命雷達測驗 Q1/5：請在 LINE 卡片中選擇最符合你的答案。"
    assert payload["flex"]["header"]["contents"][1]["text"] == "Q1/5"


def test_bias_radar_options_use_hidden_postback_state() -> None:
    flex = app_module._build_bias_radar_question_flex_contents(0)
    first_option_action = flex["body"]["contents"][1]["action"]

    assert first_option_action["type"] == "postback"
    assert first_option_action["data"] == "本命雷達:0:男團"
    assert "text" not in first_option_action
    assert "displayText" not in first_option_action


def test_bias_radar_recommends_member_from_csv_after_five_answers() -> None:
    client = app.test_client()
    user_id = "bias-flow"
    app_module.bias_radar_sessions.clear()
    client.post("/analyze", json={"message": "本命雷達", "user_id": user_id})

    messages = [
        "本命雷達:0:男團",
        "本命雷達:1:小兔",
        "本命雷達:2:Vocal",
        "本命雷達:3:甜系",
        "本命雷達:4:初戀感",
    ]
    payload = None
    for message in messages:
        response = client.post("/analyze", json={"message": message, "user_id": user_id})
        payload = response.get_json()

    assert payload is not None
    assert payload["report"].startswith("你的本命雷達結果")
    assert payload["flex"]["header"]["contents"][0]["text"] == "你的本命雷達結果"

    recommended = next(
        line.removeprefix("推薦：")
        for line in payload["report"].splitlines()
        if line.startswith("推薦：")
    )
    csv_path = Path(app_module.__file__).resolve().parent / "data" / "play_zone" / "bias_radar_members.csv"
    with csv_path.open(newline="", encoding="utf-8") as file:
        csv_recommendations = {
            f"{row['artist']} {row['member']}"
            for row in csv.DictReader(file)
        }

    assert recommended in csv_recommendations


def test_fan_attribute_quiz_options_use_hidden_postback_state() -> None:
    flex = app_module._build_fan_attribute_quiz_flex_contents("粉絲屬性測驗")
    first_option_action = flex["body"]["contents"][1]["action"]

    assert first_option_action["type"] == "postback"
    assert first_option_action["data"] == "粉絲屬性測驗:1:3,1,0"
    assert "text" not in first_option_action
    assert "displayText" not in first_option_action


def test_fan_attribute_quiz_scores_group_fan_result() -> None:
    scores = {key: 0 for key in app_module.FAN_ATTRIBUTE_ORDER}
    for question in app_module.FAN_ATTRIBUTE_QUIZ:
        scores = app_module._add_fan_attribute_scores(
            scores,
            question["options"][0]["weights"],
        )

    action_text = app_module._fan_attribute_action_text(
        len(app_module.FAN_ATTRIBUTE_QUIZ),
        scores,
    )
    client = app.test_client()

    response = client.post("/analyze", json={"message": action_text})
    payload = response.get_json()

    assert response.status_code == 200
    assert "你的粉絲屬性是：團飯" in payload["report"]
    assert payload["flex"]["header"]["contents"][1]["text"] == "團飯"


def test_play_zone_describes_three_fan_attribute_types() -> None:
    flex = app_module._build_play_zone_flex_contents()

    fan_quiz_item = flex["body"]["contents"][2]

    assert fan_quiz_item["contents"][1]["contents"][0]["text"] == "粉絲屬性測驗"
    assert "團飯、唯飯還是跟風粉" in fan_quiz_item["contents"][1]["contents"][1]["text"]


def _use_photo_card_csv(monkeypatch, tmp_path: Path, csv_text: str) -> Path:
    play_zone_dir = tmp_path / "data" / "play_zone"
    play_zone_dir.mkdir(parents=True)
    csv_path = play_zone_dir / "photo_cards.csv"
    csv_path.write_text(csv_text, encoding="utf-8")
    monkeypatch.setattr(app_module, "settings", SimpleNamespace(base_dir=tmp_path))
    app_module.photo_card_queue = []
    app_module.photo_card_source_key = ()
    return csv_path


def test_photo_cards_csv_template_is_readable() -> None:
    csv_path = Path(app_module.__file__).resolve().parent / "data" / "play_zone" / "photo_cards.csv"

    header = csv_path.read_text(encoding="utf-8").splitlines()[0]

    assert header == "artist,type,url"


def test_photo_cards_csv_loads_valid_rows(monkeypatch, tmp_path: Path) -> None:
    _use_photo_card_csv(
        monkeypatch,
        tmp_path,
        "artist,type,url\nKarina,直拍,https://example.com/karina\n,,\n",
    )

    rows = app_module._load_photo_card_rows()

    assert rows == [
        {
            "artist": "Karina",
            "type": "直拍",
            "url": "https://example.com/karina",
        }
    ]


def test_photo_card_empty_csv_uses_fallback_text(monkeypatch, tmp_path: Path) -> None:
    _use_photo_card_csv(monkeypatch, tmp_path, "artist,type,url\n")
    client = app.test_client()

    response = client.post("/analyze", json={"message": "神圖抽卡"})
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["report"] == "目前還沒有神圖資料，請先補 data/play_zone/photo_cards.csv"
    assert payload["flex"] is None


def test_photo_card_with_data_returns_plain_text_recommendation(monkeypatch, tmp_path: Path) -> None:
    _use_photo_card_csv(
        monkeypatch,
        tmp_path,
        "artist,type,url\nKarina,直拍,https://example.com/karina\n",
    )
    client = app.test_client()

    response = client.post("/analyze", json={"message": "抽卡"})
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["report"] == (
        "✨ 神圖抽卡結果 ✨\n"
        "\n"
        "🎉 恭喜你今天抽到\n"
        "💖 Karina\n"
        "📸 類型：直拍\n"
        "\n"
        "🔗 點開看神圖\n"
        "https://example.com/karina"
    )


def test_photo_card_draw_returns_redraw_flex(monkeypatch, tmp_path: Path) -> None:
    _use_photo_card_csv(
        monkeypatch,
        tmp_path,
        "artist,type,url\nIVE,活動,https://example.com/ive\n",
    )
    client = app.test_client()

    response = client.post("/analyze", json={"message": "再抽一次神圖"})
    payload = response.get_json()
    flex = payload["flex"]

    assert flex["header"]["contents"][0]["text"] == "再抽一次"
    assert flex["body"]["contents"][0]["text"] == "想再抽一張神圖嗎？"
    assert flex["body"]["contents"][1]["action"]["text"] == "神圖抽卡"
    assert flex["body"]["contents"][2]["action"]["text"] == "互動專區"


def test_photo_card_queue_avoids_short_term_repeats(monkeypatch, tmp_path: Path) -> None:
    _use_photo_card_csv(
        monkeypatch,
        tmp_path,
        "\n".join(
            [
                "artist,type,url",
                "Karina,直拍,https://example.com/karina",
                "IVE,活動,https://example.com/ive",
                "Taeyeon,簽售,https://example.com/taeyeon",
            ]
        )
        + "\n",
    )

    draws = [app_module._load_photo_card_recommendation() for _ in range(3)]
    draw_keys = {
        (draw["artist"], draw["type"], draw["url"])
        for draw in draws
        if draw is not None
    }

    assert len(draw_keys) == 3


def test_unknown_input_does_not_crash() -> None:
    client = app.test_client()

    response = client.post("/analyze", json={"message": "這是一個未知指令"})
    payload = response.get_json()

    assert response.status_code == 200
    assert "目前支援固定指令" in payload["report"]


def test_daily_kpop_entry_still_returns_flex() -> None:
    client = app.test_client()

    response = client.post("/analyze", json={"message": "每日一首"})
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["report"] == "每日一首 K-pop"
    assert payload["flex"]["header"]["contents"][1]["text"] == "每日一首 K-pop"
