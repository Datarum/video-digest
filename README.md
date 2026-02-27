# VideoDigest v2.0 - YouTube 视频智能摘要工具

输入一个 YouTube 链接，自动生成结构化摘要，包含：
- **概览与要点**：视频核心内容一句话总结 + 关键要点列表
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

# 将 Homebrew 加入 PATH（如果尚未配置）
echo 'export PATH="/opt/homebrew/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### 3. 获取 Anthropic API Key

1. 访问 [console.anthropic.com](https://console.anthropic.com) 注册/登录
2. 在 API Keys 页面创建新 Key（格式 `sk-ant-...`）

---

## 安装

```bash
cd "/Users/bytedance/CodingDir/video parse 2.0"

pip3 install yt-dlp anthropic openai-whisper imagehash Pillow rich flask
```

> 首次安装需要几分钟。rough.js（导图渲染）通过 CDN 加载，无需安装。

---

## 配置 API Key

```bash
# 永久设置（推荐）
echo 'export ANTHROPIC_API_KEY="sk-ant-你的key"' >> ~/.zshrc
source ~/.zshrc
```

---

## 方式一：网页界面（推荐）

### 启动服务器

```bash
cd "/Users/bytedance/CodingDir/video parse 2.0"
python3 server.py
```

看到 `* Running on http://127.0.0.1:5000` 说明启动成功。

### 使用步骤

1. 浏览器访问 **http://localhost:5000**
2. 粘贴 YouTube 视频链接
3. 选择输出语言（默认中文）
4. 点击 **"开始分析"**
5. 等待分析完成（约 1–5 分钟，取决于视频长度）
6. 结果页面显示摘要 + 核心结构导图 + 章节详情

### 导图交互

- **点击导图卡片** 或 **"⛶ 展开浏览"** 按钮 → 全屏查看
- 全屏模式下：**拖拽**平移，**滚轮**缩放，**双指捏合**缩放（触屏），**Esc** 关闭

### 停止服务器

终端按 `Ctrl + C`。

---

## 方式二：命令行（CLI）

```bash
cd "/Users/bytedance/CodingDir/video parse 2.0"

# 基本用法
python3 -m videodigest.cli "https://www.youtube.com/watch?v=视频ID" -o output/我的摘要

# 常用示例
python3 -m videodigest.cli "https://youtu.be/dQw4w9WgXcQ" -o output/test
python3 -m videodigest.cli "https://youtu.be/dQw4w9WgXcQ" --no-frames   # 跳过帧提取，更快
python3 -m videodigest.cli "https://youtu.be/dQw4w9WgXcQ" --lang English
```

### 输出文件

```
output/我的摘要/
├── summary.md        # Markdown 格式摘要
├── summary.json      # 结构化 JSON（含 diagram_data 节点/边数据）
└── frames/           # 提取的关键帧截图
    ├── frame_001.jpg
    └── ...
```

### 完整参数

```
python3 -m videodigest.cli <URL> [选项]

必填：
  URL                   YouTube 视频链接

可选：
  -o, --output DIR      输出目录
  -l, --lang LANG       输出语言：Chinese/English/Japanese/Korean（默认：Chinese）
  --api-key KEY         Anthropic API Key（建议用环境变量代替）
  --max-frames N        最多提取关键帧数量（默认：12）
  --no-frames           跳过视频下载和帧提取，仅生成文字摘要
  --whisper-model SIZE  Whisper 模型大小：tiny/base/small/medium/large（默认：base）
  --merge-window SEC    字幕合并窗口（秒），默认 60
  --keep-temp           保留临时下载文件（调试用）
```

---

## 工作流程

```
YouTube 链接
    ↓
获取视频元数据（标题、时长、频道）
    ↓
下载字幕（优先中文/英文）→ 若无字幕则用 Whisper 语音转录
    ↓
下载视频 → 提取关键帧 → 去除相似帧
    ↓
Claude AI 主分析（字幕 + 关键帧）→ 概览 + 要点 + 章节摘要
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
