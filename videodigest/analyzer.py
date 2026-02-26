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
    title: str
    overview: str
    chapters: List[Chapter]
    frames: List[Frame]
    diagram_data: dict = field(default_factory=dict)   # nodes + edges JSON

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "overview": self.overview,
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
            "diagram_data": self.diagram_data,
        }


# ── prompt templates ──────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a video analyst. Given a video transcript (with timestamps) and optional \
key frame screenshots, produce a structured analysis in the requested JSON format.
Be concise and insightful. Preserve timestamps exactly as they appear in the transcript.
Always respond with valid JSON only — no markdown fences, no extra text."""

_TIMESTAMPS_SYSTEM = """\
You are a video analyst. Identify key content-transition moments in a transcript.
Return only valid JSON — no markdown, no extra text."""

_DIAGRAM_SYSTEM = """\
You are a visual knowledge architect. Given a video title, overview, and chapter list, \
produce a node-edge graph structure for a hand-drawn style diagram.
Return only valid JSON — no markdown fences, no extra text."""


def _build_user_prompt(
    video_title: str,
    transcript_text: str,
    output_language: str,
) -> str:
    lang_note = (
        f"Write ALL output fields in {output_language}."
        if output_language.lower() != "english"
        else "Write all output fields in English."
    )

    return f"""\
Video title: {video_title}

Transcript (format: [MM:SS] or [HH:MM:SS] followed by text):
{transcript_text}

{lang_note}

Return a JSON object with EXACTLY this structure:
{{
  "overview": "<1-2 sentences: the single core thesis or takeaway of this video — what it is about and why it matters. Do NOT list content sections or repeat chapter details.>",
  "chapters": [
    {{
      "title": "<chapter title>",
      "timestamp": "<[MM:SS] from transcript>",
      "start_seconds": <number>,
      "summary": "<detailed paragraph of ~80-100 words: explain the specific arguments, examples, demonstrations, or data points covered in this segment. Include concrete details visible on screen if frames are provided. Do NOT repeat the overview or points already covered in other chapters.>"
    }}
  ]
}}

Requirements:
- overview: 1-2 sentences max. State the core thesis only — no section listing.
- chapters: 4-8 chapters at natural content transitions in chronological order. Each summary must be a rich paragraph (~80-100 words) with concrete, segment-specific detail. No cross-chapter repetition.
- ANTI-REPETITION: Overview = what+why (big picture only). Chapters = when + segment-specific detail. Never repeat the same sentence or point across fields."""


def _build_diagram_prompt(
    video_title: str,
    overview: str,
    chapter_titles: List[str],
    output_language: str,
) -> str:
    lang_note = (
        f"Write ALL node labels in {output_language}."
        if output_language.lower() != "english"
        else "Write all node labels in English."
    )
    chapters_list = "\n".join(f"- {t}" for t in chapter_titles)

    return f"""\
Video title: {video_title}

Overview: {overview}

Chapters:
{chapters_list}

{lang_note}

Create a knowledge graph for a hand-drawn diagram. Return a JSON object:
{{
  "nodes": [
    {{"id": "root", "label": "<core thesis in one memorable sentence, 8-12 words>", "type": "core"}},
    {{"id": "p1",   "label": "<Phase 1 heading, 3-5 words>", "type": "phase"}},
    {{"id": "p1a",  "label": "<specific insight with concrete detail, 10-15 words>", "type": "insight"}},
    {{"id": "p1b",  "label": "<another specific insight from this phase, 10-15 words>", "type": "insight"}},
    {{"id": "p2",   "label": "<Phase 2 heading, 3-5 words>", "type": "phase"}},
    {{"id": "p2a",  "label": "<key conclusion or evidence with detail, 10-15 words>", "type": "insight"}},
    {{"id": "p2b",  "label": "<supporting mechanism or implication, 10-15 words>", "type": "insight"}},
    {{"id": "p3",   "label": "<Phase 3 heading, 3-5 words>", "type": "phase"}},
    {{"id": "p3a",  "label": "<actionable takeaway or broader impact, 10-15 words>", "type": "insight"}},
    {{"id": "p3b",  "label": "<why this matters or what to do next, 10-15 words>", "type": "insight"}}
  ],
  "edges": [
    {{"from": "root", "to": "p1"}},
    {{"from": "p1", "to": "p1a"}},
    {{"from": "p1", "to": "p1b"}},
    {{"from": "root", "to": "p2"}},
    {{"from": "p2", "to": "p2a"}},
    {{"from": "p2", "to": "p2b"}},
    {{"from": "root", "to": "p3"}},
    {{"from": "p3", "to": "p3a"}},
    {{"from": "p3", "to": "p3b"}}
  ]
}}

