from __future__ import annotations

import app as app_module
from app import app


class FakeSaveResult:
    def __init__(self, status: str) -> None:
        self.status = status

    @property
    def saved(self) -> bool:
        return self.status == "saved"

    @property
    def duplicate(self) -> bool:
        return self.status == "duplicate"


class FakeRadarRepository:
    enabled = True

    def __init__(self) -> None:
        self.preference = "all"
        self.saved_item_ids: set[str] = set()
        self.item = {
            "id": "00000000-0000-0000-0000-000000000001",
            "item_type": "mv",
            "gender_category": "girl_group",
            "artist": "NMIXX",
            "member": "",
            "title": "DASH",
            "url": "https://example.com/nmixx-dash",
        }

    def ensure_user(self, line_user_id: str) -> None:
        self.line_user_id = line_user_id

    def get_preference(self, line_user_id: str) -> str:
        return self.preference

    def upsert_preference(self, line_user_id: str, preferred_gender: str) -> str:
        self.preference = preferred_gender
        return preferred_gender

    def saved_counts(self, line_user_id: str) -> dict[str, int]:
        return {"mv": len(self.saved_item_ids), "fancam": 0, "photo": 0}

    def list_saved_items(self, line_user_id: str, item_type: str) -> list[dict[str, str]]:
        if item_type == "mv" and self.saved_item_ids:
            return [self.item]
        return []

    def save_item(self, line_user_id: str, item_id: str):
        if item_id in self.saved_item_ids:
            return FakeSaveResult("duplicate")
        self.saved_item_ids.add(item_id)
        return FakeSaveResult("saved")

    def recommend_daily_mv(self, line_user_id: str) -> dict[str, str]:
        return self.item


class DisabledRadarRepository(FakeRadarRepository):
    enabled = False


def test_kpop_radar_home_flex_uses_current_counts(monkeypatch) -> None:
    fake_repo = FakeRadarRepository()
    monkeypatch.setattr(app_module, "radar_repo", fake_repo)
    client = app.test_client()

    response = client.post(
        "/analyze",
        json={"message": "我的 K-pop 雷達", "user_id": "radar-user"},
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["report"] == "我的 K-pop 雷達"
    assert payload["flex"]["header"]["contents"][1]["text"] == "我的 K-pop 雷達"
    info_box = payload["flex"]["body"]["contents"][1]["contents"]
    assert info_box[0]["text"] == "目前推薦偏好：都可以"
    assert info_box[1]["text"] == "🎬 收藏過的 MV：0 個"


def test_kpop_radar_preference_update_returns_home(monkeypatch) -> None:
    fake_repo = FakeRadarRepository()
    monkeypatch.setattr(app_module, "radar_repo", fake_repo)
    client = app.test_client()

    response = client.post(
        "/analyze",
        json={
            "message": "action=set_pref&gender=girl_group",
            "user_id": "pref-user",
        },
    )
    payload = response.get_json()

    assert payload["report"] == "已更新每日 MV 推薦偏好：女團"
    info_box = payload["flex"]["body"]["contents"][1]["contents"]
    assert info_box[0]["text"] == "目前推薦偏好：女團"


def test_kpop_radar_save_item_reports_duplicate(monkeypatch) -> None:
    fake_repo = FakeRadarRepository()
    monkeypatch.setattr(app_module, "radar_repo", fake_repo)
    client = app.test_client()

    first = client.post(
        "/analyze",
        json={
            "message": "action=save_item&item_id=00000000-0000-0000-0000-000000000001",
            "user_id": "save-user",
        },
    ).get_json()
    second = client.post(
        "/analyze",
        json={
            "message": "action=save_item&item_id=00000000-0000-0000-0000-000000000001",
            "user_id": "save-user",
        },
    ).get_json()

    assert first["report"] == "已加入你的 K-pop 雷達收藏庫 ⭐"
    assert second["report"] == "這個內容已經在你的收藏庫裡了 ⭐"


def test_daily_mv_supabase_response_includes_save_postback(monkeypatch) -> None:
    fake_repo = FakeRadarRepository()
    monkeypatch.setattr(app_module, "radar_repo", fake_repo)
    client = app.test_client()

    response = client.post(
        "/analyze",
        json={"message": "每日 MV", "user_id": "daily-user"},
    )
    payload = response.get_json()

    assert payload["report"].startswith("🎵 今日推薦 MV")
    actions = [
        content["action"]
        for content in payload["flex"]["body"]["contents"]
        if content["type"] == "button"
    ]
    assert actions[0]["data"].startswith("action=save_item&item_id=")
