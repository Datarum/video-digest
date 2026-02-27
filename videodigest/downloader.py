"""M3 - Downloader: fetch subtitles, audio, and video via yt-dlp."""

from pathlib import Path
from typing import List, Optional

import yt_dlp

from .url_parser import VideoInfo

# Preferred subtitle language order when the caller does not specify
_DEFAULT_LANG_PREF = ["zh-Hans", "zh-Hant", "zh", "en"]

# Use browser cookies to authenticate with YouTube and avoid 403 errors.
# Change to ("chrome",) or ("firefox",) if you don't use Safari.
_COOKIES_OPTS = {"cookiesfrombrowser": ("chrome",)}


def download_subtitles(
    video_info: VideoInfo,
    output_dir: Path,
    lang_pref: Optional[List[str]] = None,
) -> Optional[Path]:
    """Download subtitles in SRT format.

    Tries manual subtitles first, then falls back to auto-generated captions.
    Returns the path to the downloaded .srt file, or None if unavailable.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    langs = lang_pref or _DEFAULT_LANG_PREF

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": langs,
        "subtitlesformat": "srt",
        "outtmpl": str(output_dir / "%(id)s.%(ext)s"),
        **_COOKIES_OPTS,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_info.url])

    # yt-dlp names the file: <video_id>.<lang>.srt
    # Return the first match in lang preference order
    for lang in langs:
        candidate = output_dir / f"{video_info.video_id}.{lang}.srt"
        if candidate.exists():
            return candidate

    # Fallback: any .srt file for this video
    matches = list(output_dir.glob(f"{video_info.video_id}*.srt"))
    return matches[0] if matches else None


def download_audio(video_info: VideoInfo, output_dir: Path) -> Path:
    """Download audio as MP3 (128 kbps) for Whisper ASR transcription.

    Used as fallback when no subtitles are available.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    expected = output_dir / f"{video_info.video_id}.mp3"

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        # bestaudio: audio-only DASH (may fail with SABR)
        # 18/22/17: progressive mp4 (no SABR, widely available)
        # best: last resort combined stream
        "format": "bestaudio/18/22/17/best",
        "extractor_args": {"youtube": {"player_client": ["android"]}},
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "128",
            }
        ],
        "outtmpl": str(output_dir / f"{video_info.video_id}.%(ext)s"),
        # No cookies: android client does not support cookies and will be skipped if present
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_info.url])

    return expected


def download_video(
    video_info: VideoInfo,
    output_dir: Path,
    max_height: int = 480,
) -> Path:
    """Download video at low resolution for frame extraction.

    Caps resolution at `max_height` to keep file size manageable.
    Returns path to the downloaded video file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        # Prefer a single mp4 file; fall back to merging best streams
        "format": (
            f"bestvideo[height<={max_height}][ext=mp4]+bestaudio[ext=m4a]"
            f"/best[height<={max_height}][ext=mp4]"
            f"/best[height<={max_height}]"
            f"/best"
        ),
        "extractor_args": {"youtube": {"player_client": ["android"]}},
        "merge_output_format": "mp4",
        "outtmpl": str(output_dir / f"{video_info.video_id}.%(ext)s"),
        # No cookies: android client does not support cookies and will be skipped if present
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_info.url])

    # Locate the downloaded file (extension may vary)
    for ext in ("mp4", "mkv", "webm"):
        candidate = output_dir / f"{video_info.video_id}.{ext}"
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        f"Video download succeeded but file not found in {output_dir}"
    )
