import app as app_module
from app import app


def test_fan_attribute_quiz_starts_with_first_question() -> None:
    client = app.test_client()

    response = client.post("/analyze", json={"message": "粉絲屬性測驗"})
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["report"] == "粉絲屬性測驗 Q1/5：請在 LINE 卡片中選擇最符合你的答案。"
    assert payload["flex"]["header"]["contents"][1]["text"] == "Q1/5"


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
