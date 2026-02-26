"""Smoke tests for M6 (analyzer) — all Claude API calls are mocked."""

import json
from unittest.mock import MagicMock, patch

from videodigest.transcriber import Segment
from videodigest.frame_extractor import Frame
from videodigest.analyzer import (
    Summary,
    Chapter,
    _segments_to_text,
    _chunk_transcript,
    _frames_for_chunk,
    _merge_chunk_results,
    _build_user_prompt,
    analyze,
)

# ── fixtures ──────────────────────────────────────────────────────────────────

def make_segments(n=10, gap=60) -> list:
    return [Segment(start=i * gap, end=(i + 1) * gap, text=f"Segment {i} content.") for i in range(n)]


MOCK_CLAUDE_RESPONSE = {
    "overview": "This is a test video about Python programming.",
    "key_points": [
        "Python is easy to learn",
        "Lists and dicts are fundamental",
        "Functions reduce repetition",
        "Testing is important",
        "Use virtual environments",
    ],
    "chapters": [
        {
            "title": "Introduction",
            "timestamp": "[00:00]",
            "start_seconds": 0,
            "summary": "Brief intro to Python.",
        },
        {
            "title": "Data Structures",
            "timestamp": "[02:00]",
            "start_seconds": 120,
            "summary": "Lists, dicts, and sets explained.",
        },
    ],
}


# ── unit tests ────────────────────────────────────────────────────────────────

def test_segments_to_text():
    print("=== M6: _segments_to_text ===")
    segs = make_segments(3, gap=90)
    text = _segments_to_text(segs)
    lines = text.strip().splitlines()
    assert len(lines) == 3
    assert lines[0].startswith("[00:00]")
    assert lines[1].startswith("[01:30]")
    assert lines[2].startswith("[03:00]")
    print(f"  {len(lines)} lines, timestamps OK")
    print(f"  Sample: {lines[0]}")


def test_chunk_transcript_short():
    print("\n=== M6: _chunk_transcript (short video, fits in 1 chunk) ===")
    segs = make_segments(5, gap=60)
    chunks = _chunk_transcript(segs, max_chars=100_000)
    assert len(chunks) == 1
    assert len(chunks[0]) == 5
    print(f"  5 segments → 1 chunk: OK")


def test_chunk_transcript_long():
    print("\n=== M6: _chunk_transcript (long video, splits into chunks) ===")
    # Each segment ~30 chars; limit to 100 chars → forces splits
    segs = make_segments(20, gap=60)
    chunks = _chunk_transcript(segs, max_chars=100)
    assert len(chunks) > 1
    total = sum(len(c) for c in chunks)
    assert total == 20, f"Expected 20 total segments across chunks, got {total}"
    print(f"  20 segments → {len(chunks)} chunks (max_chars=100): OK")


def test_frames_for_chunk():
    print("\n=== M6: _frames_for_chunk ===")
    from pathlib import Path
    segs = make_segments(5, gap=60)  # 0–300s

    frames = [
        Frame(path=Path("a.jpg"), timestamp=30.0, segment_index=0),
        Frame(path=Path("b.jpg"), timestamp=90.0, segment_index=1),
        Frame(path=Path("c.jpg"), timestamp=500.0, segment_index=8),  # outside range
    ]

    matched = _frames_for_chunk(frames, segs)
    assert len(matched) == 2
    assert all(f.timestamp <= 300 for f in matched)
    print(f"  3 frames, 2 within [0, 300s] → {len(matched)} matched: OK")


def test_merge_single_chunk():
    print("\n=== M6: _merge_chunk_results (single chunk) ===")
    result = _merge_chunk_results([MOCK_CLAUDE_RESPONSE], "Test Video")
    assert result["overview"] == MOCK_CLAUDE_RESPONSE["overview"]
    assert len(result["key_points"]) == 5
    print("  single chunk passthrough: OK")


def test_merge_multiple_chunks():
    print("\n=== M6: _merge_chunk_results (multiple chunks) ===")
    chunk2 = {
        "overview": "The second half covers advanced topics.",
        "key_points": [
            "Decorators add behavior",
            "Generators save memory",
            "Python is easy to learn",  # duplicate — should be deduplicated
        ],
        "chapters": [
            {
                "title": "Advanced Topics",
                "timestamp": "[05:00]",
                "start_seconds": 300,
                "summary": "Decorators and generators.",
            }
        ],
    }
    merged = _merge_chunk_results([MOCK_CLAUDE_RESPONSE, chunk2], "Test Video")
    # Chapters combined
    assert len(merged["chapters"]) == 3
    # Duplicate key point removed
    points = merged["key_points"]
    lower_points = [p.lower() for p in points]
    assert lower_points.count("python is easy to learn") == 1, "Duplicate key point not removed"
    print(f"  2 chunks merged: {len(merged['chapters'])} chapters, {len(points)} deduped key points: OK")


def test_analyze_mocked():
    print("\n=== M6: analyze() with mocked Claude API ===")

    mock_response_text = json.dumps(MOCK_CLAUDE_RESPONSE)

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=mock_response_text)]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_message

    with patch("anthropic.Anthropic", return_value=mock_client):
        segs = make_segments(5, gap=60)
        summary = analyze(
            video_title="Test Python Video",
            segments=segs,
            frames=[],
            api_key="test-key",
            output_language="English",
        )

    assert isinstance(summary, Summary)
    assert summary.title == "Test Python Video"
    assert "Python" in summary.overview
    assert len(summary.key_points) == 5
    assert len(summary.chapters) == 2
    assert isinstance(summary.chapters[0], Chapter)

    print(f"  overview: {summary.overview}")
    print(f"  key_points ({len(summary.key_points)}): {summary.key_points[:2]} ...")
    print(f"  chapters ({len(summary.chapters)}): {[c.title for c in summary.chapters]}")

    d = summary.to_dict()
    assert d["title"] == "Test Python Video"
    print(f"  to_dict(): OK")


def test_prompt_language():
    print("\n=== M6: prompt language injection ===")
    prompt_en = _build_user_prompt("Title", "transcript", "English")
    prompt_zh = _build_user_prompt("Title", "transcript", "Chinese")
    assert "English" in prompt_en
    assert "Chinese" in prompt_zh
    print("  English prompt: OK")
    print("  Chinese prompt: OK")


if __name__ == "__main__":
    test_segments_to_text()
    test_chunk_transcript_short()
    test_chunk_transcript_long()
    test_frames_for_chunk()
    test_merge_single_chunk()
    test_merge_multiple_chunks()
    test_analyze_mocked()
    test_prompt_language()
    print("\nAll M6 checks passed.")
