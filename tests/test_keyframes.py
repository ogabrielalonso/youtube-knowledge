import json

from PIL import Image
import pytest

from youtube_knowledge.keyframes import select


def frames(tmp_path, colors):
    directory = tmp_path / "frames"
    directory.mkdir()
    for index, color in enumerate(colors, 1):
        Image.new("RGB", (64, 36), color).save(directory / f"frame_{index:06d}.jpg")


def test_identical_collapse_changed_kept(tmp_path):
    frames(tmp_path, ["black", "black", "white", "white", "black"])
    result = select(tmp_path)
    assert [f["frame"] for f in result["keyframes"]] == [1, 3, 5]
    assert result["keyframes"][1]["start"] == 10
    assert result["keyframes"][1]["end"] == 15
    assert json.loads((tmp_path / "keyframes.json").read_text()) == result


def test_cap_spans_video_and_reports_omissions(tmp_path):
    frames(tmp_path, ["black", "white", "black", "white", "black"])
    result = select(tmp_path, maximum=2)
    assert [f["frame"] for f in result["keyframes"]] == [1, 5]
    assert result["truncated"] is True


def test_zero_threshold_still_collapses_identical(tmp_path):
    frames(tmp_path, ["black", "black"])
    assert select(tmp_path, threshold=0)["keyframe_count"] == 1


@pytest.mark.parametrize("kwargs", [{"threshold": -1}, {"threshold": 256}, {"maximum": 0}])
def test_bad_options(tmp_path, kwargs):
    with pytest.raises(ValueError):
        select(tmp_path, **kwargs)