Rules:
- Exactly 1 root node (type "core"), 3-4 phase nodes, 2-3 insight nodes per phase
- Each insight label must be a complete thought (10-15 words) — NOT a vague topic label
- Labels must NOT contain double quotes, backslashes, or special JSON chars
- Keep all labels under 80 characters"""


def _build_timestamps_prompt(
    video_title: str,
    transcript_text: str,
    n_moments: int,
) -> str:
    return f"""\
Video title: {video_title}

Transcript:
{transcript_text}

Identify exactly {n_moments} key moments in this video where the content, topic, or visual context notably shifts.
Choose timestamps at natural transition points — beginnings of new arguments, demonstrations, or topic changes.

Return JSON:
{{
  "key_moments": [
    {{"seconds": <number>, "label": "<brief label>"}},
    ...
  ]
}}"""


# ── transcript helpers ────────────────────────────────────────────────────────

def _segments_to_text(segments: List[Segment]) -> str:
    """Convert segments to a readable transcript with timestamps."""
    return "\n".join(f"{s.timestamp_str} {s.text}" for s in segments)


def _chunk_transcript(segments: List[Segment], max_chars: int) -> List[List[Segment]]:
    """Split segments into chunks that fit within max_chars."""
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


# ── JSON repair ───────────────────────────────────────────────────────────────

def _escape_json_strings(raw: str) -> str:
    """Repair common LLM JSON string issues:
    - Literal newlines/tabs inside strings → escaped (\\n, \\t)
    - Unescaped double quotes inside strings → escaped (\\")
      Uses a lookahead heuristic: a `"` that is NOT followed (after optional
      whitespace) by a JSON structural char (,  }  ]  :) is treated as an
      embedded literal quote rather than the end of the string.
    """
    result = []
    i = 0
    n = len(raw)
    in_string = False

    while i < n:
        ch = raw[i]

        if in_string:
            if ch == "\\" and i + 1 < n:
                # Already-escaped sequence — pass through both chars unchanged
                result.append(ch)
                result.append(raw[i + 1])
                i += 2
                continue
            elif ch == '"':
                # Lookahead: skip whitespace, check what follows
                j = i + 1
                while j < n and raw[j] in " \t\r\n":
                    j += 1
                if j >= n or raw[j] in ",}]:":
                    # Valid end-of-string quote
                    in_string = False
                    result.append('"')
                else:
                    # Embedded literal quote — escape it
                    result.append('\\"')
            elif ch == "\n":
                result.append("\\n")
            elif ch == "\r":
                result.append("\\r")
            elif ch == "\t":
                result.append("\\t")
            else:
                result.append(ch)
        else:
            if ch == '"':
                in_string = True
                result.append('"')
            else:
                result.append(ch)

        i += 1

    return "".join(result)


def _parse_json_response(raw: str) -> dict:
    """Strip markdown fences and parse JSON, with string repair fallback."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = "\n".join(raw.splitlines()[1:])
    if raw.endswith("```"):
        raw = raw[: raw.rfind("```")]
    return json.loads(_escape_json_strings(raw))


