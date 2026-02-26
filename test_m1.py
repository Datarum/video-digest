"""Smoke tests for M1 (cli): argument parsing and pipeline orchestration (fully mocked)."""

import argparse
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

# ── helpers ───────────────────────────────────────────────────────────────────

def make_args(**kwargs) -> argparse.Namespace:
    defaults = dict(
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        output=None,
        lang="Chinese",
        api_key="test-key",
        max_frames=12,
        no_frames=False,
        whisper_model="base",
        merge_window=60.0,
        keep_temp=False,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def make_mock_info(video_id="dQw4w9WgXcQ", has_subs=True):
    info = MagicMock()
    info.video_id = video_id
    info.title = "Test Video"
    info.channel = "Test Channel"
    info.duration_str = "03:33"
    info.has_any_subtitles = has_subs
    return info


def make_mock_segments(n=5):
    from videodigest.transcriber import Segment
    return [Segment(start=i * 60, end=(i + 1) * 60, text=f"Segment {i}") for i in range(n)]


def make_mock_summary():
    from videodigest.analyzer import Summary, Chapter
    return Summary(
        title="Test Video",
        overview="A test overview.",
        key_points=["Point 1", "Point 2"],
        chapters=[Chapter("Intro", 0, "[00:00]", "Introduction.")],
        frames=[],
    )


# ── tests ─────────────────────────────────────────────────────────────────────

def test_parser_defaults():
    print("=== M1: argument parser defaults ===")
    from videodigest.cli import _build_parser
    p = _build_parser()
    args = p.parse_args(["https://youtu.be/abc123"])

    assert args.url == "https://youtu.be/abc123"
    assert args.lang == "Chinese"
    assert args.max_frames == 12
    assert args.no_frames is False
    assert args.whisper_model == "base"
    assert args.merge_window == 60.0
    assert args.keep_temp is False
    print("  defaults: OK")


def test_parser_flags():
    print("\n=== M1: argument parser flags ===")
    from videodigest.cli import _build_parser
    p = _build_parser()
    args = p.parse_args([
        "https://youtu.be/abc123",
        "--lang", "English",
        "--max-frames", "5",
        "--no-frames",
        "--whisper-model", "small",
        "--merge-window", "30",
        "--keep-temp",
        "-o", "/tmp/out",
        "--api-key", "sk-test",
    ])
    assert args.lang == "English"
    assert args.max_frames == 5
    assert args.no_frames is True
    assert args.whisper_model == "small"
    assert args.merge_window == 30.0
    assert args.keep_temp is True
    assert args.output == "/tmp/out"
    assert args.api_key == "sk-test"
    print("  all flags parsed: OK")


def test_pipeline_with_subtitles():
    print("\n=== M1: run() — subtitle path (mocked) ===")
    from videodigest.cli import run

    segs = make_mock_segments()
    summary = make_mock_summary()

    with tempfile.TemporaryDirectory() as tmp:
        args = make_args(output=tmp, no_frames=True)

        fake_srt = Path(tmp) / "sub.srt"
        fake_srt.write_text("1\n00:00:00,000 --> 00:00:05,000\nHello\n")

        with patch("videodigest.cli.get_video_info", return_value=make_mock_info(has_subs=True)), \
             patch("videodigest.cli.download_subtitles", return_value=fake_srt), \
             patch("videodigest.cli.parse_srt", return_value=segs), \
             patch("videodigest.cli.merge_segments", return_value=segs), \
             patch("videodigest.cli.analyze", return_value=summary), \
             patch("videodigest.cli.save_markdown", return_value=Path(tmp) / "summary.md"), \
             patch("videodigest.cli.save_json", return_value=Path(tmp) / "summary.json"):

            out = run(args, "test-api-key")

        assert out == Path(tmp)
        print(f"  pipeline (subtitle path) completed → {out}: OK")


def test_pipeline_whisper_fallback():
    print("\n=== M1: run() — Whisper fallback (no subtitles, mocked) ===")
    from videodigest.cli import run

    segs = make_mock_segments()
    summary = make_mock_summary()

    with tempfile.TemporaryDirectory() as tmp:
        args = make_args(output=tmp, no_frames=True)

        with patch("videodigest.cli.get_video_info", return_value=make_mock_info(has_subs=False)), \
             patch("videodigest.cli.download_audio", return_value=Path(tmp) / "audio.mp3"), \
             patch("videodigest.cli.transcribe_audio", return_value=segs), \
             patch("videodigest.cli.merge_segments", return_value=segs), \
             patch("videodigest.cli.analyze", return_value=summary), \
             patch("videodigest.cli.save_markdown", return_value=Path(tmp) / "summary.md"), \
             patch("videodigest.cli.save_json", return_value=Path(tmp) / "summary.json"):

            out = run(args, "test-api-key")

        assert out == Path(tmp)
        print(f"  pipeline (Whisper fallback) completed → {out}: OK")


def test_pipeline_with_frames():
    print("\n=== M1: run() — with frame extraction (mocked) ===")
    from videodigest.cli import run
    from videodigest.frame_extractor import Frame

    segs = make_mock_segments()
    fake_frame = Frame(path=Path("/tmp/frame.jpg"), timestamp=30.0, segment_index=0)
    summary = make_mock_summary()
    summary.frames = [fake_frame]

    with tempfile.TemporaryDirectory() as tmp:
        args = make_args(output=tmp, no_frames=False, max_frames=3)
        fake_srt = Path(tmp) / "sub.srt"
        fake_srt.write_text("dummy")

        with patch("videodigest.cli.get_video_info", return_value=make_mock_info(has_subs=True)), \
             patch("videodigest.cli.download_subtitles", return_value=fake_srt), \
             patch("videodigest.cli.parse_srt", return_value=segs), \
             patch("videodigest.cli.merge_segments", return_value=segs), \
             patch("videodigest.cli.download_video", return_value=Path(tmp) / "video.mp4"), \
             patch("videodigest.cli.extract_frames", return_value=[fake_frame]), \
             patch("videodigest.cli.analyze", return_value=summary), \
             patch("videodigest.cli.save_markdown", return_value=Path(tmp) / "summary.md"), \
             patch("videodigest.cli.save_json", return_value=Path(tmp) / "summary.json"):

            out = run(args, "test-api-key")

        assert out == Path(tmp)
        print(f"  pipeline (with frames) completed → {out}: OK")


def test_api_key_from_env():
    print("\n=== M1: main() — API key from env ===")
    from videodigest.cli import _build_parser
    import os

    p = _build_parser()
    args = p.parse_args(["https://youtu.be/abc"])
    # No --api-key flag → must read from env
    assert args.api_key is None
    key = args.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    # In CI there's no key, just verify the logic path works
    print(f"  api_key from env: {'SET' if key else 'NOT SET (expected in test)'}: OK")


def test_output_dir_default():
    print("\n=== M1: output dir defaults to ./<video_id>/ ===")
    from videodigest.cli import run

    segs = make_mock_segments()
    summary = make_mock_summary()
    video_id = "dQw4w9WgXcQ"

    with tempfile.TemporaryDirectory() as tmp:
        import os; os.chdir(tmp)
        args = make_args(output=None, no_frames=True)  # no output dir specified

        fake_srt = Path(tmp) / "sub.srt"
        fake_srt.write_text("dummy")

        with patch("videodigest.cli.get_video_info", return_value=make_mock_info(video_id=video_id, has_subs=True)), \
             patch("videodigest.cli.download_subtitles", return_value=fake_srt), \
             patch("videodigest.cli.parse_srt", return_value=segs), \
             patch("videodigest.cli.merge_segments", return_value=segs), \
             patch("videodigest.cli.analyze", return_value=summary), \
             patch("videodigest.cli.save_markdown", return_value=Path(tmp) / video_id / "summary.md"), \
             patch("videodigest.cli.save_json", return_value=Path(tmp) / video_id / "summary.json"):

            out = run(args, "test-key")

        assert out.name == video_id, f"Expected output dir name '{video_id}', got '{out.name}'"
        print(f"  default output dir = ./{video_id}/: OK")


if __name__ == "__main__":
    test_parser_defaults()
    test_parser_flags()
    test_pipeline_with_subtitles()
    test_pipeline_whisper_fallback()
    test_pipeline_with_frames()
    test_api_key_from_env()
    test_output_dir_default()
    print("\nAll M1 checks passed.")
