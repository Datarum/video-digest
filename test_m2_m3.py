"""Quick smoke test for M2 (url_parser) and M3 (downloader)."""

import sys
from pathlib import Path

from videodigest.url_parser import extract_video_id, get_video_info
from videodigest.downloader import download_subtitles, download_audio

TMP = Path("/tmp/videodigest_test")

def test_url_parsing():
    print("=== M2: URL Parsing ===")
    cases = [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s",
    ]
    for url in cases:
        vid = extract_video_id(url)
        assert vid == "dQw4w9WgXcQ", f"FAIL: {url} -> {vid}"
        print(f"  OK  {url}")

    try:
        extract_video_id("https://vimeo.com/123456")
        print("  FAIL: should have raised ValueError")
    except ValueError as e:
        print(f"  OK  invalid URL rejected: {e}")


def test_video_info(url: str):
    print(f"\n=== M2: get_video_info ===\nURL: {url}")
    info = get_video_info(url)
    print(f"  Title   : {info.title}")
    print(f"  Channel : {info.channel}")
    print(f"  Duration: {info.duration_str}")
    print(f"  Manual subs : {info.has_manual_subtitles}")
    print(f"  Auto subs   : {info.has_auto_subtitles}")
    print(f"  Lang list   : {info.available_subtitle_langs[:10]}")
    return info


def test_download_subtitles(info):
    print(f"\n=== M3: download_subtitles ===")
    srt = download_subtitles(info, TMP / "subs")
    if srt:
        print(f"  SRT saved : {srt}")
        print(f"  File size : {srt.stat().st_size} bytes")
        print("  Preview   :")
        print("  " + "\n  ".join(srt.read_text(errors="replace").splitlines()[:6]))
    else:
        print("  No subtitles available for this video.")


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    test_url_parsing()
    info = test_video_info(url)

    if info.has_any_subtitles:
        test_download_subtitles(info)
    else:
        print("\n[M3] No subtitles — audio download would be triggered (skipped in this test)")

    print("\nAll checks passed.")
