# VideoDigest - YouTube 视频智能摘要工具

输入一个 YouTube 链接，自动生成包含关键帧截图的结构化摘要文档（Markdown + JSON）。

支持网页界面和命令行两种使用方式。

---

## 准备工作

### 1. Python 版本

需要 Python 3.9 或更高版本：

```bash
python3 --version
```

### 2. 安装 ffmpeg

ffmpeg 用于提取视频关键帧：

```bash
# macOS（使用 Homebrew）
brew install ffmpeg
```

### 3. 获取 Anthropic API Key

访问 [console.anthropic.com](https://console.anthropic.com) 创建 API Key（格式为 `sk-ant-...`）。

---

## 安装

```bash
pip3 install yt-dlp anthropic openai-whisper imagehash Pillow rich flask
```

---

## 配置 API Key

```bash
export ANTHROPIC_API_KEY="sk-ant-你的key"
```

---

## 方式一：网页界面

```bash
python server.py
```

访问 **http://localhost:5000**，粘贴 YouTube 链接，点击开始分析。

---

## 方式二：命令行

```bash
python3 -m videodigest.cli "https://youtu.be/VIDEO_ID" -o output/my-summary

# 只生成文字摘要（跳过视频帧）
python3 -m videodigest.cli "https://youtu.be/VIDEO_ID" --no-frames

# 生成英文摘要
python3 -m videodigest.cli "https://youtu.be/VIDEO_ID" --lang English
```

### 输出文件

```
output/my-summary/
├── summary.md
├── summary.json
└── frames/
    ├── frame_001.jpg
    └── ...
```

---

## 完整参数说明（CLI）

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `URL` | YouTube 视频链接 | 必填 |
| `-o, --output DIR` | 输出目录 | `./<video_id>/` |
| `-l, --lang LANG` | 输出语言 Chinese/English/Japanese/Korean | Chinese |
| `--api-key KEY` | Anthropic API Key | 环境变量 |
| `--max-frames N` | 最多提取关键帧数量 | 12 |
| `--no-frames` | 跳过视频下载和帧提取 | - |
| `--whisper-model SIZE` | Whisper 模型 tiny/base/small/medium/large | base |
| `--merge-window SEC` | 字幕合并窗口（秒） | 60 |
| `--keep-temp` | 保留临时下载文件 | - |

---

## 工作流程

```
YouTube 链接
    ↓
获取视频元数据（标题、时长、频道）
    ↓
下载字幕（优先中文/英文）→ 若无字幕则下载音频用 Whisper 转录
    ↓
下载视频 → 按时间均匀提取关键帧 → 去除相似帧
    ↓
将字幕文本 + 关键帧图片发送给 Claude AI
    ↓
生成结构化摘要（概览 + 要点 + 章节分段）
    ↓
输出 summary.md 和 summary.json
```
