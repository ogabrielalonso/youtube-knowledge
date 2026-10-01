"""Select visual changes with Pillow and NumPy, without ffmpeg."""

from pathlib import Path
import re

import numpy as np
from PIL import Image

from .config import write_json
from .transcript import timestamp


def select(workdir: Path, threshold: float = 12.0, maximum: int | None = None) -> dict:
    """Threshold is mean absolute grayscale difference in the range 0..255."""
    if not 0 <= threshold <= 255:
        raise ValueError("threshold must be between 0 and 255")
    if maximum is not None and maximum < 1:
        raise ValueError("max must be positive")
    frames = sorted(
        (p for p in (workdir / "frames").glob("frame_*.jpg") if re.fullmatch(r"frame_\d+\.jpg", p.name)),
        key=lambda p: int(p.stem.split("_")[-1]),
    )
    if not frames:
        raise ValueError(f"No frames in {workdir / 'frames'}. Fetch without --no-video first.")
    selected, previous = [], None
    for frame in frames:
        with Image.open(frame) as source:
            thumb = np.asarray(source.convert("L").resize((32, 18)), dtype=np.float32)
        diff = float(np.abs(thumb - previous).mean()) if previous is not None else None
        if previous is None or (diff > 0 and diff >= threshold):
            index = int(frame.stem.split("_")[-1])
            start = (index - 1) * 5
            selected.append({"path": str(frame.absolute()), "frame": index, "start": start,
                             "end": index * 5, "timestamp": timestamp(start), "diff": diff})
        previous = thumb
    candidate_count = len(selected)
    if maximum is not None and len(selected) > maximum:
        # Spread a requested cap across the entire video, not just its beginning.
        indices = np.linspace(0, len(selected) - 1, maximum, dtype=int)
        selected = [selected[i] for i in indices]
    result = {"frame_count": len(frames), "candidate_count": candidate_count,
              "keyframe_count": len(selected), "threshold": threshold,
              "truncated": candidate_count > len(selected), "keyframes": selected}
    write_json(workdir / "keyframes.json", result)
    return result
