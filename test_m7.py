"""Smoke tests for M7 (formatter): Markdown and JSON output."""

import json
import shutil
import tempfile
from pathlib import Path
from PIL import Image

from videodigest.analyzer import Summary, Chapter
from videodigest.frame_extractor import Frame
from videodigest.formatter import save_markdown, save_json, _nearest_frame

TMP = Path(tempfile.mkdtemp(prefix="videodigest_m7_"))


def make_fake_frame(ts: float, idx: int, frames_dir: Path) -> Frame:
    img = Image.new("RGB", (64, 64), color=(idx * 30 % 255, 100, 200))
    p = frames_dir / f"frame_{idx:04d}_{int(ts):05d}.jpg"
    img.save(p, "JPEG")
    return Frame(path=p, timestamp=ts, segment_index=idx)


def make_summary(frames: list) -> Summary:
    return Summary(
        title="Introduction to Python",
        overview="This video teaches Python from scratch, covering syntax, data structures, and functions.",
        key_points=[
            "Python uses indentation for blocks",
            "Lists store ordered collections",
            "Dictionaries map keys to values",
            "Functions promote code reuse",
            "Modules let you organize code",
        ],
        chapters=[
            Chapter(title="Introduction",    start_time=0,   timestamp_str="[00:00]", summary="Overview of Python and its history."),
            Chapter(title="Variables",       start_time=120, timestamp_str="[02:00]", summary="Declaring and using variables in Python."),
            Chapter(title="Data Structures", start_time=300, timestamp_str="[05:00]", summary="Lists, tuples, dicts, and sets explained."),
        ],
        frames=frames,
    )


def test_nearest_frame():
    print("=== M7: _nearest_frame ===")
    frames_dir = TMP / "frames_nearest"
    frames_dir.mkdir()
    frames = [make_fake_frame(ts, i, frames_dir) for i, ts in enumerate([10.0, 130.0, 310.0])]

    assert _nearest_frame(frames, 0) == frames[0]
    assert _nearest_frame(frames, 125) == frames[1]
    assert _nearest_frame(frames, 400) == frames[2]
    assert _nearest_frame([], 100) is None
    print("  nearest_frame selection: OK")


def test_save_json():
    print("\n=== M7: save_json ===")
    frames_dir = TMP / "frames_json"
    frames_dir.mkdir()
    frames = [make_fake_frame(ts, i, frames_dir) for i, ts in enumerate([5.0, 130.0, 310.0])]
    summary = make_summary(frames)

    out = TMP / "output_json" / "summary.json"
    path = save_json(summary, out)

    assert path.exists()
    data = json.loads(path.read_text())

    assert data["title"] == "Introduction to Python"
    assert len(data["key_points"]) == 5
    assert len(data["chapters"]) == 3
    assert data["chapters"][1]["timestamp"] == "[02:00]"
    assert data["frame_count"] == 3

    print(f"  JSON written: {path}")
    print(f"  title: {data['title']}")
    print(f"  chapters: {[c['title'] for c in data['chapters']]}")


def test_save_markdown_structure():
    print("\n=== M7: save_markdown — structure ===")
    frames_dir = TMP / "frames_md"
    frames_dir.mkdir()
    frames = [make_fake_frame(ts, i, frames_dir) for i, ts in enumerate([5.0, 130.0, 310.0])]
    summary = make_summary(frames)

    out = TMP / "output_md" / "summary.md"
    path = save_markdown(summary, out, video_id="dQw4w9WgXcQ", channel="Test Channel", duration_str="08:30")

    assert path.exists()
    md = path.read_text()

    assert "# Introduction to Python" in md
    assert "Test Channel" in md
    assert "08:30" in md
    assert "youtube.com/watch" in md
    assert "## Overview" in md
    assert "## Key Points" in md
    assert "## Chapters" in md
    assert "[00:00]" in md
    assert "[02:00]" in md
    assert "[05:00]" in md

    print(f"  Markdown written: {path} ({path.stat().st_size} bytes)")
    print("  All required sections present: OK")


def test_save_markdown_no_frames():
    print("\n=== M7: save_markdown — no frames (text-only) ===")
    summary = make_summary([])
    out = TMP / "output_noframes" / "summary.md"
    path = save_markdown(summary, out, video_id="abc123")

    md = path.read_text()
    assert "## Overview" in md
    assert "## Key Points" in md
    assert "![" not in md
    print("  Text-only markdown (no images): OK")


if __name__ == "__main__":
    test_nearest_frame()
    test_save_json()
    test_save_markdown_structure()
    test_save_markdown_no_frames()

    shutil.rmtree(TMP, ignore_errors=True)
    print("\nAll M7 checks passed.")
