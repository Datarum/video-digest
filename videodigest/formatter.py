"""M7 - Formatter: render a Summary into Markdown and JSON output files."""

import json
import shutil
from pathlib import Path
from typing import Optional

from .analyzer import Summary, Chapter
from .frame_extractor import Frame


def _nearest_frame(frames: list, target_time: float) -> Optional[Frame]:
    if not frames:
        return None
    return min(frames, key=lambda f: abs(f.timestamp - target_time))


def _frames_already_used(used: set, frame: Frame) -> bool:
    return str(frame.path) in used


def _copy_frames(frames: list, dest_dir: Path) -> dict:
    frames_dir = dest_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    mapping = {}
    for frame in frames:
        dest = frames_dir / frame.path.name
        if not dest.exists():
            shutil.copy2(frame.path, dest)
        mapping[str(frame.path)] = f"frames/{frame.path.name}"
    return mapping


def _youtube_url(video_id: str, timestamp: float) -> str:
    t = int(timestamp)
    return f"https://www.youtube.com/watch?v={video_id}&t={t}s"


def _render_markdown(
    summary: Summary,
    video_id: str,
    channel: str,
    duration_str: str,
    frame_path_map: dict,
) -> str:
    lines = []

    lines.append(f"# {summary.title}\n")
    lines.append(
        f"**Channel**: {channel}  "
        f"**Duration**: {duration_str}  "
        f"**Link**: [Watch on YouTube](https://www.youtube.com/watch?v={video_id})\n"
    )
    lines.append("---\n")

    lines.append("## Overview\n")
    lines.append(f"{summary.overview}\n")
    lines.append("---\n")

    lines.append("## Key Points\n")
    for point in summary.key_points:
        lines.append(f"- {point}")
    lines.append("")
    lines.append("---\n")

    lines.append("## Chapters\n")
    used_frame_paths = set()

    for chapter in summary.chapters:
        yt_link = _youtube_url(video_id, chapter.start_time)
        ts = chapter.timestamp_str
        lines.append(f"### [{chapter.title}]({yt_link}) {ts}\n")

        candidate = _nearest_frame(summary.frames, chapter.start_time)
        if candidate and not _frames_already_used(used_frame_paths, candidate):
            rel_path = frame_path_map.get(str(candidate.path))
            if rel_path:
                lines.append(f"![{chapter.title}]({rel_path})\n")
                used_frame_paths.add(str(candidate.path))

        lines.append(f"{chapter.summary}\n")

    leftover = [f for f in summary.frames if str(f.path) not in used_frame_paths]
    if leftover:
        lines.append("---\n")
        lines.append("## Additional Screenshots\n")
        for frame in leftover:
            rel_path = frame_path_map.get(str(frame.path))
            if rel_path:
                lines.append(f"![{frame.timestamp_str}]({rel_path})\n")
                lines.append(f"*{frame.timestamp_str}*\n")

    return "\n".join(lines)


def save_markdown(
    summary: Summary,
    output_path: Path,
    video_id: str = "",
    channel: str = "",
    duration_str: str = "",
) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    frame_path_map = _copy_frames(summary.frames, output_path.parent)

    md = _render_markdown(
        summary=summary,
        video_id=video_id,
        channel=channel,
        duration_str=duration_str,
        frame_path_map=frame_path_map,
    )

    output_path.write_text(md, encoding="utf-8")
    return output_path


def save_json(summary: Summary, output_path: Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    data = summary.to_dict()
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path
