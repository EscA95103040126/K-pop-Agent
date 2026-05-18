from app import app


def test_health_reports_integrations() -> None:
    client = app.test_client()

    response = client.get("/health")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["sqlite_ok"] is True
    assert payload["bugs_tool_available"] is True
    assert payload["naver_mode"] in {"real", "mock"}
    assert payload["gemini_mode"] in {"real", "mock"}
    assert payload["line_mode"] in {"real", "mock"}
    assert payload["sqlite"]["chart_history_rows"] >= 0
