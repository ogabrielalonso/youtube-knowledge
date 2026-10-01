"""Resumable single-video extraction using bundled binary dependencies."""

from contextlib import contextmanager
import fcntl
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid
from urllib.parse import parse_qs, urlparse

from . import config
from .media import ffmpeg_path
from .transcript import transcribe, vtt_to_text

VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
MARKER = ".youtube-knowledge.json"


def video_id(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"https", "http"}:
        raise ValueError("Provide an http(s) YouTube video URL.")
    if host in {"youtu.be", "www.youtu.be"}:
        candidate = parsed.path.strip("/")
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtube-nocookie.com", "www.youtube-nocookie.com"}:
        parts = parsed.path.strip("/").split("/")
        candidate = parse_qs(parsed.query).get("v", [""])[0]
        if len(parts) == 2 and parts[0] in {"shorts", "embed", "live"}:
            candidate = parts[1]
    else:
        raise ValueError("Only YouTube video URLs are supported.")
    if not VIDEO_ID.fullmatch(candidate):
        raise ValueError("The URL must identify a single YouTube video (11-character ID).")
    return candidate


def deno_path() -> str:
    import deno

    return str(deno.find_deno_bin())


class QuietLogger:
    def debug(self, message):
        pass

    def warning(self, message):
        print(f"yt-dlp: {message}", file=sys.stderr)

    def error(self, message):
        pass  # The command reports the exception once, with actionable context.


def ydl_options(settings: dict) -> dict:
    # Verified against https://github.com/yt-dlp/yt-dlp/wiki/EJS:
    # Deno >=2.3.0 is recommended; yt-dlp[default] includes matching EJS scripts.
    options = {"quiet": True, "no_warnings": False, "noprogress": True,
               "logger": QuietLogger(), "noplaylist": True,
               "ffmpeg_location": ffmpeg_path(),
               "js_runtimes": {"deno": {"path": deno_path()}},
               "cachedir": str(config.home() / "state" / "yt-dlp-cache")}
    if settings["cookies_from_browser"]:
        options["cookiesfrombrowser"] = (settings["cookies_from_browser"],)
    return options


def explain_error(error: Exception) -> str:
    message = str(error)
    lower = message.lower()
    if any(term in lower for term in ("not a bot", "confirm you", "sign in", "login required", "http error 403")):
        return ("YouTube blocked access or requires sign-in. Datacenter and VPN IPs are often blocked. "
                "On a machine with a logged-in browser, run: yk config set cookies_from_browser chrome "
                "(or safari/firefox), then retry. Cookies may not overcome an IP block; use a residential connection. "
                f"Details: {message}")
    if any(term in lower for term in ("private", "unavailable", "removed", "members-only", "not available")):
        return ("This video is private, unavailable, removed, or restricted. Check the URL and your browser access. "
                "For content your account can access, run: yk config set cookies_from_browser chrome. "
                f"Details: {message}")
    return (f"Extraction failed: {message}. Check the URL and network. "
            "Re-run the installer to upgrade yt-dlp before retrying a persistent extractor error.")


@contextmanager
def work_lock(workdir: Path):
    """Serialize artifact and lease changes; locks belong to the installation."""
    root = config.home() / "state" / "locks"
    root.mkdir(parents=True, exist_ok=True)
    identifier = hashlib.sha256(str(workdir).encode()).hexdigest()
    lock = root / f"{identifier}.lock"
    with lock.open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError(f"Workdir {workdir} is in use by another yk command.") from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def languages(info: dict) -> tuple[str | None, list[str]]:
    original = info.get("language")
    auto = info.get("automatic_captions") or {}
    if not original:
        original = next((key.removesuffix("-orig") for key in auto if key.endswith("-orig")), None)
    if not original:
        original = next((f.get("language") for f in info.get("formats", []) if f.get("language")), None)
    manual = info.get("subtitles") or {}
    if not original:
        # Best available hint if the extractor does not identify original audio.
        original = next((key for key in manual if key != "live_chat"), None)
    available = set(manual) | set(auto)
    wanted = []
    for lang in (original, "en"):
        if not lang:
            continue
        base = lang.split("-")[0]
        variants = sorted(key for key in available if key == lang or key == base or key.startswith(base + "-"))
        variants.sort(key=lambda key: (key != lang + "-orig", key != lang, key))
        wanted.extend(key for key in variants if key not in wanted and key != "live_chat")
    return original, wanted


