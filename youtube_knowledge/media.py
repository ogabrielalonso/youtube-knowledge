"""Bundled ffmpeg selection shared by video extraction and audio decoding."""

from pathlib import Path


def ffmpeg_path() -> str:
    import imageio_ffmpeg

    # Ignore IMAGEIO_FFMPEG_EXE overrides: the package binary is deterministic.
    binary_dir = Path(imageio_ffmpeg.__file__).parent / "binaries"
    candidates = sorted(p for p in binary_dir.glob("ffmpeg-*") if p.is_file())
    if not candidates:
        raise RuntimeError("Bundled ffmpeg is missing. Re-run the installer on a supported platform.")
    detected = Path(imageio_ffmpeg.get_ffmpeg_exe())
    return str(detected if detected in candidates else candidates[0])
