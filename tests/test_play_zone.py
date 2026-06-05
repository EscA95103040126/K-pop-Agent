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
    assert payload["flex"]["header"]["backgroundColor"] == "#5D6F66"
    assert payload["flex"]["body"]["backgroundColor"] == "#F7FAF8"
    assert payload["flex"]["header"]["contents"][1]["text"] == "Q1/5"


def test_bias_radar_options_use_hidden_postback_state() -> None:
    flex = app_module._build_bias_radar_question_flex_contents(0)
    first_option_action = flex["body"]["contents"][1]["action"]

    assert first_option_action["type"] == "postback"
    assert first_option_action["data"] == "本命雷達:0:男團"
    assert "text" not in first_option_action
    assert "displayText" not in first_option_action


def test_bias_radar_result_uses_matching_radar_image(monkeypatch, tmp_path: Path) -> None:
    image_dir = tmp_path / "data" / "play_zone" / "radar_image"
    image_dir.mkdir(parents=True)
    (image_dir / "aespa-karina.jpg").write_bytes(b"fake image")
    monkeypatch.setattr(app_module, "settings", SimpleNamespace(base_dir=tmp_path))
    result = {
        "recommendation": {
            "id": "aespa-karina",
            "artist": "aespa",
            "member": "KARINA",
            "group_type": "girl_group",
            "url": "https://example.com",
        },
        "matched_label_text": "貓咪、Dance",
        "reason": "你偏好貓咪、Dance的本命型，所以推薦你關注 aespa KARINA。",
    }

    with app.test_request_context("/analyze"):
        flex = app_module._build_bias_radar_result_flex_contents(result)

    assert flex["hero"]["url"] == "http://localhost/play-zone/radar-image/aespa-karina.jpg"
    assert flex["hero"]["aspectMode"] == "fit"

    response = app.test_client().get("/play-zone/radar-image/aespa-karina.jpg")
    assert response.status_code == 200
    assert response.data == b"fake image"


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
        "本命雷達:4:白月光感",
    ]
    payload = None
    for message in messages:
        response = client.post("/analyze", json={"message": message, "user_id": user_id})
        payload = response.get_json()

    assert payload is not None
    assert payload["report"].startswith("你的本命雷達結果")
    assert payload["flex"]["header"]["backgroundColor"] == "#5D6F66"
    assert payload["flex"]["body"]["backgroundColor"] == "#F7FAF8"
    assert payload["flex"]["header"]["contents"][0]["text"] == "你的本命雷達結果"
    assert payload["flex"]["body"]["contents"][-2]["color"] == "#5D6F66"

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

    assert flex["header"]["backgroundColor"] == "#5D6F66"
    assert flex["body"]["backgroundColor"] == "#F7FAF8"
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
    assert payload["flex"]["header"]["backgroundColor"] == "#5D6F66"
    assert payload["flex"]["body"]["backgroundColor"] == "#F7FAF8"
    assert payload["flex"]["header"]["contents"][1]["text"] == "團飯"
    assert payload["flex"]["body"]["contents"][-1]["color"] == "#5D6F66"


def test_play_zone_describes_three_fan_attribute_types() -> None:
    flex = app_module._build_play_zone_flex_contents()

    fan_quiz_item = flex["body"]["contents"][2]

    assert flex["header"]["backgroundColor"] == "#5D6F66"
    assert flex["body"]["backgroundColor"] == "#F7FAF8"
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
    image_dir.mkdir(parents=True)
    Image.new("RGB", (2, 3), color="white").save(image_dir / "q001.jpg")
    Image.new("RGB", (4, 5), color="white").save(image_dir / "q002.png")
    csv_path = play_zone_dir / "member_quiz.csv"
    csv_path.write_text(csv_text, encoding="utf-8")
    monkeypatch.setattr(app_module, "settings", SimpleNamespace(base_dir=tmp_path))
    app_module.member_quiz_queue = []
    app_module.member_quiz_source_key = ()
    return csv_path


