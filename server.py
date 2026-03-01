#!/usr/bin/env python3
"""Web server for VideoDigest — serves the frontend and streams pipeline progress via SSE."""

import json
import os
import queue
import shutil
import tempfile
import threading
import traceback
import uuid
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_from_directory

BASE_DIR = Path(__file__).parent

# ── load .env file (if present) ───────────────────────────────────────────────
_env_file = BASE_DIR / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

app = Flask(__name__, template_folder="templates")

# job_id → queue.Queue (holds SSE message strings; None = sentinel / done)
_jobs: dict = {}


# ── SSE helper ────────────────────────────────────────────────────────────────

def _put(q: queue.Queue, event_type: str, **kwargs) -> None:
    payload = json.dumps({"type": event_type, **kwargs})
    q.put(f"data: {payload}\n\n")


# ── pipeline (runs in background thread) ─────────────────────────────────────

def _run_pipeline(
    job_id: str,
    url: str,
    lang: str,
    api_key: str,
    max_frames: int,
    no_frames: bool,
    mode: str = "old_timer",
    sf_api_key: str = "",
    viz_template: str = "auto",
) -> None:
    q = _jobs[job_id]
    is_nbb = (mode == "new_born_baby")

    def emit(event_type: str, **kwargs):
        _put(q, event_type, **kwargs)

    work_dir = Path(tempfile.mkdtemp(prefix="videodigest_"))

    try:
        # ── Step 1: video info ────────────────────────────────────────────────
        emit("step", step="fetch", status="active", message="正在获取视频信息…")
        from videodigest.url_parser import get_video_info
        info = get_video_info(url)
        emit("step", step="fetch", status="done",
             message=f"{info.title}  ·  {info.channel}  ·  {info.duration_str}")

        video_out_dir = OUTPUT_DIR / info.video_id
        video_out_dir.mkdir(parents=True, exist_ok=True)

        # ── Step 2: transcript ────────────────────────────────────────────────
        from videodigest.downloader import download_subtitles, download_audio
        from videodigest.transcriber import parse_srt, transcribe_audio, merge_segments

        segments = []

        if info.has_any_subtitles:
            emit("step", step="transcript", status="active", message="正在下载字幕…")
            srt = download_subtitles(info, work_dir / "subs")
            if srt:
                segments = parse_srt(srt)
                emit("step", step="transcript", status="done",
                     message=f"已解析 {len(segments)} 条字幕 ({srt.name})")

        if not segments:
            emit("step", step="transcript", status="active",
                 message="无字幕，正在下载音频并用 Whisper 转录…")
            audio = download_audio(info, work_dir / "audio")
            segments = transcribe_audio(audio, model_size="base")
            # Clean up audio immediately after transcription — no longer needed
            shutil.rmtree(work_dir / "audio", ignore_errors=True)
            emit("step", step="transcript", status="done",
                 message=f"Whisper 已转录 {len(segments)} 段")

        merged = merge_segments(segments, window_seconds=60.0)

        # ── Step 2.5: content type classification (New Born Baby only) ────────
        content_type_data = {}
        if is_nbb:
            if viz_template and viz_template != "auto":
                # User manually specified a viz template — skip Claude classification
                content_type_data = {"viz_template": viz_template}
                emit("step", step="classify", status="done",
                     message=f"样式: {viz_template}（手动指定）")
            else:
                emit("step", step="classify", status="active", message="正在识别内容类型…")
                from videodigest.analyzer import analyze_content_type
                content_type_data = analyze_content_type(
                    video_title=info.title,
                    segments=merged,
                    api_key=api_key,
                )
                ct = content_type_data.get("content_type", "educational")
                vt = content_type_data.get("viz_template", "comparison")
                emit("step", step="classify", status="done",
                     message=f"类型: {ct}  ·  布局: {vt}")

        # ── Step 3: key frames ────────────────────────────────────────────────
        frames = []

        if not no_frames and max_frames > 0:
            emit("step", step="frames", status="active", message="正在分析视频结构，识别关键时刻…")
            try:
                from videodigest.analyzer import get_key_timestamps
                from videodigest.downloader import download_video
                from videodigest.frame_extractor import extract_frames_at_timestamps

                # First pass: ask Claude to identify key timestamps from transcript
                key_timestamps = get_key_timestamps(
                    video_title=info.title,
                    segments=merged,
                    api_key=api_key,
                    n_moments=max_frames,
                )

                if key_timestamps:
                    emit("step", step="frames", status="active",
                         message=f"已定位 {len(key_timestamps)} 个关键时刻，正在下载视频…")
                    video_path = download_video(info, work_dir / "video")

                    frames = extract_frames_at_timestamps(
                        video_path, key_timestamps, work_dir / "frames"
                    )
                    # Clean up video immediately after frame extraction
                    shutil.rmtree(work_dir / "video", ignore_errors=True)

                emit("step", step="frames", status="done",
                     message=f"已提取 {len(frames)} 张关键帧")
            except (EnvironmentError, OSError) as e:
                emit("step", step="frames", status="warn",
                     message=f"截帧跳过: {e}")
        else:
            emit("step", step="frames", status="skip", message="已跳过截帧（--no-frames）")

        # ── Step 4: AI analysis ───────────────────────────────────────────────
        emit("step", step="analyze", status="active",
             message=f"正在用 Claude 深度分析（语言: {lang}）…")
        from videodigest.analyzer import analyze
        summary = analyze(
            video_title=info.title,
            segments=merged,
            frames=frames,
            api_key=api_key,
            output_language=lang,
        )
        summary.content_type_data = content_type_data
        emit("step", step="analyze", status="done",
             message=f"分析完成 — {len(summary.chapters)} 章节")

        # ── Step 4.5: generate infographic illustration (New Born Baby only) ────
        if is_nbb and sf_api_key:
            emit("step", step="illustrate", status="active", message="正在生成主题插图…")
            try:
                from videodigest.infographic import build_infographic_prompt, call_siliconflow
                key_insights = [
                    str(s) for s in summary.diagram_data.get("stats", [])[:3]
                ]
                infographic_prompt, neg_prompt = build_infographic_prompt(
                    content_type_data=content_type_data,
                    overview=summary.overview,
                    key_insights=key_insights,
                    diagram_data=summary.diagram_data,
                )
                illustration_url = call_siliconflow(
                    prompt=infographic_prompt,
                    api_key=sf_api_key,
                    negative_prompt=neg_prompt,
                )
                if illustration_url:
                    summary.illustration_url = illustration_url
                    emit("step", step="illustrate", status="done", message="插图生成完成")
                else:
                    emit("step", step="illustrate", status="warn", message="插图生成失败，跳过")
            except Exception as ill_err:
                emit("step", step="illustrate", status="warn",
                     message=f"插图跳过: {ill_err}")
        elif is_nbb and not sf_api_key:
            emit("step", step="illustrate", status="skip", message="未配置硅基流动 Key，跳过插图")

        # ── Step 5: save output ───────────────────────────────────────────────
        emit("step", step="output", status="active", message="正在保存报告…")
        from videodigest.formatter import save_markdown, save_json
        save_markdown(
            summary, video_out_dir / "summary.md",
            video_id=info.video_id,
            channel=info.channel,
            duration_str=info.duration_str,
        )
        save_json(summary, video_out_dir / "summary.json")
        emit("step", step="output", status="done",
             message=f"报告已保存到 output/{info.video_id}/")

        # ── Build result payload ──────────────────────────────────────────────
        result = summary.to_dict()
        result["video_id"] = info.video_id
        result["channel"] = info.channel
        result["duration_str"] = info.duration_str
        result["youtube_url"] = info.url
        result["thumbnail_url"] = (
            f"https://img.youtube.com/vi/{info.video_id}/maxresdefault.jpg"
        )

        # Copy frames to output dir and build web-accessible URLs
        frames_out = video_out_dir / "frames"
        frames_out.mkdir(exist_ok=True)
        web_frames = []
        for frame in summary.frames:
            dest = frames_out / frame.path.name
            if not dest.exists():
                shutil.copy2(frame.path, dest)
            web_frames.append({
                "url": f"/output/{info.video_id}/frames/{frame.path.name}",
                "timestamp": frame.timestamp,
                "timestamp_str": frame.timestamp_str,
            })
        result["web_frames"] = web_frames

        # Attach nearest frame URL to each chapter
        for chapter in result["chapters"]:
            nearest = None
            if web_frames:
                nearest = min(
                    web_frames,
                    key=lambda f: abs(f["timestamp"] - chapter["start_seconds"]),
                )
            chapter["frame_url"] = nearest["url"] if nearest else None

        emit("result", data=result)

    except Exception as e:
        emit("error", message=str(e), detail=traceback.format_exc())

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        q.put(None)  # sentinel — tells the SSE generator to stop


# ── routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    server_has_key    = bool(os.environ.get("ANTHROPIC_API_KEY"))
    server_has_sf_key = bool(os.environ.get("SILICONFLOW_API_KEY"))
    return render_template(
        "index.html",
        server_has_key=server_has_key,
        server_has_sf_key=server_has_sf_key,
    )


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    data = request.get_json() or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL 不能为空"}), 400

    api_key = data.get("api_key", "").strip() or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return jsonify({"error": "需要 Anthropic API Key"}), 400

    mode = data.get("mode", "old_timer")
    sf_api_key = data.get("sf_api_key", "").strip() or os.environ.get("SILICONFLOW_API_KEY", "")
    viz_template = data.get("viz_template", "auto").strip()

    job_id = str(uuid.uuid4())
    _jobs[job_id] = queue.Queue()

    threading.Thread(
        target=_run_pipeline,
        args=(
            job_id,
            url,
            data.get("lang", "Chinese"),
            api_key,
            int(data.get("max_frames", 12)),
            bool(data.get("no_frames", False)),
            mode,
            sf_api_key,
            viz_template,
        ),
        daemon=True,
    ).start()

    return jsonify({"job_id": job_id})


@app.route("/api/stream/<job_id>")
def api_stream(job_id):
    def generate():
        q = _jobs.get(job_id)
        if not q:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Job not found'})}\n\n"
            return
        while True:
            msg = q.get()
            if msg is None:
                yield "data: {\"type\": \"done\"}\n\n"
                break
            yield msg
        _jobs.pop(job_id, None)

    return Response(
        generate(),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/output/<path:filename>")
def serve_output(filename):
    return send_from_directory(OUTPUT_DIR, filename)


# ── main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="VideoDigest web server")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5000)
    args = p.parse_args()
    print(f"\n  VideoDigest  →  http://{args.host}:{args.port}\n")
    app.run(host=args.host, port=args.port, threaded=True, debug=False)
