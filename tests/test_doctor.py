from youtube_knowledge import config, doctor
from youtube_knowledge.cli import main


def test_doctor_failures_are_independent(monkeypatch, capsys):
    monkeypatch.setattr(doctor, "ffmpeg_path", lambda: "/missing/binary")
    monkeypatch.setattr(doctor, "deno_path", lambda: "/missing/runtime")
    result = doctor.diagnose()
    assert not result["ok"]
    checks = {item["name"]: item for item in result["checks"]}
    assert not checks["Bundled ffmpeg"]["ok"]
    assert not checks["JavaScript runtime"]["ok"]
    assert not checks["Obsidian vault"]["ok"]
    assert not checks["Agent skill"]["ok"]
    assert checks["Python"]["ok"]
    assert main(["doctor", "--json"]) == 1
    assert '"ok": false' in capsys.readouterr().out


def test_doctor_real_dependencies(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    config.set_value("vault", str(vault))
    agent = tmp_path / "claude"
    skill = agent / "skills/youtube-knowledge/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(f"<!-- youtube-knowledge:managed installation-id:{config.home()} -->")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(agent))
    result = doctor.diagnose()
    assert result["ok"], result
    assert any(item["name"] == "curl_cffi impersonation" and item["ok"] for item in result["checks"])
    skill.write_text("<!-- youtube-knowledge:managed installation-id:/another/install -->")
    checks = {item["name"]: item for item in doctor.diagnose()["checks"]}
    assert not checks["Agent skill"]["ok"]