def _use_ai_curator_reason_csv(
    monkeypatch,
    tmp_path: Path,
    *,
    bias_members_csv: str | None = None,
    daily_fancam_csv: str,
    daily_mv_csv: str,
    use_gemini_mock: bool = True,
) -> None:
    play_zone_dir = tmp_path / "data" / "play_zone"
    play_zone_dir.mkdir(parents=True)
    (play_zone_dir / "bias_radar_members.csv").write_text(
        bias_members_csv
        or "\n".join(
            [
                "id,artist,member,gender_group,group_type,appearance,position,vibe,relationship,url,source_url",
                "1,NMIXX,Sullyoon,女團,group,鹿,Vocal,清冷,初戀感,,",
            ]
        ),
        encoding="utf-8",
    )
    (play_zone_dir / "daily_fancam.csv").write_text(daily_fancam_csv, encoding="utf-8")
    (play_zone_dir / "daily_mv.csv").write_text(daily_mv_csv, encoding="utf-8")
    monkeypatch.setattr(
        app_module,
        "settings",
        SimpleNamespace(
            base_dir=tmp_path,
            use_gemini_mock=use_gemini_mock,
            use_naver_mock=True,
            gemini_api_key="test-key",
            gemini_model="gemini-3.5-flash",
        ),
    )
    app_module.ai_curator_reason_contexts.clear()


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
    assert flex["header"]["backgroundColor"] == "#5D6F66"
    assert flex["body"]["backgroundColor"] == "#F7FAF8"
    assert flex["body"]["contents"][0]["text"] == "想再抽一張神圖嗎？"
    assert flex["body"]["contents"][1]["action"]["text"] == "神圖抽卡"
    assert flex["body"]["contents"][1]["color"] == "#5D6F66"
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
    cache_files = list((tmp_path / "data" / "cache" / "play_zone" / "flex").glob("q001-*.jpg"))
    assert len(cache_files) == 1

    second_response = client.get("/play-zone/images/flex/q001.jpg")

    assert second_response.status_code == 200
    assert second_response.data == response.data


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
    assert payload["flex"]["header"]["backgroundColor"] == "#4E779A"
    assert payload["flex"]["body"]["backgroundColor"] == "#F4F8FC"
    assert payload["flex"]["header"]["contents"][1]["text"] == "每日一首 K-pop"


def test_ai_entry_returns_ai_curator_entry_flex() -> None:
    client = app.test_client()

    response = client.post("/analyze", json={"message": "AI 入坑"})
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["report"] == "AI 入坑"
    assert payload["flex"]["header"]["backgroundColor"] == "#6F5BA7"
    assert payload["flex"]["header"]["contents"][1]["text"] == "AI 入坑"
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
    assert payload["report"].startswith("🧭 AI 入坑")
    assert "清冷感" in payload["report"]
    assert payload["flex"]["header"]["contents"][0]["text"] == "接下來想看？"
    button_texts = [
        item["action"]["text"]
        for item in payload["flex"]["body"]["contents"]
    ]
    assert len(button_texts) == 6
    assert all(text.startswith("為什麼推薦 ") for text in button_texts[:3])
    assert all(" " not in text.removeprefix("為什麼推薦 ").removesuffix("？") for text in button_texts[:3])
    assert "本命雷達測驗" in button_texts
    assert "每日 MV" in button_texts
    assert "每日直拍" in button_texts
    assert not any(text.startswith("分析 ") for text in button_texts)
    assert {
        item.get("style")
        for item in payload["flex"]["body"]["contents"]
    } == {"secondary"}
    assert not any("color" in item for item in payload["flex"]["body"]["contents"])


def test_ai_curator_accepts_simple_appearance_preference(monkeypatch) -> None:
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

    response = client.post("/analyze", json={"message": "我喜歡小鹿臉的"})
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["report"].startswith("🧭 AI 入坑")
    assert "目前支援固定指令" not in payload["report"]
    assert payload["flex"]["header"]["contents"][0]["text"] == "接下來想看？"
    button_texts = [
        item["action"]["text"]
        for item in payload["flex"]["body"]["contents"]
    ]
    reason_buttons = [
        text for text in button_texts if text.startswith("為什麼推薦 ")
    ]
    assert len(reason_buttons) >= 2
    assert "本命雷達測驗" in button_texts
    assert "每日 MV" in button_texts
    assert "每日直拍" in button_texts


def test_ai_curator_accepts_loose_rap_member_question(monkeypatch) -> None:
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
        json={"message": "有沒有推薦很會rap的女團成員"},
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["report"].startswith("🧭 AI 入坑")
    assert "目前支援固定指令" not in payload["report"]
    assert payload["flex"]["header"]["contents"][0]["text"] == "接下來想看？"


def test_ai_curator_accepts_artist_member_question(monkeypatch) -> None:
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
        json={"message": "有沒有推薦nmixx的成員"},
    )
    payload = response.get_json()
    context = app_module._build_ai_curator_context("有沒有推薦nmixx的成員")

    assert response.status_code == 200
    assert payload["report"].startswith("🧭 AI 入坑")
    assert "NMIXX" in payload["report"]
    assert context["member_candidates"]
    assert {
        member["artist"]
        for member in context["member_candidates"][:3]
    } == {"NMIXX"}


