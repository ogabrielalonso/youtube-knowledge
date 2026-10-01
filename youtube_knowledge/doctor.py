"""Environment checks that never contact YouTube or download a model."""

import importlib
from importlib.metadata import version
import os
from pathlib import Path
import re
import subprocess
import sys

from . import config
from .fetch import deno_path, ffmpeg_path


def skill_marker() -> str:
    return f"<!-- youtube-knowledge:managed installation-id:{config.home()} -->"


def diagnose() -> dict:
    checks = []

    def check(name, function):
        try:
            detail = function()
            checks.append({"name": name, "ok": True, "detail": str(detail)})
        except Exception as exc:
            checks.append({"name": name, "ok": False, "detail": str(exc)})

    def python_check():
        if sys.version_info < (3, 12):
            raise ValueError("Python 3.12 or newer required")
        return sys.version.split()[0]

    def executable(path):
        result = subprocess.run([path, "-version" if "ffmpeg" in Path(path).name else "--version"],
                                check=True, capture_output=True, text=True, timeout=20)
        return result.stdout.splitlines()[0]

    def runtime():
        output = executable(deno_path())
        match = re.search(r"deno (\d+)\.(\d+)\.(\d+)", output)
        if not match or tuple(map(int, match.groups())) < (2, 3, 0):
            raise ValueError(f"Deno >=2.3.0 required: {output}")
        return output

    def vault_check():
        value = config.get("vault")
        if not value:
            raise ValueError("Unset. Run: yk config set vault /path/to/vault")
        if not (Path(value) / ".obsidian").is_dir():
            raise ValueError(f"Missing .obsidian directory: {value}")
        return value

    def skills_check():
        installed = []
        marker = skill_marker()
        for name, env, default in (("Claude Code", "CLAUDE_CONFIG_DIR", "~/.claude"), ("Codex", "CODEX_HOME", "~/.codex")):
            path = Path(os.environ.get(env, default)).expanduser() / "skills/youtube-knowledge/SKILL.md"
            if path.is_file() and marker in path.read_text(encoding="utf-8"):
                installed.append(name)
        if not installed:
            raise ValueError("No managed skill found. Re-run install.sh --all")
        return ", ".join(installed)

    check("Python", python_check)
    check("yt-dlp", lambda: version("yt-dlp"))
    check("curl_cffi impersonation", lambda: (importlib.import_module("curl_cffi"), version("curl-cffi"))[1])
    check("Bundled ffmpeg", lambda: executable(ffmpeg_path()))
    check("JavaScript runtime", runtime)
    check("yt-dlp EJS", lambda: version("yt-dlp-ejs"))
    check("faster-whisper", lambda: (importlib.import_module("faster_whisper"), version("faster-whisper"))[1])
    check("Obsidian vault", vault_check)
    check("Agent skill", skills_check)
    return {"ok": all(item["ok"] for item in checks), "checks": checks}
