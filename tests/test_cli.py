import json

from youtube_knowledge.cli import main


def test_json_on_either_side(capsys):
    assert main(["--json", "config", "get", "whisper_model"]) == 0
    assert json.loads(capsys.readouterr().out) == {"whisper_model": "base"}
    assert main(["config", "get", "no_dashes", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"no_dashes": True}


def test_json_failure(capsys):
    assert main(["clean", "../../", "--lease", "a" * 32, "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_check_nonzero(tmp_path, capsys):
    path = tmp_path / "bad.md"
    path.write_text("Broken [[missing]]")
    assert main(["check", str(path), "--vault", str(tmp_path), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["files"][0]["ok"] is False


def test_clean_accepts_exact_registered_workdir(tmp_path, monkeypatch, capsys):
    from youtube_knowledge import config, fetch

    identifier = "abcdefghijk"
    path = tmp_path / f"yt_{identifier}"
    path.mkdir()
    lease = "a" * 32
    config.write_json(path / fetch.MARKER, fetch.ownership_marker(identifier))
    (path / "leases").mkdir()
    (path / "leases" / lease).touch()
    assert main(["clean", str(path), "--lease", lease, "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"workdir": str(path), "removed": True, "remaining_leases": 0}
    assert not path.exists()


def test_clean_requires_lease(capsys):
    import pytest
    with pytest.raises(SystemExit) as error:
        main(["clean", "abcdefghijk"])
    assert error.value.code == 2
    assert "--lease" in capsys.readouterr().err
