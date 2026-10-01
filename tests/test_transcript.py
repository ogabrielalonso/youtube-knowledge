from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import imageio_ffmpeg
import numpy as np
import pytest

from youtube_knowledge import transcript
from youtube_knowledge.transcript import timestamp, vtt_to_text


def test_rolling_captions():
    text = vtt_to_text((Path(__file__).parent / "fixtures/rolling.vtt").read_text())
    assert text == (
        "[00:00:01] Welcome to the workshop.\n"
        "[00:00:02] Today we build a second brain.\n"
        "[00:00:04] Capture & connect ideas.\n"
        "[00:00:06] Keep the context.\n"
        "[00:00:30] Keep the context.\n"
    )


def test_real_youtube_auto_captions_are_clean_and_not_duplicated():
    import html
    import re

    source = (Path(__file__).parent / "fixtures/youtube-auto-format.vtt").read_text()
    lines = vtt_to_text(source).splitlines()
    assert lines[0] == "[00:00:06] Nu loli nulo fali. Mo rimi ka"
    assert all(re.fullmatch(r"\[\d{2}:\d{2}:\d{2}\] .+", line) for line in lines)
    spoken = [line.split("] ", 1)[1] for line in lines]
    assert all(not right.startswith(left) for left, right in zip(spoken, spoken[1:]))
    # Word timing tags identify newly spoken words; each tagged cue also has
    # one leading word before its first timing tag.
    reference_words = 0
    for cue in re.split(r"\n\s*\n", source):
        if "<c>" not in cue:
            continue
        reference_words += 1
        reference_words += sum(len(html.unescape(word).split()) for word in re.findall(
            r"<\d{2}:\d{2}:\d{2}\.\d{3}><c>(.*?)</c>", cue))
    actual_words = sum(len(line.split()) for line in spoken)
    assert abs(actual_words - reference_words) / reference_words < 0.05


def test_word_overlap_and_cue_identifiers():
    text = "WEBVTT\r\n\r\n1\r\n01:02.100 --> 01:04.000\r\n<c>One two three</c>\r\n\r\n2\r\n01:03.000 --> 01:05.000\r\ntwo three four\r\n"
    assert vtt_to_text(text) == "[00:01:02] One two three\n[00:01:03] four\n"
    assert timestamp(3665.9) == "01:01:05"


def test_empty_and_style_blocks():
    assert vtt_to_text("WEBVTT\n\nSTYLE\n::cue { color: red; }\n") == ""


def test_sequential_manual_repetition_is_preserved():
    content = ("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nNever give up.\n\n"
               "00:00:01.100 --> 00:00:02.000\nNever give up.\n")
    assert vtt_to_text(content) == "[00:00:00] Never give up.\n[00:00:01] Never give up.\n"


@pytest.mark.parametrize("copies", [1, 120000])
def test_whisper_receives_pcm_array_without_pyav(tmp_path, monkeypatch, copies):
    # The larger case crosses the 1 MiB conversion boundary.
    pcm = np.tile(np.array([-32768, -16384, 0, 16384, 32767], dtype="<i2"), copies)
    calls = []

    def ffmpeg(command, **kwargs):
        calls.append(command)
        assert command[0] == imageio_ffmpeg.get_ffmpeg_exe()
        assert command[command.index("-i") + 1] == str(tmp_path / "video.mkv")
        assert command[command.index("-ar") + 1] == "16000"
        assert command[command.index("-ac") + 1] == "1"
        assert command[command.index("-f") + 1] == "s16le"
        kwargs["stdout"].write(pcm.tobytes())
        return subprocess.CompletedProcess(command, 0)

    class Model:
        def __init__(self, name, **kwargs):
            assert name == "tiny"
            assert kwargs == {"device": "cpu", "compute_type": "int8"}

        def transcribe(self, audio, **kwargs):
            assert isinstance(audio, np.ndarray), "A filename would invoke PyAV"
            assert audio.dtype == np.float32 and audio.ndim == 1
            np.testing.assert_array_equal(audio, pcm.astype(np.float32) / 32768)
            assert kwargs == {"language": "en", "beam_size": 5}
            return iter([SimpleNamespace(start=62.5, text=" Hello. ")]), None

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=Model))
    monkeypatch.setattr(subprocess, "run", ffmpeg)
    output = tmp_path / "transcript.txt"
    transcript.transcribe(tmp_path / "video.mkv", output, model="tiny", language="en")
    assert len(calls) == 1
    assert output.read_text() == "[00:01:02] Hello.\n"