# ── API calls ──────────────────────────────────────────────────────────────────

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
        max_tokens=4096,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
    )

    return _parse_json_response(response.content[0].text)


# ── chunk result merging ──────────────────────────────────────────────────────

def _merge_chunk_results(results: List[dict], video_title: str) -> dict:
    """Merge multiple per-chunk JSON results into a single coherent result."""
    if len(results) == 1:
        return results[0]

    all_chapters = []
    overviews = []

    for r in results:
        overviews.append(r.get("overview", ""))
        all_chapters.extend(r.get("chapters", []))

    return {
        "overview": " ".join(overviews),
        "chapters": all_chapters,
    }


# ── public API ────────────────────────────────────────────────────────────────

def get_key_timestamps(
    video_title: str,
    segments: List[Segment],
    api_key: str,
    n_moments: int = 8,
) -> List[float]:
    """First-pass analysis: identify key chapter timestamps from transcript alone.

    This lightweight call lets the frame extractor target the exact moments
    Claude identifies as content transitions, so every frame matches its
    corresponding chapter's content rather than being uniformly sampled.

    Args:
        video_title:  Title of the video.
        segments:     Merged transcript segments.
        api_key:      Anthropic API key.
        n_moments:    Number of key moments to identify (≈ max_frames).

    Returns:
        List of timestamps in seconds, in chronological order.
    """
    try:
        import anthropic
    except ImportError:
        raise ImportError("anthropic SDK is required. Install with: pip3 install anthropic")

    client = anthropic.Anthropic(api_key=api_key)

    transcript_text = _segments_to_text(segments)
    if len(transcript_text) > _MAX_TRANSCRIPT_CHARS:
        transcript_text = transcript_text[:_MAX_TRANSCRIPT_CHARS]

    prompt = _build_timestamps_prompt(video_title, transcript_text, n_moments)

    response = client.messages.create(
        model=_MODEL,
        max_tokens=512,
        system=_TIMESTAMPS_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    data = _parse_json_response(response.content[0].text)
    timestamps = [float(m["seconds"]) for m in data.get("key_moments", [])]
    return sorted(timestamps)


def get_diagram(
    video_title: str,
    overview: str,
    chapter_titles: List[str],
    api_key: str,
    output_language: str = "English",
) -> dict:
    """Generate a knowledge graph (nodes + edges) for the diagram.

    Separate lightweight Claude call — not embedded in the main JSON response,
    so there are no JSON escaping issues with complex strings.

    Args:
        video_title:     Title of the video.
        overview:        The overview text from the main analysis.
        chapter_titles:  List of chapter title strings.
        api_key:         Anthropic API key.
        output_language: Language for node labels.

    Returns:
        dict with "nodes" and "edges" lists, or empty dict on failure.
    """
    try:
        import anthropic
    except ImportError:
        return {}

    client = anthropic.Anthropic(api_key=api_key)
    prompt = _build_diagram_prompt(video_title, overview, chapter_titles, output_language)

    try:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            system=_DIAGRAM_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        data = _parse_json_response(response.content[0].text)
        if "nodes" in data and "edges" in data:
            return data
    except Exception:
        pass

    return {}


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
        video_title:          Title of the video.
        segments:             Merged transcript segments from M4.
        frames:               Key frames from M5 (ideally targeted via get_key_timestamps).
        api_key:              Anthropic API key.
        output_language:      Language for all output text.
        max_frames_per_chunk: Max images sent per API call (cost control).

    Returns:
        A Summary with overview, chapters, diagram_data, and frames.
    """
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

    overview = merged.get("overview", "")

    # ── Second pass: generate diagram separately (avoids JSON escaping issues)
    chapter_titles = [c.title for c in chapters]
    diagram_data = get_diagram(video_title, overview, chapter_titles, api_key, output_language)

    return Summary(
        title=video_title,
        overview=overview,
        chapters=chapters,
        frames=frames,
        diagram_data=diagram_data,
    )
