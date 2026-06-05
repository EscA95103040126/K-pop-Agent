from types import SimpleNamespace

import app as app_module


def _event(event_id: str, user_id: str = "user-1"):
    return SimpleNamespace(
        webhook_event_id=event_id,
        source=SimpleNamespace(user_id=user_id),
    )


def test_line_event_id_supports_sdk_snake_case() -> None:
    assert app_module._line_event_id(_event("event-1")) == "event-1"


def test_line_event_dedupe_skips_processed_event(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(app_module, "LINE_EVENT_DEDUPE_PATH", tmp_path / "seen.json")
    monkeypatch.setattr(app_module, "line_processed_event_ids", None)
    app_module.line_processing_event_ids.clear()
    app_module.line_recent_message_keys.clear()

    event = _event("event-1")

    assert app_module._should_skip_line_event(event, "每日 MV") is False
    app_module._mark_line_event_processed(event)
    assert app_module._should_skip_line_event(event, "每日 MV") is True


def test_line_event_dedupe_survives_process_restart(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(app_module, "LINE_EVENT_DEDUPE_PATH", tmp_path / "seen.json")
    monkeypatch.setattr(app_module, "line_processed_event_ids", None)
    app_module.line_processing_event_ids.clear()
    app_module.line_recent_message_keys.clear()

    event = _event("event-1")
    assert app_module._should_skip_line_event(event, "每日 MV") is False
    app_module._mark_line_event_processed(event)

    monkeypatch.setattr(app_module, "line_processed_event_ids", None)
    app_module.line_processing_event_ids.clear()
    app_module.line_recent_message_keys.clear()

    assert app_module._should_skip_line_event(event, "每日 MV") is True


def test_line_event_dedupe_writes_cache_atomically(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "seen.json"
    monkeypatch.setattr(app_module, "LINE_EVENT_DEDUPE_PATH", cache_path)
    monkeypatch.setattr(app_module, "line_processed_event_ids", None)
    app_module.line_processing_event_ids.clear()
    app_module.line_recent_message_keys.clear()

    event = _event("event-atomic")
    assert app_module._should_skip_line_event(event, "每日 MV") is False
    app_module._mark_line_event_processed(event)

    assert cache_path.exists()
    assert not cache_path.with_name(f"{cache_path.name}.tmp").exists()


def test_line_message_debounce_skips_fast_duplicate(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(app_module, "LINE_EVENT_DEDUPE_PATH", tmp_path / "seen.json")
    monkeypatch.setattr(app_module, "line_processed_event_ids", None)
    app_module.line_processing_event_ids.clear()
    app_module.line_recent_message_keys.clear()

    assert app_module._should_skip_line_event(_event("event-1"), "每日 MV") is False
    assert app_module._should_skip_line_event(_event("event-2"), "每日 MV") is True
