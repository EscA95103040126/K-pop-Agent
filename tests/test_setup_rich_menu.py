from scripts import setup_rich_menu


def test_rich_menu_payload_matches_declared_items() -> None:
    payload = setup_rich_menu._rich_menu_payload()
    action_texts = [
        area["action"]["text"]
        for area in payload["areas"]
    ]

    assert action_texts == [
        item["action_text"]
        for item in setup_rich_menu.RICH_MENU_ITEMS
    ]
    assert setup_rich_menu.RICH_MENU_ITEMS[-1]["label"] == "我的口袋"
    assert setup_rich_menu.RICH_MENU_ITEMS[-1]["action_text"] == "我的口袋"
