"""M4 - Transcriber: parse SRT subtitles and fallback to Whisper ASR."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass
class Segment:
    start: float  # seconds
    end: float    # seconds
    text: str

    @property
    def midpoint(self) -> float:
        """Middle timestamp — used by frame extractor to pick a representative frame."""
        return (self.start + self.end) / 2

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def timestamp_str(self) -> str:
        """Start time formatted as [MM:SS] or [HH:MM:SS]."""
        h = int(self.start // 3600)
        m = int((self.start % 3600) // 60)
        s = int(self.start % 60)
        return f"[{h:02d}:{m:02d}:{s:02d}]" if h else f"[{m:02d}:{s:02d}]"


# Matches both SRT (comma) and VTT (dot) time separators
_TIME_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
    r"\s*-->\s*"
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)
# HTML/VTT inline tags e.g. <c>, <font color="white">, <00:00:01.234>
_TAG_RE = re.compile(r"<[^>]+>")


def _to_seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse_srt(path: Path) -> List[Segment]:
    """Parse an SRT (or SRT-like VTT) file into Segment objects.

    Handles:
    - Standard SRT blocks (index + timestamp + text)
    - Inline HTML/VTT tags stripped from text
    - UTF-8 BOM and encoding errors
    - Blank-line-separated or tightly packed blocks
    """
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    blocks = re.split(r"\n{2,}", raw.strip())

    segments: List[Segment] = []
    for block in blocks:
        lines = [ln.strip() for ln in block.strip().splitlines() if ln.strip()]
        if len(lines) < 2:
            continue

        # Locate the timestamp line (skip numeric index if present)
        time_match = None
        text_lines_start = 0
        for i, line in enumerate(lines):
            m = _TIME_RE.search(line)
            if m:
                time_match = m
                text_lines_start = i + 1
                break

        if not time_match or text_lines_start >= len(lines):
            continue

        start = _to_seconds(*time_match.groups()[:4])
        end = _to_seconds(*time_match.groups()[4:])
        text = " ".join(lines[text_lines_start:])
        text = _TAG_RE.sub("", text).strip()

        if text:
            segments.append(Segment(start=start, end=end, text=text))

    return segments


def transcribe_audio(
    audio_path: Path,
    model_size: str = "base",
    language: str = None,
) -> List[Segment]:
    """Transcribe audio with OpenAI Whisper (ASR fallback).

    Args:
        audio_path: Path to the audio file (mp3, wav, m4a, etc.)
        model_size: Whisper model size — "tiny", "base", "small", "medium", "large".
                    "base" balances speed and accuracy for most cases.
        language:   ISO 639-1 language hint (e.g. "zh", "en"). None = auto-detect.

    Returns:
        List of Segment objects with timestamps from Whisper output.
    """
    try:
        import whisper
    except ImportError:
        raise ImportError(
            "openai-whisper is required for audio transcription.\n"
            "Install it with: pip3 install openai-whisper"
        )

    model = whisper.load_model(model_size)
    kwargs = {"task": "transcribe", "verbose": False}
    if language:
        kwargs["language"] = language

    result = model.transcribe(str(audio_path), **kwargs)

    return [
        Segment(start=seg["start"], end=seg["end"], text=seg["text"].strip())
        for seg in result["segments"]
        if seg["text"].strip()
    ]


def merge_segments(segments: List[Segment], window_seconds: float = 60.0) -> List[Segment]:
    """Merge consecutive short segments into larger chunks.

    Groups segments whose combined span fits within `window_seconds`.
    This creates better-sized passages for LLM summarization and reduces
    the number of key frames needed.

    Example: 200 one-second segments → ~3 sixty-second chunks.
    """
    if not segments:
        return []

    merged: List[Segment] = []
    chunk_start = segments[0].start
    chunk_end = segments[0].end
    chunk_texts = [segments[0].text]

    for seg in segments[1:]:
        if seg.end - chunk_start <= window_seconds:
            chunk_end = seg.end
            chunk_texts.append(seg.text)
        else:
            merged.append(Segment(
                start=chunk_start,
                end=chunk_end,
                text=" ".join(chunk_texts),
            ))
            chunk_start = seg.start
            chunk_end = seg.end
            chunk_texts = [seg.text]

    merged.append(Segment(
        start=chunk_start,
        end=chunk_end,
        text=" ".join(chunk_texts),
    ))

    return merged
