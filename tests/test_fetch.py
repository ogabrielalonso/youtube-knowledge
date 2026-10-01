import json
from pathlib import Path
import subprocess

import pytest

from youtube_knowledge import config, fetch

IDENTIFIER = "abcdefghijk"
URL = f"https://www.youtube.com/watch?v={IDENTIFIER}"


@pytest.mark.parametrize("url", [URL, "https://youtu.be/abcdefghijk?t=2", "https://www.youtube.com/shorts/abcdefghijk", "https://youtube.com/live/abcdefghijk"])
def test_video_urls(url):
    assert fetch.video_id(url) == IDENTIFIER


@pytest.mark.parametrize("url", ["https://evil.test/watch?v=abcdefghijk", "../../etc", "https://youtube.com/playlist?list=abc", "https://youtu.be/../x"])
def test_invalid_urls(url):
    with pytest.raises(ValueError):
        fetch.video_id(url)


def test_runtime_options(monkeypatch):
    settings = config.load() | {"cookies_from_browser": "chrome"}
    monkeypatch.setattr(fetch, "ffmpeg_path", lambda: "/bundled/ffmpeg")
    monkeypatch.setattr(fetch, "deno_path", lambda: "/venv/deno")
    options = fetch.ydl_options(settings)
    assert options["cookiesfrombrowser"] == ("chrome",)
    assert options["ffmpeg_location"] == "/bundled/ffmpeg"
    assert options["js_runtimes"] == {"deno": {"path": "/venv/deno"}}


def test_languages_original_and_english():
    info = {"language": "pt", "subtitles": {"pt": [], "en": [], "fr": []},
            "automatic_captions": {"pt-orig": [], "en-US": []}}
    original, wanted = fetch.languages(info)
    assert original == "pt"
    assert set(wanted) == {"pt", "pt-orig", "en", "en-US"}


def test_original_language_from_auto_track():
    assert fetch.languages({"automatic_captions": {"de-orig": [], "en": []}}) == ("de", ["de-orig", "en"])


def fake_ydl(monkeypatch, info):
    import yt_dlp

    calls = []

    class FakeYDL:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, url, download=False):
            calls.append((url, download))
            return info

        def sanitize_info(self, value):
            return value

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(fetch, "ydl_options", lambda settings: {})
    return calls


def mock_subtitle_transport(monkeypatch):
    """Adapt existing transport failure tests to the track-level boundary."""
    import yt_dlp
    from types import SimpleNamespace

    downloader = yt_dlp.YoutubeDL

    def download(info, options, workdir, lang, kind, tracks, path):
        with downloader(options) as ydl:
            with ydl.urlopen(SimpleNamespace(url=tracks[-1]["url"])) as response:
                path.write_bytes(response.read())

    monkeypatch.setattr(fetch, "_download_subtitle_track", download)


def test_fetch_subtitles_idempotence_and_clean(tmp_path, monkeypatch):
    config.set_value("tmp_dir", str(tmp_path / "temporary"))
    workdir = tmp_path / "temporary" / f"yt_{IDENTIFIER}"
    info = {"id": IDENTIFIER, "title": "Topic", "channel": "Teacher", "duration": 5,
            "language": "en", "subtitles": {}, "automatic_captions": {}}
    calls = fake_ydl(monkeypatch, info)

    def subtitles(info, options, directory, failures):
        (directory / "transcript.txt").write_text("[00:00:00] Hello\n")
        return "manual", "en"

    monkeypatch.setattr(fetch, "download_subtitles", subtitles)
    result = fetch.fetch(URL, no_video=True)
    assert result["transcript_source"] == "manual"
    assert result["frame_count"] == 0
    assert json.loads((workdir / "info.json").read_text())["id"] == IDENTIFIER
    second = fetch.fetch(URL, no_video=True)
    assert second["lease"] != result["lease"]
    assert {k: v for k, v in second.items() if k != "lease"} == {k: v for k, v in result.items() if k != "lease"}
    assert (workdir / "leases" / result["lease"]).is_file()
    assert (workdir / "leases" / second["lease"]).is_file()
    assert len(calls) == 2
    neighbor = workdir.parent / "yt_12345678901"
    neighbor.mkdir()
    (neighbor / "keep").write_text("another session")
    assert fetch.clean(str(workdir), result["lease"]) == {"workdir": str(workdir), "removed": False, "remaining_leases": 1}
    assert (workdir / "transcript.txt").exists()
    with pytest.raises(ValueError, match="Stale|unknown"):
        fetch.clean(str(workdir), result["lease"])
    assert fetch.clean(str(workdir), second["lease"])["removed"] is True
    assert (neighbor / "keep").exists()


