"""Infographic image generator for NBB mode.

Builds a content-rich image generation prompt that injects actual video content
(headline, step titles + bullet points, stats, quote) directly into the prompt,
so the generated image contains the real information rather than abstract placeholders.
"""

import requests
from typing import Optional

# ── Silicon Flow API ──────────────────────────────────────────────────────────

_SF_API_URL = "https://api.siliconflow.cn/v1/images/generations"
_SF_MODEL   = "Qwen/Qwen-Image"

_DEFAULT_NEG = (
    "照片写实，摄影风格，3D渲染，CGI，模糊，低画质，变形扭曲，水印，logo，"
    "纯白背景，浅色背景，卡通风格，儿童插画，过度饱和"
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe(text: str, max_chars: int = 60) -> str:
    """Strip quotes, newlines, and truncate."""
    return text.replace('"', "'").replace("\n", " ").replace("**", "").strip()[:max_chars]


def _get_steps(diagram_data: dict, n: int = 4) -> list:
    """Return up to n step dicts, each with title + two points (padded if needed)."""
    steps = diagram_data.get("steps", []) if diagram_data else []
    result = []
    for s in steps[:n]:
        title  = _safe(str(s.get("title", "")), 40)
        points = s.get("points", [])
        p1 = _safe(str(points[0]), 80) if len(points) > 0 else "Key insight"
        p2 = _safe(str(points[1]), 80) if len(points) > 1 else "Important detail"
        result.append({"title": title, "p1": p1, "p2": p2})
    # pad to n if needed
    while len(result) < n:
        result.append({"title": "Key Point", "p1": "Important insight", "p2": "Core detail"})
    return result


def _extract_content(diagram_data: dict, key_insights: list) -> dict:
    """Extract all text fields from diagram_data for prompt injection."""
    dd = diagram_data or {}
    headline = _safe(str(dd.get("headline", "Video Summary")), 80)
    subtitle = _safe(str(dd.get("subtitle", "Key Insights")), 50)
    quote    = _safe(str(dd.get("quote", "")), 120)
    stats    = dd.get("stats", [])
    i1 = _safe(str(stats[0]), 80) if len(stats) > 0 else _safe(str(key_insights[0]) if key_insights else "Core insight", 80)
    i2 = _safe(str(stats[1]), 80) if len(stats) > 1 else _safe(str(key_insights[1]) if len(key_insights) > 1 else "Key finding", 80)
    i3 = _safe(str(stats[2]), 80) if len(stats) > 2 else _safe(str(key_insights[2]) if len(key_insights) > 2 else "Main takeaway", 80)
    return dict(headline=headline, subtitle=subtitle, quote=quote, i1=i1, i2=i2, i3=i3)


# ── Per-type prompt builders ──────────────────────────────────────────────────

def _prompt_comparison(content: dict, steps: list) -> str:
    """educational → left/right contrast with actual content text."""
    return f"""\
手绘速写风格信息图，横向宽屏构图。
整体色调：深炭灰黑色背景（接近纯黑），铅笔和钢笔手绘线条。
主色：暖橙棕色（用于标题、强调线、图标），文字为暖奶白色，线条为灰白色，粗细自然变化。
排版风格：专业杂志编辑美学，层次清晰，手写感强。

【文字处理原则】下方各区域内容为参考，请完整呈现所有信息要点，可在表达相同含义的前提下适当改写措辞，确保每个汉字清晰可辨、不出现乱码或残缺。

【顶部标题区】
大号粗体手写标题（暖橙色），参考：{content['headline']}
副标题（小号，奶白色），参考：{content['subtitle']}
标题下方有一条橙色手绘横线分隔

【左栏：问题/现状】
左上角橙色手写标签框
栏标题（橙色粗体手写），参考：{steps[0]['title']}
• 要点（奶白色手写）参考：{steps[0]['p1']}
• 要点参考：{steps[0]['p2']}
背景有交织乱线纹理，营造"混乱/问题"氛围

【中央分隔区】
垂直橙色手绘虚线，中部有一个粗体向右箭头（→），箭头用橙色填充

【右栏：解决方案/结论】
栏标题（橙色粗体手写），参考：{steps[1]['title']}
• 要点（奶白色手写）参考：{steps[1]['p1']}
• 要点参考：{steps[1]['p2']}
右侧点缀对勾图标（✓）和灯泡手绘图标，橙色

【底部数据条，深灰色背景衬底】
三个圆角矩形标签框并排，橙色边框，奶白色文字，各参考：
{content['i1']} ｜ {content['i2']} ｜ {content['i3']}

【右下角引用框】
手绘不规则边框，左侧有橙色引号装饰（"），奶白色斜体文字，参考：
{content['quote']}

风格要求：铅笔素描线条为主，局部橙色水彩晕染，整体暗色调，专业沉稳，文字清晰可读，禁止出现浅色或白色背景。"""


def _prompt_steps(content: dict, steps: list) -> str:
    """tutorial → numbered horizontal flowchart with actual step content."""
    return f"""\
手绘速写风格信息图，横向宽屏构图。
整体色调：深炭灰黑色背景，隐约可见极细的网格纹（深灰色，几乎融入背景）。
主色：暖橙棕色（标题、编号圆圈、箭头），文字为奶白色，线条为灰白手绘笔触。
排版风格：教程流程图美学，步骤感强，干净有序。

【文字处理原则】下方各区域内容为参考，请完整呈现所有信息要点，可在表达相同含义的前提下适当改写措辞，确保每个汉字清晰可辨、不出现乱码或残缺。

【顶部标题区】
大号粗体手写标题（橙色），参考：{content['headline']}
副标题（小号，奶白色），参考：{content['subtitle']}
下方橙色手绘分隔线

【主体区域：四个步骤卡片横向排列，用粗手绘波浪箭头（橙色）依次连接】

步骤卡片1（左起第一，深灰色圆角卡片，橙色边框）：
  编号圆圈"①"（橙色填充，白色数字）
  卡片标题（橙色粗手写），参考：{steps[0]['title']}
  • 要点（奶白色），参考：{steps[0]['p1']}
  • 要点参考：{steps[0]['p2']}

→（手绘橙色粗箭头）

步骤卡片2：
  编号圆圈"②"
  卡片标题参考：{steps[1]['title']}
  • 参考：{steps[1]['p1']}
  • 参考：{steps[1]['p2']}

→

步骤卡片3：
  编号圆圈"③"
  卡片标题参考：{steps[2]['title']}
  • 参考：{steps[2]['p1']}
  • 参考：{steps[2]['p2']}

→

步骤卡片4（最右）：
  编号圆圈"④"（橙色）
  卡片标题参考：{steps[3]['title']}
  • 参考：{steps[3]['p1']}
  • 参考：{steps[3]['p2']}

【底部横幅，深色矩形条，橙色点缀】
核心结论（奶白色大字），参考：{content['i1']}

【右下角引用框，手绘矩形边框，橙色】
参考：{content['quote']}

风格要求：粗细不均的铅笔线条，橙色用于所有强调元素，暗色调整体氛围，文字清晰可读。"""


def _prompt_story_panels(content: dict, steps: list) -> str:
    """narrative → horizontal timeline with 3 story panels."""
    return f"""\
手绘速写风格信息图，横向宽屏构图。
整体色调：深炭黑背景，局部橙棕色水彩晕染营造氛围感。
主色：暖橙棕色（时间线、标题、关键节点），文字为奶白色，线条为手绘钢笔风格。
排版风格：叙事性故事板美学，时间感强，图文并茂。

【文字处理原则】下方各区域内容为参考，请完整呈现所有信息要点，可在表达相同含义的前提下适当改写措辞，确保每个汉字清晰可辨、不出现乱码或残缺。

【顶部标题区】
卷轴式标题横幅（深灰色底，橙色手绘边框装饰）
大号粗体手写标题（橙色），参考：{content['headline']}
副标题（奶白色小字），参考：{content['subtitle']}

【主体：全宽时间轴箭头，贯穿画面中部】
时间轴为橙色粗手绘水平线，两端有箭头，线上有三个橙色菱形节点标记

节点1（左侧面板）：
  节点标签（橙色圆形徽章），参考：{steps[0]['title']}
  面板内有手绘场景小图标
  手写文字（奶白色），参考：{steps[0]['p1']}

节点2（中央面板，视觉上略大于两侧）：
  节点标签参考：{steps[1]['title']}
  手写文字参考：{steps[1]['p1']}
  补充说明参考：{steps[1]['p2']}

节点3（右侧面板）：
  节点标签参考：{steps[2]['title']}
  手写文字参考：{steps[2]['p1']}

【时间轴下方，引用框，手绘不规则边框】
大号橙色引号，奶白色斜体引言，参考：{content['quote']}

【底部三栏关键信息，各自有橙色手绘下划线】
参考：{content['i1']} ｜ {content['i2']} ｜ {content['i3']}

风格要求：手绘钢笔线稿加橙色水彩晕染，暗色背景凸显叙事层次，文字清晰可读。"""


def _prompt_argument_tree(content: dict, steps: list) -> str:
    """opinion → radial hub-and-spoke with actual argument text."""
    return f"""\
手绘速写风格信息图，横向宽屏构图。
整体色调：深炭黑背景，隐约可见极淡的方格纸纹理（深灰色线条，非常细）。
主色：暖橙棕色（中心圆、分支线条、标题），文字为奶白色，线条粗犷自信。
排版风格：观点分析图，放射状结构，层次分明，力量感强。

【文字处理原则】下方各区域内容为参考，请完整呈现所有信息要点，可在表达相同含义的前提下适当改写措辞，确保每个汉字清晰可辨、不出现乱码或残缺。

【顶部标题区，左对齐】
大号粗体手写标题（橙色），参考：{content['headline']}
副标题（奶白色小字），参考：{content['subtitle']}

【画面主体：辐射状论点树，中心偏左居中】
中心圆（占主体区域核心位置）：
  橙色粗手绘圆形，内有与主题相关的手绘图标
  圆心白色文字标注核心主题

四条粗手绘分支线（橙色）从圆心向上下左右四方辐射：

上方分支文字框（深灰色圆角矩形，橙色边框）：
  框标题（橙色粗手写），参考：{steps[0]['title']}
  补充说明（奶白色），参考：{steps[0]['p1']}

右方分支文字框：
  框标题参考：{steps[1]['title']}
  补充说明参考：{steps[1]['p1']}

下方分支文字框：
  框标题参考：{steps[2]['title']}
  补充说明参考：{steps[2]['p1']}

左方分支文字框：
  框标题参考：{steps[3]['title']}
  补充说明参考：{steps[3]['p1']}

【右侧边栏，竖向排列，与主图分隔一条橙色细线】
三条关键发现，每条前有橙色小圆点，参考：
· {content['i1']}
· {content['i2']}
· {content['i3']}

【底部引用框，手绘矩形，橙色虚线边框】
参考：{content['quote']}

风格要求：自信粗犷的钢笔线条，橙色为唯一强调色，暗色调整体，分析感强，文字清晰可读。"""


def _prompt_grid(content: dict, steps: list) -> str:
    """showcase → 2×3 card grid with actual content labels."""
    return f"""\
手绘速写风格信息图，横向宽屏构图。
整体色调：深炭黑背景，卡片用深灰色（稍浅于背景）填充，橙色边框分隔。
主色：暖橙棕色（标题、卡片边框、图标），文字为奶白色。
排版风格：产品展示/合集海报美学，整齐有序，视觉冲击力强。

【文字处理原则】下方各区域内容为参考，请完整呈现所有信息要点，可在表达相同含义的前提下适当改写措辞，确保每个汉字清晰可辨、不出现乱码或残缺。

【顶部横幅，深灰色底条】
大号粗体手写标题（橙色），参考：{content['headline']}
副标题（奶白色），参考：{content['subtitle']}
右侧点缀3-4个手绘装饰小图标

【主体：2行×3列卡片网格，卡片间距均匀】
每张卡片：深灰色圆角矩形，橙色手绘边框，内部有手绘图标

第1行：
  卡片A（橙色图标+奶白色文字）：
    标题参考：{steps[0]['title']}
    说明参考：{steps[0]['p1']}
  卡片B：
    标题参考：{steps[1]['title']}
    说明参考：{steps[1]['p1']}
  卡片C：
    标题参考：{steps[2]['title']}
    说明参考：{steps[2]['p1']}

第2行：
  卡片D：
    标题参考：{steps[3]['title']}
    说明参考：{steps[3]['p1']}
  卡片E（橙色底，白色文字，强调卡）：
    核心洞察参考：{content['i1']}
  卡片F（橙色底，白色文字）：
    核心洞察参考：{content['i2']}

【底部引用条，左侧有橙色粗引号】
参考：{content['quote']}

风格要求：干净利落的手绘线条，橙色与深灰形成鲜明对比，整体暗色调，文字清晰可读。"""


def _prompt_qa(content: dict, steps: list) -> str:
    """interview → Q/A two-zone dialogue layout with actual content."""
    return f"""\
手绘速写风格信息图，横向宽屏构图。
整体色调：深炭黑背景，左右分区用微妙的深灰色区别，橙色贯穿全图作为视觉主线。
主色：暖橙棕色（问号图标、话框边框、关键词），文字为奶白色。
排版风格：对话/访谈问答布局，左右呼应，动态感强。

【文字处理原则】下方各区域内容为参考，请完整呈现所有信息要点，可在表达相同含义的前提下适当改写措辞，确保每个汉字清晰可辨、不出现乱码或残缺。

【顶部标题区，居中排版】
大号粗体手写标题（橙色），参考：{content['headline']}
副标题（奶白色小字），参考：{content['subtitle']}
下方橙色细线分隔

【左区 — 提问区】
顶部大号橙色手绘"？"图标
手绘拼图碎片装饰背景（极淡，深灰色）

对话气泡1（手绘圆角矩形，橙色边框，左下角有三角气泡尾）：
  气泡标题（橙色粗手写），参考：{steps[0]['title']}
  气泡内容（奶白色），参考：{steps[0]['p1']}

对话气泡2（同样风格，略小）：
  气泡标题参考：{steps[1]['title']}
  气泡内容参考：{steps[1]['p1']}

【中央分隔区】
垂直橙色虚线
中央手绘麦克风图标（橙色填充），上下各有装饰横线

【右区 — 回答区】
顶部橙色手绘灯泡图标

回答气泡1（填充深灰色，橙色边框，右下角气泡尾）：
  回答标题（橙色粗手写），参考：{steps[2]['title']}
  回答内容（奶白色），参考：{steps[2]['p1']}

回答气泡2：
  回答标题参考：{steps[3]['title']}
  回答内容参考：{steps[3]['p1']}

【底部数据条，深灰色底】
三个关键洞察，橙色竖线分隔，参考：
{content['i1']} ｜ {content['i2']} ｜ {content['i3']}

【引用框，居中或右下，手绘边框】
参考：{content['quote']}

风格要求：手绘线条自然有力，橙色强调重点，暗色背景营造深度访谈氛围，所有文字清晰可读。"""


_PROMPT_BUILDERS = {
    "comparison":    _prompt_comparison,
    "steps":         _prompt_steps,
    "story_panels":  _prompt_story_panels,
    "argument_tree": _prompt_argument_tree,
    "grid":          _prompt_grid,
    "qa":            _prompt_qa,
}


# ── Public API ────────────────────────────────────────────────────────────────

def build_infographic_prompt(
    content_type_data: dict,
    overview: str,
    key_insights: list,
    diagram_data: dict = None,
) -> tuple:
    """Build a content-rich image generation prompt with actual video information.

    Args:
        content_type_data: dict from analyzer.analyze_content_type()
        overview:          video overview string
        key_insights:      list of insight strings (from diagram_data.stats)
        diagram_data:      full diagram dict with headline, subtitle, steps, stats, quote

    Returns:
        (prompt: str, negative_prompt: str)
    """
    viz     = content_type_data.get("viz_template", "comparison")
    content = _extract_content(diagram_data, key_insights)
    steps   = _get_steps(diagram_data, n=4)

    builder = _PROMPT_BUILDERS.get(viz, _prompt_comparison)
    prompt  = builder(content, steps)

    return prompt, _DEFAULT_NEG


def call_siliconflow(
    prompt: str,
    api_key: str,
    negative_prompt: str = _DEFAULT_NEG,
    model: str = _SF_MODEL,
    image_size: str = "1664x928",
    num_steps: int = 25,
    guidance_scale: float = 5.0,
) -> Optional[str]:
    """Call Silicon Flow image-generation API.

    Args:
        prompt:          The image generation prompt.
        api_key:         Silicon Flow API key (SILICONFLOW_API_KEY).
        negative_prompt: Things to avoid.
        model:           Silicon Flow model ID (default: Qwen/Qwen-Image).
        image_size:      WxH string, e.g. '1664x928' (16:9 landscape).
        num_steps:       Inference steps.
        guidance_scale:  CFG scale.

    Returns:
        Image URL string, or None on failure.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }
    payload = {
        "model":                 model,
        "prompt":                prompt,
        "negative_prompt":       negative_prompt,
        "image_size":            image_size,
        "num_inference_steps":   num_steps,
        "guidance_scale":        guidance_scale,
        "num_images":            1,
    }

    resp = requests.post(_SF_API_URL, headers=headers, json=payload, timeout=120)
    if not resp.ok:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:2000]}")
    data   = resp.json()
    images = data.get("images", [])
    if images:
        url = images[0].get("url")
        if url:
            return url
        b64 = images[0].get("b64_json")
        if b64:
            return f"data:image/png;base64,{b64}"
    raise RuntimeError(f"API 未返回图片，响应: {str(data)[:2000]}")
