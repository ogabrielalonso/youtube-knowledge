import pytest

from youtube_knowledge import config


def test_roundtrip(tmp_path):
    assert config.get("notes_language") == "auto"
    assert config.get("whisper_model") == "base"
    assert config.get("no_dashes") is True
    config.set_value("vault", str(tmp_path / "notes with spaces"))
    config.set_value("no_dashes", "false")
    config.set_value("cookies_from_browser", "firefox")
    assert config.get("vault") == str(tmp_path / "notes with spaces")
    assert config.get("no_dashes") is False
    assert config.get("cookies_from_browser") == "firefox"


@pytest.mark.parametrize("key,value", [("unknown", "x"), ("no_dashes", "maybe"), ("cookies_from_browser", "bad"), ("notes_language", "")])
def test_invalid(key, value):
    with pytest.raises(ValueError):
        config.set_value(key, value)