def test_whisper_fallback_no_video_still_fetches_audio(tmp_path, monkeypatch):
    config.set_value("tmp_dir", str(tmp_path))
    fake_ydl(monkeypatch, {"id": IDENTIFIER, "title": "No captions"})
    monkeypatch.setattr(fetch, "download_subtitles", lambda *args: (None, "en"))
    calls = []

    def media(url, workdir, options, audio_only=False):
        calls.append(audio_only)
        target = workdir / "audio.webm"
        target.write_bytes(b"fake audio")
        return target

    def transcribe(media, output, model, language):
        assert model == "base" and language == "en"
        output.write_text("[00:00:00] Recovered speech\n")

    monkeypatch.setattr(fetch, "download_media", media)
    monkeypatch.setattr(fetch, "transcribe", transcribe)
    result = fetch.fetch(URL, no_video=True)
    assert result["transcript_source"] == "whisper"
    assert calls == [True]


def test_subtitle_provenance_prefers_original_auto_over_english_manual(tmp_path):
    (tmp_path / "subs.en.manual.vtt").write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello\n")
    (tmp_path / "subs.pt.auto.vtt").write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nOla\n")
    assert fetch.download_subtitles({"language": "pt"}, {}, tmp_path) == ("auto", "pt")
    assert "Ola" in (tmp_path / "transcript.txt").read_text()


def test_hls_playlist_cached_as_vtt_is_never_a_caption(tmp_path):
    path = tmp_path / "subs.en.auto.vtt"
    path.write_text("#EXTM3U\n#EXTINF:4.0,\nhttps://example.test/timedtext\n#EXT-X-ENDLIST\n")
    failures = {}
    assert fetch.download_subtitles({"language": "en"}, {}, tmp_path, failures) == (None, "en")
    assert not (tmp_path / "transcript.txt").exists()
    assert "not usable WebVTT" in failures[path.name]


def test_ytdlp_resolves_hls_auto_subtitles_and_keeps_manual_separate(tmp_path):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    auto_vtt = (Path(__file__).parent / "fixtures/youtube-auto-format.vtt").read_bytes()
    manual_vtt = b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nManual caption\n"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/playlist.m3u8":
                body = (b"#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXT-X-MEDIA-SEQUENCE:0\n"
                        b"#EXTINF:4,\n/auto.vtt\n#EXT-X-ENDLIST\n")
            elif self.path == "/auto.vtt":
                body = auto_vtt
            else:
                body = manual_vtt
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            info = {"id": IDENTIFIER, "title": "Subtitles", "language": "en",
                    "subtitles": {"en": [{"ext": "vtt", "url": base + "/manual.vtt"}]},
                    "automatic_captions": {"en": [{"ext": "vtt", "protocol": "m3u8_native",
                                                    "url": base + "/playlist.m3u8"}]}}
            (tmp_path / "subs.en.auto.vtt").write_text("#EXTM3U\n#EXT-X-ENDLIST\n")
            assert fetch.download_subtitles(info, {"quiet": True, "noprogress": True}, tmp_path) == ("manual", "en")
            auto = tmp_path / "subs.en.auto.vtt"
            assert auto.read_text().startswith("WEBVTT")
            assert "Nu<00:00:04.799><c> loli</c>" in auto.read_text()
            assert (tmp_path / "subs.en.manual.vtt").read_bytes() == manual_vtt
            assert (tmp_path / "transcript.txt").read_text() == "[00:00:00] Manual caption\n"
        finally:
            server.shutdown()
            thread.join()