def test_ai_curator_followup_has_three_reason_buttons_when_three_members(monkeypatch) -> None:
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

    response = client.post("/analyze", json={"message": "我喜歡小鹿臉的"})
    payload = response.get_json()
    button_texts = [
        item["action"]["text"]
        for item in payload["flex"]["body"]["contents"]
    ]

    assert response.status_code == 200
    assert len([text for text in button_texts if text.startswith("為什麼推薦 ")]) == 3


def test_ai_curator_followup_without_recommended_members_keeps_default_buttons() -> None:
    flex = app_module._build_ai_curator_followup_flex_contents(None, [])
    button_texts = [item["action"]["text"] for item in flex["body"]["contents"]]

    assert button_texts == ["本命雷達測驗", "每日 MV", "每日直拍"]


def test_ai_curator_followup_reason_buttons_keep_member_only_text_for_duplicate_names() -> None:
    flex = app_module._build_ai_curator_followup_flex_contents(
        None,
        [
            {"artist": "NMIXX", "member": "JIWOO"},
            {"artist": "Hearts2Hearts", "member": "JIWOO"},
        ],
    )
    button_texts = [item["action"]["text"] for item in flex["body"]["contents"]]

    assert button_texts.count("為什麼推薦 Jiwoo？") == 1
    assert "為什麼推薦 NMIXX Jiwoo？" not in button_texts
    assert "為什麼推薦 Hearts2Hearts Jiwoo？" not in button_texts


def test_ai_curator_daily_entry_comes_from_recommended_artists(monkeypatch) -> None:
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

    context = app_module._build_ai_curator_context("我想入坑清冷感、舞台強的女團")
    recommended_artists = set(context["recommended_artists"][:3])

    assert context["daily_items"]
    assert all(item["artist"] in recommended_artists for item in context["daily_items"])


def test_ai_curator_reason_followup_uses_member_csv_and_fancam(monkeypatch) -> None:
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

    response = client.post("/analyze", json={"message": "為什麼推薦 Sullyoon？"})
    payload = response.get_json()

    assert response.status_code == 200
    assert "NMIXX Sullyoon" in payload["report"]
    assert "小鹿、小兔" in payload["report"]
    assert "聲線和鏡頭感" in payload["report"]
    assert "Vocal、Visual" not in payload["report"]
    assert "資料裡最貼的點" not in payload["report"]
    assert "外貌是" not in payload["report"]
    assert "定位是" not in payload["report"]
    assert "氣質是" not in payload["report"]
    assert "關係感是" not in payload["report"]
    assert "外貌：" not in payload["report"]
    assert "定位：" not in payload["report"]
    assert "氣質：" not in payload["report"]
    assert "關係感：" not in payload["report"]
    assert "資料裡" not in payload["report"]
    assert "標籤" not in payload["report"]
    assert "本地本命雷達資料裡有這幾個明確標籤" not in payload["report"]
    assert "Naver 近期資料" not in payload["report"]
    assert "先用這支直拍確認感覺：NMIXX Sullyoon" in payload["report"]
    assert "https://youtu" in payload["report"]
    assert "flex" not in payload


def test_ai_curator_reason_followup_accepts_lowercase_member(monkeypatch) -> None:
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

    response = client.post("/analyze", json={"message": "推薦 karina 的理由是什麼？"})
    payload = response.get_json()

    assert response.status_code == 200
    assert "aespa Karina" in payload["report"]
    assert "冷感、霸氣、反差" in payload["report"]
    assert "直拍" in payload["report"]


def test_ai_curator_reason_followup_uses_artist_to_disambiguate_duplicate_member(
    monkeypatch,
) -> None:
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

    response = client.post("/analyze", json={"message": "為什麼推薦 NMIXX Jiwoo？"})
    payload = response.get_json()

    assert response.status_code == 200
    assert "NMIXX Jiwoo" in payload["report"]
    assert "Hearts2Hearts Jiwoo" not in payload["report"]
    assert "🎬 先用這支直拍確認感覺：NMIXX Jiwoo" in payload["report"]


