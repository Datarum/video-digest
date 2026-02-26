"""M6 - Analyzer: send transcript + frames to Claude API, return structured summary."""

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .transcriber import Segment
from .frame_extractor import Frame

# Max tokens to use for transcript text per API call (rough char budget)
_MAX_TRANSCRIPT_CHARS = 60_000

# Claude model to use
_MODEL = "claude-sonnet-4-6"


# ── output data structures ────────────────────────────────────────────────────

@dataclass
class Chapter:
    title: str
    start_time: float      # seconds
    timestamp_str: str     # e.g. "[03:42]"
    summary: str


@dataclass
class Summary:
    title: str             # video title
    overview: str          # 1-3 sentence overview
    key_points: List[str]  # 5-10 bullet points
    chapters: List[Chapter]
    frames: List[Frame]    # aligned key frames (from M5)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "overview": self.overview,
            "key_points": self.key_points,
            "chapters": [
                {
                    "title": c.title,
                    "timestamp": c.timestamp_str,
                    "start_seconds": c.start_time,
                    "summary": c.summary,
                }
                for c in self.chapters
            ],
            "frame_count": len(self.frames),
        }


# ── prompt templates ──────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a video analyst. Given a video transcript (with timestamps) and optional \
key frame screenshots, produce a structured analysis in the requested JSON format.
Be concise and factual. Preserve timestamps exactly as they appear in the transcript.
Always respond with valid JSON only — no markdown fences, no extra text."""


def _build_user_prompt(
    video_title: str,
    transcript_text: str,
    output_language: str,
) -> str:
    lang_note = (
        f"Write all output fields in {output_language}."
        if output_language.lower() != "english"
        else "Write all output fields in English."
    )

    return f"""\
Video title: {video_title}

Transcript (format: [MM:SS] or [HH:MM:SS] followed by text):
{transcript_text}

{lang_note}

Return a JSON object with exactly this structure:
{{
  "overview": "<1-3 sentence summary of the entire video>",
  "key_points": [
    "<point 1>",
    "<point 2>",
    ... (5 to 10 items)
  ],
  "chapters": [
    {{
      "title": "<chapter title>",
      "timestamp": "<[MM:SS] from transcript>",
      "start_seconds": <number>,
      "summary": "<1-2 sentence chapter summary>"
    }},
    ...
  ]
}}"""


# ── transcript helpers ────────────────────────────────────────────────────────

def _segments_to_text(segments: List[Segment]) -> str:
    """Convert segments to a readable transcript with timestamps."""
    return "\n".join(f"{s.timestamp_str} {s.text}" for s in segments)


def _chunk_transcript(segments: List[Segment], max_chars: int) -> List[List[Segment]]:
    """Split segments into chunks that fit within max_chars.

    Used for very long videos that exceed the context budget.
    Each chunk is analyzed separately, then results are merged.
    """
    chunks: List[List[Segment]] = []
    current: List[Segment] = []
    current_chars = 0

    for seg in segments:
        seg_chars = len(seg.text) + 12  # account for timestamp prefix
        if current_chars + seg_chars > max_chars and current:
            chunks.append(current)
            current = []
            current_chars = 0
        current.append(seg)
        current_chars += seg_chars

    if current:
        chunks.append(current)

    return chunks


# ── image encoding ────────────────────────────────────────────────────────────

def _encode_image(path: Path) -> str:
    """Base64-encode a JPEG for the Claude vision API."""
    return base64.standard_b64encode(path.read_bytes()).decode("utf-8")


def _frames_for_chunk(frames: List[Frame], segments: List[Segment]) -> List[Frame]:
    """Return frames whose timestamps fall within the time span of `segments`."""
    if not segments or not frames:
        return []
    start = segments[0].start
    end = segments[-1].end
    return [f for f in frames if start <= f.timestamp <= end]


# ── API call ──────────────────────────────────────────────────────────────────

def _call_claude(
    client,
    video_title: str,
    segments: List[Segment],
    frames: List[Frame],
    output_language: str,
) -> dict:
    """Send one transcript chunk + frames to Claude and parse JSON response."""
    transcript_text = _segments_to_text(segments)
    user_text = _build_user_prompt(video_title, transcript_text, output_language)

    # Build content blocks: text first, then images
    content = [{"type": "text", "text": user_text}]
    for frame in frames:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": _encode_image(frame.path),
            },
        })

    response = client.messages.create(
        model=_MODEL,
        max_tokens=2048,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
    )

    raw = response.content[0].text.strip()
    # Strip accidental markdown fences if the model adds them
    if raw.startswith("```"):
        raw = "\n".join(raw.splitlines()[1:])
    if raw.endswith("```"):
        raw = raw[: raw.rfind("```")]

    return json.loads(raw)


# ── chunk result merging ──────────────────────────────────────────────────────

def _merge_chunk_results(results: List[dict], video_title: str) -> dict:
    """Merge multiple per-chunk JSON results into a single coherent result.

    For single-chunk videos this is a no-op.
    For multi-chunk videos we concatenate chapters and consolidate key points.
    """
    if len(results) == 1:
        return results[0]

    all_chapters = []
    all_points = []
    overviews = []

    for r in results:
        overviews.append(r.get("overview", ""))
        all_points.extend(r.get("key_points", []))
        all_chapters.extend(r.get("chapters", []))

    # Deduplicate key points (keep first occurrence, drop near-duplicates)
    seen = set()
    deduped_points = []
    for p in all_points:
        key = p.strip().lower()[:60]
        if key not in seen:
            seen.add(key)
            deduped_points.append(p)

    return {
        "overview": " ".join(overviews),
        "key_points": deduped_points[:10],
        "chapters": all_chapters,
    }


# ── public API ────────────────────────────────────────────────────────────────

def analyze(
    video_title: str,
    segments: List[Segment],
    frames: List[Frame],
    api_key: str,
    output_language: str = "English",
    max_frames_per_chunk: int = 4,
) -> Summary:
    """Analyze a video transcript and key frames with Claude.

    For long videos the transcript is automatically split into chunks,
    each analyzed separately, then merged into one Summary.

    Args:
        video_title:        Title of the video (used in prompts).
        segments:           Merged transcript segments from M4.
        frames:             Key frames from M5 (may be empty if no video).
        api_key:            Anthropic API key.
        output_language:    Language for all output text (default "English").
        max_frames_per_chunk: Max images sent per API call (cost control).

    Returns:
        A Summary dataclass with overview, key_points, chapters, and frames.
    """
    try:
        import anthropic
    except ImportError:
        raise ImportError(
            "anthropic SDK is required. Install with: pip3 install anthropic"
        )

    client = anthropic.Anthropic(api_key=api_key)
    chunks = _chunk_transcript(segments, _MAX_TRANSCRIPT_CHARS)

    chunk_results = []
    for chunk_segments in chunks:
        chunk_frames = _frames_for_chunk(frames, chunk_segments)[:max_frames_per_chunk]
        result = _call_claude(client, video_title, chunk_segments, chunk_frames, output_language)
        chunk_results.append(result)

    merged = _merge_chunk_results(chunk_results, video_title)

    chapters = [
        Chapter(
            title=c.get("title", ""),
            start_time=float(c.get("start_seconds", 0)),
            timestamp_str=c.get("timestamp", ""),
            summary=c.get("summary", ""),
        )
        for c in merged.get("chapters", [])
    ]

    return Summary(
        title=video_title,
        overview=merged.get("overview", ""),
        key_points=merged.get("key_points", []),
        chapters=chapters,
        frames=frames,
    )