def test_subtitle_downloads_both_languages_and_reuses_files(tmp_path, monkeypatch):
    import io
    import yt_dlp

    requests = []

    class Downloader:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def urlopen(self, request):
            requests.append(request.url)
            return io.BytesIO(b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nA caption\n")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", Downloader)
    mock_subtitle_transport(monkeypatch)
    info = {"language": "de", "subtitles": {"de": [{"ext": "vtt", "url": "https://example.test/de"}],
                                              "en": [{"ext": "vtt", "url": "https://example.test/en"}]}}
    assert fetch.download_subtitles(info, {}, tmp_path) == ("manual", "de")
    assert set(requests) == {"https://example.test/de", "https://example.test/en"}
    fetch.download_subtitles(info, {}, tmp_path)
    assert len(requests) == 2


def test_download_media_completion_marker(tmp_path, monkeypatch):
    import yt_dlp

    calls = []
    media = tmp_path / "video.webm"

    class Downloader:
        def __init__(self, options):
            assert options["format"] == "bestvideo[height<=720]+bestaudio/best[height<=720]"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, url, download):
            calls.append(download)
            media.write_bytes(b"completed")
            return {"requested_downloads": [{"filepath": str(media)}]}

        def prepare_filename(self, result):
            return str(media)

    monkeypatch.setattr(yt_dlp, "YoutubeDL", Downloader)
    (tmp_path / "video.webm.part").write_bytes(b"incomplete")
    assert fetch.download_media(URL, tmp_path, {}) == media
    assert fetch.download_media(URL, tmp_path, {}) == media
    assert calls == [True]


def test_partial_frames_are_replaced_without_completion_marker(tmp_path, monkeypatch):
    directory = tmp_path / "frames"
    directory.mkdir()
    stale = directory / "frame_000099.jpg"
    stale.write_bytes(b"interrupted")
    monkeypatch.setattr(fetch, "ffmpeg_path", lambda: "ffmpeg")

    def extraction(*args, **kwargs):
        assert not stale.exists()
        (directory / "frame_000001.jpg").write_bytes(b"complete")

    monkeypatch.setattr(fetch.subprocess, "run", extraction)
    assert fetch.extract_frames(tmp_path / "video.mkv", tmp_path) == 1
    assert (tmp_path / ".frames.json").exists()


def test_scoped_clean_guards(tmp_path):
    config.set_value("tmp_dir", str(tmp_path))
    with pytest.raises(ValueError):
        fetch.clean("*", "a" * 32)
    target = tmp_path / f"yt_{IDENTIFIER}"
    target.mkdir()
    (target / "keep").write_text("not managed")
    with pytest.raises(ValueError, match="not marked"):
        fetch.clean(str(target), "a" * 32)
    target.rename(tmp_path / "elsewhere")
    target.symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    with pytest.raises(ValueError, match="Unsafe"):
        fetch.clean(str(target), "a" * 32)
    assert (tmp_path / "elsewhere/keep").exists()


def test_active_lock_blocks_clean(tmp_path):
    config.set_value("tmp_dir", str(tmp_path))
    target = tmp_path / f"yt_{IDENTIFIER}"
    with fetch.work_lock(target):
        with pytest.raises(ValueError, match="in use"):
            fetch.clean(str(target), "a" * 32)


def test_custom_workdir_cleanup(tmp_path, monkeypatch):
    directory = tmp_path / "custom" / f"yt_{IDENTIFIER}"
    fake_ydl(monkeypatch, {"id": IDENTIFIER, "title": "Test"})

    def subtitles(info, options, path, failures):
        (path / "transcript.txt").write_text("[00:00:00] Test\n")
        return "auto", "en"

    monkeypatch.setattr(fetch, "download_subtitles", subtitles)
    result = fetch.fetch(URL, directory, no_video=True)
    assert fetch.clean(str(directory), result["lease"])["workdir"] == str(directory)
    assert not directory.exists()


