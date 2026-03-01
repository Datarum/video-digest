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
    content_type_data: dict = field(default_factory=dict)  # content classification (NBB)
    illustration_url: str = ""                             # Flux image URL (NBB)

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
            "content_type_data": self.content_type_data,
            "illustration_url": self.illustration_url,
        }


# ── prompt templates ──────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a video analyst. Given a video transcript (with timestamps) and optional \
key frame screenshots, produce a structured analysis in the requested JSON format.
Be concise and insightful. Preserve timestamps exactly as they appear in the transcript.
Always respond with valid JSON only — no markdown fences, no extra text.
CRITICAL JSON rule: never use ASCII double-quote characters (") inside string values. \
For quoted terms in any language use single quotes (') or omit quotes entirely."""

_TIMESTAMPS_SYSTEM = """\
You are a video analyst. Identify key content-transition moments in a transcript.
Return only valid JSON — no markdown, no extra text.
CRITICAL JSON rule: never use ASCII double-quote characters (") inside string values."""

_DIAGRAM_SYSTEM = """\
You are a visual content strategist. Given a video title, overview, and chapter list, \
produce a structured infographic summary with steps, stats, and a memorable quote.
Return only valid JSON — no markdown fences, no extra text.
CRITICAL JSON rule: never use ASCII double-quote characters (") inside string values. \
For quoted terms use single quotes (') or omit quotes entirely."""

_CONTENT_TYPE_SYSTEM = """\
You are a video content analyst. Classify the video type based on title and transcript.
Return only valid JSON — no markdown, no extra text.
CRITICAL JSON rule: never use ASCII double-quote characters (") inside string values."""


def _build_content_type_prompt(video_title: str, transcript_excerpt: str) -> str:
    return f"""\
Video title: {video_title}

Transcript excerpt (first portion):
{transcript_excerpt}

Classify this video and return JSON:
{{
  "content_type": "<educational | tutorial | narrative | opinion | showcase | interview>",
  "viz_template": "<comparison | steps | story_panels | argument_tree | grid | qa>",
  "color_palette": "<tech_blue | warm_earth | nature_green | dramatic_dark | editorial_clean>",
  "key_themes": ["<theme 1, English, 2-4 words>", "<theme 2, English, 2-4 words>", "<theme 3, English, 2-4 words>"],
  "visual_metaphor": "<one concrete visual scene capturing the video essence, English, 10-20 words>",
  "mood": "<inspiring | analytical | dramatic | educational | celebratory | critical>"
}}

Definitions:
- educational: explains concepts/theories, how things work, why something matters
- tutorial: step-by-step practical how-to guide, actionable instructions
- narrative: story, history, retrospective, event recap, documentary-style
- opinion: commentary, debate, analysis, review, critique
- showcase: product demo, collection tour, portfolio, before/after comparison
- interview: Q&A, conversation, podcast-style discussion

viz_template must match content_type:
- educational → comparison
- tutorial → steps
- narrative → story_panels
- opinion → argument_tree
- showcase → grid
- interview → qa

color_palette guide:
- tech/AI/digital/science topics → tech_blue
- lifestyle/creator/business/human → warm_earth
- nature/health/environment/growth → nature_green
- history/drama/geopolitics/dark → dramatic_dark
- data/research/minimal/clean → editorial_clean"""


def _default_content_type() -> dict:
    return {
        "content_type": "educational",
        "viz_template": "comparison",
        "color_palette": "warm_earth",
        "key_themes": ["key insights", "core concepts", "main ideas"],
        "visual_metaphor": "a journey of discovery through interconnected ideas and pathways",
        "mood": "educational",
    }


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
      "summary": "<detailed paragraph of ~80-100 words: explain the specific arguments, examples, demonstrations, or data points covered in this segment. Include concrete details visible on screen if frames are provided. Do NOT repeat the overview or points already covered in other chapters. Wrap 2-4 key terms, names, or pivotal phrases in **double asterisks** to mark them as highlights.>"
    }}
  ]
}}

Requirements:
- overview: 1-2 sentences max. State the core thesis only — no section listing.
- chapters: 4-8 chapters at natural content transitions in chronological order. Each summary must be a rich paragraph (~80-100 words) with concrete, segment-specific detail. No cross-chapter repetition.
- ANTI-REPETITION: Overview = what+why (big picture only). Chapters = when + segment-specific detail. Never repeat the same sentence or point across fields."""


def _build_infographic_prompt(
    video_title: str,
    overview: str,
    chapters: List[dict],
    output_language: str,
) -> str:
    lang_note = (
        f"Write ALL text in {output_language}."
        if output_language.lower() != "english"
        else "Write all text in English."
    )
    n = len(chapters)
    chapters_text = "\n".join(
        f"{i+1}. [{c.get('timestamp', '')}] {c.get('title', '')} — {c.get('summary', '')}"
        for i, c in enumerate(chapters)
    )

    return f"""\
Video title: {video_title}

Overview: {overview}

Chapters ({n} total):
{chapters_text}

