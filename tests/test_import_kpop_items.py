from __future__ import annotations

from scripts.import_kpop_items import build_kpop_items


def test_import_kpop_items_builds_three_item_types() -> None:
    items = build_kpop_items()
    item_types = {item["item_type"] for item in items}

    assert {"mv", "fancam", "photo"} <= item_types
    assert any(item["gender_category"] == "girl_group" for item in items)
    assert any(item["gender_category"] == "boy_group" for item in items)
    assert all(item["artist"] and item["title"] and item["url"] for item in items)


def test_import_kpop_items_maps_photo_member_to_group() -> None:
    items = build_kpop_items()
    sullyoon_photo = next(
        item
        for item in items
        if item["item_type"] == "photo" and item["member"] == "Sullyoon"
    )

    assert sullyoon_photo["artist"] == "NMIXX"
    assert sullyoon_photo["gender_category"] == "girl_group"
    assert "Sullyoon" in sullyoon_photo["title"]
