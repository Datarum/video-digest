"""M5 - Frame Extractor: extract key frames from video and deduplicate via perceptual hashing."""

import subprocess
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .transcriber import Segment

_DEFAULT_DEDUP_THRESHOLD = 8


@dataclass
class Frame:
    path: Path
    timestamp: float
    segment_index: int

    @property
    def timestamp_str(self) -> str:
        h = int(self.timestamp // 3600)
        m = int((self.timestamp % 3600) // 60)
        s = int(self.timestamp % 60)
        return f"[{h:02d}:{m:02d}:{s:02d}]" if h else f"[{m:02d}:{s:02d}]"


def _require_ffmpeg() -> str:
    binary = shutil.which("ffmpeg")
    if not binary:
        raise EnvironmentError(
            "ffmpeg not found. Install it with:\n"
            "  macOS:  brew install ffmpeg\n"
            "  Ubuntu: sudo apt install ffmpeg\n"
            "  Windows: https://ffmpeg.org/download.html"
        )
    return binary


def _extract_single_frame(
    ffmpeg: str,
    video_path: Path,
    timestamp: float,
    output_path: Path,
) -> bool:
    cmd = [
        ffmpeg, "-y",
        "-ss", f"{timestamp:.3f}",
        "-i", str(video_path),
        "-vframes", "1",
        "-q:v", "2",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True)
    return result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0


def _phash(image_path: Path):
    try:
        import imagehash
        from PIL import Image
        return imagehash.phash(Image.open(image_path))
    except Exception:
        return None


def _is_duplicate(new_hash, kept_hashes: list, threshold: int) -> bool:
    if new_hash is None:
        return False
    return any((new_hash - h) < threshold for h in kept_hashes if h is not None)


def _select_candidates(segments: List[Segment], max_candidates: int) -> List[int]:
    n = len(segments)
    if n <= max_candidates:
        return list(range(n))
    step = n / max_candidates
    return [int(i * step) for i in range(max_candidates)]


def extract_frames(
    video_path: Path,
    segments: List[Segment],
    output_dir: Path,
    max_frames: int = 12,
    dedup_threshold: int = _DEFAULT_DEDUP_THRESHOLD,
) -> List[Frame]:
    if not segments:
        return []

    ffmpeg = _require_ffmpeg()
    output_dir.mkdir(parents=True, exist_ok=True)

    candidate_indices = _select_candidates(segments, max_candidates=max_frames * 3)

    kept_frames: List[Frame] = []
    kept_hashes: list = []

    for idx in candidate_indices:
        if len(kept_frames) >= max_frames:
            break

        seg = segments[idx]
        ts = seg.midpoint
        frame_path = output_dir / f"frame_{idx:04d}_{int(ts):05d}.jpg"

        if not _extract_single_frame(ffmpeg, video_path, ts, frame_path):
            continue

        phash = _phash(frame_path)

        if _is_duplicate(phash, kept_hashes, dedup_threshold):
            frame_path.unlink(missing_ok=True)
            continue

        kept_hashes.append(phash)
        kept_frames.append(Frame(path=frame_path, timestamp=ts, segment_index=idx))

    return kept_frames


def extract_frames_at_timestamps(
    video_path: Path,
    timestamps: List[float],
    output_dir: Path,
    dedup_threshold: int = _DEFAULT_DEDUP_THRESHOLD,
) -> List[Frame]:
    segments = [Segment(start=max(0.0, t - 0.5), end=t + 0.5, text="") for t in timestamps]
    return extract_frames(
        video_path=video_path,
        segments=segments,
        output_dir=output_dir,
        max_frames=len(timestamps),
        dedup_threshold=dedup_threshold,
    )
