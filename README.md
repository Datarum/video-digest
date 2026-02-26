# VideoDigest - YouTube 视频智能摘要工具

输入一个 YouTube 链接，自动生成包含关键帧截图的结构化摘要文档（Markdown + JSON）。

支持网页界面和命令行两种使用方式。

---

## 准备工作

在开始前，请确认以下几项已经就绪：

### 1. 检查 Python 版本

需要 Python 3.9 或更高版本：

```bash
python3 --version
```

如果版本低于 3.9，请先升级 Python。

### 2. 确认 ffmpeg 已安装

ffmpeg 用于提取视频关键帧。在终端中运行：

```bash
ffmpeg -version
```

如果提示"找不到命令"，请先安装：

```bash
# macOS（使用 Homebrew）
brew install ffmpeg

# 安装后，将 Homebrew 加入 PATH（如果尚未配置）
echo 'export PATH="/opt/homebrew/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### 3. 获取 Anthropic API Key

本工具调用 Claude AI 生成摘要，需要 API Key：

1. 访问 [console.anthropic.com](https://console.anthropic.com) 注册/登录
2. 在 API Keys 页面创建一个新 Key
3. 将 Key 保存好（格式为 `sk-ant-...`）

---

## 安装

打开终端，进入项目目录，安装所有依赖包：

```bash
cd "/Users/bytedance/CodingDir/video parse"

pip3 install yt-dlp anthropic openai-whisper imagehash Pillow rich flask
```

> 首次安装会下载所有依赖包，需要等待几分钟。

---

## 配置 API Key（推荐方式）

将 API Key 设置为环境变量，避免每次输入，也更安全：

```bash
# 临时设置（仅本次终端窗口有效）
export ANTHROPIC_API_KEY="sk-ant-你的key"

# 永久设置（写入 ~/.zshrc，重启终端后依然有效）
echo 'export ANTHROPIC_API_KEY="sk-ant-你的key"' >> ~/.zshrc
source ~/.zshrc
```

> **安全提示：** 不要把 API Key 直接写在命令行参数里（如 `--api-key sk-ant-...`），
> 这样会被记录在 shell 历史中。使用环境变量更安全。

---

## 方式一：网页界面（推荐新手使用）

### 启动服务器

```bash
cd "/Users/bytedance/CodingDir/video parse"
python server.py
```

看到如下输出说明启动成功：

```
* Running on http://127.0.0.1:5000
```

### 打开浏览器

访问：**http://localhost:5000**

### 使用步骤

1. 在 **YouTube URL** 输入框中粘贴视频链接
2. 选择**输出语言**（默认中文）
3. 选择**最多提取关键帧数量**（推荐 6 或 12）
4. 如果没有设置环境变量，在 **API Key** 框填入你的 Key
5. 点击 **"开始分析"** 按钮
6. 等待进度条依次完成 5 个步骤（约 1-5 分钟，取决于视频长度）
7. 分析完成后，页面直接显示摘要内容，支持**下载 JSON 报告**

### 停止服务器

在终端中按 `Ctrl + C` 停止。

---

## 方式二：命令行（CLI）

适合批量处理或集成到脚本中。

### 基本用法

```bash
cd "/Users/bytedance/CodingDir/video parse"

python3 -m videodigest.cli "https://www.youtube.com/watch?v=视频ID" -o output/我的摘要
```

### 常用示例

```bash
# 分析一个视频，输出到 output/ 目录下
python3 -m videodigest.cli "https://youtu.be/dQw4w9WgXcQ" -o output/test

# 只提取文字摘要，跳过视频帧（速度更快）
python3 -m videodigest.cli "https://youtu.be/dQw4w9WgXcQ" --no-frames

# 生成英文摘要
python3 -m videodigest.cli "https://youtu.be/dQw4w9WgXcQ" --lang English

# 提取更多关键帧（默认 12，可改为 20）
python3 -m videodigest.cli "https://youtu.be/dQw4w9WgXcQ" --max-frames 20
```

### 输出文件

分析完成后，会在指定目录生成：

```
output/我的摘要/
├── summary.md        # Markdown 格式摘要（可用 Typora 等工具打开）
├── summary.json      # 结构化 JSON 数据
└── frames/           # 提取的关键帧截图
    ├── frame_001.jpg
    ├── frame_002.jpg
    └── ...
```

---

## 完整参数说明（CLI）

```
python3 -m videodigest.cli <URL> [选项]

必填：
  URL                   YouTube 视频链接

可选：
  -o, --output DIR      输出目录（默认：当前目录下以视频ID命名的文件夹）
  -l, --lang LANG       输出语言，可选 Chinese/English/Japanese/Korean（默认：Chinese）
  --api-key KEY         Anthropic API Key（不推荐，建议用环境变量）
  --max-frames N        最多提取关键帧数量（默认：12）
  --no-frames           跳过视频下载和帧提取，仅生成文字摘要
  --whisper-model SIZE  Whisper 语音识别模型大小：tiny/base/small/medium/large
                        （当视频没有字幕时使用，默认：base）
  --merge-window SEC    字幕合并窗口（秒），默认 60
  --keep-temp           保留临时下载文件（调试用）
```

---

## 常见问题

**Q: 分析失败，提示网络错误**

某些视频或网络环境下 yt-dlp 可能无法下载。可以尝试：
- 换一个视频链接测试
- 检查是否需要代理

**Q: 没有字幕，提示要用 Whisper 转录，很慢**

Whisper 需要下载视频音频并在本地运行语音识别。首次运行还会下载模型文件（约几百 MB）。
可以用 `--whisper-model tiny` 加快速度（精度会降低）。

**Q: 提示 ffmpeg 找不到**

确认 ffmpeg 已安装，并且 `/opt/homebrew/bin` 在 PATH 中。
运行 `which ffmpeg` 验证，应该输出 `/opt/homebrew/bin/ffmpeg`。

**Q: 如何查看已生成的摘要**

生成的 `summary.md` 可以用任何 Markdown 阅读器打开，推荐：
- **VS Code**（直接预览）
- **Typora**（所见即所得编辑器）
- **GitHub**（拖入仓库即可在线预览）

---

## 工作流程说明

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
