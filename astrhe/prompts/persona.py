"""会话人格与夜间人格不同时，给汇报、规划、审稿的说明。只在确有不同的会话时出现。"""

from __future__ import annotations

from typing import Any

NO_PERSONA_TEXT = (
    "这个会话没有设置人格：白天在这里说话的你不带任何人格设定。"
    "汇报时用平实、客观的口吻。"
)

PLANNER_PERSONA_RULES = """规则：
1. 给这些会话写的段落、待办、闹钟卡片，都以那个会话的人格为准：白天和闹钟唤醒时在那里说话的是那个人格，它只看得到自己的人格提示词和你写给它的内容。身份、称呼、口吻、在意的事都按它的人格来写，不要写成你自己的口吻，也不要让它以你的身份说话。
2. 关系本按你自己的人格记录。这些会话里称呼谁、用什么语气，以那个人格的提示词为准，别照搬关系本里的叫法；它们的汇报里的 person_updates 是那个人格的视角，写进关系本前换成你自己的视角。
3. 不同人格之间更要守口：你在别的会话（尤其是私聊）里知道的事，别让另一个人格在它的会话里说出来；确实需要时，也要写成那个人格本来就会知道、会说的样子。
4. day_reminders 只会出现在和你同一个人格的会话里，这些会话看不到；它们要记住的事，写进它们自己的段落或待办。
5. 闹钟到点唤醒时用的是目标会话的人格：发往这些会话的闹钟卡片，要写成那个人格拿到就能照着做的样子。"""

REVIEWER_PERSONA_CHECKS = """审查时额外检查：
- 发往这些会话的段落、待办、闹钟卡片，身份、称呼、口吻是否符合那个会话的人格，有没有写成夜间人格自己的口吻。
- 有没有让某个人格说出它的会话里不该知道的事（尤其是别的会话、私聊里的事）。
- 只跟这些会话有关的事有没有写进 day_reminders：这些会话看不到白天提醒，应该写进它们的段落或待办。"""


def persona_prompt_text(info: Any) -> str:
    """给汇报员的人格正文；没有人格的会话换成说明。"""
    return NO_PERSONA_TEXT if info.none else info.prompt


def daytime_phrase(info: Any) -> str:
    """「白天用的是人格「X」」/「白天没有设置人格」，避免拼出病句。"""
    return "白天没有设置人格" if info.none else f"白天用的是{info.label}"


def reporter_persona_note(info: Any) -> str:
    if info.none:
        who = (
            "这个会话白天没有设置人格，和夜间复盘设置的人格不同，"
            "所以这份汇报不带人格设定，用平实、客观的口吻来写。"
        )
    else:
        who = (
            f"这个会话{daytime_phrase(info)}，和夜间复盘设置的人格不同，"
            "所以这份汇报由它来写：从它的身份和角度回想。"
        )
    return (
        f"【本会话的人格】{who}"
        "下面关系本里的关系和称呼是按另一个人格记的，只当了解这些人的资料"
        + ("。" if info.none else "，以你自己的人格为准。")
    )


def build_persona_material(personas: Any, role: str) -> str:
    """会话人格对照；role 为 planner 或 reviewer。没有不同的会话时返回空串。"""
    if personas is None or not personas.differing:
        return ""
    selected = personas.selected
    lines = [
        "【会话人格】",
        f"夜间复盘用的是{selected.label}（就是你现在的人格）。"
        "下面这些会话白天用的是别的人格，它们的汇报也是由那个人格写的：",
    ]
    prompts: dict[str, str] = {}
    for umo, info in personas.differing.items():
        if info.none:
            lines.append(
                f"- {umo}：没有设置人格（在这里说话时不带任何人格设定，"
                "写给它的内容用平实、中性的口吻）"
            )
            continue
        lines.append(f"- {umo}：{info.label}")
        prompts.setdefault(info.name or info.label, info.prompt)
    if prompts:
        lines.append("\n各人格的提示词（同一个人格只列一次）：")
        for name, prompt in prompts.items():
            lines.append(f"「{name}」：\n{prompt}")
    lines.append(
        "\n" + (PLANNER_PERSONA_RULES if role == "planner" else REVIEWER_PERSONA_CHECKS)
    )
    return "\n".join(lines)
