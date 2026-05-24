import csv
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import app as app_module
from app import app
from PIL import Image


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


def _use_member_quiz_csv(monkeypatch, tmp_path: Path, csv_text: str) -> Path:
    play_zone_dir = tmp_path / "data" / "play_zone"
    image_dir = play_zone_dir / "member_quiz_images"
    line_image_dir = play_zone_dir / "member_quiz_line_images"
    image_dir.mkdir(parents=True)
    line_image_dir.mkdir(parents=True)
    Image.new("RGB", (2, 3), color="white").save(image_dir / "q001.jpg")
    Image.new("RGB", (4, 5), color="white").save(image_dir / "q002.png")
    Image.new("RGB", (2, 3), color="white").save(line_image_dir / "q001.jpg")
    Image.new("RGB", (4, 5), color="white").save(line_image_dir / "q002.jpg")
    csv_path = play_zone_dir / "member_quiz.csv"
    csv_path.write_text(csv_text, encoding="utf-8")
    monkeypatch.setattr(app_module, "settings", SimpleNamespace(base_dir=tmp_path))
    app_module.member_quiz_queue = []
    app_module.member_quiz_source_key = ()
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


def test_member_quiz_csv_template_is_readable() -> None:
    csv_path = Path(app_module.__file__).resolve().parent / "data" / "play_zone" / "member_quiz.csv"

    header = csv_path.read_text(encoding="utf-8").splitlines()[0]

    assert header == "id,question,image_path,option_a,option_b,answer"


def test_member_quiz_empty_csv_does_not_crash(monkeypatch, tmp_path: Path) -> None:
    _use_member_quiz_csv(
        monkeypatch,
        tmp_path,
        "id,question,image_path,option_a,option_b,answer\n",
    )
    client = app.test_client()

    response = client.post("/analyze", json={"message": "認人測驗"})
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["report"] == app_module.MEMBER_QUIZ_EMPTY_TEXT
    assert payload["flex"] is None


def test_member_quiz_with_data_returns_question_flex(monkeypatch, tmp_path: Path) -> None:
    _use_member_quiz_csv(
        monkeypatch,
        tmp_path,
        (
            "id,question,image_path,option_a,option_b,answer\n"
            "q001,左邊是誰？,data/play_zone/member_quiz_images/q001.jpg,Winter,Karina,A\n"
        ),
    )
    client = app.test_client()

    response = client.post("/analyze", json={"message": "再一題"})
    payload = response.get_json()
    flex = payload["flex"]

    assert response.status_code == 200
    assert payload["report"] == "認人測驗：左邊是誰？"
    assert "image_url" not in payload
    assert flex["hero"]["type"] == "image"
    assert flex["hero"]["url"] == "http://localhost/play-zone/images/q001.jpg"
    assert flex["hero"]["aspectMode"] == "fit"
    assert flex["hero"]["aspectRatio"] == "1:1"
    first_action = flex["body"]["contents"][0]["action"]
    second_action = flex["body"]["contents"][1]["action"]
    assert first_action["type"] == "postback"
    assert first_action["data"] == "認人答案:q001:A"
    assert "text" not in first_action
    assert "displayText" not in first_action
    assert second_action["type"] == "postback"
    assert second_action["data"] == "認人答案:q001:B"
    assert "text" not in second_action
    assert "displayText" not in second_action


def test_member_quiz_answers_return_result_and_again_flex(monkeypatch, tmp_path: Path) -> None:
    _use_member_quiz_csv(
        monkeypatch,
        tmp_path,
        (
            "id,question,image_path,option_a,option_b,answer\n"
            "q001,哪一位是 Karina？,data/play_zone/member_quiz_images/q001.jpg,Karina,Giselle,A\n"
        ),
    )
    client = app.test_client()

    correct_response = client.post("/analyze", json={"message": "認人答案:q001:A"})
    wrong_response = client.post("/analyze", json={"message": "認人答案:q001:B"})
    correct_payload = correct_response.get_json()
    wrong_payload = wrong_response.get_json()

    assert correct_payload["report"] == "答對了！"
    assert wrong_payload["report"] == "答錯了。正解是 Karina。"
    assert correct_payload["flex"]["header"]["contents"][0]["text"] == "再來一題？"
    assert correct_payload["flex"]["body"]["contents"][1]["action"]["text"] == "認人測驗"
    assert correct_payload["flex"]["body"]["contents"][2]["action"]["text"] == "互動專區"


def test_member_quiz_missing_id_returns_missing_text(monkeypatch, tmp_path: Path) -> None:
    _use_member_quiz_csv(
        monkeypatch,
        tmp_path,
        (
            "id,question,image_path,option_a,option_b,answer\n"
            "q001,哪一位是 Karina？,data/play_zone/member_quiz_images/q001.jpg,Karina,Giselle,A\n"
        ),
    )
    client = app.test_client()

    response = client.post("/analyze", json={"message": "認人答案:missing:A"})
    payload = response.get_json()

    assert payload["report"] == "這題資料已不存在，請重新抽一題。"
    assert payload["flex"] is None


