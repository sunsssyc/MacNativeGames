"""The hint prompt (shared by every backend) and the clean-up of the answer for the in-game panel."""
import json
import re

TIER_NAMES = {1: '去哪里', 2: '用什么', 3: '完整解法'}
MAX_LINES = 6
MAX_CHARS = 210

SYSTEM = """你是《塞尔达传说 王国之泪》（1.4.3 版，在 Mac 上运行）的卡关助手。你的回答会显示在游戏画面角落的小窗口里，玩家边玩边看。

一、先查数据，再回答
- 提示必须以存档和游戏数据为依据：请求里附带的存档快照，以及 totk-harness 的工具 game_state、quest_log、search_text（允许截图时还有 screenshot）。
- 地名、人名、物品名、能力名一律用游戏里的简体中文原名；拿不准就用 search_text 核对。工具查不到的事实不要编造。
- 没有玩家的问题描述时，自己判断玩家最可能卡在哪：林克在神庙或神殿里，就针对那里；否则选正在进行的主要任务里目标离林克最近、最合理的下一步。只讲一件事。
- 只用 totk-harness 的工具，不要运行命令、不要读写其他文件。

二、分档，绝不超过玩家要的档位
- 1 档（去哪里）：只说该去哪里、找谁、往哪个方向、大概多远。不提要用的能力、道具或解法。
- 2 档（用什么）：在 1 档基础上，说要用的能力、道具、装备或思路，但不给完整步骤。
- 3 档（完整解法）：按步骤给出完整做法。不能确定的步骤以“建议”开头。
- 玩家还没走到的任务日志（工具标为“尚未到达”）和对话原文会剧透：1、2 档不要用，3 档只在确实需要时用。

三、输出格式
- 简体中文纯文本，最多 6 行，每行尽量不超过 28 个字；第一行直接给结论。
- 不要 Markdown，不要标题、表情、客套话，不要复述规则或说明你查了什么。"""


def user_prompt(tier, snapshot=None, question=None, previous=None, screenshot=False):
    lines = [f'提示等级：{tier} 档（{TIER_NAMES[tier]}）。']
    if question:
        lines.append(f'玩家的问题：{question}')
    else:
        lines.append('玩家没有描述问题，只按下了“卡关提示”键。')
    if previous:
        lines.append('同一次求助里已经给过的提示（这次要更进一步，并且和它保持一致，不要换话题）：')
        for t, text in previous:
            lines.append(f'第 {t} 档：{text}')
    lines.append('本次允许截图：需要时可以调用 screenshot 看当前画面。' if screenshot else '本次不允许截图。')
    if snapshot is not None:
        lines.append('存档快照（game_state 与 quest_log 的结果，JSON）：')
        lines.append(json.dumps(snapshot, ensure_ascii=False, separators=(',', ':')))
        lines.append('快照不够时再调用工具（例如 search_text 核对名字、quest_log 查别的任务）。')
    else:
        lines.append('请先调用 game_state 和 quest_log 了解进度。')
    lines.append(f'最后只输出给玩家看的 {TIER_NAMES[tier]} 提示正文（不超过 6 行）。')
    return '\n'.join(lines)


_MARKDOWN = re.compile(r'^\s*(?:#{1,6}\s+|[-*•]\s+|>\s*)')


def clean(text):
    """The model's answer as panel text: no Markdown, no empty lines, at most MAX_LINES lines and MAX_CHARS characters."""
    text = (text or '').replace('\r', '')
    text = re.sub(r'```[a-z]*', '', text)
    lines = []
    for line in text.split('\n'):
        line = _MARKDOWN.sub('', line)
        line = re.sub(r'\*\*(.+?)\*\*|__(.+?)__', lambda m: m.group(1) or m.group(2), line)
        line = line.replace('`', '').strip()
        if line:
            lines.append(line)
    if len(lines) > MAX_LINES:
        lines = lines[:MAX_LINES]
        lines[-1] = lines[-1].rstrip('。，,.') + '…'
    out = '\n'.join(lines)
    if len(out) > MAX_CHARS:
        out = out[:MAX_CHARS - 1].rstrip() + '…'
    return out
