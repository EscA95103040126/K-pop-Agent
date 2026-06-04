from __future__ import annotations

import logging
import random
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

from src.config import Settings, settings

logger = logging.getLogger(__name__)

VALID_GENDERS = {"girl_group", "boy_group", "all"}
VALID_ITEM_TYPES = {"mv", "fancam", "photo"}
DAILY_MV_SOURCE_FEATURE = "daily_mv"


class KpopRadarError(RuntimeError):
    pass


@dataclass(frozen=True)
class SaveItemResult:
    status: str
    item: dict[str, Any] | None = None

    @property
    def saved(self) -> bool:
        return self.status == "saved"

    @property
    def duplicate(self) -> bool:
        return self.status == "duplicate"


class SupabaseRestClient:
    def __init__(self, url: str, service_role_key: str, timeout_seconds: int = 10) -> None:
        self.url = url.rstrip("/")
        self.service_role_key = service_role_key
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()

    def request(
        self,
        method: str,
        table: str,
        *,
        params: dict[str, str] | None = None,
        json_payload: dict[str, Any] | list[dict[str, Any]] | None = None,
        prefer: str | None = None,
    ) -> Any:
        headers = {
            "apikey": self.service_role_key,
        }
        if not self.service_role_key.startswith("sb_"):
            headers["Authorization"] = f"Bearer {self.service_role_key}"
        if json_payload is not None:
            headers["Content-Type"] = "application/json"
        if prefer:
            headers["Prefer"] = prefer

        response = self.session.request(
            method,
            f"{self.url}/rest/v1/{table}",
            params=params,
            json=json_payload,
            headers=headers,
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            raise KpopRadarError(
                f"Supabase {method} {table} failed: "
                f"{response.status_code} {response.text[:300]}"
            )
        if response.status_code == 204 or not response.content:
            return None
        return response.json()


class KpopRadarRepository:
    def __init__(
        self,
        config: Settings = settings,
        client: SupabaseRestClient | None = None,
    ) -> None:
        self.config = config
        self.client = client or self._client_from_settings(config)

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def ensure_user(
        self,
        line_user_id: str,
        *,
        display_name: str | None = None,
        picture_url: str | None = None,
    ) -> None:
        if not self.client:
            return
        if not line_user_id:
            raise ValueError("line_user_id is required")

        user_payload = {"line_user_id": line_user_id}
        if display_name:
            user_payload["display_name"] = display_name
        if picture_url:
            user_payload["picture_url"] = picture_url
        self.client.request(
            "POST",
            "users",
            params={"on_conflict": "line_user_id"},
            json_payload=user_payload,
            prefer="resolution=ignore-duplicates,return=minimal",
        )
        self.client.request(
            "POST",
            "user_preferences",
            params={"on_conflict": "line_user_id"},
            json_payload={"line_user_id": line_user_id, "preferred_gender": "all"},
            prefer="resolution=ignore-duplicates,return=minimal",
        )

    def get_preference(self, line_user_id: str) -> str:
        if not self.client:
            return "all"
        self.ensure_user(line_user_id)
        rows = self.client.request(
            "GET",
            "user_preferences",
            params={
                "select": "preferred_gender",
                "line_user_id": f"eq.{line_user_id}",
                "limit": "1",
            },
        )
        preference = _first(rows).get("preferred_gender") if rows else None
        return preference if preference in VALID_GENDERS else "all"

    def upsert_preference(self, line_user_id: str, preferred_gender: str) -> str:
        if preferred_gender not in VALID_GENDERS:
            raise ValueError(f"Unsupported preferred_gender: {preferred_gender}")
        if not self.client:
            return preferred_gender

        self.ensure_user(line_user_id)
        rows = self.client.request(
            "POST",
            "user_preferences",
            params={"on_conflict": "line_user_id"},
            json_payload={
                "line_user_id": line_user_id,
                "preferred_gender": preferred_gender,
                "updated_at": _now_iso(),
            },
            prefer="resolution=merge-duplicates,return=representation",
        )
        preference = _first(rows).get("preferred_gender") if rows else preferred_gender
        return preference if preference in VALID_GENDERS else preferred_gender

    def saved_counts(self, line_user_id: str) -> dict[str, int]:
        counts = {"mv": 0, "fancam": 0, "photo": 0}
        if not self.client:
            return counts
        self.ensure_user(line_user_id)
        rows = self.client.request(
            "GET",
            "user_saved_items",
            params={
                "select": "item_type",
                "line_user_id": f"eq.{line_user_id}",
            },
        )
        counter = Counter(row.get("item_type") for row in rows or [])
        return {item_type: int(counter.get(item_type, 0)) for item_type in counts}

    def save_item(self, line_user_id: str, item_id: str) -> SaveItemResult:
        if not self.client:
            return SaveItemResult(status="disabled")
        self.ensure_user(line_user_id)
        item = self.get_item(item_id)
        if item is None:
            return SaveItemResult(status="missing")
        item_type = str(item.get("item_type") or "")
        if item_type not in VALID_ITEM_TYPES:
            raise KpopRadarError(f"kpop_items.item_type is invalid for {item_id}: {item_type}")

        rows = self.client.request(
            "POST",
            "user_saved_items",
            params={"on_conflict": "line_user_id,item_id"},
            json_payload={
                "line_user_id": line_user_id,
                "item_id": item_id,
                "item_type": item_type,
            },
            prefer="resolution=ignore-duplicates,return=representation",
        )
        if rows:
            return SaveItemResult(status="saved", item=item)
        return SaveItemResult(status="duplicate", item=item)

    def list_saved_items(self, line_user_id: str, item_type: str) -> list[dict[str, Any]]:
        if item_type not in VALID_ITEM_TYPES:
            raise ValueError(f"Unsupported item_type: {item_type}")
        if not self.client:
            return []
        self.ensure_user(line_user_id)
        saved_rows = self.client.request(
            "GET",
            "user_saved_items",
            params={
                "select": "item_id,item_type,created_at",
                "line_user_id": f"eq.{line_user_id}",
                "item_type": f"eq.{item_type}",
                "order": "created_at.desc",
            },
        )
        if not saved_rows:
            return []

        item_ids = [str(row["item_id"]) for row in saved_rows if row.get("item_id")]
        items = self._get_items_by_ids(item_ids)
        by_id = {str(item.get("id")): item for item in items}
        return [
            {**by_id[str(row["item_id"])], "saved_at": row.get("created_at")}
            for row in saved_rows
            if str(row.get("item_id")) in by_id
        ]

    def recommend_daily_mv(self, line_user_id: str) -> dict[str, Any] | None:
        if not self.client:
            return None
        self.ensure_user(line_user_id)
        preferred_gender = self.get_preference(line_user_id)
        all_items = self._list_recommendable_mv_items(preferred_gender)
        if not all_items:
            return None

        excluded_ids = set(self._saved_item_ids(line_user_id))
        excluded_ids.update(self._drawn_item_ids(line_user_id, DAILY_MV_SOURCE_FEATURE))
        candidates = [
            item for item in all_items if str(item.get("id")) not in excluded_ids
        ] or all_items
        item = random.choice(candidates)
        self._record_draw(line_user_id, item, DAILY_MV_SOURCE_FEATURE)
        return item

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        if not self.client:
            return None
        rows = self.client.request(
            "GET",
            "kpop_items",
            params={
                "select": "*",
                "id": f"eq.{item_id}",
                "limit": "1",
            },
        )
        return _first(rows) if rows else None

    def _list_recommendable_mv_items(self, preferred_gender: str) -> list[dict[str, Any]]:
        params = {
            "select": "*",
            "item_type": "eq.mv",
        }
        if preferred_gender != "all":
            params["gender_category"] = f"eq.{preferred_gender}"
        return self.client.request("GET", "kpop_items", params=params) or []

    def _saved_item_ids(self, line_user_id: str) -> list[str]:
        rows = self.client.request(
            "GET",
            "user_saved_items",
            params={
                "select": "item_id",
                "line_user_id": f"eq.{line_user_id}",
            },
        )
        return [str(row["item_id"]) for row in rows or [] if row.get("item_id")]

    def _drawn_item_ids(self, line_user_id: str, source_feature: str) -> list[str]:
        rows = self.client.request(
            "GET",
            "user_draw_history",
            params={
                "select": "item_id",
                "line_user_id": f"eq.{line_user_id}",
                "source_feature": f"eq.{source_feature}",
            },
        )
        return [str(row["item_id"]) for row in rows or [] if row.get("item_id")]

    def _record_draw(
        self,
        line_user_id: str,
        item: dict[str, Any],
        source_feature: str,
    ) -> None:
        item_id = str(item.get("id") or "")
        item_type = str(item.get("item_type") or "")
        if not item_id or item_type not in VALID_ITEM_TYPES:
            return
        self.client.request(
            "POST",
            "user_draw_history",
            params={"on_conflict": "line_user_id,item_id,source_feature"},
            json_payload={
                "line_user_id": line_user_id,
                "item_id": item_id,
                "item_type": item_type,
                "source_feature": source_feature,
            },
            prefer="resolution=ignore-duplicates,return=minimal",
        )

    def _get_items_by_ids(self, item_ids: list[str]) -> list[dict[str, Any]]:
        if not item_ids:
            return []
        rows = self.client.request(
            "GET",
            "kpop_items",
            params={
                "select": "*",
                "id": f"in.({','.join(item_ids)})",
            },
        )
        return rows or []

    @staticmethod
    def _client_from_settings(config: Settings) -> SupabaseRestClient | None:
        if not (config.supabase_url and config.supabase_service_role_key):
            return None
        return SupabaseRestClient(
            url=config.supabase_url,
            service_role_key=config.supabase_service_role_key,
        )


def _first(rows: Any) -> dict[str, Any]:
    if isinstance(rows, list) and rows:
        return rows[0]
    return {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