def test_two_workdirs_same_video_require_exact_cleanup(tmp_path, monkeypatch):
    fake_ydl(monkeypatch, {"id": IDENTIFIER, "title": "Test"})
    def subtitles(info, options, path, failures):
        (path / "transcript.txt").write_text("[00:00:00] Test\n")
        return "manual", "en"
    monkeypatch.setattr(fetch, "download_subtitles", subtitles)
    a = fetch.fetch(URL, tmp_path / "a" / f"yt_{IDENTIFIER}", no_video=True)
    b = fetch.fetch(URL, tmp_path / "b" / f"yt_{IDENTIFIER}", no_video=True)
    with pytest.raises(ValueError, match="absolute"):
        fetch.clean(IDENTIFIER, a["lease"])
    with pytest.raises(ValueError, match="unknown"):
        fetch.clean(b["workdir"], a["lease"])
    assert fetch.clean(a["workdir"], a["lease"])["removed"]
    assert Path(b["workdir"]).exists()
    assert fetch.clean(b["workdir"], b["lease"])["removed"]


def test_cleanup_rejects_replaced_ownership_marker(tmp_path, monkeypatch):
    fake_ydl(monkeypatch, {"id": IDENTIFIER, "title": "Test"})
    def subtitles(info, options, path, failures):
        (path / "transcript.txt").write_text("Test")
        return "manual", "en"
    monkeypatch.setattr(fetch, "download_subtitles", subtitles)
    result = fetch.fetch(URL, tmp_path / f"yt_{IDENTIFIER}", no_video=True)
    path = Path(result["workdir"])
    marker = path / fetch.MARKER
    marker.write_text(json.dumps({"video_id": IDENTIFIER, "token": "other"}))
    with pytest.raises(ValueError, match="owned"):
        fetch.clean(str(path), result["lease"])
    assert path.exists()


def test_live_retry_refreshes_metadata(tmp_path, monkeypatch):
    config.set_value("tmp_dir", str(tmp_path))
    calls = fake_ydl(monkeypatch, {"id": IDENTIFIER, "is_live": True})
    with pytest.raises(ValueError, match="still live"):
        fetch.fetch(URL, no_video=True)
    calls = fake_ydl(monkeypatch, {"id": IDENTIFIER, "title": "Recording"})
    def subtitles(info, options, path, failures):
        (path / "transcript.txt").write_text("Test")
        return "manual", "en"
    monkeypatch.setattr(fetch, "download_subtitles", subtitles)
    assert fetch.fetch(URL, no_video=True)["title"] == "Recording"
    assert len(calls) == 1