@pytest.mark.parametrize("source,silent", [
    ("sine=frequency=440:sample_rate=48000", False),
    ("anullsrc=r=48000:cl=stereo", True),
])
def test_decode_real_bundled_ffmpeg(tmp_path, source, silent):
    media = tmp_path / "audio with spaces.mkv"
    subprocess.run([
        imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-v", "error", "-f", "lavfi",
        "-i", source, "-t", "0.25", "-ac", "2", "-c:a", "pcm_s16le", str(media),
    ], check=True)
    audio = transcript.decode_audio(media)
    assert audio.dtype == np.float32
    assert audio.shape == (4000,)
    assert np.isfinite(audio).all()
    assert np.max(np.abs(audio)) <= 1
    assert bool(np.any(audio)) is not silent


@pytest.mark.parametrize("payload", [b"", b"\x00"])
def test_decode_rejects_empty_or_incomplete_pcm(tmp_path, monkeypatch, payload):
    def ffmpeg(command, **kwargs):
        kwargs["stdout"].write(payload)
    monkeypatch.setattr(subprocess, "run", ffmpeg)
    with pytest.raises(ValueError, match="PCM"):
        transcript.decode_audio(tmp_path / "empty.mkv")


def test_decode_failure_preserves_transcript(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=None))
    def ffmpeg(command, **kwargs):
        raise subprocess.CalledProcessError(1, command, stderr=b"Invalid data found")
    monkeypatch.setattr(subprocess, "run", ffmpeg)
    output = tmp_path / "transcript.txt"
    output.write_text("previous transcript")
    with pytest.raises(RuntimeError, match="Invalid data found"):
        transcript.transcribe(tmp_path / "broken.mkv", output)
    assert output.read_text() == "previous transcript"


@pytest.mark.parametrize("gap", [0, 0.1, 1, 30])
def test_manual_sequential_extended_repetition(gap):
    content = ("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nNever give up.\n\n"
               f"00:00:{1 + gap:06.3f} --> 00:00:35.000\nNever give up. Keep going.\n")
    assert vtt_to_text(content).splitlines()[1].endswith("Never give up. Keep going.")


@pytest.mark.parametrize("gap,dedup", [(0, True), (0.1, True), (0.101, False), (1, False), (30, False)])
def test_rolling_dedup_resets_after_gap(gap, dedup):
    content = ("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n<c>Never give up.</c>\n\n"
               f"00:00:{1 + gap:06.3f} --> 00:00:35.000\nNever give up. Keep going.\n")
    expected = "Keep going." if dedup else "Never give up. Keep going."
    assert vtt_to_text(content).splitlines()[1].split("] ", 1)[1] == expected


def test_nonrolling_overlap_preserves_partial_repetition():
    content = ("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nOne two three\n\n"
               "00:00:01.000 --> 00:00:03.000\ntwo three four\n")
    assert vtt_to_text(content) == "[00:00:00] One two three\n[00:00:01] two three four\n"


@pytest.mark.parametrize("start,count", [(1, 1), (2, 2), (3, 2)])
def test_manual_exact_duplicate_only_when_overlapping(start, count):
    content = ("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nRepeat\n\n"
               f"00:00:0{start}.000 --> 00:00:04.000\nRepeat\n")
    assert len(vtt_to_text(content).splitlines()) == count


def test_long_pause_does_not_enable_later_manual_dedup():
    content = (
        "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nOpening words\n\n"
        "00:00:01.000 --> 00:00:03.000\nOpening words continued\n\n"
        "00:00:30.000 --> 00:00:31.000\nNever give up.\n\n"
        "00:00:31.500 --> 00:00:33.000\nNever give up. Keep going.\n"
    )
    assert vtt_to_text(content) == (
        "[00:00:00] Opening words\n"
        "[00:00:01] Opening words continued\n"
        "[00:00:30] Never give up.\n"
        "[00:00:31] Never give up. Keep going.\n"
    )
