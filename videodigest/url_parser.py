"""M2 - URL Parser: validate YouTube URLs, extract video ID, fetch metadata."""

import re
from dataclasses import dataclass, field
from typing import List

import yt_dlp


@dataclass
class VideoInfo:
    video_id: str
    url: str           # normalized URL
    title: str
    duration: int      # seconds
    channel: str
    description: str
    has_manual_subtitles: bool
    has_auto_subtitles: bool
    available_subtitle_langs: List[str] = field(default_factory=list)

    @property
    def has_any_subtitles(self) -> bool:
        return self.has_manual_subtitles or self.has_auto_subtitles

    @property
    def duration_str(self) -> str:
        h, m = divmod(self.duration, 3600)
        m, s = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# Matches all common YouTube URL formats
_YT_ID_RE = re.compile(
    r"(?:v=|/v/|youtu\.be/|/embed/|/shorts/|/live/)"
    r"([a-zA-Z0-9_-]{11})"
)


def extract_video_id(url: str) -> str:
    """Extract the 11-character video ID from any YouTube URL format."""
    match = _YT_ID_RE.search(url)
    if not match:
        raise ValueError(
            f"Unrecognized YouTube URL: {url!r}\n"
            "Supported formats: watch?v=, youtu.be/, /shorts/, /embed/, /live/"
        )
    return match.group(1)


def get_video_info(url: str) -> VideoInfo:
    """Fetch video metadata via yt-dlp. No download is performed."""
    video_id = extract_video_id(url)
    normalized_url = f"https://www.youtube.com/watch?v={video_id}"

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(normalized_url, download=False)

    manual_subs: dict = info.get("subtitles") or {}
    auto_subs: dict = info.get("automatic_captions") or {}
    all_langs = sorted(set(manual_subs) | set(auto_subs))

    return VideoInfo(
        video_id=video_id,
        url=normalized_url,
        title=info.get("title", "Unknown"),
        duration=info.get("duration", 0),
        channel=info.get("channel") or info.get("uploader", "Unknown"),
        description=info.get("description", ""),
        has_manual_subtitles=bool(manual_subs),
        has_auto_subtitles=bool(auto_subs),
        available_subtitle_langs=all_langs,
    )
