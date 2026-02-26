# VideoDigest v2.0 - YouTube 视频智能摘要工具

输入一个 YouTube 链接，自动生成结构化摘要，包含：
- **概览**：视频核心内容一句话总结
- **核心结构导图**：Excalidraw 风格手绘思维导图，支持展开全图、拖拽平移、滚轮缩放
- **章节详情**：按时间段划分的章节摘要

支持网页界面和命令行两种使用方式。

---

## 准备工作

### 1. 检查 Python 版本

需要 Python 3.9 或更高版本：

```bash
python3 --version
```

### 2. 确认 ffmpeg 已安装

```bash
ffmpeg -version
```

如果提示"找不到命令"，请先安装：

```bash
# macOS（使用 Homebrew）
brew install ffmpeg
echo 'export PATH="/opt/homebrew/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### 3. 获取 Anthropic API Key

访问 [console.anthropic.com](https://console.anthropic.com)，在 API Keys 页面创建新 Key（格式 `sk-ant-...`）。

---

## 安装

```bash
pip3 install yt-dlp anthropic openai-whisper imagehash Pillow rich flask
```

> rough.js（导图渲染）通过 CDN 加载，无需安装。

---

## 配置 API Key

```bash
echo 'export ANTHROPIC_API_KEY="sk-ant-你的key"' >> ~/.zshrc
source ~/.zshrc
```

---

## 方式一：网页界面（推荐）

```bash
python3 server.py
```

浏览器访问 **http://localhost:5000**，粘贴 YouTube 链接，点击开始分析。

### 导图交互

- **点击导图卡片** 或 **"⛶ 展开浏览"** 按钮 → 全屏查看
- 全屏模式下：**拖拽**平移，**滚轮**缩放，**双指捏合**缩放（触屏），**Esc** 关闭

---

## 方式二：命令行（CLI）

```bash
python3 -m videodigest.cli "https://youtu.be/VIDEO_ID" -o output/my-summary

# 跳过帧提取（更快）
python3 -m videodigest.cli "https://youtu.be/VIDEO_ID" --no-frames

# 生成英文摘要
python3 -m videodigest.cli "https://youtu.be/VIDEO_ID" --lang English
```

### 输出文件

```
output/my-summary/
├── summary.md        # Markdown 格式摘要
├── summary.json      # 结构化 JSON（含 diagram_data 节点/边数据）
└── frames/           # 提取的关键帧截图
```

### 完整参数

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
下载字幕（优先中文/英文）→ 若无字幕则用 Whisper 语音转录
    ↓
Claude AI 第一步分析字幕 → 识别关键时间点
    ↓
下载视频 → 在关键时间点提取帧 → 去除相似帧
    ↓
Claude AI 主分析（字幕 + 关键帧）→ 概览 + 章节摘要
    ↓
Claude AI 图表分析 → 核心结构节点/边 JSON
    ↓
前端 rough.js 渲染 Excalidraw 风格导图
    ↓
输出 summary.md 和 summary.json
```

---

## 常见问题

**Q: 分析失败，提示网络错误**

某些视频或网络环境下 yt-dlp 可能无法下载，换个视频测试，或检查是否需要代理。

**Q: 没有字幕，Whisper 转录很慢**

Whisper 首次运行会下载模型文件（约几百 MB）。可用 `--whisper-model tiny` 加快速度（精度降低）。

**Q: 提示 ffmpeg 找不到**

运行 `which ffmpeg` 验证路径，应输出 `/opt/homebrew/bin/ffmpeg`。

**Q: 导图字体显示不正常**

导图使用 Caveat 手写字体（Google Fonts CDN），需要网络连接加载字体。
