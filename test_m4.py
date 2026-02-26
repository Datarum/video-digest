"""Smoke tests for M4 (transcriber): parse_srt and merge_segments."""

import tempfile
from pathlib import Path

from videodigest.transcriber import parse_srt, merge_segments, Segment

# ── helpers ──────────────────────────────────────────────────────────────────

SAMPLE_SRT = """\
1
00:00:00,000 --> 00:00:03,500
Hello, welcome to this video.

2
00:00:03,500 --> 00:00:07,000
Today we're going to talk about Python.

3
00:00:07,000 --> 00:00:12,000
<font color="white">Specifically, how to parse subtitles.</font>

4
00:00:12,000 --> 00:00:18,000
Let's get started with a simple example.

5
00:00:18,000 --> 00:00:25,000
First, we read the SRT file line by line.

6
00:01:05,000 --> 00:01:10,000
After a long pause, we continue here.
"""


def test_parse_srt():
    print("=== M4: parse_srt ===")
    with tempfile.NamedTemporaryFile(suffix=".srt", mode="w", delete=False) as f:
        f.write(SAMPLE_SRT)
        tmp = Path(f.name)

    segs = parse_srt(tmp)
    tmp.unlink()

    assert len(segs) == 6, f"Expected 6 segments, got {len(segs)}"

    assert segs[0].start == 0.0
    assert segs[0].end == 3.5
    assert segs[0].text == "Hello, welcome to this video."

    # HTML tags should be stripped
    assert "<font" not in segs[2].text
    assert segs[2].text == "Specifically, how to parse subtitles."

    print(f"  Parsed {len(segs)} segments")
    for s in segs:
        print(f"  {s.timestamp_str}  ({s.duration:.1f}s)  {s.text[:60]}")


def test_merge_segments():
    print("\n=== M4: merge_segments ===")
    with tempfile.NamedTemporaryFile(suffix=".srt", mode="w", delete=False) as f:
        f.write(SAMPLE_SRT)
        tmp = Path(f.name)

    segs = parse_srt(tmp)
    tmp.unlink()

    # window=60s: segs 0-4 (0..25s) merge into one; seg 5 (65s) is separate
    merged = merge_segments(segs, window_seconds=60.0)
    assert len(merged) == 2, f"Expected 2 chunks, got {len(merged)}"
    assert "Hello" in merged[0].text
    assert "long pause" in merged[1].text

    print(f"  {len(segs)} segments → {len(merged)} chunks (window=60s)")
    for c in merged:
        print(f"  {c.timestamp_str}  ({c.duration:.1f}s)  {c.text[:80]}...")

    # window=10s: should produce more chunks
    merged_small = merge_segments(segs, window_seconds=10.0)
    print(f"  {len(segs)} segments → {len(merged_small)} chunks (window=10s)")
    assert len(merged_small) > 2


def test_segment_properties():
    print("\n=== M4: Segment properties ===")
    s = Segment(start=3661.5, end=3665.0, text="test")
    assert s.midpoint == 3663.25
    assert s.duration == 3.5
    assert s.timestamp_str == "[01:01:01]"
    print(f"  midpoint={s.midpoint}  duration={s.duration}  ts={s.timestamp_str}  OK")


if __name__ == "__main__":
    test_parse_srt()
    test_merge_segments()
    test_segment_properties()
    print("\nAll M4 checks passed.")
