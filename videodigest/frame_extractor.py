"""M5 - Frame Extractor: extract key frames from video and deduplicate via perceptual hashing."""

import subprocess
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .transcriber import Segment

# Hamming distance below this → frames are considered duplicates (0-64 scale)
_DEFAULT_DEDUP_THRESHOLD = 8


@dataclass
class Frame:
    path: Path
    timestamp: float   # seconds (midpoint of source segment)
    segment_index: int  # index into the original segments list

    @property
    def timestamp_str(self) -> str:
        h = int(self.timestamp // 3600)
        m = int((self.timestamp % 3600) // 60)
        s = int(self.timestamp % 60)
        return f"[{h:02d}:{m:02d}:{s:02d}]" if h else f"[{m:02d}:{s:02d}]"


# ── ffmpeg helpers ────────────────────────────────────────────────────────────

def _require_ffmpeg() -> str:
    """Return ffmpeg binary path or raise a clear error."""
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
    """Extract one frame at `timestamp` seconds using ffmpeg.

    Uses -ss before -i (fast seek) then grabs the nearest keyframe.
    Returns True if the file was created successfully.
    """
    cmd = [
        ffmpeg, "-y",
        "-ss", f"{timestamp:.3f}",
        "-i", str(video_path),
        "-vframes", "1",
        "-q:v", "2",          # JPEG quality (2=best, 31=worst)
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True)
    return result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0


# ── perceptual hashing ────────────────────────────────────────────────────────

def _phash(image_path: Path):
    """Compute perceptual hash for an image. Returns None on failure."""
    try:
        import imagehash
        from PIL import Image
        return imagehash.phash(Image.open(image_path))
    except Exception:
        return None


def _is_duplicate(new_hash, kept_hashes: list, threshold: int) -> bool:
    if new_hash is None:
        return False  # can't judge → keep it
    return any((new_hash - h) < threshold for h in kept_hashes if h is not None)


# ── candidate selection ───────────────────────────────────────────────────────

def _select_candidates(segments: List[Segment], max_candidates: int) -> List[int]:
    """Uniformly sub-sample segment indices when there are too many segments.

    Returns a list of indices into `segments` to use as frame candidates.
    This prevents processing hundreds of 1-second segments one by one.
    """
    n = len(segments)
    if n <= max_candidates:
        return list(range(n))

    step = n / max_candidates
    return [int(i * step) for i in range(max_candidates)]


# ── public API ────────────────────────────────────────────────────────────────

def extract_frames(
    video_path: Path,
    segments: List[Segment],
    output_dir: Path,
    max_frames: int = 12,
    dedup_threshold: int = _DEFAULT_DEDUP_THRESHOLD,
) -> List[Frame]:
    """Extract representative key frames from a video aligned to transcript segments.

    Algorithm:
    1. Uniformly sub-sample candidate segments if there are too many.
    2. For each candidate, extract the frame at segment.midpoint via ffmpeg.
    3. Compute perceptual hash (pHash) and discard frames too similar to
       already-kept ones (hamming distance < dedup_threshold).
    4. Stop once max_frames unique frames are collected.

    Args:
        video_path:       Path to the downloaded video file.
        segments:         Transcript segments (typically merged 60s chunks from M4).
        output_dir:       Directory to save JPEG frames.
        max_frames:       Maximum number of frames to return (default 12).
        dedup_threshold:  Hamming distance cutoff; lower = stricter dedup (0–64).

    Returns:
        List of Frame objects, in chronological order.
    """
    if not segments:
        return []

    ffmpeg = _require_ffmpeg()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Pre-select candidates to avoid iterating hundreds of short segments
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
    """Convenience wrapper: extract frames at explicit timestamps (no segments needed).

    Useful for testing or when you want manual control over which moments to capture.
    """
    segments = [Segment(start=max(0.0, t - 0.5), end=t + 0.5, text="") for t in timestamps]
    return extract_frames(
        video_path=video_path,
        segments=segments,
        output_dir=output_dir,
        max_frames=len(timestamps),
        dedup_threshold=dedup_threshold,
    )
