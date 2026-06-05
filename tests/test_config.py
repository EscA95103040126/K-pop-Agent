from src.config import _int_from_env


def test_int_from_env_falls_back_for_invalid_values(monkeypatch) -> None:
    monkeypatch.setenv("PORT", "not-a-port")

    assert _int_from_env("PORT", 5000) == 5000


def test_int_from_env_reads_valid_values(monkeypatch) -> None:
    monkeypatch.setenv("PORT", "7860")

    assert _int_from_env("PORT", 5000) == 7860
