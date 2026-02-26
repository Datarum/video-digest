"""M3 - Downloader: fetch subtitles, audio, and video via yt-dlp."""

from pathlib import Path
from typing import List, Optional

import yt_dlp

from .url_parser import VideoInfo

_DEFAULT_LANG_PREF = ["zh-Hans", "zh-Hant", "zh", "en"]
_COOKIES_OPTS = {"cookiesfrombrowser": ("chrome",)}


def download_subtitles(
    video_info: VideoInfo,
    output_dir: Path,
    lang_pref: Optional[List[str]] = None,
) -> Optional[Path]:
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

    for lang in langs:
        candidate = output_dir / f"{video_info.video_id}.{lang}.srt"
        if candidate.exists():
            return candidate

    matches = list(output_dir.glob(f"{video_info.video_id}*.srt"))
    return matches[0] if matches else None


def download_audio(video_info: VideoInfo, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    expected = output_dir / f"{video_info.video_id}.mp3"

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "bestaudio/18/best",
        "extractor_args": {"youtube": {"player_client": ["android"]}},
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "128",
            }
        ],
        "outtmpl": str(output_dir / f"{video_info.video_id}.%(ext)s"),
        **_COOKIES_OPTS,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_info.url])

    return expected


def download_video(
    video_info: VideoInfo,
    output_dir: Path,
    max_height: int = 480,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "format": (
            f"bestvideo[height<={max_height}][ext=mp4]"
            f"+bestaudio[ext=m4a]"
            f"/best[height<={max_height}][ext=mp4]"
            f"/best[height<={max_height}]"
            f"/18"
        ),
        "extractor_args": {"youtube": {"player_client": ["android"]}},
        "merge_output_format": "mp4",
        "outtmpl": str(output_dir / f"{video_info.video_id}.%(ext)s"),
        **_COOKIES_OPTS,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_info.url])

    for ext in ("mp4", "mkv", "webm"):
        candidate = output_dir / f"{video_info.video_id}.{ext}"
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        f"Video download succeeded but file not found in {output_dir}"
    )
