"""M1 - CLI: orchestrate the full pipeline from YouTube URL to summary report."""

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

from .url_parser import get_video_info
from .downloader import download_subtitles, download_audio, download_video
from .transcriber import parse_srt, transcribe_audio, merge_segments
from .frame_extractor import extract_frames
from .analyzer import analyze
from .formatter import save_markdown, save_json

console = Console()


# ── argument parsing ──────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="videodigest",
        description="Summarize a YouTube video: transcript + key screenshots → Markdown report",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  videodigest https://youtu.be/dQw4w9WgXcQ
  videodigest https://youtu.be/dQw4w9WgXcQ -o ./output --lang Chinese
  videodigest https://youtu.be/dQw4w9WgXcQ --no-frames
  ANTHROPIC_API_KEY=sk-... videodigest <url>
        """,
    )
    p.add_argument("url", help="YouTube video URL")
    p.add_argument(
        "-o", "--output",
        metavar="DIR",
        help="Output directory (default: ./<video_id>/)",
    )
    p.add_argument(
        "-l", "--lang",
        default="Chinese",
        metavar="LANG",
        help="Output language for the summary (default: Chinese)",
    )
    p.add_argument(
        "--api-key",
        metavar="KEY",
        help="Anthropic API key (or set ANTHROPIC_API_KEY env var)",
    )
    p.add_argument(
        "--max-frames",
        type=int,
        default=12,
        metavar="N",
        help="Max number of key frames to extract (default: 12)",
    )
    p.add_argument(
        "--no-frames",
        action="store_true",
        help="Skip video download and frame extraction (faster, text-only)",
    )
    p.add_argument(
        "--whisper-model",
        default="base",
        choices=["tiny", "base", "small", "medium", "large"],
        help="Whisper model for ASR fallback when no subtitles exist (default: base)",
    )
    p.add_argument(
        "--merge-window",
        type=float,
        default=60.0,
        metavar="SEC",
        help="Merge transcript segments into chunks of this many seconds (default: 60)",
    )
    p.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep temporary download files (useful for debugging)",
    )
    return p


# ── step helpers ──────────────────────────────────────────────────────────────

def _step(label: str) -> None:
    console.print(f"  [bold cyan]→[/bold cyan] {label}")


def _ok(label: str) -> None:
    console.print(f"  [bold green]✓[/bold green] {label}")


def _warn(label: str) -> None:
    console.print(f"  [bold yellow]![/bold yellow] {label}")


def _err(label: str) -> None:
    console.print(f"  [bold red]✗[/bold red] {label}")


# ── pipeline ──────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace, api_key: str) -> Path:
    """Execute the full pipeline. Returns the path to the output directory."""
    work_dir = Path(tempfile.mkdtemp(prefix="videodigest_"))

    try:
        # ── Step 1: fetch video metadata ──────────────────────────────────────
        _step("Fetching video info…")
        info = get_video_info(args.url)
        _ok(f"{info.title} [{info.duration_str}] — {info.channel}")

        # Determine output directory
        out_dir = Path(args.output) if args.output else Path.cwd() / info.video_id
        out_dir.mkdir(parents=True, exist_ok=True)

        # ── Step 2: get transcript ────────────────────────────────────────────
        segments = []

        if info.has_any_subtitles:
            _step("Downloading subtitles…")
            srt_path = download_subtitles(info, work_dir / "subs")
            if srt_path:
                segments = parse_srt(srt_path)
                _ok(f"Parsed {len(segments)} subtitle segments ({srt_path.name})")
            else:
                _warn("Subtitle download returned nothing — falling back to ASR")

        if not segments:
            _step("Downloading audio for Whisper transcription…")
            audio_path = download_audio(info, work_dir / "audio")
            _ok(f"Audio saved: {audio_path.name}")
            _step(f"Transcribing with Whisper [{args.whisper_model}]… (this may take a while)")
            segments = transcribe_audio(audio_path, model_size=args.whisper_model)
            _ok(f"Transcribed {len(segments)} segments")

        if not segments:
            _err("Could not obtain any transcript. Aborting.")
            sys.exit(1)

        merged = merge_segments(segments, window_seconds=args.merge_window)
        _ok(f"Merged into {len(merged)} chunks (window={args.merge_window:.0f}s)")

        # ── Step 3: extract key frames ────────────────────────────────────────
        frames = []

        if not args.no_frames:
            _step("Downloading video for frame extraction…")
            try:
                video_path = download_video(info, work_dir / "video")
                _ok(f"Video saved: {video_path.name} ({video_path.stat().st_size // (1024*1024)} MB)")

                _step(f"Extracting up to {args.max_frames} key frames…")
                frames_dir = work_dir / "frames"
                frames = extract_frames(video_path, merged, frames_dir, max_frames=args.max_frames)
                _ok(f"Extracted {len(frames)} unique frames")
            except (EnvironmentError, OSError) as e:
                _warn(f"Frame extraction skipped: {e}")
        else:
            _warn("Frame extraction skipped (--no-frames)")

        # ── Step 4: AI analysis ───────────────────────────────────────────────
        _step(f"Analyzing with Claude [{args.lang}]…")
        summary = analyze(
            video_title=info.title,
            segments=merged,
            frames=frames,
            api_key=api_key,
            output_language=args.lang,
        )
        _ok(f"Analysis complete — {len(summary.chapters)} chapters, {len(summary.key_points)} key points")

        # ── Step 5: save output ───────────────────────────────────────────────
        _step("Writing output files…")
        md_path = save_markdown(
            summary, out_dir / "summary.md",
            video_id=info.video_id,
            channel=info.channel,
            duration_str=info.duration_str,
        )
        json_path = save_json(summary, out_dir / "summary.json")
        _ok(f"Markdown → {md_path}")
        _ok(f"JSON     → {json_path}")

        return out_dir

    finally:
        if not args.keep_temp:
            shutil.rmtree(work_dir, ignore_errors=True)
        else:
            console.print(f"\n  [dim]Temp files kept at: {work_dir}[/dim]")


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    # Resolve API key
    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        console.print(
            "[bold red]Error:[/bold red] Anthropic API key is required.\n"
            "Set it via [bold]--api-key KEY[/bold] or the "
            "[bold]ANTHROPIC_API_KEY[/bold] environment variable."
        )
        sys.exit(1)

    console.print(Panel.fit(
        f"[bold]VideoDigest[/bold]  [dim]YouTube → Markdown summary[/dim]\n"
        f"[cyan]{args.url}[/cyan]",
        border_style="blue",
    ))
    console.print()

    try:
        out_dir = run(args, api_key)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        sys.exit(130)
    except Exception as e:
        _err(str(e))
        if os.environ.get("VIDEODIGEST_DEBUG"):
            raise
        sys.exit(1)

    console.print()
    console.print(Rule(style="green"))
    console.print(f"\n[bold green]Done![/bold green] Report saved to [bold]{out_dir}/[/bold]\n")


if __name__ == "__main__":
    main()
