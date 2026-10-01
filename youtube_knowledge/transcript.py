"""Timestamp-preserving WebVTT rolling-caption deduplication and CPU Whisper."""

import html
from pathlib import Path
import re
import subprocess
import tempfile

import numpy as np

from .config import atomic_text
from .media import ffmpeg_path

TIMING = re.compile(r"(?P<start>(?:\d+:)?\d{2}:\d{2}[.,]\d+)\s+-->\s+(?P<end>(?:\d+:)?\d{2}:\d{2}[.,]\d+)")


def seconds(value: str) -> float:
    result = 0.0
    for piece in value.replace(",", ".").split(":"):
        result = result * 60 + float(piece)
    return result


def timestamp(value: float) -> str:
    value = max(0, int(value))
    return f"{value // 3600:02}:{value // 60 % 60:02}:{value % 60:02}"


def vtt_to_text(content: str) -> str:
    """Deduplicate adjacent cues only with rolling markup and continuous timing."""
    output = []
    previous = []
    previous_start = previous_end = -10.0
    rolling_track = bool(re.search(r"<(?:\d{2}:\d{2}:\d{2}\.\d{3}|c(?:\.[^>]+)?)>", content))
    for block in re.split(r"\n\s*\n", content.replace("\r\n", "\n")):
        lines = block.strip().splitlines()
        if not lines or lines[0].startswith(("NOTE", "STYLE", "REGION")):
            continue
        timing_index = next((i for i, line in enumerate(lines) if TIMING.search(line)), None)
        if timing_index is None:
            continue
        match = TIMING.search(lines[timing_index])
        start, end = seconds(match["start"]), seconds(match["end"])
        text = html.unescape(re.sub(r"<[^>]*>", "", " ".join(lines[timing_index + 1:])))
        words = text.split()
        if not words:
            continue
        overlap = 0
        if rolling_track and start <= previous_end + 0.1 and end > previous_start:
            for size in range(min(len(previous), len(words)), 0, -1):
                if previous[-size:] == words[:size]:
                    overlap = size
                    break
        elif not rolling_track and words == previous and start < previous_end and end > previous_start:
            overlap = len(words)
        if words[overlap:]:
            output.append(f"[{timestamp(start)}] {' '.join(words[overlap:])}")
        previous, previous_start, previous_end = words, start, end
    return "\n".join(output) + ("\n" if output else "")


def decode_audio(media: Path) -> np.ndarray:
    """Decode to mono 16 kHz float32 without invoking PyAV.

    ffmpeg spools s16le to a temporary file under TMPDIR. Convert in 1 MiB
    chunks into one preallocated array, avoiding full-size intermediate copies.
    Three hours need 330 MiB temporary disk and 660 MiB RAM for the returned
    array, plus small conversion buffers. Whisper's model/features are extra.
    """
    with tempfile.TemporaryFile() as pcm:
        try:
            subprocess.run([
                ffmpeg_path(), "-nostdin", "-v", "error", "-i", str(media.resolve()),
                "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000",
                "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1",
            ], stdout=pcm, stderr=subprocess.PIPE, check=True)
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or b"").decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"ffmpeg audio decoding failed: {detail}") from exc
        size = pcm.seek(0, 2)
        if not size or size % 2:
            raise ValueError("ffmpeg produced empty or incomplete PCM audio.")
        audio = np.empty(size // 2, dtype=np.float32)
        pcm.seek(0)
        offset = 0
        while chunk := pcm.read(1024 * 1024):
            samples = np.frombuffer(chunk, dtype="<i2")
            end = offset + samples.size
            np.multiply(samples, 1 / 32768, out=audio[offset:end], dtype=np.float32)
            offset = end
    return audio


def transcribe(media: Path, output: Path, model: str = "base", language: str | None = None) -> None:
    from faster_whisper import WhisperModel

    audio = decode_audio(media)
    engine = WhisperModel(model, device="cpu", compute_type="int8")
    segments, _ = engine.transcribe(audio, language=language, beam_size=5)
    lines = [f"[{timestamp(segment.start)}] {segment.text.strip()}" for segment in segments if segment.text.strip()]
    if not lines:
        raise ValueError("Whisper found no speech. No transcript was written.")
    atomic_text(output, "\n".join(lines) + "\n")