def download_subtitles(info: dict, options: dict, workdir: Path,
                       failures: dict[str, str] | None = None) -> tuple[str | None, str | None]:
    failures = failures if failures is not None else {}
    original, wanted = languages(info)
    for lang in wanted:
        for kind, field in (("manual", "subtitles"), ("auto", "automatic_captions")):
            tracks = (info.get(field) or {}).get(lang, [])
            if not tracks:
                continue
            safe_lang = re.sub(r"[^A-Za-z0-9_-]", "_", lang)
            path = workdir / f"subs.{safe_lang}.{kind}.vtt"
            if not path.exists() or not valid_subtitle(path):
                try:
                    _download_subtitle_track(info, options, workdir, lang, kind, tracks, path)
                except Exception as exc:
                    failures[path.name] = f"Subtitle track {lang} ({kind}) failed: {exc}"
    # Prefer original-language manual, then original automatic, then English.
    ranked = sorted(workdir.glob("subs.*.*.vtt"), key=lambda p: (
        not (original and p.name.split(".")[1].split("-")[0] == original.split("-")[0]),
        ".manual." not in p.name,
        "-orig." not in p.name,
        p.name,
    ))
    selected = None
    for path in ranked:
        try:
            if not valid_subtitle(path):
                failures[path.name] = f"Subtitle track {path.name} is not usable WebVTT"
                continue
            text = vtt_to_text(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            failures[path.name] = f"Subtitle track {path.name} could not be read: {exc}"
            continue
        if not text.strip():
            failures[path.name] = f"Subtitle track {path.name} contains no usable captions"
            continue
        failures.pop(path.name, None)
        if selected is None:
            config.atomic_text(workdir / "transcript.txt", text)
            selected = "manual" if ".manual." in path.name else "auto"
    return selected, original


def _download_subtitle_track(info: dict, options: dict, workdir: Path, lang: str,
                             kind: str, tracks: list[dict], path: Path) -> None:
    """Use yt-dlp's subtitle downloader, including its HLS fragment handling."""
    from yt_dlp import YoutubeDL

    safe_lang = re.sub(r"[^A-Za-z0-9_-]", "_", lang)
    if safe_lang != lang:
        raise ValueError("Unsafe subtitle language identifier")
    prefix = workdir / f".subtitle-{kind}-{safe_lang}"
    candidate = workdir / f".subtitle-{kind}-{safe_lang}.{lang}.vtt"
    candidate.unlink(missing_ok=True)
    subtitle_options = options | {
        "skip_download": True,
        "writesubtitles": kind == "manual",
        "writeautomaticsub": kind == "auto",
        "subtitleslangs": [re.escape(lang) + "$"],
        "subtitlesformat": "vtt/best",
        "outtmpl": str(prefix) + ".%(ext)s",
    }
    try:
        with YoutubeDL(subtitle_options) as ydl:
            selected = ydl.process_subtitles(
                info.get("id") or "subtitle",
                {lang: tracks} if kind == "manual" else None,
                {lang: tracks} if kind == "auto" else None,
            ) or {}
            track = selected.get(lang)
            if not track or track.get("ext") != "vtt":
                raise ValueError("No WebVTT subtitle format is available")
            result = info.copy()
            result.setdefault("id", "subtitle")
            result.setdefault("title", "subtitle")
            result.setdefault("ext", "mp4")
            result["requested_subtitles"] = {lang: track}
            ydl.process_info(result)
            produced = Path(track.get("filepath", ""))
        if not produced.is_file() or not valid_subtitle(produced):
            raise ValueError("Downloaded subtitle is not usable WebVTT")
        produced.replace(path)
    finally:
        candidate.unlink(missing_ok=True)


def valid_subtitle(path: Path) -> bool:
    """Reject HLS playlists and other mislabeled downloads before caching them."""
    try:
        with path.open(encoding="utf-8-sig") as stream:
            return stream.read(64).lstrip().startswith("WEBVTT")
    except (OSError, UnicodeError):
        return False


def download_media(url: str, workdir: Path, options: dict, audio_only: bool = False) -> Path:
    from yt_dlp import YoutubeDL

    prefix = "audio" if audio_only else "video"
    marker = workdir / f".{prefix}.json"
    if marker.exists():
        path = workdir / json.loads(marker.read_text())["file"]
        if path.is_file() and path.stat().st_size:
            return path
    opts = options | {"outtmpl": str(workdir / f"{prefix}.%(ext)s"),
                      "format": "bestaudio/best" if audio_only else "bestvideo[height<=720]+bestaudio/best[height<=720]",
                      "merge_output_format": "mkv"}
    with YoutubeDL(opts) as ydl:
        result = ydl.extract_info(url, download=True)
        paths = [Path(item["filepath"]) for item in result.get("requested_downloads", []) if item.get("filepath")]
        paths += [Path(ydl.prepare_filename(result)), workdir / f"{prefix}.mkv"]
    # Merged output takes precedence over individual streams.
    merged = workdir / f"{prefix}.mkv"
    if merged.exists():
        paths.insert(0, merged)
    path = next((p for p in paths if p.is_file() and p.stat().st_size), None)
    if path is None:
        raise ValueError("yt-dlp completed without a usable media file.")
    config.write_json(marker, {"file": path.name})
    return path


def extract_frames(media: Path, workdir: Path) -> int:
    frames = workdir / "frames"
    marker = workdir / ".frames.json"
    if marker.exists():
        count = json.loads(marker.read_text())["count"]
        if count > 0 and len(list(frames.glob("frame_*.jpg"))) == count:
            return count
    frames.mkdir(exist_ok=True)
    for path in frames.glob("frame_*.jpg"):
        path.unlink()
    subprocess.run([ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(media),
                    "-vf", "fps=1/5:start_time=0,scale=1280:-1", "-q:v", "2",
                    str(frames / "frame_%06d.jpg")], check=True, stdout=subprocess.DEVNULL)
    count = len(list(frames.glob("frame_*.jpg")))
    if not count:
        raise ValueError("ffmpeg extracted no frames.")
    config.write_json(marker, {"count": count})
    return count


def ownership_marker(identifier: str) -> dict:
    return {"video_id": identifier, "installation": str(config.home().resolve())}


def fetch(url: str, workdir: Path | None = None, no_video: bool = False) -> dict:
    from yt_dlp import YoutubeDL
    from yt_dlp.networking.exceptions import RequestError
    from yt_dlp.utils import DownloadError

    settings = config.load()
    identifier = video_id(url)
    root = config.temporary_root(settings)
    workdir = workdir.expanduser().absolute() if workdir else root / f"yt_{identifier}"
    if workdir.name != f"yt_{identifier}":
        raise ValueError(f"--workdir must end in yt_{identifier}, so cleanup can target it safely.")
    if workdir.is_symlink():
        raise ValueError("The workdir must not be a symbolic link.")
    workdir = workdir.resolve()
    with work_lock(workdir):
        if workdir.exists() and not (workdir / MARKER).exists() and any(workdir.iterdir()):
            raise ValueError("Refusing to use a nonempty directory not created by yk.")
        workdir.mkdir(parents=True, exist_ok=True)
        marker = workdir / MARKER
        expected = ownership_marker(identifier)
        if marker.exists() and json.loads(marker.read_text()) != expected:
            raise ValueError("Workdir ownership marker is invalid or belongs to another installation.")
        config.write_json(marker, expected)
        leases = workdir / "leases"
        if leases.is_symlink():
            raise ValueError("The leases directory must not be a symbolic link.")
        leases.mkdir(exist_ok=True)
        options = ydl_options(settings)
        try:
            info_path = workdir / "info.json"
            with YoutubeDL(options) as ydl:
                info = ydl.sanitize_info(ydl.extract_info(url, download=False))
            if info.get("id") != identifier or info.get("_type") == "playlist":
                raise ValueError("The extractor did not return the requested single video.")
            config.write_json(info_path, info)
            if info.get("is_live"):
                raise ValueError("This stream is still live. Retry after the recording is available.")
            meta_path = workdir / "meta.json"
            old = json.loads(meta_path.read_text()) if meta_path.exists() else {}
            failures = dict(old.get("subtitle_failures", {}))
            source = old.get("transcript_source")
            language = old.get("language") or info.get("language")
            transcript = workdir / "transcript.txt"
            if not (transcript.exists() and transcript.stat().st_size):
                source = None
            subtitle_source, subtitle_language = download_subtitles(info, options, workdir, failures)
            source = subtitle_source or source
            language = subtitle_language or language
            media = None
            frame_count = len(list((workdir / "frames").glob("frame_*.jpg")))
            if not no_video:
                media = download_media(url, workdir, options)
                frame_count = extract_frames(media, workdir)
            if not source:
                media = media or download_media(url, workdir, options, audio_only=True)
                transcribe(media, transcript, settings["whisper_model"], language.split("-")[0] if language else None)
                source = "whisper"
            result = {"video_id": identifier, "title": info.get("title"), "channel": info.get("channel") or info.get("uploader"),
                      "duration": info.get("duration"), "upload_date": info.get("upload_date"), "language": language,
                      "url": f"https://www.youtube.com/watch?v={identifier}", "transcript_source": source,
                      "frame_count": frame_count, "workdir": str(workdir), "warnings": list(failures.values()),
                      "subtitle_failures": failures}
            config.write_json(meta_path, result)
            # Only successful fetches acquire a lease. Interrupted attempts remain resumable.
            lease = uuid.uuid4().hex
            (leases / lease).touch(exist_ok=False)
            return result | {"lease": lease}
        except (DownloadError, RequestError) as exc:
            raise RuntimeError(explain_error(exc)) from exc


def clean(workdir: str, lease: str) -> dict:
    target = Path(workdir).expanduser()
    video = target.name.removeprefix("yt_")
    if not target.is_absolute() or target.name != f"yt_{video}" or not VIDEO_ID.fullmatch(video):
        raise ValueError("Expected the exact absolute workdir returned by fetch and its lease.")
    if target.is_symlink():
        raise ValueError("Unsafe cleanup target. No files were deleted.")
    if not re.fullmatch(r"[0-9a-f]{32}", lease):
        raise ValueError("Invalid or unknown lease. No files were deleted.")
    target = target.resolve()
    with work_lock(target):
        marker = target / MARKER
        ownership = json.loads(marker.read_text()) if marker.is_file() else {}
        if ownership != ownership_marker(video):
            raise ValueError("Directory is not marked as owned by this installation. No files were deleted.")
        leases = target / "leases"
        token = leases / lease
        if leases.is_symlink() or token.is_symlink() or not token.is_file():
            raise ValueError("Stale or unknown lease. No files were deleted.")
        token.unlink()
        remaining = sum(1 for _ in leases.iterdir())
        if remaining == 0:
            shutil.rmtree(target)
    return {"workdir": str(target), "removed": remaining == 0, "remaining_leases": remaining}