def test_member_quiz_queue_avoids_short_term_repeats(monkeypatch, tmp_path: Path) -> None:
    _use_member_quiz_csv(
        monkeypatch,
        tmp_path,
        "\n".join(
            [
                "id,question,image_path,option_a,option_b,answer",
                "q001,左邊是誰？,data/play_zone/member_quiz_images/q001.jpg,Winter,Karina,A",
                "q002,右邊是誰？,data/play_zone/member_quiz_images/q002.png,Rei,Yujin,B",
            ]
        )
        + "\n",
    )

    draws = [app_module._load_member_quiz_recommendation() for _ in range(2)]

    assert {draw["id"] for draw in draws if draw is not None} == {"q001", "q002"}


def test_member_quiz_image_route_blocks_path_traversal(monkeypatch, tmp_path: Path) -> None:
    _use_member_quiz_csv(
        monkeypatch,
        tmp_path,
        "id,question,image_path,option_a,option_b,answer\n",
    )
    client = app.test_client()

    ok_response = client.get("/play-zone/images/q001.jpg")
    traversal_response = client.get("/play-zone/images/%2E%2E/member_quiz.csv")
    unsupported_response = client.get("/play-zone/images/q001.gif")

    assert ok_response.status_code == 200
    assert traversal_response.status_code == 404
    assert unsupported_response.status_code == 404


def test_member_quiz_flex_image_route_returns_square_jpeg(monkeypatch, tmp_path: Path) -> None:
    _use_member_quiz_csv(
        monkeypatch,
        tmp_path,
        "id,question,image_path,option_a,option_b,answer\n",
    )
    client = app.test_client()

    response = client.get("/play-zone/images/flex/q001.jpg")

    assert response.status_code == 200
    assert response.content_type == "image/jpeg"
    with Image.open(BytesIO(response.data)) as image:
        assert image.size == (3, 3)


def test_member_quiz_line_image_route_returns_normalized_jpeg(monkeypatch, tmp_path: Path) -> None:
    _use_member_quiz_csv(
        monkeypatch,
        tmp_path,
        "id,question,image_path,option_a,option_b,answer\n",
    )
    client = app.test_client()

    response = client.get("/play-zone/images/line/q001.jpg")
    traversal_response = client.get("/play-zone/images/line/%2E%2E/q001.jpg")
    unsupported_response = client.get("/play-zone/images/line/q001.png")

    assert response.status_code == 200
    assert response.content_type == "image/jpeg"
    assert response.headers["Cache-Control"] == "public, max-age=86400"
    assert traversal_response.status_code == 404
    assert unsupported_response.status_code == 404


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


def test_my_radar_returns_ai_curator_entry_flex() -> None:
    client = app.test_client()

    response = client.post("/analyze", json={"message": "我的雷達"})
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["report"] == "AI K-pop 策展人"
    assert payload["flex"]["header"]["contents"][1]["text"] == "AI K-pop 策展人"
    assert payload["flex"]["body"]["contents"][1]["contents"][1]["contents"][0]["text"] == "清冷女團入坑"


def test_ai_curator_preference_uses_local_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        app_module,
        "settings",
        SimpleNamespace(
            base_dir=Path(app_module.__file__).resolve().parent,
            use_gemini_mock=True,
            gemini_api_key=None,
            gemini_model="gemini-3.5-flash",
        ),
    )
    client = app.test_client()

    response = client.post(
        "/analyze",
        json={"message": "我想入坑清冷感、舞台強的女團"},
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["report"].startswith("🧭 AI K-pop 策展人")
    assert "清冷感" in payload["report"]
    assert payload["flex"]["header"]["contents"][0]["text"] == "接下來想看？"
    button_texts = [
        item["action"]["text"]
        for item in payload["flex"]["body"]["contents"]
    ]
    assert "本命雷達測驗" in button_texts
    assert "每日 MV" in button_texts


def test_member_quiz_does_not_affect_photo_card_or_fan_attribute(monkeypatch, tmp_path: Path) -> None:
    _use_photo_card_csv(
        monkeypatch,
        tmp_path,
        "artist,type,url\nKarina,直拍,https://example.com/karina\n",
    )
    client = app.test_client()

    photo_response = client.post("/analyze", json={"message": "神圖抽卡"})
    fan_response = client.post("/analyze", json={"message": "粉絲屬性測驗"})

    assert "神圖抽卡結果" in photo_response.get_json()["report"]
    assert fan_response.get_json()["report"].startswith("粉絲屬性測驗 Q1/5")