def test_secondary_subtitle_failure_is_warning(tmp_path, monkeypatch):
    import io
    import yt_dlp
    class Downloader:
        def __init__(self, options): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def urlopen(self, request):
            if request.url.endswith("en"):
                raise RuntimeError("expired URL")
            return io.BytesIO(b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nOla\n")
    monkeypatch.setattr(yt_dlp, "YoutubeDL", Downloader)
    mock_subtitle_transport(monkeypatch)
    info = {"language": "pt", "subtitles": {"pt": [{"ext": "vtt", "url": "https://test/pt"}],
                                           "en": [{"ext": "vtt", "url": "https://test/en"}]}}
    failures = {}
    assert fetch.download_subtitles(info, {}, tmp_path, failures) == ("manual", "pt")
    assert "en" in failures["subs.en.manual.vtt"]


def test_all_subtitle_failures_fall_back_to_whisper(tmp_path, monkeypatch):
    import yt_dlp
    config.set_value("tmp_dir", str(tmp_path))
    info = {"id": IDENTIFIER, "language": "en", "subtitles": {"en": [{"ext": "vtt", "url": "https://test/en"}]}}
    class Downloader:
        def __init__(self, options): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def extract_info(self, url, download=False): return info
        def sanitize_info(self, value): return value
        def urlopen(self, request): raise RuntimeError("expired URL")
    monkeypatch.setattr(yt_dlp, "YoutubeDL", Downloader)
    mock_subtitle_transport(monkeypatch)
    monkeypatch.setattr(fetch, "ydl_options", lambda settings: {})
    def media(url, workdir, options, audio_only=False):
        path = workdir / "audio.webm"
        path.write_bytes(b"audio")
        return path
    monkeypatch.setattr(fetch, "download_media", media)
    monkeypatch.setattr(fetch, "transcribe", lambda media, output, model, language: output.write_text("Whisper text"))
    result = fetch.fetch(URL, no_video=True)
    assert result["transcript_source"] == "whisper"
    assert result["warnings"] and "en" in result["warnings"][0]
    assert json.loads((Path(result["workdir"]) / "meta.json").read_text())["warnings"] == result["warnings"]


def test_retry_uses_fresh_subtitle_url_and_keeps_completed_transcript(tmp_path, monkeypatch):
    import io
    import yt_dlp

    config.set_value("tmp_dir", str(tmp_path))
    urls = []
    metadata_calls = []
    current = {"url": "https://test/expired"}
    class Downloader:
        def __init__(self, options): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def extract_info(self, url, download=False):
            metadata_calls.append(url)
            return {"id": IDENTIFIER, "language": "en", "subtitles": {
                "en": [{"ext": "vtt", "url": current["url"]}]}}
        def sanitize_info(self, value): return value
        def urlopen(self, request):
            urls.append(request.url)
            if request.url.endswith("expired"):
                raise RuntimeError("expired URL")
            return io.BytesIO(b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nRecovered\n")
    monkeypatch.setattr(yt_dlp, "YoutubeDL", Downloader)
    mock_subtitle_transport(monkeypatch)
    monkeypatch.setattr(fetch, "ydl_options", lambda settings: {})
    monkeypatch.setattr(fetch, "download_media", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline audio")))
    with pytest.raises(RuntimeError, match="offline audio"):
        fetch.fetch(URL, no_video=True)
    current["url"] = "https://test/fresh"
    result = fetch.fetch(URL, no_video=True)
    assert result["transcript_source"] == "manual"
    assert urls == ["https://test/expired", "https://test/fresh"]
    assert len(metadata_calls) == 2
    assert "Recovered" in (Path(result["workdir"]) / "transcript.txt").read_text()
    assert fetch.fetch(URL, no_video=True)["transcript_source"] == "manual"
    assert urls == ["https://test/expired", "https://test/fresh"]


def test_cli_json_reports_secondary_subtitle_warning(tmp_path, monkeypatch, capsys):
    import io
    import yt_dlp
    from youtube_knowledge.cli import main

    config.set_value("tmp_dir", str(tmp_path))
    info = {"id": IDENTIFIER, "language": "pt", "subtitles": {
        "pt": [{"ext": "vtt", "url": "https://test/pt"}],
        "en": [{"ext": "vtt", "url": "https://test/en"}],
    }}
    class Downloader:
        def __init__(self, options): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def extract_info(self, url, download=False): return info
        def sanitize_info(self, value): return value
        def urlopen(self, request):
            if request.url.endswith("en"):
                raise RuntimeError("secondary unavailable")
            return io.BytesIO(b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nOla\n")
    monkeypatch.setattr(yt_dlp, "YoutubeDL", Downloader)
    mock_subtitle_transport(monkeypatch)
    monkeypatch.setattr(fetch, "ydl_options", lambda settings: {})
    assert main(["fetch", URL, "--no-video", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["transcript_source"] == "manual"
    assert result["warnings"] and "en" in result["warnings"][0]
    meta = json.loads((Path(result["workdir"]) / "meta.json").read_text())
    assert meta["warnings"] == result["warnings"]


@pytest.mark.parametrize("message", ["Sign in to confirm you're not a bot", "Private video", "Video unavailable"])
def test_download_error_guidance(message):
    assert "yk config set cookies_from_browser chrome" in fetch.explain_error(Exception(message))


def test_bundled_ffmpeg_extracts_and_reuses_real_frames(tmp_path, monkeypatch):
    from PIL import Image

    monkeypatch.setenv("IMAGEIO_FFMPEG_EXE", "/not/the/bundled/ffmpeg")
    binary = fetch.ffmpeg_path()
    assert "imageio_ffmpeg/binaries" in binary
    media = tmp_path / "video.mkv"
    subprocess.run([binary, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    "color=c=red:s=64x36:r=1:d=11", "-c:v", "mpeg4", str(media)], check=True)
    count = fetch.extract_frames(media, tmp_path)
    assert count >= 2
    with Image.open(next((tmp_path / "frames").glob("*.jpg"))) as image:
        assert image.width == 1280
    monkeypatch.setattr(fetch, "ffmpeg_path", lambda: pytest.fail("Complete frame extraction repeated"))
    assert fetch.extract_frames(media, tmp_path) == count


def test_stale_lease_cannot_clean_recreated_workdir(tmp_path, monkeypatch):
    fake_ydl(monkeypatch, {"id": IDENTIFIER, "title": "Test"})
    def subtitles(info, options, path, failures):
        (path / "transcript.txt").write_text("Test")
        return "manual", "en"
    monkeypatch.setattr(fetch, "download_subtitles", subtitles)
    path = tmp_path / f"yt_{IDENTIFIER}"
    first = fetch.fetch(URL, path, no_video=True)
    fetch.clean(first["workdir"], first["lease"])
    second = fetch.fetch(URL, path, no_video=True)
    with pytest.raises(ValueError, match="Stale|unknown"):
        fetch.clean(first["workdir"], first["lease"])
    assert (path / "leases" / second["lease"]).exists()
    assert (path / "transcript.txt").read_text() == "Test"
    assert fetch.clean(second["workdir"], second["lease"])["removed"]


def test_failed_fetch_does_not_leave_unclaimed_lease(tmp_path, monkeypatch):
    fake_ydl(monkeypatch, {"id": IDENTIFIER, "is_live": True})
    path = tmp_path / f"yt_{IDENTIFIER}"
    with pytest.raises(ValueError, match="still live"):
        fetch.fetch(URL, path, no_video=True)
    assert not list((path / "leases").iterdir())


def test_cached_subtitle_warnings_retry_persist_and_clear(tmp_path, monkeypatch, capsys):
    import io
    import yt_dlp
    from youtube_knowledge.cli import main

    config.set_value("tmp_dir", str(tmp_path))
    requests = []
    available = False
    advertised = True
    class Downloader:
        def __init__(self, options): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def extract_info(self, url, download=False):
            tracks = {"pt": [{"ext": "vtt", "url": "https://test/pt"}]}
            if advertised:
                tracks["en"] = [{"ext": "vtt", "url": "https://test/en"}]
            return {"id": IDENTIFIER, "title": "Test", "language": "pt", "subtitles": tracks}
        def sanitize_info(self, value): return value
        def urlopen(self, request):
            requests.append(request.url)
            if request.url.endswith("en") and not available:
                raise RuntimeError("secondary unavailable")
            return io.BytesIO(b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nOla\n")
    monkeypatch.setattr(yt_dlp, "YoutubeDL", Downloader)
    mock_subtitle_transport(monkeypatch)
    monkeypatch.setattr(fetch, "ydl_options", lambda settings: {})
    assert main(["fetch", URL, "--no-video"]) == 0
    human = capsys.readouterr()
    assert "Warning:" in human.err and "secondary unavailable" in human.err
    assert "lease:" in human.out and "workdir:" in human.out
    for _ in range(2):
        assert main(["fetch", URL, "--no-video", "--json"]) == 0
        result = json.loads(capsys.readouterr().out)
        assert "secondary unavailable" in result["warnings"][0]
        assert json.loads((Path(result["workdir"]) / "meta.json").read_text())["warnings"] == result["warnings"]
    assert requests.count("https://test/pt") == 1
    assert requests.count("https://test/en") == 3
    advertised = False
    assert fetch.fetch(URL, no_video=True)["warnings"]
    advertised = available = True
    recovered = fetch.fetch(URL, no_video=True)
    assert recovered["warnings"] == []
    assert recovered["subtitle_failures"] == {}
    assert (Path(recovered["workdir"]) / "subs.en.manual.vtt").exists()
    assert json.loads((Path(recovered["workdir"]) / "meta.json").read_text())["warnings"] == []