def test_ai_curator_reason_followup_uses_last_ai_context_for_duplicate_member_name(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _use_ai_curator_reason_csv(
        monkeypatch,
        tmp_path,
        bias_members_csv=(
            "id,artist,member,gender_group,group_type,appearance,position,vibe,relationship,url,source_url\n"
            "1,Hearts2Hearts,JIWOO,女團,group,小鹿,Dance,清冷,朋友感,,\n"
            "2,NMIXX,JIWOO,女團,group,狗狗,Rap,反差,朋友感,,\n"
        ),
        daily_fancam_csv=(
            "artist,title,member,url\n"
            "Hearts2Hearts,The Chase,JIWOO,https://example.com/h2h-jiwoo\n"
            "NMIXX,Love Me Like This,JIWOO,https://example.com/nmixx-jiwoo\n"
        ),
        daily_mv_csv="artist,title,url\nNMIXX,DASH,https://example.com/nmixx-mv\n",
    )
    app_module._store_ai_curator_reason_context(
        "duplicate-jiwoo",
        [{"artist": "NMIXX", "member": "JIWOO"}],
    )
    client = app.test_client()

    response = client.post(
        "/analyze",
        json={"message": "為什麼推薦 Jiwoo？", "user_id": "duplicate-jiwoo"},
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert "NMIXX Jiwoo" in payload["report"]
    assert "https://example.com/nmixx-jiwoo" in payload["report"]
    assert "Hearts2Hearts Jiwoo" not in payload["report"]
    assert "https://example.com/h2h-jiwoo" not in payload["report"]


def test_ai_curator_reason_followup_prefers_member_fancam_csv(monkeypatch, tmp_path: Path) -> None:
    _use_ai_curator_reason_csv(
        monkeypatch,
        tmp_path,
        daily_fancam_csv=(
            "artist,title,member,url\n"
            "NMIXX,Love Me Like This,Sullyoon,https://example.com/sullyoon-fancam\n"
        ),
        daily_mv_csv="artist,title,url\nNMIXX,DASH,https://example.com/nmixx-mv\n",
    )
    client = app.test_client()

    response = client.post("/analyze", json={"message": "為什麼推薦 Sullyoon？"})
    payload = response.get_json()

    assert response.status_code == 200
    assert "https://example.com/sullyoon-fancam" in payload["report"]
    assert "https://example.com/nmixx-mv" not in payload["report"]


def test_ai_curator_reason_followup_falls_back_to_artist_mv_without_fancam(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _use_ai_curator_reason_csv(
        monkeypatch,
        tmp_path,
        daily_fancam_csv="artist,title,member,url\n",
        daily_mv_csv="artist,title,url\nNMIXX,DASH,https://example.com/nmixx-dash-mv\n",
    )
    client = app.test_client()

    response = client.post("/analyze", json={"message": "為什麼推薦 Sullyoon？"})
    payload = response.get_json()

    assert response.status_code == 200
    assert "https://example.com/nmixx-dash-mv" in payload["report"]
    assert "目前沒有找到 Sullyoon 的直拍" in payload["report"]


def test_ai_curator_reason_followup_gemini_failure_still_returns_link(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _use_ai_curator_reason_csv(
        monkeypatch,
        tmp_path,
        daily_fancam_csv=(
            "artist,title,member,url\n"
            "NMIXX,Love Me Like This,Sullyoon,https://example.com/sullyoon-fancam\n"
        ),
        daily_mv_csv="artist,title,url\nNMIXX,DASH,https://example.com/nmixx-mv\n",
        use_gemini_mock=False,
    )

    def raise_gemini_error(*args, **kwargs):
        raise RuntimeError("Gemini unavailable")

    monkeypatch.setattr(app_module.requests, "post", raise_gemini_error)
    client = app.test_client()

    response = client.post("/analyze", json={"message": "為什麼推薦 Sullyoon？"})
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["report"]
    assert "https://example.com/sullyoon-fancam" in payload["report"]


def test_ai_curator_reason_followup_runs_after_fixed_analyze_routes(monkeypatch) -> None:
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
    app_module.bias_radar_sessions.clear()

    ai_entry = client.post("/analyze", json={"message": "AI 入坑"}).get_json()
    preference = client.post("/analyze", json={"message": "我喜歡小鹿臉的"}).get_json()
    daily_mv = client.post("/analyze", json={"message": "每日 MV"}).get_json()
    daily_fancam = client.post("/analyze", json={"message": "每日直拍"}).get_json()
    radar = client.post(
        "/analyze",
        json={"message": "本命雷達測驗", "user_id": "route-order"},
    ).get_json()
    fan_attribute = client.post("/analyze", json={"message": "粉絲屬性測驗"}).get_json()
    artist_report = client.post("/analyze", json={"message": "分析 aespa 推薦理由"}).get_json()
    reason = client.post("/analyze", json={"message": "推薦理由 Sullyoon"}).get_json()

    assert ai_entry["report"] == "AI 入坑"
    assert preference["report"].startswith("🧭 AI 入坑")
    assert daily_mv["report"].startswith("🎵 今日推薦 MV")
    assert daily_fancam["report"].startswith("🎵 今日推薦 直拍")
    assert radar["report"].startswith("本命雷達測驗 Q1/5")
    assert fan_attribute["report"].startswith("粉絲屬性測驗 Q1/5")
    assert artist_report["cache"]["type"] == "absa"
    assert artist_report["cache"]["artist"] == "aespa"
    assert reason["report"].startswith("✨ 我會先推 NMIXX Sullyoon")
    assert "flex" not in reason


def test_webhook_mock_routes_reason_followup_after_fixed_commands(monkeypatch) -> None:
    monkeypatch.setattr(
        app_module,
        "settings",
        SimpleNamespace(
            base_dir=Path(app_module.__file__).resolve().parent,
            use_line_mock=True,
            use_gemini_mock=True,
            gemini_api_key=None,
            gemini_model="gemini-3.5-flash",
        ),
    )
    client = app.test_client()

    daily_response = json.loads(client.post("/webhook", json={"message": "每日 MV"}).data)
    ai_entry_response = json.loads(client.post("/webhook", json={"message": "AI 入坑"}).data)
    reason_response = json.loads(client.post(
        "/webhook",
        json={"message": "為何推薦 Sullyoon？"},
    ).data)

    assert daily_response["mock_reply"].startswith("🎵 今日推薦 MV")
    assert ai_entry_response["mock_reply"].startswith("請在 LINE 中點選 AI 入坑")
    assert reason_response["mock_reply"].startswith("✨ 我會先推 NMIXX Sullyoon")


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


def test_analyze_artist_payload_is_used_when_message_has_no_artist() -> None:
    client = app.test_client()

    response = client.post(
        "/analyze",
        json={"message": "請幫我分析", "artist": "aespa"},
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["cache"]["type"] == "absa"
    assert payload["cache"]["artist"] == "aespa"


def test_historical_weekly_chart_command_returns_selected_week() -> None:
    client = app.test_client()

    response = client.post("/analyze", json={"message": "歷史週榜:2026-05-11"})
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["cache"]["type"] == "weekly_chart_history"
    assert payload["cache"]["chart_date"] == "2026-05-11"
    assert payload["report"].startswith("# Bugs 歷史週榜")
    assert "榜單日期：2026-05-11" in payload["report"]


def test_weekly_chart_history_quick_reply_excludes_current_week(monkeypatch) -> None:
    monkeypatch.setattr(
        app_module,
        "agent",
        SimpleNamespace(
            list_weekly_chart_dates=lambda limit=13, min_items=1: [
                "2026-05-18",
                "2026-05-11",
            ]
        ),
    )

    qr = app_module._build_weekly_chart_history_quick_reply(
        current_chart_date="2026-05-18"
    )

    assert qr is not None
    items = qr.items
    assert len(items) == 1
    action = items[0].action
    assert action.label == "📅 5/11-5/17"
    assert action.text == "歷史週榜:2026-05-11"


def test_bias_radar_session_prunes_expired_session(monkeypatch) -> None:
    app_module.bias_radar_sessions.clear()
    app_module.bias_radar_sessions["expired-user"] = {
        "question_index": 1,
        "answers": ["男團"],
        "updated_at": 1,
    }
    monkeypatch.setattr(app_module, "time", lambda: 10_000)

    assert app_module._is_bias_radar_quiz_request("普通訊息", "expired-user") is False
    assert "expired-user" not in app_module.bias_radar_sessions


def test_reply_text_bias_radar_uses_passed_user_id() -> None:
    app_module.bias_radar_sessions.clear()

    first_reply = app_module._reply_text_for_message(
        "本命雷達測驗",
        user_id="text-flow-user",
    )
    second_reply = app_module._reply_text_for_message(
        "本命雷達:0:女團",
        user_id="text-flow-user",
    )

    assert first_reply.startswith("本命雷達測驗 Q1/5")
    assert second_reply.startswith("本命雷達測驗 Q2/5")


def test_ai_curator_reason_context_prunes_expired_context(monkeypatch) -> None:
    app_module.ai_curator_reason_contexts.clear()
    app_module.ai_curator_reason_contexts["expired-user"] = {
        "members": [{"artist": "NMIXX", "member": "Sullyoon"}],
        "stored_at": 1,
    }
    monkeypatch.setattr(app_module, "time", lambda: 10_000)

    members = app_module._ai_curator_reason_context_members("expired-user")

    assert members == []
    assert "expired-user" not in app_module.ai_curator_reason_contexts
