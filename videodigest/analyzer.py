"""M6 - Analyzer: send transcript + frames to Claude API, return structured summary."""

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .transcriber import Segment
from .frame_extractor import Frame

_MAX_TRANSCRIPT_CHARS = 60_000
_MODEL = "claude-sonnet-4-6"


@dataclass
class Chapter:
    title: str
    start_time: float
    timestamp_str: str
    summary: str


@dataclass
class Summary:
    title: str
    overview: str
    key_points: List[str]
    chapters: List[Chapter]
    frames: List[Frame]

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


_SYSTEM_PROMPT = """\
You are a video analyst. Given a video transcript (with timestamps) and optional \
key frame screenshots, produce a structured analysis in the requested JSON format.
Be concise and factual. Preserve timestamps exactly as they appear in the transcript.
Always respond with valid JSON only — no markdown fences, no extra text."""


def _build_user_prompt(video_title: str, transcript_text: str, output_language: str) -> str:
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


def _segments_to_text(segments: List[Segment]) -> str:
    return "\n".join(f"{s.timestamp_str} {s.text}" for s in segments)


def _chunk_transcript(segments: List[Segment], max_chars: int) -> List[List[Segment]]:
    chunks: List[List[Segment]] = []
    current: List[Segment] = []
    current_chars = 0

    for seg in segments:
        seg_chars = len(seg.text) + 12
        if current_chars + seg_chars > max_chars and current:
            chunks.append(current)
            current = []
            current_chars = 0
        current.append(seg)
        current_chars += seg_chars

    if current:
        chunks.append(current)

    return chunks


def _encode_image(path: Path) -> str:
    return base64.standard_b64encode(path.read_bytes()).decode("utf-8")


def _frames_for_chunk(frames: List[Frame], segments: List[Segment]) -> List[Frame]:
    if not segments or not frames:
        return []
    start = segments[0].start
    end = segments[-1].end
    return [f for f in frames if start <= f.timestamp <= end]


def _call_claude(client, video_title: str, segments: List[Segment], frames: List[Frame], output_language: str) -> dict:
    transcript_text = _segments_to_text(segments)
    user_text = _build_user_prompt(video_title, transcript_text, output_language)

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
    if raw.startswith("```"):
        raw = "\n".join(raw.splitlines()[1:])
    if raw.endswith("```"):
        raw = raw[: raw.rfind("```")]

    return json.loads(raw)


def _merge_chunk_results(results: List[dict], video_title: str) -> dict:
    if len(results) == 1:
        return results[0]

    all_chapters = []
    all_points = []
    overviews = []

    for r in results:
        overviews.append(r.get("overview", ""))
        all_points.extend(r.get("key_points", []))
        all_chapters.extend(r.get("chapters", []))

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


def analyze(
    video_title: str,
    segments: List[Segment],
    frames: List[Frame],
    api_key: str,
    output_language: str = "English",
    max_frames_per_chunk: int = 4,
) -> Summary:
    try:
        import anthropic
    except ImportError:
        raise ImportError("anthropic SDK is required. Install with: pip3 install anthropic")

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