{lang_note}

Create an infographic summary. Return a JSON object with EXACTLY this structure:
{{
  "headline": "<the single most important takeaway from this video, 10-16 words>",
  "subtitle": "<content type or theme, 4-8 words, e.g. 'Technical Tutorial' or 'Market Analysis'>",
  "steps": [
    {{
      "num": 1,
      "icon": "<one relevant emoji that visually represents this chapter>",
      "title": "<chapter title condensed to 3-6 words>",
      "duration": "<time range, e.g. '00:00 — 03:15'>",
      "points": ["<key insight 1 from this chapter, 8-14 words>", "<key insight 2, 8-14 words>"]
    }}
  ],
  "stats": [
    "<most important conclusion from the whole video, 10-16 words>",
    "<second key finding or number, 10-16 words>",
    "<third takeaway, implication, or recommendation, 10-16 words>"
  ],
  "quote": "<a memorable phrase or the strongest argument from the video, 15-30 words>"
}}

Rules:
- steps: exactly {n} entries, one per chapter, in chronological order
- icon: choose emoji matching each chapter theme (e.g. 🔍 discovery, ⚙️ process, 📊 data, 💡 insight, 🎯 goal, 🤖 AI/tech, 💰 finance, 🌍 global)
- duration: use chapter timestamps, format as 'MM:SS — MM:SS'
- points: exactly 2 per step, each a complete informative sentence (NO vague labels)
- stats: exactly 3 standalone insights not tied to a specific chapter
- quote: the most quotable statement — paraphrase if no obvious direct quote exists
- String values must NOT contain ASCII double-quote characters ("); use single quotes (') for any quoted terms"""


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

def _repair_control_chars(raw: str) -> str:
    """Fix only unambiguous issues inside JSON strings: literal newlines/tabs/carriage
    returns → their escaped equivalents.  Deliberately does NOT touch double-quote
    characters — the old lookahead heuristic that tried to escape unquoted `"` was
    unsafe: whenever an embedded quote happened to be followed (after whitespace) by
    a structural char like `,` or `}`, the heuristic wrongly treated it as the
    end-of-string, then consumed the adjacent JSON structure as string content.
    """
    result = []
    in_string = False
    i = 0
    while i < len(raw):
        c = raw[i]
        if in_string:
            if c == "\\" and i + 1 < len(raw):
                # Already-escaped pair — pass through unchanged
                result.append(c)
                result.append(raw[i + 1])
                i += 2
                continue
            elif c == '"':
                in_string = False
                result.append(c)
            elif c == "\n":
                result.append("\\n")
            elif c == "\r":
                result.append("\\r")
            elif c == "\t":
                result.append("\\t")
            elif ord(c) < 0x20:
                result.append("\\u{:04x}".format(ord(c)))
            else:
                result.append(c)
        else:
            if c == '"':
                in_string = True
                result.append(c)
            else:
                result.append(c)
        i += 1
    return "".join(result)


def _extract_json_candidate(raw: str) -> str:
    """Extract the outermost balanced {...} block using brace-matching.
    Falls back to raw if no balanced block found.
    Unlike the old find/rfind approach, this correctly handles preamble
    text that itself contains '{' characters.
    """
    depth = 0
    in_string = False
    start = None
    i = 0
    while i < len(raw):
        c = raw[i]
        if in_string:
            if c == "\\" and i + 1 < len(raw):
                i += 2
                continue
            elif c == '"':
                in_string = False
        else:
            if c == '"':
                in_string = True
            elif c == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif c == "}":
                if depth > 0:
                    depth -= 1
                    if depth == 0 and start is not None:
                        return raw[start : i + 1]
        i += 1
    # Fallback: simple find/rfind
    s, e = raw.find("{"), raw.rfind("}")
    if s != -1 and e > s:
        return raw[s : e + 1]
    return raw


def _escape_embedded_quotes(raw: str) -> str:
    """Strategy 3: escape unescaped ASCII double-quotes that appear inside JSON
    string values.  Used as a last-resort fallback when direct parsing and
    control-char repair both fail (common cause: Claude uses ASCII " as Chinese
    quotation marks, e.g. 揭示"喜忧参半"的真实面貌).

    Heuristic: while inside a JSON string, a `"` whose next non-whitespace
    character is NOT a JSON structural char (`,  }  ]  :`) is treated as an
    embedded literal quote and escaped.  The heuristic can misfire when an
    embedded quote happens to precede one of those structural chars, but since
    this function is only called after the safer strategies have already failed,
    any remaining corruption only causes a parse error — it never silently
    corrupts a successfully-parsed result.
    """
    result = []
    in_string = False
    i = 0
    n = len(raw)
    while i < n:
        c = raw[i]
        if in_string:
            if c == "\\" and i + 1 < n:
                result.append(c)
                result.append(raw[i + 1])
                i += 2
                continue
            elif c == '"':
                j = i + 1
                while j < n and raw[j] in " \t\r\n":
                    j += 1
                if j >= n or raw[j] in ",}]:":
                    in_string = False
                    result.append('"')
                else:
                    result.append('\\"')
            elif c == "\n":
                result.append("\\n")
            elif c == "\r":
                result.append("\\r")
            elif c == "\t":
                result.append("\\t")
            elif ord(c) < 0x20:
                result.append("\\u{:04x}".format(ord(c)))
            else:
                result.append(c)
        else:
            if c == '"':
                in_string = True
                result.append(c)
            else:
                result.append(c)
        i += 1
    return "".join(result)


def _parse_json_response(raw: str) -> dict:
    """Multi-strategy JSON extraction from LLM responses.

    Strategies tried in order (each only reached if the previous fails):
    1. Direct json.loads — handles valid JSON with zero corruption risk.
    2. _repair_control_chars — fixes literal \\n/\\t inside strings; safe.
    3. _escape_embedded_quotes — last resort; escapes unescaped ASCII " used
       as Chinese quotation marks or other embedded literals.  Can misfire on
       edge cases but is only invoked when the JSON is already broken.
    Raises ValueError if all strategies fail.
    """
    raw = raw.strip()
    # Strip markdown fences (```json ... ```)
    if raw.startswith("```"):
        raw = "\n".join(raw.splitlines()[1:])
    if "```" in raw:
        raw = raw[: raw.rfind("```")]
    raw = raw.strip()

    candidate = _extract_json_candidate(raw)

    last_exc: Exception = ValueError("no candidate")
    for attempt in (
        candidate,
        _repair_control_chars(candidate),
        _escape_embedded_quotes(candidate),
    ):
        try:
            return json.loads(attempt)
        except (json.JSONDecodeError, ValueError) as exc:
            last_exc = exc

    raise ValueError(
        f"JSON parse failed after all repair attempts. "
        f"Error: {last_exc}. "
        f"Raw (first 300 chars): {raw[:300]!r}"
    )


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

    raw_text = response.content[0].text

    # Primary: full JSON parse
    try:
        data = _parse_json_response(raw_text)
        timestamps = [float(m["seconds"]) for m in data.get("key_moments", [])]
        if timestamps:
            return sorted(timestamps)
    except (ValueError, KeyError, TypeError):
        pass

    # Fallback: extract "seconds" values directly via regex — immune to any JSON
    # structural corruption, as long as the numbers are present in the output.
    import re
    seconds_strs = re.findall(r'"seconds"\s*:\s*([\d.]+)', raw_text)
    if seconds_strs:
        return sorted(float(s) for s in seconds_strs)

    # Nothing found — return empty list; frame extractor will use uniform sampling
    return []


def get_diagram(
    video_title: str,
    overview: str,
    chapters: List[dict],
    api_key: str,
    output_language: str = "English",
) -> dict:
    """Generate an infographic summary (headline, steps, stats, quote) for the diagram.

    Separate lightweight Claude call — not embedded in the main JSON response,
    so there are no JSON escaping issues with complex strings.

    Args:
        video_title:     Title of the video.
        overview:        The overview text from the main analysis.
        chapters:        List of dicts with "title", "timestamp", "summary" keys.
        api_key:         Anthropic API key.
        output_language: Language for all output text.

    Returns:
        dict with "headline", "subtitle", "steps", "stats", "quote", or empty dict on failure.
    """
    try:
        import anthropic
    except ImportError:
        return {}

    client = anthropic.Anthropic(api_key=api_key)
    prompt = _build_infographic_prompt(video_title, overview, chapters, output_language)

    try:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=2048,
            system=_DIAGRAM_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        data = _parse_json_response(response.content[0].text)
        if "headline" in data and "steps" in data and isinstance(data["steps"], list):
            return data
    except Exception:
        pass

    return {}


def analyze_content_type(
    video_title: str,
    segments: List[Segment],
    api_key: str,
) -> dict:
    """Quick content type classification using the first portion of transcript.

    Returns a dict with content_type, viz_template, color_palette, key_themes,
    visual_metaphor, mood. Falls back to defaults on any error.
    """
    try:
        import anthropic
    except ImportError:
        return _default_content_type()

    client = anthropic.Anthropic(api_key=api_key)
    transcript_text = _segments_to_text(segments)
    excerpt = transcript_text[:6000]
    prompt = _build_content_type_prompt(video_title, excerpt)

    try:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=512,
            system=_CONTENT_TYPE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        data = _parse_json_response(response.content[0].text)
        if "content_type" in data and "key_themes" in data:
            return data
    except Exception:
        pass

    return _default_content_type()


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

    # ── Second pass: generate infographic separately (avoids JSON escaping issues)
    chapters_data = [
        {"title": c.title, "timestamp": c.timestamp_str, "summary": c.summary}
        for c in chapters
    ]
    diagram_data = get_diagram(video_title, overview, chapters_data, api_key, output_language)

    return Summary(
        title=video_title,
        overview=overview,
        chapters=chapters,
        frames=frames,
        diagram_data=diagram_data,
    )
